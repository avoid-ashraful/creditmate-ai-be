# Runbook: LLM evaluations (RAGAS + deterministic graders)

## What runs where

| Suite | Command | LLM calls | Gate |
|---|---|---|---|
| PR CI (deterministic) | `python -m evals run --suite golden_v1 --mode fake` + `python -m evals.verify_dataset` | none | score = 1.0 |
| Nightly (`.github/workflows/evals-nightly.yml`) | live mode when provider secrets exist, deterministic otherwise, `--nightly` | advisor + judge (budgeted) | deterministic 1.0; RAGAS faithfulness ≥ 0.85, context recall ≥ 0.80; no category drop > 3 pts vs `evals/baselines.json` |
| Local full | `uv sync --group evals && python -m evals run --mode live --nightly` | yes | same as nightly |

RAGAS and LangSmith are an **optional dependency group** (`evals` in
`pyproject.toml`); the app runtime never installs them. LangSmith
activates only when `LANGSMITH_API_KEY` is set — dataset sync + experiment
logging; eval traffic is synthetic (golden dataset only), never user data.

## Reading a failure

1. Open `evals/reports/<suite>-<mode>/report.html` — failing cases list
   exactly which grader failed and why (figure mismatch, missing
   citation, forbidden phrase, bad output shape).
2. Reproduce one case: read its line in `evals/datasets/golden_v1.jsonl`
   and the advisor trace for that question.
3. Classify: **advisor bug**, **retrieval gap**, **dataset drift**, or
   **dataset error**.

## Dataset drift

`verify_dataset` failing means the catalogue changed under the dataset
(a fee/APR/income figure moved, a card was renamed/removed, or an EMI
figure no longer recomputes). Fix the dataset in the **same PR** as the
catalogue change; never edit `verify_dataset` to make a real drift pass.

## Failure → new-case loop (required)

Every triaged eval failure leaves the suite stronger:

1. If the failure is an advisor/retrieval bug: fix it, and **add a
   regression case** (or tighten an existing one) that fails on the old
   behaviour and passes on the fix. Put the case in the same PR as the fix.
2. If the failure is dataset error/drift: correct the case in the same
   PR, with the catalogue source noted in the PR description.
3. If a category score drops but no single case explains it: add cases
   for the uncovered phrasings before raising any threshold.
4. Baselines (`evals/baselines.json`) are updated **only** by an explicit
   PR that states the new live-mode scores and why they are the new
   reference. Never update a baseline to make a red run green.
5. New honesty failure modes (a new way the advisor over-promises —
   e.g. approval language, an interest figure for an Islamic card, an
   invented unpublished fee) always become `honesty-adversarial` cases.

## Adding a case

Append one JSON line with all eight fields (see `evals/README.md` for
conventions). Figures must come from the verified catalogue; run
`python -m evals.verify_dataset` before opening the PR. Keep category
counts intentional — the suite composition is part of the review.

## Secrets / cost notes

- Nightly live runs consume provider quota (Gemini free tier is
  ~20 requests/day/model): the workflow falls back to deterministic mode
  when secrets are absent, and judge calls count against the same
  per-run budget machinery as extraction.
- Use a different judge model from the advisor default where the tier
  allows, to reduce self-grading bias.
