#!/usr/bin/env python3
"""Measure the scorer against hand-labelled ground truth.

This is the part almost nobody builds, and it is the reason this repo is worth
showing anyone. Without it you have a machine that produces confident numbers
you cannot check. With it you have an instrument with a known error rate.

    python evals/run_eval.py                 # needs ANTHROPIC_API_KEY
    python evals/run_eval.py --mock          # runs offline, proves the harness

The labels in evals/labels.csv are OPINIONS - yours. Disagree with any of them
and change them. The scorer is measured against your judgment, which is exactly
the thing you are trying to scale.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from icp_scorer.config import load_icp           # noqa: E402
from icp_scorer.fetch import fetch_company_text  # noqa: E402
from icp_scorer.scoring import score_company     # noqa: E402


def load_labels(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("domain")]


def confusion(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs is a list of (actual_fit, predicted_fit)."""
    tp = sum(1 for a, p in pairs if a and p)
    fp = sum(1 for a, p in pairs if not a and p)
    fn = sum(1 for a, p in pairs if a and not p)
    tn = sum(1 for a, p in pairs if not a and not p)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(pairs) if pairs else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="evals/labels.csv")
    ap.add_argument("--rubric", default="icp.yaml")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--fixtures", default=None, help="offline page text folder")
    args = ap.parse_args()

    icp = load_icp(args.rubric)
    rows = load_labels(Path(args.labels))
    if args.limit:
        rows = rows[: args.limit]

    threshold = icp.fit_threshold
    print(f"Rubric      : {icp.name}")
    print(f"Fingerprint : {icp.fingerprint()}")
    print(f"Threshold   : score >= {threshold} counts as 'fit'")
    print(f"Labelled set: {len(rows)} companies")
    print(f"Mode        : {'MOCK (no model called)' if args.mock else 'live'}\n")
    if args.mock:
        print("!! Mock mode produces deterministic nonsense scores. The numbers below\n   prove the harness runs. They are NOT a result. Never quote them.\n")

    pairs: list[tuple[bool, bool]] = []
    misses: list[tuple[str, str, float, str]] = []
    scores: list[tuple[str, bool, float]] = []
    ungrounded_total = 0

    for i, row in enumerate(rows, 1):
        domain = row["domain"].strip()
        actual = row["label"].strip().lower() == "fit"
        text = fetch_company_text(domain, refresh=args.refresh, fixtures_dir=args.fixtures)
        result = score_company(icp, domain, text, mock=args.mock, refresh=args.refresh)
        ungrounded_total += result.ungrounded_count

        predicted = result.score >= threshold
        pairs.append((actual, predicted))
        scores.append((domain, actual, result.score))

        mark = "." if actual == predicted else "X"
        print(
            f"{mark} [{i:>2}/{len(rows)}] {domain:<22} "
            f"score {result.score:>5.1f}  actual {'fit' if actual else 'not_fit':<8} "
            f"predicted {'fit' if predicted else 'not_fit'}"
            + (f"  ERROR {result.error}" if result.error else "")
        )
        if actual != predicted:
            kind = "FALSE NEGATIVE (missed a good account)" if actual else "FALSE POSITIVE (wasted a rep's time)"
            misses.append((domain, kind, result.score, row.get("note", "")))

    m = confusion(pairs)

    print("\n" + "=" * 62)
    print("CONFUSION MATRIX".center(62))
    print("=" * 62)
    print(f"{'':<22}{'predicted fit':>18}{'predicted not':>18}")
    print(f"{'actually fit':<22}{m['tp']:>18}{m['fn']:>18}")
    print(f"{'actually not fit':<22}{m['fp']:>18}{m['tn']:>18}")
    print("-" * 62)
    print(f"Precision {m['precision']:.1%}   of accounts it flagged, this many were really fit")
    print(f"Recall    {m['recall']:.1%}   of the really-fit accounts, it caught this many")
    print(f"F1        {m['f1']:.1%}")
    print(f"Accuracy  {m['accuracy']:.1%}   ({m['tp'] + m['tn']}/{len(pairs)})")
    print(f"Ungrounded evidence quotes rejected: {ungrounded_total}")

    if misses:
        print("\n" + "-" * 62)
        print("WHERE IT WENT WRONG - fix the rubric here, not the code")
        print("-" * 62)
        for domain, kind, score, note in misses:
            print(f"  {domain:<22} {score:>5.1f}  {kind}")
            if note:
                print(f"  {'':<22}        your note: {note}")

    # Threshold sweep: would a different cut-off do better on this same data?
    print("\n" + "-" * 62)
    print("THRESHOLD SWEEP - accuracy if you moved the fit cut-off")
    print("-" * 62)
    best = (0.0, threshold)
    for t in range(20, 95, 5):
        swept = [(a, s >= t) for _, a, s in scores]
        acc = confusion(swept)["accuracy"]
        star = ""
        if acc > best[0]:
            best = (acc, t)
        print(f"  cut-off {t:>3}   accuracy {acc:>6.1%}{star}")
    print(f"\n  Best on this set: cut-off {best[1]} at {best[0]:.1%} accuracy.")
    print("  (Careful: tuning the cut-off to the eval set is how you fool yourself.")
    print("   Move it only if the reason makes sense in GTM terms.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
