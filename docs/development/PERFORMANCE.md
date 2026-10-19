# Local API performance baseline (issue #42)

Measured on 2026-10-19 in `perf/api-load-baseline`, based on `edd34f9`.
This is a shared host with **2 CPUs and approximately 11 GiB RAM**, running k6,
three synchronous gunicorn workers, PostgreSQL 16 and Redis on the same machine.
Other applications also run here. These numbers describe this machine and this
small catalog; they are not a production capacity guarantee.

## Reproduce the environment

From `/home/ubuntu/credit-workers/r2-be-perf`:

```bash
uv venv --python 3.12 .venv
heavy uv sync --dev
source scripts/performance/environment.sh
heavy uv run python manage.py migrate --noinput
heavy uv run python manage.py loaddata all_banks.json
heavy uv run python manage.py import_cards credit_cards/fixtures/verified_cards_2026-10-18.json
heavy uv run python -m scripts.performance.server start
```

`environment.sh` sets the exact following environment. The key is generated at
runtime and its value must never be logged:

```bash
export DEBUG=False ENVIRONMENT=production-like
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DATABASE_URL=postgresql:///creditmate_perf
export ALLOWED_HOSTS=127.0.0.1,localhost
export SECURE_SSL_REDIRECT=False SECURE_HSTS_SECONDS=0
export SECURE_HSTS_INCLUDE_SUBDOMAINS=False SECURE_HSTS_PRELOAD=False
export SESSION_COOKIE_SECURE=False CSRF_COOKIE_SECURE=False
export CACHE_BACKEND=redis REDIS_CACHE_URL=redis://127.0.0.1:6379/6
export SEARCH_ENABLED=False SEARCH_SYNC_MODE=off
export THROTTLE_RATE_ANON=100000/min THROTTLE_RATE_USER=100000/min
export THROTTLE_RATE_BURST=1000/sec
export DJANGO_SETTINGS_MODULE=scripts.performance.local_settings
```

The normal settings force HTTPS and secure cookies whenever `DEBUG=False`, even
when the flags above are false. The guarded `scripts.performance.local_settings`
module imports normal settings and overrides those six HTTP flags for loopback.
It requires `ENVIRONMENT=production-like`, `creditmate_perf`, Redis DB 6 and the
exact loopback host list. Normal production settings are unchanged.

The server helper runs exactly this command in a subprocess with `close_fds=True`
so a daemon does not retain the `heavy` semaphore lock:

```bash
.venv/bin/gunicorn credit_mate_ai.wsgi:application \
  --workers 3 --bind 127.0.0.1:8020 --daemon \
  --pid .cache/performance/gunicorn.pid \
  --error-logfile .cache/performance/gunicorn.log
```

The dataset has **65 banks and 135 cards: 105 active verified/public and 30 active
drafts**. No synthetic catalog expansion or user/review data was added. DB 6 may
be cleared by the query profiler; no other Redis database is cleared. Run query
profiling separately from load because it clears that isolated cache.

```bash
uv run python -m scripts.performance.profile_queries before
heavy uv run python -m scripts.performance.run_load before-smoke \
  /home/ubuntu/credit/load-tests/smoke.js \
  --master-pid "$(cat .cache/performance/gunicorn.pid)"
mv smoke-results.json docs/development/performance-results/before-smoke-summary.json
heavy uv run python -m scripts.performance.run_load before-average \
  scripts/performance/average.js \
  --master-pid "$(cat .cache/performance/gunicorn.pid)"
heavy uv run python -m scripts.performance.run_load before-supplemental \
  scripts/performance/supplemental.js \
  --master-pid "$(cat .cache/performance/gunicorn.pid)"
```

The parent `/home/ubuntu/credit/load-tests` scripts were read and left unchanged.
The average wrapper imports the original default action and setup functions,
retaining their checks and mix (40% list, 25% detail, 20% typeahead, 10% advanced,
5% health). It changes the stages to **0 → 30 VUs in 1 min, hold 3 min, → 0 in
1 min**, and seeds randomness with 42. Think times are the original log-normal
0.5–10 s. A seed reduces variability but scheduling still changes samples.
Additional tagged thresholds expose per-endpoint p50/p95/p99 in summary JSON.
The supplemental run uses 1 VU for 30 s on banks and compare-by-ids because the
parent smoke/average scripts omit those routes. Comparison is the list endpoint
with `ids=...`, not a separate `/compare/` route.

All load commands pass through `heavy`. CPU sampling starts after the gate opens.
CPU is read from `/proc` each second: gunicorn master + its workers vs **all local
Postgres processes**. 100% means one full CPU; the host has 200% total capacity.
Postgres CPU can include unrelated databases. The generator and Redis are not
included in those process totals. One-minute host load is also recorded.

