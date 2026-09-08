# Context for Claude Code

Read this before changing anything in this repo.

## What this is

`icp-scorer` scores B2B accounts against a written ICP rubric using Claude, and
measures its own accuracy against a hand-labelled set. It is a GTM engineering
tool, not a general-purpose scraper.

## Non-negotiables

1. **Grounding is not optional.** Any dimension scored above 0 must carry a
   verbatim quote that exists in the fetched page text. If you are tempted to
   relax this to improve scores, you have misunderstood the project.
2. **Never fabricate eval numbers.** The results table in the README is filled
   in from real runs only. If a number wasn't produced by `make eval`, it does
   not go in a document.
3. **The rubric lives in `icp.yaml`.** Scoring logic never hard-codes dimension
   names, weights, or thresholds. Adding a dimension to the YAML must require
   zero code changes.
4. **Cache keys include `icp.fingerprint()`.** Any new cache must too, or
   editing the rubric will silently serve stale scores.
5. **One bad domain must never kill a run.** Errors are captured per company
   and written to the output row.

## The ICP being scored for

B2B SaaS, roughly 50–500 employees, sells to revenue teams (sales, marketing,
RevOps), runs a human outbound motion. Product-led self-serve companies are a
poor fit regardless of size, because there is no sales team to sell into.

## Conventions

- Python 3.10+. Standard library first; a dependency needs a reason.
- `src/` layout. Tests run with `PYTHONPATH=src` via `pytest.ini`.
- Everything must run offline: `make test` and `make demo` never touch the
  network or need an API key. Fixtures in `data/fixtures/` are fictional
  companies; do not add real companies' text there.
- Docstrings explain *why*, not *what*. The what is readable from the code.

## Commands

    make test        # 20 tests, offline
    make demo        # full pipeline, offline, no key
    make score       # real run, needs ANTHROPIC_API_KEY
    make eval        # accuracy against evals/labels.csv
    make explain DOMAIN=gong.io
