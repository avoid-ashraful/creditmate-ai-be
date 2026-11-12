# CreditMate AI — Backend

The API behind CreditMate AI: a comparison platform for banking products in
Bangladesh — credit cards, deposits, loans, and bank accounts — built entirely
on **published data with provenance**. Every figure the API serves traces back
to a bank-published source or an official Bangladesh Bank chart, and passes a
human review gate before it becomes public.

[![Tests](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/tests.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/tests.yml)
[![Code Quality](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/code-quality.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/code-quality.yml)
[![Migration Checks](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/migrations.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/migrations.yml)
[![Security Checks](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/security.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/security.yml)
[![Workflow Audit (zizmor)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/workflow-audit.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/workflow-audit.yml)
[![Secret Scan (gitleaks)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/secret-scan.yml)
[![LLM Evals (nightly)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/evals-nightly.yml/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions/workflows/evals-nightly.yml)

> **Status:** pre-launch, in active development. Some capabilities are merged
> behind feature flags and are off by default (see
> [Feature flags](#feature-flags)).

**Related repositories:**
[Umbrella (Helm charts, platform docs)](https://github.com/avoid-ashraful/creditmate-ai) ·
[Frontend (React + TypeScript)](https://github.com/avoid-ashraful/creditmate-ai-fe)

---

## What the API serves

| Vertical | Catalogue | Notes |
| --- | --- | --- |
| Credit cards | 135 catalogued, 105 public | Fees, APRs, rewards, lounge access, per-field provenance and fee-change history |
| Deposits | 80 products, 367 rates | Seeded from Bangladesh Bank's official rate charts; FDR ranking net of tax, DPS with IRR-based effective yield; Sanchayapatra shown as an unranked government benchmark |
| Loans | 50 products, 15 lenders | Rates published as **bands, never invented point rates**; scenario costing at both band ends; regulatory caps as dated configuration |
| Bank accounts | 87 products, 11 banks | Rate slabs kept as published; ranking by net annual value at the user's balance |

On top of the catalogues:

- **Eligibility checker** — a stateless endpoint
  (`POST /api/v1/credit-cards/eligibility/`) that stores nothing. It takes
  income, employment type, TIN and CIB self-declaration and returns each card
  as Eligible / Likely / No published requirement / Not yet, with reasons
  quoting the published numbers. Results are estimates — the API never claims
  pre-approval or a guarantee.
- **CreditMate Score** — a 0–10 score computed only from published card data
  (annual cost, interest vs the 25% Bangladesh Bank cap, rewards, lounge
  perks, data confidence), with the weights published in the methodology and
  a per-component breakdown per card.
- **Calculators** — EMI and payoff tools using real cards' published APRs;
  cards with no published APR (including Islamic cards) require a custom
  rate rather than pretending 0%.
- **Community reviews** — public ratings, reviews and comments for all four
  product types (50+ approved reviews earn a "Community reviewed" marker).
- **Personalisation** — JWT accounts with server-stored profiles (only the
  numbers a user volunteers), cross-device shortlists, saved searches,
  bank-follow and a per-user change-alerts feed. Eligibility inputs are
  never stored.

Islamic products are modelled on their own terms throughout: expected
profit, never "interest".

## Architecture

Django 5.2 / DRF monolith with Celery workers, organised by vertical. The
data pipeline is deliberately conservative:

```
 bank pages / BB charts ──▶ crawl ──▶ SHA-256 change detection
        ──▶ LLM extraction (draft only) ──▶ review queue ──▶ verified data
```

No automated path can modify verified data: extraction output lands in a
draft/review queue, and only a human approval promotes it. Sources that
don't change cost zero LLM calls.

### Django apps

| App | Responsibility |
| --- | --- |
| `credit_cards` | Card catalogue, provenance/field history, eligibility, CreditMate Score |
| `banks` | Bank directory and bank-level pages data |
| `deposits` | Deposit products, BB chart snapshots, tax rules, scenario ranking |
| `loans` | Loan products, rate bands, regulatory caps, scenario costing |
| `bank_accounts` | Account products, fee schedules, net-value ranking |
| `accounts` | Auth (JWT), user profiles |
| `saved` | Shortlists and saved searches |
| `alerts` | Bank-follow and change alerts |
| `reviews` | Community ratings, reviews, comments for all product types |
| `search` | Elasticsearch-backed search (can be disabled with `SEARCH_ENABLED=False`) |
| `common` | Shared infrastructure: LLM provider abstraction, embeddings, usage ledger |
| `streaming` | Kafka event streaming via the transactional outbox pattern *(flag-gated)* |
| `retrieval` | pgvector document store, chunking and hybrid search *(flag-gated)* |
| `advisor` | LangGraph advisor agent + MCP server *(flag-gated)* |
| `evals/` | Standalone LLM evaluation harness (not a Django app) |

## AI components

- **Extraction pipeline** — provider-agnostic LLM layer (`common/llm`) with
  Gemini, OpenRouter and Claude providers; per-run call budgets
  (`LLM_MAX_CALLS_PER_RUN`), provider ordering (`LLM_PROVIDER_ORDER`) and the
  extraction model set via `GEMINI_MODEL`.
- **Cost & latency engineering** — an `LLMUsage` ledger records every call's
  tokens, cost (only when the provider reports it — never estimated) and
  latency, with dated price configuration, per-run/session budgets,
  routing, retry/backoff, a circuit breaker and Prometheus metrics.
- **Advisor** — a LangGraph agent over 7 read-only tools (card search,
  detail, compare, eligibility, calculators, product search, retrieval
  grounding), also exposed through an MCP server built on the official SDK.
  Answers are validated and must cite published data. See
  [the ADR](docs/adr/advisor-langgraph-mcp-vs-bedrock.md) for why LangGraph +
  MCP over Bedrock Agents.
- **Retrieval** — structure-aware chunking of product documents into
  pgvector (HNSW cosine + full-text, hybrid RRF ranking) with provenance on
  every chunk. Embeddings are provider-pluggable (Gemini/OpenAI/local).
  See [the ADR](docs/adr/pgvector-vs-managed-vector-dbs.md).
- **Streaming** — transactional outbox → Kafka (Redpanda locally) with
  idempotent consumers, a dead-letter topic and replay. Consumers may only
  create review-queue drafts. See [the ADR](docs/adr/kafka-streaming.md).
- **Evaluation** — an 80-case golden dataset built from the verified card
  fixture (factual, comparison, eligibility, calculator, grounding, honesty
  and fallback cases) with deterministic graders; RAGAS and LangSmith are
  optional, key-guarded adapters over a local-first harness.

## Tech stack

- **Python 3.14** (`.python-version`; CI also tests 3.13), **Django 5.2**,
  **Django REST Framework 3.17**, **Celery 5.6**
- **PostgreSQL 17 + pgvector**, **Redis 7**, **Elasticsearch 8**
- **drf-spectacular** (OpenAPI), **SimpleJWT**, **prometheus-client**,
  **Sentry**
- **LangGraph**, **MCP SDK**, **confluent-kafka**, **pgvector** (Python)
- Tooling: **uv**, **pytest**, **black / isort / flake8**

## Local development

Prerequisites: Python 3.14 (or 3.13), [uv](https://docs.astral.sh/uv/),
PostgreSQL 17 with the pgvector extension, and Redis. Elasticsearch is
optional (`SEARCH_ENABLED=False`).

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env        # then fill in SECRET_KEY, DB_* and any LLM keys

# 3. Start backing services (Postgres + Redis; add the search/streaming
#    compose files only if you need them)
docker compose up -d db redis
# docker compose -f docker-compose.yml -f docker-compose.search.yml up -d
# docker compose -f docker-compose.yml -f docker-compose.streaming.yml up -d

# 4. Migrate and run
uv run python manage.py migrate
uv run python manage.py runserver

# 5. Workers (separate terminals)
uv run celery -A credit_mate_ai worker -l info
uv run celery -A credit_mate_ai beat -l info
```

The API is then at `http://localhost:8000/api/v1/`, with interactive docs at
`/api/v1/docs/swagger/` and `/api/v1/docs/redoc/`.

### Useful commands

```bash
uv run python manage.py bootstrap_sync_sources   # seed the 120 sync sources
uv run python manage.py import_cards <file.json> # upsert a verified-cards export
uv run python manage.py export_verified_cards    # write the verified-cards JSON
uv run python manage.py run_nightly_sync         # run the sync pipeline once
uv run python manage.py llm_status               # LLM provider/budget status
python -m evals verify_dataset                   # validate the eval golden dataset
```

Ingestion commands for the Bangladesh Bank charts
(`ingest_bb_deposit_chart`, `ingest_bb_lending_chart`) and per-vertical seed
commands (`seed_loan_products`, `seed_account_products`,
`seed_deposit_benchmarks`, …) are listed by `manage.py help`.

### Running tests

```bash
DEBUG=True REDIS_CACHE_URL=redis://localhost:6379/14 uv run pytest
```

Two caveats that will otherwise bite: tests expect `DEBUG=True` in a clean
environment, and `REDIS_CACHE_URL` must point at Redis DB **14** (as in CI).
The suite runs with `--nomigrations`, so the pgvector extension must exist
in your `template1` for the retrieval tests:

```sql
psql -d template1 -c "CREATE EXTENSION IF NOT EXISTS vector"
```

## Feature flags

All default to **off**; the features are merged dark until a deliberate
rollout.

| Flag | Enables |
| --- | --- |
| `ADVISOR_ENABLED` | Advisor API + SSE streaming endpoints (404 when off) |
| `EVENT_STREAMING_ENABLED` | Kafka outbox relay and consumers |
| `VECTOR_SEARCH_ENABLED` | pgvector retrieval search endpoint |
| `SEARCH_ENABLED` | Elasticsearch-backed search |

## API documentation

- OpenAPI schema: `GET /api/v1/schema/` · Swagger UI: `/api/v1/docs/swagger/`
  · ReDoc: `/api/v1/docs/redoc/`
- Guides: [docs/api-docs.md](docs/api-docs.md) ·
  [docs/auth-api.md](docs/auth-api.md) · [docs/api/](docs/api/)
- Architecture decisions: [docs/adr/](docs/adr/)
- Development docs: [docs/development/](docs/development/) — start with
  [LOCAL_DEVELOPMENT.md](docs/development/LOCAL_DEVELOPMENT.md) and
  [ARCHITECTURE.md](docs/development/ARCHITECTURE.md)

## CI

Every pull request runs:

- **Tests** — pytest on Python 3.13 and 3.14 against PostgreSQL 17 +
  pgvector and Redis
- **Code Quality** — black, isort, flake8
- **Migration Checks** — `makemigrations --check`, migration graph applied
  to a clean database, and OpenAPI schema validation
- **Security Checks** — pip-audit and bandit
- **Workflow Audit** — zizmor over the workflow files themselves
- **Secret Scan** — gitleaks on the PR's commits (weekly full-history scan)

The LLM eval harness also runs nightly (`LLM Evals (nightly)`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch, commit and review
conventions. The short version: Conventional Commits, focused branches,
tests and `manage.py check` green before review, and never commit secrets.
