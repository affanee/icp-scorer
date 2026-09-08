"""Command line entry point.

    python -m icp_scorer score --input data/domains_sample.csv
    python -m icp_scorer score --input data/domains_sample.csv --mock
    python -m icp_scorer explain stripe.com
"""

from __future__ import annotations

import argparse
import sys

from .config import load_icp
from .fetch import clean_domain, fetch_company_text
from .pipeline import run
from .scoring import score_company


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="icp-scorer", description=__doc__)
    parser.add_argument("--rubric", default="icp.yaml", help="path to the ICP rubric")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="score a CSV of domains")
    p_score.add_argument("--input", required=True)
    p_score.add_argument("--out-csv", default="out/scored.csv")
    p_score.add_argument("--out-json", default="out/scored.json")
    p_score.add_argument("--limit", type=int, default=None)
    p_score.add_argument("--mock", action="store_true", help="run with no API key (demo only)")
    p_score.add_argument("--refresh", action="store_true", help="ignore caches")
    p_score.add_argument(
        "--fixtures",
        default=None,
        help="read page text from this folder instead of the internet (offline demo)",
    )

    p_explain = sub.add_parser("explain", help="score one domain and print the evidence")
    p_explain.add_argument("domain")
    p_explain.add_argument("--mock", action="store_true")
    p_explain.add_argument("--refresh", action="store_true")
    p_explain.add_argument("--fixtures", default=None)

    args = parser.parse_args(argv)
    icp = load_icp(args.rubric)

    if args.command == "score":
        run(
            icp,
            args.input,
            out_csv=args.out_csv,
            out_json=args.out_json,
            mock=args.mock,
            refresh=args.refresh,
            limit=args.limit,
            fixtures_dir=args.fixtures,
        )
        return 0

    if args.command == "explain":
        domain = clean_domain(args.domain)
        text = fetch_company_text(domain, refresh=args.refresh, fixtures_dir=args.fixtures)
        if not text:
            print(f"Could not retrieve any page text for {domain}")
            return 1
        result = score_company(icp, domain, text, mock=args.mock, refresh=args.refresh)
        if result.error:
            print(f"ERROR: {result.error}")
            return 1

        print(f"\n{domain}   {result.score}/100   Tier {result.tier}")
        print(f"{result.summary}\n")
        for d in result.dimensions:
            if not d.grounded:
                mark = "!! "   # model invented the quote; score zeroed
            elif d.score == 0 and not d.evidence:
                mark = "-- "   # honestly found nothing, which is allowed
            else:
                mark = "OK "
            print(f"{mark}{d.key:<16} {d.score}/3   (grounding {d.grounding_score})")
            if d.evidence:
                print(f'      "{d.evidence[:150]}"')
            if not d.grounded:
                print(f"      REJECTED - quote not found in source. Model wanted {d.original_score}/3.")
            print()
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