## Measurements

Raw query plans and k6 summaries are in [performance-results](performance-results/).

### Five-minute average load

| Metric | Before | After |
|---|---:|---:|
| Requests | 4179 | 4141 |
| RPS | 13.80 | 13.78 |
| Overall p50 (ms) | 14.93 | 11.18 |
| Overall p95 (ms) | 82.91 | 38.07 |
| Overall p99 (ms) | 154.31 | 51.06 |
| HTTP error rate (429 excluded) | 0.00% | 0.00% |
| 429 rate | 0.00% | 0.00% |
| Check pass rate | 99.964% | 99.988% |
| Gunicorn CPU mean / peak (%) | 21.83 / 49.52 | 15.46 / 45.47 |
| Postgres CPU mean / peak (%) | 8.84 / 32.59 | 2.11 / 6.94 |
| Host 1-minute load mean / peak | 0.91 / 1.40 | 0.74 / 0.98 |

All configured k6 thresholds passed. Three baseline checks and one after check
failed their individual latency target; there were no failed HTTP requests.
Throughput is limited by the workload think times, so this is not a maximum-RPS
test. CPU percentages use one core as 100% (200% available on this host).

### Per-endpoint latency and throughput

| Endpoint | Before p50 / p95 / p99 (ms) | After p50 / p95 / p99 (ms) | RPS before → after |
|---|---:|---:|---:|
| list | 13.60 / 46.67 / 74.79 | 13.27 / 25.61 / 35.12 | 5.35 → 5.56 |
| detail | 11.81 / 23.82 / 38.03 | 11.49 / 17.92 / 28.33 | 3.44 → 3.44 |
| advanced-search | 78.72 / 171.22 / 191.03 | 36.65 / 55.04 / 97.00 | 1.42 → 1.40 |
| typeahead | 19.06 / 29.23 / 40.75 | 4.27 / 9.10 / 19.63 | 2.78 → 2.61 |
| health | 1.01 / 2.01 / 11.67 | 0.99 / 2.04 / 2.92 | 0.80 → 0.77 |
| banks (supplemental) | 20.88 / 26.08 / 28.69 | 7.74 / 12.31 / 13.26 | 0.97 → 0.98 |
| compare (supplemental) | 4.29 / 7.02 / 12.71 | 4.27 / 8.14 / 12.52 | 0.97 → 0.98 |

Endpoint percentiles include successful HTTP 200 responses. Every endpoint had
**0% errors and 0% 429s** in both runs. Endpoint RPS is derived from each status
check count divided by run duration (supplemental: one request per endpoint per
iteration), excluding setup-list. Banks and compare use their separate 1-VU,
30-second run, not the 30-VU average mix.

### Smoke and supplemental checks

| Run | Before | After |
|---|---|---|
| smoke | 157 requests; 402/402 checks; 5.05 RPS; exit 0 | 157 requests; 402/402 checks; 5.17 RPS; exit 0 |
| supplemental | 61 requests; 60/60 checks; 1.97 RPS; exit 0 | 61 requests; 60/60 checks; 2.00 RPS; exit 0 |

Both smoke and supplemental runs had zero HTTP errors and zero 429s.

### SQL query budgets

| Endpoint | Cold queries before → after | Warm queries before → after | Cold SQL ms before → after |
|---|---:|---:|---:|
| list | 22 → 3 | 0 → 0 | 3 → 3 |
| detail | 2 → 2 | 2 → 2 | 2 → 1 |
| advanced-search | 53 → 6 | 0 → 0 | 19 → 6 |
| typeahead | 4 → 4 | 4 → 0 | 3 → 3 |
| banks | 22 → 2 | 22 → 2 | 0 → 1 |
| compare | 5 → 3 | 0 → 0 | 1 → 1 |

Cold probes use fee-filtered populated lists/search (20 returned cards), a public
detail, `q=visa`, a 20-bank page and comparison of three real IDs. SQL times are
rounded diagnostic samples, not percentile latency estimates. Zero warm queries
means a response-cache hit; detail and banks remain uncached.

## Bottlenecks and changes

- **Nested bank counts:** `Bank.credit_card_count` ran a COUNT for every serialized
  bank, including repeated banks on card lists. Bank views now annotate all public
  counts together. Card list/detail and advanced search prefetch banks with those
  counts in one extra query. Counts remain bank-wide, independent of the current
  fee/search filter, and exclude drafts/inactive cards.
