import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from icp_scorer.config import load_icp


def test_rubric_loads():
    icp = load_icp(ROOT / "icp.yaml")
    assert icp.dimensions
    assert icp.max_weighted > 0


def test_normalisation_maps_perfect_score_to_100():
    icp = load_icp(ROOT / "icp.yaml")
    assert icp.normalise(icp.max_weighted) == 100.0
    assert icp.normalise(0) == 0.0


def test_tiers_are_ordered():
    icp = load_icp(ROOT / "icp.yaml")
    assert icp.tier(100) == "A"
    assert icp.tier(icp.tier_b_min) == "B"
    assert icp.tier(0) == "C"


def test_fingerprint_changes_when_rubric_changes():
    icp = load_icp(ROOT / "icp.yaml")
    before = icp.fingerprint()
    mutated = dict(icp.raw)
    mutated["name"] = "something else entirely"
    from icp_scorer.config import ICP

    after = ICP(
        icp.name, icp.description, icp.dimensions,
        icp.tier_a_min, icp.tier_b_min, icp.fit_threshold, mutated,
    ).fingerprint()
    assert before != after


def test_missing_rubric_raises():
    with pytest.raises(FileNotFoundError):
        load_icp(ROOT / "does_not_exist.yaml")
