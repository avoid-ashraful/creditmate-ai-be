# Backend environment reference

This inventory follows literal `os.getenv()` calls in `credit_mate_ai/settings.py`. Defaults are defined there; check that file when changing configuration. Production secrets must come from the deployment secret store, never committed `.env` files. Compose staging consumes `.env.staging`; Kubernetes uses ConfigMap plus External Secrets Operator (see the parent DevOps repo).

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key; required and non-empty when `ENVIRONMENT=production`. |
| `DEBUG`, `ENVIRONMENT`, `ALLOWED_HOSTS` | Debug mode, environment name, and accepted hostnames; production disallows wildcard/empty hosts. |
| `DATABASE_URL` | Optional full PostgreSQL URL; takes precedence over split DB settings. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection components when `DATABASE_URL` is unset. |
| `CACHE_BACKEND`, `REDIS_CACHE_URL` | Cache implementation (`redis` default, `locmem` option) and Redis cache URL. |
| `CACHE_TTL_CARD_LIST`, `CACHE_TTL_FILTER_RESULTS`, `CACHE_TTL_SEARCH_SUGGESTIONS` | Cache lifetimes in seconds. |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Celery transport and result backend URLs. |
| `SEARCH_ENABLED`, `SEARCH_URL`, `SEARCH_INDEX_PREFIX`, `SEARCH_REQUEST_TIMEOUT`, `SEARCH_VERIFY_CERTS` | Elasticsearch enablement, endpoint, index prefix, timeout seconds, and TLS certificate verification. |
| `SEARCH_SYNC_MODE`, `SEARCH_QUEUE_VIA_CELERY`, `SEARCH_QUEUE_BATCH_SIZE`, `SEARCH_QUEUE_MAX_ATTEMPTS` | Search outbox mode (`queue`, `sync`, `off`), Celery routing, batch size, and retry ceiling. |
| `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | Optional crawler LLM provider credentials. |
| `MAX_JSON_REQUEST_BYTES`, `MAX_UPLOAD_REQUEST_BYTES` | Request body limits in bytes. |
| `METRICS_TOKEN`, `METRICS_ALLOWED_IPS` | `/metrics` access control: bearer token and/or comma-separated IPs/CIDRs. Configure at least one for scraping. |
| `READYZ_TIMEOUT_SECONDS` | Timeout per dependency check on readiness endpoint. |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE` | Optional error reporting DSN, environment/release labels, and trace sampling fraction. |
| `REVIEW_QUEUE_NOTIFY_EMAILS` | Comma-separated recipients for opted-in high-priority review notifications. |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Mail transport. Non-production defaults to console backend; production defaults to SMTP. Password is secret. |
| `DEFAULT_FROM_EMAIL`, `ALERTS_PUBLIC_BASE_URL`, `FRONTEND_URL` | Outgoing sender and public links used for alert/frontend flows. |
| `THROTTLE_RATE_ANON`, `THROTTLE_RATE_USER`, `THROTTLE_RATE_BURST`, `THROTTLE_RATE_REVIEW_WRITE`, `THROTTLE_RATE_AUTH_BURST`, `THROTTLE_RATE_AUTH_ANON`, `THROTTLE_RATE_AUTH_USER` | DRF throttle rates by client/action. Use DRF rate syntax such as `100/min`. |
| `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `CORS_ALLOW_ALL_ORIGINS` | CORS origins and credential behavior. Allow-all is honored only when DEBUG is true. |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | HTTPS, HSTS, and secure-cookie controls; non-debug settings force production security defaults. |
| `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_BROWSER_XSS_FILTER`, `X_FRAME_OPTIONS`, `CSP_HEADER`, `REFERRER_POLICY` | Browser security response header configuration. |

Boolean values are parsed from `true`, `1`, or `yes` (some settings also accept `on`); do not assume arbitrary non-empty strings mean true. Empty values may differ from unset values. `DATABASE_URL` may include credentials: keep it secret and avoid logging it. This inventory covers settings.py calls only; deployment manifests may define additional variable names that are mapped into these settings.
