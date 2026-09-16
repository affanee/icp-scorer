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
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ICP, MAX_DIMENSION_SCORE
from .grounding import is_grounded, similarity

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
TOOL_NAME = "submit_icp_score"

# Which model provider to use. "anthropic" (paid) or "gemini" (has a free tier).
DEFAULT_PROVIDER = os.environ.get("MODEL_PROVIDER", "anthropic").lower()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


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



# ── Gemini: the same job, a different provider ───────────────────────────────
#
# Claude guarantees output shape with a forced tool call. Gemini does the same
# thing with `responseSchema` - you hand it a schema, it returns JSON matching
# it. Different mechanism, identical guarantee, and the rest of the pipeline
# (grounding, weighting, tiering) does not care which one produced the payload.
#
# That separation is the point: the provider is swappable, the judgment is not.

def build_gemini_schema(icp: ICP) -> dict:
    """The tool schema, re-expressed in Gemini's OpenAPI-subset dialect.

    Note it has no min/max on `score` - Gemini's schema subset does not support
    them. That is fine: finalise() clamps every score to 0-3 anyway, because
    trusting a model to respect its own schema is not a safety model.
    """
    keys = [d.key for d in icp.dimensions]
    return {
        "type": "OBJECT",
        "properties": {
            "dimensions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "key": {"type": "STRING", "enum": keys},
                        "score": {"type": "INTEGER"},
                        "evidence": {"type": "STRING"},
                        "reasoning": {"type": "STRING"},
                    },
                    "required": ["key", "score", "evidence", "reasoning"],
                },
            },
            "summary": {"type": "STRING"},
        },
        "required": ["dimensions", "summary"],
    }


def list_gemini_models(key: str) -> list:
    """Used only to make a 'model not found' error actually helpful."""
    import requests

    try:
        r = requests.get(GEMINI_ENDPOINT, headers={"x-goog-api-key": key}, timeout=30)
        return [
            m["name"].split("/")[-1]
            for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    except Exception:  # noqa: BLE001
        return []


def score_with_gemini(icp: ICP, domain: str, page_text: str, model: str = GEMINI_MODEL) -> dict:
    """Real call against Gemini. Requires GEMINI_API_KEY."""
    import requests

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")

    body = {
        "contents": [{"parts": [{"text": build_prompt(icp, domain, page_text)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": build_gemini_schema(icp),
            "temperature": 0,
        },
    }
    # The free tier throttles aggressively. A 429 is not an error condition,
    # it is the API telling you to slow down - so back off and try again
    # rather than losing the row. This is the single most common reason a
    # batch job "half works" and nobody notices.
    backoffs = [5, 15, 40]
    for attempt in range(len(backoffs) + 1):
        r = requests.post(
            GEMINI_ENDPOINT + "/" + model + ":generateContent",
            json=body,
            headers={"x-goog-api-key": key},
            timeout=90,
        )
        if r.status_code != 429:
            break
        if attempt == len(backoffs):
            raise RuntimeError("Gemini rate limit: still throttled after 3 retries.")
        wait = backoffs[attempt]
        print("    rate limited, waiting " + str(wait) + "s...", flush=True)
        time.sleep(wait)

    # Surface the API's OWN error text. An earlier version of this function
    # printed a guessed explanation ("model not found") while Google was in
    # fact saying "that model is retired, use this one instead" - and the
    # useful sentence was sitting unread in the response body. Never paraphrase
    # an upstream error you can just quote.
    if r.status_code != 200:
        try:
            upstream = r.json().get("error", {}).get("message", "")
        except ValueError:
            upstream = r.text[:300]
        if r.status_code == 404:
            available = list_gemini_models(key)
            hint = ", ".join(available[:6]) if available else "could not list models"
            upstream += "  [available: " + hint + "]"
        if r.status_code in (401, 403):
            upstream += "  [check GEMINI_API_KEY in your .env]"
        raise RuntimeError("Gemini " + str(r.status_code) + ": " + upstream)

    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError("Unexpected Gemini response: " + str(data)[:200]) from None
    return json.loads(text)


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

def cache_path(
    cache_dir: str | Path, domain: str, icp: ICP, mock: bool, provider: str = "anthropic"
) -> Path:
    """Cache key includes the rubric fingerprint, so editing icp.yaml re-scores."""
    tag = "mock" if mock else provider
    return Path(cache_dir) / f"{domain}__{icp.fingerprint()}__{tag}.json"


def score_company(
    icp: ICP,
    domain: str,
    page_text: str,
    cache_dir: str | Path = ".cache/scores",
    mock: bool = False,
    refresh: bool = False,
    model: str = "",
    provider: str = "",
) -> CompanyResult:
    provider = (provider or DEFAULT_PROVIDER).lower()
    path = cache_path(cache_dir, domain, icp, mock, provider)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            if mock:
                payload = score_mock(icp, domain, page_text)
            elif provider == "gemini":
                payload = score_with_gemini(icp, domain, page_text, model or GEMINI_MODEL)
            elif provider == "anthropic":
                payload = score_with_claude(icp, domain, page_text, model or DEFAULT_MODEL)
            else:
                raise ValueError(
                    "Unknown MODEL_PROVIDER: " + provider + ". Use anthropic or gemini."
                )
        except Exception as exc:  # noqa: BLE001 - one bad domain must not kill the run
            return CompanyResult(domain=domain, score=0.0, tier="C", error=str(exc)[:200])
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return finalise(icp, domain, payload, page_text)
