# Contributing

This repository is the Django/DRF backend. See [local setup](docs/development/LOCAL_DEVELOPMENT.md), [architecture and data model](docs/development/ARCHITECTURE.md), [deployment](docs/development/DEPLOYMENT_RUNBOOKS.md), and [incident response](docs/development/INCIDENT_RESPONSE.md).

## Branches and commits

Start from the integration branch used by your task or team (confirm its current name; do not assume `main`). Create a short branch such as `feat/card-history`, `fix/crawler-retry`, or `docs/on-call`. Keep changes focused. Use Conventional Commit style: `feat: document crawler tasks`, `fix: make crawl retry idempotent`, `docs: add backend runbook`. Do not commit secrets, generated files, local databases, or unrelated work. Push only to your authorized remote and open a review request per team process.

## Local environment and tests

Use Python 3.12+ and the project environment. In this shared development host, use the maintained environment at `/home/ubuntu/credit-workers/task-8.4-be/.venv/bin/python`; do not install dependencies into this checkout. PostgreSQL is provided by Docker container `task-63-search-db-1` on `127.0.0.1:5432`. Create a task-unique database and use Redis DB 14 (shared; avoid flushing it):

```bash
DB_NAME=creditmate_9_4_contrib DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False REDIS_CACHE_URL=redis://127.0.0.1:6379/14 DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 /home/ubuntu/credit-workers/task-8.4-be/.venv/bin/python manage.py check
DB_NAME=creditmate_9_4_contrib DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False REDIS_CACHE_URL=redis://127.0.0.1:6379/14 DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 /home/ubuntu/credit-workers/task-8.4-be/.venv/bin/python -m pytest
```

For tests requiring PostgreSQL, create the database first if absent (`createdb -h 127.0.0.1 -U postgres creditmate_9_4_contrib`), then migrate it with the same environment and `python manage.py migrate`. The sample test command covers the repository suite; for a narrow run append a test file or `-k expression`. Redis DB 14 is shared by workers: run one pytest session at a time and rerun a flaky test alone. Set `SEARCH_ENABLED=False` to avoid requiring Elasticsearch. Docker Compose development services are described in [local development](docs/development/LOCAL_DEVELOPMENT.md).

Quality tools available in the project environment:

```bash
/home/ubuntu/credit-workers/task-8.4-be/.venv/bin/flake8
/home/ubuntu/credit-workers/task-8.4-be/.venv/bin/isort --check-only .
```

Fix lint/import ordering with `flake8` and `isort` (use the configured Black profile). Run relevant tests and Django checks before review. In shared infrastructure, coordinate resource-intensive runs and follow the host's heavy-command semaphore policy.

## Schema and migrations

Change models first, generate migrations with `python manage.py makemigrations <app>`, inspect the generated operations, then test both `migrate` and `migrate --check` against a disposable local database. Commit model and migration together. Never edit an applied migration; add a forward migration. Prefer additive, backwards-compatible changes for rolling deploys: add nullable/defaulted fields, deploy compatible code, backfill separately where needed, and remove old fields only in a later release. Do not run production migrations from a web startup command. Deployment operators execute migrations as a reviewed one-off step after backup and before shifting traffic; see the [deployment runbook](docs/development/DEPLOYMENT_RUNBOOKS.md).

## Adding an app or endpoint

1. Create a Django app with `python manage.py startapp <app>`; add it to `INSTALLED_APPS`, wire its URL module from `credit_mate_ai/urls.py`, and place models, serializers, permissions, views, and tests in the app's established layout.
2. For an endpoint, validate input with a serializer, enforce explicit permissions/throttling for non-public data, use bounded pagination and queryset filtering, and return serializer-backed responses. Add regression tests for success, validation failures, authorization, and empty results.
3. Annotate DRF operations with `drf_spectacular.utils.extend_schema` (or `extend_schema_view`) with operation summary, tags, request serializer, response serializer/statuses, and parameter descriptions. The schema and Swagger/Redoc routes are configured in settings and project URLs. Add examples and update relevant `docs/api/` pages.
4. If the app adds models, create and inspect migrations; update the [data model overview](docs/development/ARCHITECTURE.md).

## Adding an idempotent Celery task

Put task logic in the owning app's `tasks.py`, keep the task wrapper thin, and use stable database identifiers as inputs. Before side effects, check whether the requested work is already complete; persist a unique operation key/status or use a database uniqueness constraint so retries and duplicate delivery cannot create duplicate records or notifications. Use `transaction.atomic()` for related database writes, `select_for_update()` when concurrent workers could race, and `transaction.on_commit()` to enqueue follow-up work only after commit. Make external effects idempotent with provider idempotency keys or an outbox/deduplication record. Configure bounded retries only for transient failures, with backoff; do not retry permanent validation failures. Add tests for duplicate delivery, retry, and concurrent execution where relevant. For periodic work, add one beat schedule entry and keep exactly one beat scheduler per environment. See [Celery tasks](docs/celery-tasks.md).

## Review checklist

- [ ] Scope is focused; no generated files, secrets, or unrelated edits.
- [ ] Tests and Django system checks pass; relevant lint/import checks pass.
- [ ] New/changed endpoints have authorization, validation, pagination, tests, and OpenAPI annotations.
- [ ] Model changes include reviewed, reversible migrations and backward-compatible rollout notes.
- [ ] Tasks tolerate retries/duplicate delivery and do not schedule duplicate periodic work.
- [ ] Configuration and operational docs are updated; links and commands are valid.
- [ ] Logs avoid credentials, tokens, and unnecessary personal data; errors are actionable.
- [ ] Reviewer can understand risk, test evidence, deployment order, and rollback plan.
