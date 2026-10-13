# Observability: health probes and metrics

The backend exposes three endpoints for Kubernetes and Prometheus, plus the
business counters the Grafana business row reads.

## Endpoints

| Path | Method | Purpose | Auth |
|------|--------|---------|------|
| `/api/healthz/` | GET, HEAD | Liveness. Reports that the process serves HTTP. Never checks a dependency. | None |
| `/api/readyz/` | GET, HEAD | Readiness. Checks the database, the cache and, when `SEARCH_ENABLED` is true, Elasticsearch. | None |
| `/metrics` | GET, HEAD | Prometheus text exposition of every series in the default registry. | Bearer token or allowed IP |
| `/health/` | GET, HEAD | Legacy health check, unchanged. | None |

### Liveness: `/api/healthz/`

```json
{"status": "alive"}
```

Always `200` while the process can answer HTTP. A database or Redis outage
must not restart the pod, so this probe has no dependency checks.

### Readiness: `/api/readyz/`

```json
{
  "status": "ready",
  "checks": {
    "database": {"healthy": true, "latency_ms": 1.82},
    "cache": {"healthy": true, "latency_ms": 0.64},
    "elasticsearch": {"healthy": true, "latency_ms": 3.10}
  },
  "total_latency_ms": 6.1
}
```

- `200` with `"status": "ready"` when every listed check passes.
- `503` with `"status": "not ready"` when any check fails. The failing check
  has `"healthy": false` and `"error"`, which is the exception class name only
  (for example `OperationalError`). Messages, hostnames and credentials are
  never returned, because this endpoint is public.
- The `elasticsearch` entry appears only when `SEARCH_ENABLED` is true.
- Each check has its own timeout, set by `READYZ_TIMEOUT_SECONDS`. Checks run
  one after another, so the worst-case response time is three times that
  value. Set the Kubernetes probe `timeoutSeconds` above that.

What each check does:

| Check | Method | Timeout behavior |
|-------|--------|------------------|
| `database` | `SELECT 1` inside a transaction | PostgreSQL `statement_timeout` is set to the readiness timeout, so a stalled query fails fast. Connection setup is not bounded by this setting. |
| `cache` | `PING` when the default cache is Redis; a set/get round trip for other backends | Redis socket connect and read timeouts are set to the readiness timeout. |
| `elasticsearch` | Cluster ping through `search.client.ping` | The client request timeout is set to the readiness timeout. |

### Metrics: `/metrics`

Access is closed by default. The endpoint returns `403` unless one of these is
configured and matches:

- `METRICS_TOKEN`: the request sends `Authorization: Bearer <token>`. The
  comparison is constant time.
- `METRICS_ALLOWED_IPS`: a comma-separated list of IPs or CIDR ranges, for
  example `10.0.0.0/8,127.0.0.1`. The check uses `REMOTE_ADDR` only.
  `X-Forwarded-For` is ignored, because clients control it. When traffic
  reaches the pod through a proxy, the allowlist has to include the proxy's
  address, not the client's.

Prometheus scrape config with a token:

```yaml
authorization:
  type: Bearer
  credentials_file: /etc/prometheus/secrets/creditmate-metrics-token
```

## Settings

| Variable | Default | Meaning |
|----------|---------|---------|
| `METRICS_TOKEN` | empty | Bearer token for `/metrics`. Empty disables token access. |
| `METRICS_ALLOWED_IPS` | empty | IPs or CIDR ranges allowed to read `/metrics`. Empty disables IP access. |
| `READYZ_TIMEOUT_SECONDS` | `1.0` | Timeout for each readiness dependency check. |
| `SEARCH_ENABLED` | `True` | Also decides whether `/api/readyz/` checks Elasticsearch. |

## HTTP metrics

Recorded by `credit_mate_ai.prometheus_middleware.PrometheusMetricsMiddleware`.
The names and label sets match django-prometheus, which the monitoring
recording rules query.

| Metric | Type | Labels |
|--------|------|--------|
| `django_http_requests_total_by_view_transport_method_total` | counter | `view`, `transport`, `method` |
| `django_http_responses_total_by_status_view_method_total` | counter | `status`, `view`, `method` |
| `django_http_requests_latency_seconds_by_view_method` | histogram (`_bucket`, `_sum`, `_count`) | `view`, `method` |

- `view` is the resolved URL name, for example `creditcard-list` or
  `advanced-search`. Unmatched paths are `unknown`. Unnamed routes are
  `unnamed`.
- `method` is one of `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`,
  or `OTHER`. Other methods cannot create new label values.
- Requests to `/metrics`, `/api/healthz/`, `/api/readyz/` and `/health/` are
  not recorded.
- The middleware is the last entry in `MIDDLEWARE`, so it only sees requests
  that get past the earlier middleware. Responses those return directly are
  not counted. Examples are CSRF 403s and the 413/415 responses from
  `RequestValidationMiddleware`.

### Process model

The default registry is per process. Gunicorn runs one worker by default (the
`Dockerfile` does not set `--workers`), so the counters describe the whole
process. If the worker count goes above one, counters must move to
`prometheus_client` multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`). That is not
configured yet.

## Business counters

Defined in `credit_mate_ai/metrics.py`. Each increments through a helper, so
call sites stay one line.

| Metric | Type | Labels | Incremented by | Status |
|--------|------|--------|----------------|--------|
| `creditmate_searches_total` | counter | `search_type` | `increment_search(search_type)` | Wired |
| `creditmate_comparisons_total` | counter | none | `increment_comparison()` | Defined. No comparison endpoint exists yet, so it stays at 0. |
| `creditmate_signups_total` | counter | none | `increment_signup()` | Defined. No signup flow exists yet, so it stays at 0. |

`creditmate_searches_total` values:

| `search_type` | Handler |
|---------------|---------|
| `search` | `GET /api/search/` |
| `suggest` | `GET /api/search/suggest/` |
| `typeahead` | `GET /api/v1/credit-cards/typeahead/` |
| `advanced` | `GET /api/v1/credit-cards/advanced-search/` (the list action only) |

Each count is one request that reached the handler, before parameter
validation. Typeahead and suggest are autocomplete endpoints and can account
for most of the total. Filter by `search_type` to compare like with like.

When a comparison or signup flow is added, call `increment_comparison()` or
`increment_signup()` from its handler. The counters are already exposed at 0.

## Verifying

```bash
curl -fsS http://localhost:8000/api/healthz/
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/readyz/
curl -sS -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/metrics \
  | grep -E '^(django_http_|creditmate_)' | head
```

An unauthenticated `curl http://localhost:8000/metrics` returns `403` when
neither `METRICS_TOKEN` nor `METRICS_ALLOWED_IPS` is set.
