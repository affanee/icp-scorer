"""The hallucination guard.

The model is asked to justify every score with a verbatim quote from the
company's own website. This module checks whether that quote is actually there.

If a quote can't be found in the source text, the score for that dimension is
forced to 0 and flagged. That is the difference between "AI scored this account"
and "AI scored this account and I can show you the sentence it used".

Exact string matching is too brittle - models normalise whitespace, fix typos,
and drop trailing punctuation. So we do two passes:

  1. Normalised substring match (fast, catches ~90% of honest quotes).
  2. Fuzzy match against a sliding window (catches near-verbatim paraphrase).

Anything below the similarity threshold is treated as invented.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

DEFAULT_THRESHOLD = 0.85
MIN_QUOTE_CHARS = 12


def normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip smart quotes and punctuation noise."""
    text = text.lower()
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9'\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(quote: str, source: str) -> float:
    """Best similarity between the quote and any same-length window of the source.

    Returns 0.0-1.0. A normalised exact substring short-circuits to 1.0.
    """
    q = normalise(quote)
    s = normalise(source)
    if not q or not s:
        return 0.0
    if q in s:
        return 1.0

    # Slide a window roughly the length of the quote across the source.
    # Step by a quarter of the window so we never straddle a match badly.
    window = len(q)
    step = max(1, window // 4)
    best = 0.0
    matcher = SequenceMatcher(a=q, autojunk=False)
    for start in range(0, max(1, len(s) - window + 1), step):
        matcher.set_seq2(s[start : start + window])
        ratio = matcher.ratio()
        if ratio > best:
            best = ratio
            if best >= 0.99:
                break
    return round(best, 3)


def is_grounded(quote: str, source: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True if the quote genuinely appears in the source text.

    A very short quote is rejected outright: "we" appears in every website ever
    and grounding a score on it would be meaningless.
    """
    if not quote or len(quote.strip()) < MIN_QUOTE_CHARS:
        return False
    return similarity(quote, source) >= threshold
