# Retrieval tuning — measurement record (SKELETON)

Status: **harness built; sweep deferred to the final consolidated test
pass** (per Ash's reduced-testing direction for the parallel build).
No quality numbers are claimed in this PR.

## Harness

- Golden set: `retrieval/fixtures/golden_queries.json` (~30 queries from
  real catalogue concepts; keyword-scored, with optional `relevant`
  product ids for Recall@k/MRR where a local catalogue is pinned).
- Runner: `python manage.py run_retrieval_eval` (cosine vs hybrid) after
  `python manage.py backfill_embeddings --provider fake|gemini|local`.
- Metrics: Recall@5, Recall@10, MRR (`retrieval/evaluation.py`), plus
  keyword recall for id-less cases.

## Sweep to run in the consolidated pass

| Dimension | Values |
|---|---|
| Mode | cosine-only vs hybrid RRF (vector + Postgres FTS) |
| Chunk target tokens | 300 / 500 (default) / 800 |
| HNSW `ef_search` | 20 / 40 / 100 (`SET LOCAL hnsw.ef_search`) |
| Provider | fake (plumbing only, never quoted) / gemini / local MiniLM |

## Results

_To be filled with measured values only, from the consolidated pass.
The chosen production configuration must be the measured winner of this
table — do not assert a configuration as "best" without it._

| Config | Recall@5 | Recall@10 | MRR | Keyword recall | Notes |
|---|---|---|---|---|---|
| _pending_ | | | | | |
