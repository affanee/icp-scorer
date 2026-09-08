"""Scoring behaviour, with no network and no API key."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from icp_scorer.config import load_icp
from icp_scorer.fetch import clean_domain
from icp_scorer.scoring import build_tool, finalise

SOURCE = (
    "Acme builds revenue intelligence software for B2B sales teams. "
    "We are hiring a Revenue Operations Manager to scale our outbound motion. "
    "Book a demo with our sales team today."
)


def icp():
    return load_icp(ROOT / "icp.yaml")


def test_tool_schema_matches_rubric():
    tool = build_tool(icp())
    keys = tool["input_schema"]["properties"]["dimensions"]["items"]["properties"]["key"]["enum"]
    assert keys == [d.key for d in icp().dimensions]


def test_ungrounded_score_is_zeroed_and_flagged():
    payload = {
        "dimensions": [
            {
                "key": "segment",
                "score": 3,
                "evidence": "Acme raised a $90M Series D led by Sequoia Capital",
                "reasoning": "invented",
            }
        ],
        "summary": "test",
    }
    result = finalise(icp(), "acme.com", payload, SOURCE)
    segment = next(d for d in result.dimensions if d.key == "segment")
    assert segment.score == 0
    assert segment.grounded is False
    assert segment.original_score == 3
    assert result.ungrounded_count == 1


def test_grounded_score_survives():
    payload = {
        "dimensions": [
            {
                "key": "gtm_motion",
                "score": 3,
                "evidence": "Book a demo with our sales team today",
                "reasoning": "explicit sales CTA",
            }
        ],
        "summary": "test",
    }
    result = finalise(icp(), "acme.com", payload, SOURCE)
    gtm = next(d for d in result.dimensions if d.key == "gtm_motion")
    assert gtm.score == 3
    assert gtm.grounded is True
    assert result.ungrounded_count == 0


def test_missing_dimensions_default_to_zero_not_crash():
    result = finalise(icp(), "acme.com", {"dimensions": [], "summary": ""}, SOURCE)
    assert result.score == 0.0
    assert result.tier == "C"
    assert len(result.dimensions) == len(icp().dimensions)


def test_out_of_range_scores_are_clamped():
    payload = {
        "dimensions": [
            {"key": "segment", "score": 99, "evidence": "revenue intelligence software for B2B sales teams", "reasoning": "x"}
        ],
        "summary": "",
    }
    result = finalise(icp(), "acme.com", payload, SOURCE)
    assert next(d for d in result.dimensions if d.key == "segment").score == 3


def test_domain_cleaning():
    assert clean_domain("https://www.Acme.com/pricing?utm=x") == "acme.com"
    assert clean_domain("  ACME.COM  ") == "acme.com"
