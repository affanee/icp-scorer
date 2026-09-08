"""Ask Claude to score one company against the rubric, then check its work.

Two things here are worth understanding, because they are what an interviewer
will ask about:

1. STRUCTURED OUTPUT VIA TOOL USE.
   We do not ask the model for JSON and hope. We define a tool with a strict
   input schema and force the model to call it. The API then guarantees the
   shape - right keys, right types, scores constrained to 0-3. No parsing of
   prose, no "sometimes it wraps the JSON in a code fence" bugs.

2. GROUNDING.
   Every dimension must come back with a verbatim quote. After the call we
   check each quote against the page text we actually fetched. Ungrounded
   quotes get their score zeroed and flagged. The model cannot award points
   for facts it made up.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ICP, MAX_DIMENSION_SCORE
from .grounding import is_grounded, similarity

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
TOOL_NAME = "submit_icp_score"


# ── result types ─────────────────────────────────────────────────────────────

@dataclass
class DimensionResult:
    key: str
    score: int
    evidence: str
    reasoning: str
    grounded: bool = True
    grounding_score: float = 1.0
    original_score: int | None = None  # set when we zero an ungrounded score


@dataclass
class CompanyResult:
    domain: str
    score: float                     # 0-100
    tier: str                        # A / B / C
    dimensions: list[DimensionResult] = field(default_factory=list)
    summary: str = ""
    ungrounded_count: int = 0
    error: str = ""

    def to_row(self) -> dict:
        row = {
            "domain": self.domain,
            "score": self.score,
            "tier": self.tier,
            "ungrounded": self.ungrounded_count,
            "summary": self.summary,
            "error": self.error,
        }
        for d in self.dimensions:
            row[f"{d.key}_score"] = d.score
            row[f"{d.key}_evidence"] = d.evidence
        return row


# ── the tool schema the model must fill in ───────────────────────────────────

def build_tool(icp: ICP) -> dict:
    """Build the tool definition from the rubric, so schema and rubric never drift."""
    keys = [d.key for d in icp.dimensions]
    return {
        "name": TOOL_NAME,
        "description": "Submit the ICP fit assessment for this company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "array",
                    "minItems": len(keys),
                    "maxItems": len(keys),
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "enum": keys},
                            "score": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": MAX_DIMENSION_SCORE,
                            },
                            "evidence": {
                                "type": "string",
                                "description": (
                                    "A VERBATIM quote copied from the page text above that "
                                    "justifies this score. Must appear word for word in the "
                                    "source. If you cannot find one, return an empty string "
                                    "and score 0."
                                ),
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "One short sentence linking the quote to the score.",
                            },
                        },
                        "required": ["key", "score", "evidence", "reasoning"],
                    },
                },
                "summary": {
                    "type": "string",
                    "description": "One sentence a sales rep could read before a call.",
                },
            },
            "required": ["dimensions", "summary"],
        },
    }


def build_prompt(icp: ICP, domain: str, page_text: str) -> str:
    lines = [
        f"# Ideal Customer Profile: {icp.name}",
        "",
        icp.description,
        "",
        "# Scoring rubric",
        "Score each dimension from 0 to 3 using the guidance given.",
        "",
    ]
    for d in icp.dimensions:
        lines.append(f"## {d.key}")
        lines.append(d.question)
        for level in sorted(d.guidance, reverse=True):
            lines.append(f"  {level} - {d.guidance[level]}")
        lines.append("")

    lines += [
        "# Company under assessment",
        f"Domain: {domain}",
        "",
        "# Source text (this is the ONLY evidence you may use)",
        page_text or "(no text could be retrieved for this company)",
        "",
        "# Instructions",
        "Call the submit_icp_score tool.",
        "Every evidence quote must be copied VERBATIM from the source text above.",
        "Do not paraphrase, do not summarise, do not use outside knowledge about "
        "this company. If the source text does not support a score, give 0 with an "
        "empty evidence string. Being wrong is recoverable; inventing evidence is not.",
    ]
    return "\n".join(lines)


# ── grounding + totalling ────────────────────────────────────────────────────

def finalise(icp: ICP, domain: str, payload: dict, page_text: str) -> CompanyResult:
    """Validate the model's answer against the source text and compute the score."""
    by_key = {d.key: d for d in icp.dimensions}
    results: list[DimensionResult] = []
    ungrounded = 0
    weighted = 0.0

    returned = {d.get("key"): d for d in payload.get("dimensions", [])}

    for key, dim in by_key.items():
        raw = returned.get(key, {})
        score = int(raw.get("score", 0) or 0)
        score = max(0, min(MAX_DIMENSION_SCORE, score))
        evidence = (raw.get("evidence") or "").strip()
        reasoning = (raw.get("reasoning") or "").strip()

        gscore = similarity(evidence, page_text) if evidence else 0.0
        grounded = True
        original = None

        # The rule: any score above zero has to be backed by a real quote.
        if score > 0 and not is_grounded(evidence, page_text):
            grounded = False
            ungrounded += 1
            original = score
            score = 0

        weighted += score * dim.weight
        results.append(
            DimensionResult(
                key=key,
                score=score,
                evidence=evidence,
                reasoning=reasoning,
                grounded=grounded,
                grounding_score=gscore,
                original_score=original,
            )
        )

    score_100 = icp.normalise(weighted)
    return CompanyResult(
        domain=domain,
        score=score_100,
        tier=icp.tier(score_100),
        dimensions=results,
        summary=(payload.get("summary") or "").strip(),
        ungrounded_count=ungrounded,
    )


