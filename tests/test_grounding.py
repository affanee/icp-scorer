"""The grounding guard is the most important logic in the repo, so it gets the most tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from icp_scorer.grounding import is_grounded, normalise, similarity

SOURCE = (
    "--- PAGE: / --- Acme builds revenue intelligence software for B2B sales teams. "
    "We are hiring a Revenue Operations Manager to scale our outbound motion. "
    "Book a demo with our sales team today. Trusted by over 200 companies."
)


def test_exact_quote_is_grounded():
    assert is_grounded("We are hiring a Revenue Operations Manager", SOURCE)


def test_case_and_whitespace_differences_still_ground():
    assert is_grounded("we  are HIRING a revenue operations manager", SOURCE)


def test_punctuation_differences_still_ground():
    assert is_grounded("Book a demo with our sales team, today!", SOURCE)


def test_invented_quote_is_rejected():
    assert not is_grounded("Acme raised a $50M Series C led by Sequoia", SOURCE)


def test_plausible_but_absent_quote_is_rejected():
    # This is the dangerous case: it sounds like the page but is not on it.
    assert not is_grounded("We serve enterprise customers across fifty countries", SOURCE)


def test_too_short_quote_is_rejected():
    # "sales" appears on the page but grounds nothing.
    assert not is_grounded("sales", SOURCE)


def test_empty_quote_is_rejected():
    assert not is_grounded("", SOURCE)


def test_similarity_is_bounded():
    assert similarity("Book a demo with our sales team today", SOURCE) == 1.0
    assert 0.0 <= similarity("completely unrelated text here", SOURCE) <= 1.0


def test_normalise_collapses_noise():
    assert normalise("  Hello,   WORLD!!  ") == "hello world"
