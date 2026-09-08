.PHONY: install test demo score eval explain clean

install:
	python3 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "Done. Activate it with:  source .venv/bin/activate"

test:
	python -m pytest tests -q

## Runs the whole pipeline with no API key. Proves the plumbing works.
demo:
	PYTHONPATH=src python -m icp_scorer score --input data/domains_demo.csv --mock --fixtures data/fixtures

## The real thing. Needs ANTHROPIC_API_KEY in .env
score:
	PYTHONPATH=src python -m icp_scorer score --input data/domains_sample.csv

## Measure the scorer against your hand-labelled set.
eval:
	python evals/run_eval.py

eval-mock:
	python evals/run_eval.py --labels evals/labels_demo.csv --mock --fixtures data/fixtures

## Score one company and show every quote it used.
explain:
	PYTHONPATH=src python -m icp_scorer explain $(DOMAIN)

clean:
	rm -rf .cache out .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