- **Facet round trips:** advanced search independently counted each category,
  fee/APR range, and boolean option. Those scalar counts now share one SQL
  `COUNT(...) FILTER (WHERE ...)` aggregate. Bank/network term buckets retain their
  two GROUP BY queries. Null handling, overlapping fee ranges, lounge text rules,
  and omission of empty category buckets retain their existing meanings.
- **Repeated typeahead:** bounded suggestions still ran 4–7 SQL queries per request.
  The response now uses the existing query/origin/path-aware key builder with its
  own prefix and the suggestions version/TTL (600 s). Card and bank commit signals
  invalidate it. Raw query text remains in the response and key; short queries
  still return immediately without database access.

Bank relations already used `select_related` in the original card views. Field
history and review summaries are not traversed by these public serializers, and
reward fields live directly on the card row. No other relation N+1 was found.
The serializers expose almost every card field, including reward JSON and feature
text, so `.only()`/`.defer()` would add risk and little savings here.

### Plans and index review

`profile_queries.py` uses Django's client with `CaptureQueriesContext`, clearing
only the isolated cache before each endpoint, then repeating the identical request.
It records request wall time, SQL time (Django's millisecond-resolution SQL log),
all statements and `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for the three queries
with highest recorded SQL time, or all queries when fewer than three. Ties at
0 ms use capture order. EXPLAIN overhead is excluded from request wall time.
The first client request includes lazy URL imports; use k6 for latency comparisons.

The original slow captured advanced-search queries had substantial planning cost
(4.8–6.0 ms for representative lounge/regex count queries) with execution below
1 ms. A captured typeahead facet aggregate executed in 1.51 ms. The populated list
page executed in 0.38 ms. Many bank counts were under SQL logging precision; their
repeated round trips and Python dispatch mattered more than individual execution.
After batching, the captured combined facet aggregate planned in 0.29 ms and
executed in 2.60 ms; it replaces many smaller counts. See the saved plans for
exact SQL, row counts and buffers. Fourteen original-worker versus changed-code
advanced-search payloads were also identical across populated/empty, category,
range, lounge and nullable-field cases (ignoring only the cache-hit marker).

Existing indexes cover `verification_status`, `bank_id`, `(bank_id, name)`, PKs and
verification-user FK. `is_active`, `card_network`, `is_islamic`, `annual_fee` and
`interest_rate_apr` have no dedicated indexes. There is no composite public-card
index. At **135 rows**, sequential scans are cheap and no measured plan justifies
adding these indexes. **No migration is added.** On a substantially larger catalog,
re-evaluate a partial public-card index on `(bank_id, annual_fee)` with
`WHERE is_active AND verification_status = 'verified'`, or a composite
`(verification_status, is_active, bank_id)` index for broader status queries.
Choose from actual production predicates/selectivity; avoid indexing low-cardinality
boolean columns individually. Neither index is claimed to improve this baseline.

## Production sizing and 1000 VUs

This is an **initial sizing estimate for a future load test**, not a demonstrated
1000-VU capacity claim. The profile averages about 24 active VUs across its ramps.
At 13.78 RPS, the average action cycle is about 1.74 s. Holding 1000 VUs with the
same behavior would therefore imply roughly **575–600 RPS**, with bursts above
that. A zero-think-time 1000-VU test would be a different workload.

The after run used approximately **11.2 ms of gunicorn CPU/request** and **1.53 ms
of Postgres CPU/request** (process CPU seconds divided by requests). An optimistic
linear extrapolation to 600 RPS is 6.7 app CPU cores plus 0.92 Postgres cores.
At a 60% target utilization, that suggests about 11.2 app vCPUs and 1.5 Postgres
vCPUs before extra headroom. The tiny catalog, empty filters and warm caches make
this estimate optimistic; contention and tail latency need direct measurement.

A reasonable next dedicated-test starting budget is:

- **API:** six replicas with 2 vCPUs and three synchronous gunicorn workers each
  (12 app vCPUs / 18 workers total), with memory limits selected after measuring
  worker RSS. Scale from observed queueing and latency, not VU count alone.
- **Postgres:** a separate 4-vCPU instance with 8–16 GiB RAM as a test starting
  point, connection limits sized to all API/Celery workers, and a connection pool
  if replica count grows. Recheck plans and indexes on a realistic larger catalog.
- **Redis:** a separate service with an initial 1–2 vCPU / 2 GiB budget, explicit
  memory/eviction monitoring, and an appropriate separation of cache and broker
  workloads. Redis CPU and memory were not profiled here.
- **Load generation:** a separate machine, representative Bangladeshi bank filters,
  populated-result checks, and realistic source IP/auth identities so anonymous
  throttles do not turn the exercise into a 429 benchmark.

Validate progressively at 100, 250, 500 and 1000 VUs, holding each plateau long
enough to observe cache expiry and connection pressure. Add arrival-rate tests
around 600 RPS to separate backend capacity from client think time. Measure p99,
worker queueing/RSS, Postgres CPU/locks/connections, Redis hit/eviction rates and
network transfer before committing a production capacity target.

## Scope and limitations

The upstream scripts still contain Indian bank filters (HDFC, ICICI, SBI, Axis,
etc.) while this fixture contains Bangladeshi banks. Bank-filtered actions commonly
return empty results, making the weighted average optimistic for populated browsing.
The parent suite should replace those values with banks discovered from this API,
and check response shapes in average/stress/spike as smoke already does. It should
also support reduced stage profiles and per-endpoint summary statistics directly.
The shared `lib.js` also calls `apiLatency.add(...)` without endpoint tags; the
local wrappers therefore split `http_req_duration{endpoint:...,status:200}`
instead of the custom trend. An initial average run passed (14.08 RPS, p95
87.60 ms, 0 errors/429s), but its custom per-endpoint submetrics were empty;
the baseline was repeated with corrected instrumentation. The final tables use
that repeated baseline. Those parent files were not edited. The fixed populated
query probes and the supplemental compare-by-ids run cover real returned cards, but do not replace a
representative production traffic trace.

Not measured: 1000 VUs, saturation, stress/spike, autoscaling, TLS/network/WAN cost,
Elasticsearch (disabled; advanced search uses Postgres fallback), writes/imports,
authenticated traffic, review/history endpoints, Celery/crawlers, a larger catalog,
long-term cache churn, worker RSS/memory, failover, database pooling or distributed
cache stampedes.

The cache was warmed by smoke and earlier probes rather than reset to an
identical starting key set. The repeated baseline had residual list/advanced
entries from the initial run, favoring its early cache hits. Together with shared
host activity, this makes the load comparison exploratory rather than a controlled
statistical A/B result; the query-budget reductions are independently pinned by
tests. RPS is averaged over both ramps and the hold (about 24 average active VUs),
not just the 30-VU plateau. Only the dedicated performance environment has raised
throttles. Default production anonymous/burst limits would reject most traffic from one load-generator IP; 429s
are tracked separately from errors by the parent suite.

Stop the recorded server, then confirm there is no listener on 8020:

```bash
uv run python -m scripts.performance.server stop
ss -ltnp 'sport = :8020'
```

## Validation

Test environment (normal settings, not the HTTP performance override):

```bash
export DEBUG=True SECRET_KEY=test CACHE_BACKEND=locmem SEARCH_ENABLED=False
export DATABASE_URL=postgresql:///creditmate_worker1
heavy uv run python manage.py makemigrations --check --dry-run
heavy uv run pytest credit_cards -q
heavy uv run pytest -q
```

- Migration check: **No changes detected**, exit 0; no index migration is needed.
- Credit-card suite: **414 passed, 209 warnings in 24.01 s**, exit 0.
- Full suite, run **once**: **1889 passed, 57 skipped, 516 warnings in 150.07 s**,
  exit 0. Skips retain the suite's optional-service/integration behavior.
- Eight new query-budget tests passed. They cover 1- and 8-result pages, comparison
  IDs, bank-wide public counts under a narrower card filter, draft/inactive
  exclusion, detail, all facets, response-cache hits and committed typeahead
  invalidation.

Formatting/lint checks (all 11 changed Python files):

```bash
uv run black --check banks/models.py banks/api/views.py credit_cards/models.py \
  credit_cards/api/views.py credit_cards/api/advanced_views.py \
  credit_cards/api/advanced_filters.py credit_cards/tests/test_query_budgets.py \
  scripts/performance/*.py
uv run isort --check-only banks/models.py banks/api/views.py credit_cards/models.py \
  credit_cards/api/views.py credit_cards/api/advanced_views.py \
  credit_cards/api/advanced_filters.py credit_cards/tests/test_query_budgets.py \
  scripts/performance/*.py
uv run flake8 banks/models.py banks/api/views.py credit_cards/models.py \
  credit_cards/api/views.py credit_cards/api/advanced_views.py \
  credit_cards/api/advanced_filters.py credit_cards/tests/test_query_budgets.py \
  scripts/performance
bash -n scripts/performance/environment.sh
git diff --check
```

All listed formatting/lint/syntax checks exited 0. All three gunicorn masters
started during this task were stopped by their recorded PID (987222, 988313,
993715). The final `ss -ltnp 'sport = :8020'` showed no listener. No push was made.
