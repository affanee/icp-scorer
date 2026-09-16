"""Run the scorer over a CSV of domains and write results out."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from .config import ICP
from .fetch import clean_domain, fetch_company_text
from .scoring import CompanyResult, score_company


def read_domains(path: str | Path) -> list[str]:
    """Accept a CSV with a 'domain' column, or a plain one-per-line list."""
    path = Path(path)
    rows: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        if "domain" in sample.splitlines()[0].lower():
            for row in csv.DictReader(fh):
                key = next((k for k in row if k and k.lower().strip() == "domain"), None)
                if key and row[key]:
                    rows.append(clean_domain(row[key]))
        else:
            rows = [clean_domain(line) for line in fh if line.strip()]
    seen: set[str] = set()
    return [d for d in rows if d and not (d in seen or seen.add(d))]


def run(
    icp: ICP,
    input_path: str | Path,
    out_csv: str | Path = "out/scored.csv",
    out_json: str | Path = "out/scored.json",
    mock: bool = False,
    refresh: bool = False,
    limit: int | None = None,
    fixtures_dir: str | None = None,
    provider: str = "",
) -> list[CompanyResult]:
    domains = read_domains(input_path)
    if limit:
        domains = domains[:limit]

    results: list[CompanyResult] = []
    for i, domain in enumerate(domains, 1):
        print(f"[{i}/{len(domains)}] {domain}", end=" ", flush=True)
        text = fetch_company_text(domain, refresh=refresh, fixtures_dir=fixtures_dir)
        result = score_company(
            icp, domain, text, mock=mock, refresh=refresh, provider=provider
        )
        results.append(result)
        if result.error:
            print(f"ERROR: {result.error}")
        else:
            flag = f"  [{result.ungrounded_count} ungrounded]" if result.ungrounded_count else ""
            print(f"-> {result.score:5.1f}  Tier {result.tier}{flag}")

    _write(results, out_csv, out_json)
    return results


def _write(results: list[CompanyResult], out_csv: str | Path, out_json: str | Path) -> None:
    if not results:
        return
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)

    rows = [r.to_row() for r in results]
    fieldnames: list[str] = []
    for row in rows:
        for k in row:
            if k not in fieldnames:
                fieldnames.append(k)

    with Path(out_csv).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    from dataclasses import asdict

    Path(out_json).write_text(
        json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
    )
    print(f"\nWrote {len(results)} rows to {out_csv} and {out_json}", file=sys.stderr)
