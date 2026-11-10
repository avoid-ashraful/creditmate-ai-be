# CreditMate LLM evaluation harness

Standalone package (not a Django app, not in `INSTALLED_APPS`, nothing in
the request path imports it). It evaluates the CreditMate advisor and
retrieval grounding against a versioned golden dataset.

## Quick start (offline, zero LLM calls)

```bash
python -m evals.verify_dataset          # dataset facts vs real catalogue
python -m evals run --suite golden_v1 --mode fake
# -> evals/reports/golden_v1-fake/report.json + report.html, gates PASS/FAIL
```

Fake mode builds stub responses from each case's own expected facts. It
proves the harness end-to-end and seeds `baselines.json`; it is **not** a
measure of advisor quality.

## Live mode

```bash
uv sync --group evals                   # optional: ragas, langsmith, datasets
python -m evals run --suite golden_v1 --mode live --nightly
```

Live mode calls the advisor through an import guard
(`advisor.services.ask_advisor` / `advisor.graph.run_advisor`). On a tree
without the advisor app it exits with code 2 and a clear message.
Retrieval Recall@k activates automatically if `retrieval.service`
exposes `search_chunk_ids(question, k)`; otherwise it is skipped, not
failed.

## Layout

| File | Purpose |
|---|---|
| `datasets/golden_v1.jsonl` | 80 cases: factual 15, comparison 12, eligibility 12, calculators 8, grounding 15, honesty-adversarial 12, fallback 6 |
| `verify_dataset.py` | Re-checks every verifiable figure against the Django catalogue (or the verified fixture) and EMI math; fails on drift |
| `graders.py` | Deterministic graders: figure-match, citation validity, forbidden-phrase/honesty vocabulary, output-shape (Pydantic), expected products, Recall@k hook |
| `runner.py` | Fake/live runners, stub responses, regression gates |
| `ragas_runner.py` | Import-guarded RAGAS (faithfulness, answer relevancy, context precision/recall) |
| `langsmith_adapter.py` | No-op unless `LANGSMITH_API_KEY` is set; then syncs the dataset and logs the experiment |
| `reports.py` | JSON + HTML report rendering |
| `baselines.json` | Stored baseline (currently a clearly marked fake-mode seed) |

## Dataset conventions

- Product ids are slugs of `"<bank> <name>"` (stable across DB rebuilds).
- `expected_facts` keys: `annual_fee_bdt`, `interest_rate_apr_percent`,
  `min_monthly_income_bdt` (`null` = no published requirement), plus
  slug-qualified variants (`annual_fee_bdt:<slug>`) in comparison cases,
  and calculator inputs/outputs (`principal_bdt`, `tenure_months`,
  `expected_emi_bdt` recomputed from the card's published APR).
- Figures come only from the verified catalogue fixture
  (`credit_cards/fixtures/verified_cards_2026-10-18.json`). Where a figure
  is not published, cases assert the *absence* (honesty/eligibility
  vocabulary) instead of inventing a number.
- Islamic cards publish no APR: no case assigns them an interest figure,
  and honesty cases cover asking for one.

## Gates

- **PR CI (deterministic):** score must be 1.0.
- **Nightly:** when RAGAS scores exist, faithfulness ≥ 0.85 and
  context recall ≥ 0.80, and no category may drop > 3 points vs
  `baselines.json`. Baselines change only via an explicit PR.

See `docs/runbooks/llm-evals.md` for operations and the
failure → new-case loop.
