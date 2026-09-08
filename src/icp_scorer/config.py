"""Load the ICP rubric from icp.yaml and turn it into objects the rest of the code uses.

Why this is a YAML file and not hard-coded in Python:
the rubric is the part a GTM person needs to edit weekly. Keeping it in one
readable file means changing your ICP never means touching code, and the
fingerprint below means changing it automatically invalidates cached scores.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MAX_DIMENSION_SCORE = 3


@dataclass(frozen=True)
class Dimension:
    key: str
    question: str
    guidance: dict[str, str]
    weight: float = 1.0


@dataclass(frozen=True)
class ICP:
    name: str
    description: str
    dimensions: tuple[Dimension, ...]
    tier_a_min: float
    tier_b_min: float
    fit_threshold: float
    raw: dict[str, Any]

    @property
    def max_weighted(self) -> float:
        """The highest weighted score achievable, used to normalise to 0-100."""
        return sum(MAX_DIMENSION_SCORE * d.weight for d in self.dimensions)

    def normalise(self, weighted_total: float) -> float:
        """Convert a weighted raw total into a 0-100 score."""
        if self.max_weighted == 0:
            return 0.0
        return round(100 * weighted_total / self.max_weighted, 1)

    def tier(self, score_100: float) -> str:
        if score_100 >= self.tier_a_min:
            return "A"
        if score_100 >= self.tier_b_min:
            return "B"
        return "C"

    def fingerprint(self) -> str:
        """A short hash of the rubric.

        Cached scores are keyed by this, so editing icp.yaml automatically
        invalidates every cached score instead of silently serving stale ones.
        This is the single most useful line in the file.
        """
        canonical = yaml.safe_dump(self.raw, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:10]


def load_icp(path: str | Path = "icp.yaml") -> ICP:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No rubric at {path}. Copy icp.yaml from the repo root.")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    dims_raw = raw.get("dimensions") or []
    if not dims_raw:
        raise ValueError("icp.yaml has no dimensions. A rubric with no dimensions scores nothing.")

    dimensions = []
    seen: set[str] = set()
    for d in dims_raw:
        key = d["key"]
        if key in seen:
            raise ValueError(f"Duplicate dimension key '{key}' in icp.yaml")
        seen.add(key)
        dimensions.append(
            Dimension(
                key=key,
                question=" ".join(d["question"].split()),
                guidance={str(k): v for k, v in (d.get("guidance") or {}).items()},
                weight=float(d.get("weight", 1.0)),
            )
        )

    tiers = raw.get("tiers") or {}
    return ICP(
        name=raw.get("name", "Unnamed ICP"),
        description=" ".join((raw.get("description") or "").split()),
        dimensions=tuple(dimensions),
        tier_a_min=float(tiers.get("a_min", 75)),
        tier_b_min=float(tiers.get("b_min", 55)),
        fit_threshold=float(raw.get("fit_threshold", tiers.get("b_min", 55))),
        raw=raw,
    )