# ── the two ways to get a payload ────────────────────────────────────────────

def score_with_claude(icp: ICP, domain: str, page_text: str, model: str = DEFAULT_MODEL) -> dict:
    """Real call. Requires ANTHROPIC_API_KEY."""
    from anthropic import Anthropic  # imported lazily so mock mode needs no SDK

    client = Anthropic()
    tool = build_tool(icp)
    message = client.messages.create(
        model=model,
        max_tokens=2000,
        tools=[tool],
        tool_choice={"type": "tool", "name": TOOL_NAME},  # force the tool call
        messages=[{"role": "user", "content": build_prompt(icp, domain, page_text)}],
    )
    for block in message.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block.input
    raise RuntimeError("Model did not call the scoring tool")


def score_mock(icp: ICP, domain: str, page_text: str) -> dict:
    """Deterministic fake scorer so the whole pipeline runs with no API key.

    Used by the test suite and by `make demo`. It picks a real sentence from the
    page as evidence, so the grounding check exercises properly. It is NOT a
    model - never report mock output as a result.
    """
    seed = int(hashlib.sha256(domain.encode()).hexdigest(), 16)
    sentences = [s.strip() for s in page_text.split(".") if len(s.strip()) > 40]
    dims = []
    for i, d in enumerate(icp.dimensions):
        score = (seed >> (i * 3)) % 4
        if sentences and score > 0:
            evidence = sentences[(seed >> i) % len(sentences)][:180]
        else:
            evidence = ""
            score = 0
        dims.append(
            {
                "key": d.key,
                "score": score,
                "evidence": evidence,
                "reasoning": f"(mock) deterministic score for {d.key}",
            }
        )
    return {"dimensions": dims, "summary": f"(mock) deterministic assessment of {domain}"}


# ── caching ──────────────────────────────────────────────────────────────────

def cache_path(cache_dir: str | Path, domain: str, icp: ICP, mock: bool) -> Path:
    """Cache key includes the rubric fingerprint, so editing icp.yaml re-scores."""
    tag = "mock" if mock else "live"
    return Path(cache_dir) / f"{domain}__{icp.fingerprint()}__{tag}.json"


def score_company(
    icp: ICP,
    domain: str,
    page_text: str,
    cache_dir: str | Path = ".cache/scores",
    mock: bool = False,
    refresh: bool = False,
    model: str = DEFAULT_MODEL,
) -> CompanyResult:
    path = cache_path(cache_dir, domain, icp, mock)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            payload = score_mock(icp, domain, page_text) if mock else score_with_claude(
                icp, domain, page_text, model=model
            )
        except Exception as exc:  # noqa: BLE001 - one bad domain must not kill the run
            return CompanyResult(domain=domain, score=0.0, tier="C", error=str(exc)[:200])
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return finalise(icp, domain, payload, page_text)
