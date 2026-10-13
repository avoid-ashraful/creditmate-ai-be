# Environment Variables Configuration

This document provides a comprehensive reference for all environment variables used in Credit Mate AI.

## Quick Reference

For a complete example configuration, see [.env.example](../../.env.example) in the project root.

## Core Django Settings

### Required Settings
```bash
# Django secret key for cryptographic signing
SECRET_KEY=your-super-secret-key-here

# Debug mode (True for development, False for production)
DEBUG=True

# Comma-separated list of allowed hosts
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Environment Configuration
```bash
# Environment type: local, staging, or production
# This affects email backend and other environment-specific settings
ENVIRONMENT=local
```

## Database Configuration

### SQLite (Default for Development)
```bash
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
```

### PostgreSQL (Recommended for Production)
```bash
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_ai
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
```

### Database URL (Alternative)
```bash
# Use DATABASE_URL if available (overrides individual settings)
DATABASE_URL=postgresql://user:password@localhost:5432/creditmate_ai
```

## External Services

### OpenAI / LLM API Keys
```bash
# OpenAI API key for GPT-based content parsing
OPENAI_API_KEY=sk-your-openai-api-key-here

# Google Gemini API key (alternative LLM provider)
GEMINI_API_KEY=your-gemini-key

# OpenRouter API key (alternative LLM provider)
OPENROUTER_API_KEY=your-openrouter-key
```

### Celery & Redis (Required for Background Tasks)
```bash
# Redis URL for Celery message broker
CELERY_BROKER_URL=redis://localhost:6379/0

# Redis URL for Celery result backend
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Redis URL for Django cache
REDIS_CACHE_URL=redis://127.0.0.1:6379/1
```

### Sentry Error Monitoring (Optional)
```bash
# Sentry project DSN. Leave unset to disable Sentry entirely.
SENTRY_DSN=https://your-key@o0.ingest.sentry.io/0

# Sentry environment. Defaults to ENVIRONMENT.
SENTRY_ENVIRONMENT=production

# Release identifier. If unset, Sentry uses its default release detection.
SENTRY_RELEASE=1.5.0

# Percentage of traces sampled, from 0.0 (disabled) to 1.0 (all traces).
SENTRY_TRACES_SAMPLE_RATE=0.1
```

Sentry is only initialized when `SENTRY_DSN` is present. The event filter keeps
the request method, URL path without query or fragment, and a numeric or UUID
internal user ID. It removes email, username, IP address, request body, cookies,
and request headers while retaining the configured environment and release.

## Cache Configuration

```bash
# Cache backend: "redis" (default) or "locmem" (local memory, for tests)
CACHE_BACKEND=redis

# Cache TTLs (seconds) for different cached surfaces
CACHE_TTL_CARD_LIST=300              # 5 minutes - list endpoint
CACHE_TTL_FILTER_RESULTS=120         # 2 minutes - filtered/search results
CACHE_TTL_SEARCH_SUGGESTIONS=600     # 10 minutes - search suggestions
CACHE_TTL_ADVANCED_SEARCH=120        # 2 minutes - advanced search
```

## API Request Validation

```bash
# Maximum request body size for JSON payloads (bytes, default 1MB)
MAX_JSON_REQUEST_BYTES=1048576

# Maximum request body size for multipart/form uploads (bytes, default 10MB)
MAX_UPLOAD_REQUEST_BYTES=10485760
```

## Security Configuration

### CORS (Cross-Origin Resource Sharing)
```bash
# Comma-separated list of allowed frontend origins
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://yourdomain.com

# Allow credentials in CORS requests
CORS_ALLOW_CREDENTIALS=True

# Development only - allows all origins (NEVER use in production)
CORS_ALLOW_ALL_ORIGINS=False
```

### API Rate Limiting
```bash
# Rate limit for anonymous users (requests per time period)
THROTTLE_RATE_ANON=100/min

# Rate limit for authenticated users (requests per time period)
THROTTLE_RATE_USER=1000/min

# Burst protection rate limit (requests per second)
THROTTLE_RATE_BURST=10/sec
```

### HTTPS/SSL Security (Production)
```bash
# Force HTTPS redirects
SECURE_SSL_REDIRECT=True

# HTTP Strict Transport Security
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# Secure cookies
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

### Response Security Headers
```bash
# Content-Security-Policy applied to every response (safe default shown;
# override only after auditing scripts/styles/images your pages actually use)
CSP_HEADER=frame-ancestors 'none'; object-src 'none'; base-uri 'self'

# Clickjacking protection
X_FRAME_OPTIONS=DENY

# How much referrer information is sent with requests
REFERRER_POLICY=strict-origin-when-cross-origin
```

These headers are applied by `credit_mate_ai.middleware.SecurityHeadersMiddleware`
to every response. HSTS remains handled by Django's `SecurityMiddleware`
(see `SECURE_HSTS_*` above).

### Proxy SSL Header
```bash
# For Railway/Heroku deployments behind a proxy
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
```

## Search (Elasticsearch) Configuration

```bash
# Enable/disable Elasticsearch search
SEARCH_ENABLED=True

# Elasticsearch URL (single node container on 127.0.0.1:19200)
SEARCH_URL=http://127.0.0.1:19200

# Index prefix for multi-tenancy
SEARCH_INDEX_PREFIX=

# Request timeout in seconds
SEARCH_REQUEST_TIMEOUT=10

# Verify SSL certificates
SEARCH_VERIFY_CERTS=True

# Sync mode: "queue" (default), "sync", or "off"
SEARCH_SYNC_MODE=queue

# Route queue batches through Celery (requires Redis)
SEARCH_QUEUE_VIA_CELERY=False

# Queue batch size
SEARCH_QUEUE_BATCH_SIZE=200

# Maximum retry attempts for queue items
SEARCH_QUEUE_MAX_ATTEMPTS=5
```

## Observability Configuration

```bash
# Bearer token for /metrics endpoint. Empty disables token access.
METRICS_TOKEN=

# Comma-separated list of IPs or CIDR ranges allowed to read /metrics.
# Matched against REMOTE_ADDR only (X-Forwarded-For is ignored).
METRICS_ALLOWED_IPS=

# Per-dependency timeout for /api/readyz/ checks, in seconds.
READYZ_TIMEOUT_SECONDS=1.0
```

## Email Configuration

Email configuration is environment-dependent:

### Local/Staging (Email Disabled)
```bash
ENVIRONMENT=local
# No email configuration needed - uses dummy backend
```

### Production (SMTP Required)
```bash
ENVIRONMENT=production

# Email backend configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@domain.com
EMAIL_HOST_PASSWORD=your-email-password
```

## Review Queue Notifications

```bash
# Comma-separated list of email addresses for high-priority review alerts
# Empty = no notifications sent (opt-in)
REVIEW_QUEUE_NOTIFY_EMAILS=reviewer1@example.com,reviewer2@example.com
```

## Static & Media Files

```bash
# Static files (CSS, JavaScript, Images)
STATIC_URL=static/
STATIC_ROOT=/app/staticfiles

# Media files (uploads)
MEDIA_URL=media/
MEDIA_ROOT=/app/media
```

## WhiteNoise Configuration
```bash
# Compression disabled for Railway compatibility
STATICFILES_STORAGE=whitenoise.storage.StaticFilesStorage
```

## Default Primary Key
```bash
DEFAULT_AUTO_FIELD=django.db.models.BigAutoField
```

## Environment-Specific Examples

### Local Development
```bash
# Basic local development setup
SECRET_KEY=django-insecure-dev-key-only-for-development
DEBUG=True
ENVIRONMENT=local
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL 15+)
DB_NAME=creditmate_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# OpenAI API (required for AI content parsing)
OPENAI_API_KEY=sk-your-openai-api-key-here

# Redis for Celery & Cache
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
REDIS_CACHE_URL=redis://localhost:6379/1

# CORS for frontend development
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Relaxed rate limiting for development
THROTTLE_RATE_ANON=10000/hour
THROTTLE_RATE_USER=20000/hour
THROTTLE_RATE_BURST=1000/min

# Cache TTLs
CACHE_TTL_CARD_LIST=300
CACHE_TTL_FILTER_RESULTS=120
CACHE_TTL_SEARCH_SUGGESTIONS=600
CACHE_TTL_ADVANCED_SEARCH=120

# Search (optional - can be disabled for local dev)
SEARCH_ENABLED=False
```

### Staging Environment
```bash
# Staging configuration
SECRET_KEY=your-staging-secret-key
DEBUG=False
ENVIRONMENT=staging
ALLOWED_HOSTS=staging.yourdomain.com

# PostgreSQL database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_staging
DB_USER=postgres
DB_PASSWORD=your-db-password
DB_HOST=staging-db.yourdomain.com
DB_PORT=5432

# Production-like services
OPENAI_API_KEY=sk-your-openai-api-key-here
CELERY_BROKER_URL=redis://staging-redis.yourdomain.com:6379/0
REDIS_CACHE_URL=redis://staging-redis.yourdomain.com:6379/1

# Staging CORS
CORS_ALLOWED_ORIGINS=https://staging.yourdomain.com,https://staging-app.yourdomain.com

# Standard rate limiting
THROTTLE_RATE_ANON=1000/hour
THROTTLE_RATE_USER=2000/hour
THROTTLE_RATE_BURST=100/min

# Observability
METRICS_TOKEN=your-metrics-token
READYZ_TIMEOUT_SECONDS=1.0
```

### Production Environment
```bash
# Production configuration
SECRET_KEY=your-production-secret-key
DEBUG=False
ENVIRONMENT=production
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# PostgreSQL database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_production
DB_USER=postgres
DB_PASSWORD=your-secure-db-password
DB_HOST=prod-db.yourdomain.com
DB_PORT=5432

# Production services
OPENAI_API_KEY=sk-your-production-openai-api-key
CELERY_BROKER_URL=redis://prod-redis.yourdomain.com:6379/0
REDIS_CACHE_URL=redis://prod-redis.yourdomain.com:6379/1

# Production CORS (strict)
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com,https://app.yourdomain.com
CORS_ALLOW_CREDENTIALS=True

# Production rate limiting
THROTTLE_RATE_ANON=1000/hour
THROTTLE_RATE_USER=2000/hour
THROTTLE_RATE_BURST=100/min

# HTTPS security
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Email configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yourdomain.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@yourdomain.com
EMAIL_HOST_PASSWORD=your-email-password

# Observability
METRICS_TOKEN=your-production-metrics-token
METRICS_ALLOWED_IPS=10.0.0.0/8,127.0.0.1
READYZ_TIMEOUT_SECONDS=1.0

# Search
SEARCH_ENABLED=True
SEARCH_URL=http://search:9200

# Review queue notifications
REVIEW_QUEUE_NOTIFY_EMAILS=alerts@yourdomain.com
```

## Variable Summary Table

| Variable | Default | Required in Prod | Description |
|----------|---------|------------------|-------------|
| `SECRET_KEY` | dev key | Yes | Django secret key |
| `DEBUG` | True | Yes (False) | Debug mode |
| `ENVIRONMENT` | local | Yes | Environment type |
| `ALLOWED_HOSTS` | localhost,127.0.0.1 | Yes | Allowed hosts |
| `DB_NAME` | creditmate_db | Yes | PostgreSQL database name |
| `DB_USER` | (empty) | Yes | PostgreSQL user |
| `DB_PASSWORD` | (empty) | Yes | PostgreSQL password |
| `DB_HOST` | localhost | Yes | PostgreSQL host |
| `DB_PORT` | 5432 | No | PostgreSQL port |
| `DATABASE_URL` | (empty) | Alt | Full DB URL |
| `OPENAI_API_KEY` | (empty) | Yes* | LLM API key |
| `GEMINI_API_KEY` | (empty) | No | Alternative LLM key |
| `OPENROUTER_API_KEY` | (empty) | No | Alternative LLM key |
| `CELERY_BROKER_URL` | redis://localhost:6379/0 | Yes | Celery broker |
| `CELERY_RESULT_BACKEND` | redis://localhost:6379/0 | Yes | Celery backend |
| `REDIS_CACHE_URL` | redis://127.0.0.1:6379/1 | Yes | Django cache |
| `CACHE_BACKEND` | redis | No | Cache backend type |
| `SENTRY_DSN` | (empty) | No | Error monitoring |
| `SENTRY_ENVIRONMENT` | ENVIRONMENT | No | Sentry environment |
| `SENTRY_RELEASE` | (empty) | No | Sentry release |
| `SENTRY_TRACES_SAMPLE_RATE` | 0.1 | No | Sentry sample rate |
| `CORS_ALLOWED_ORIGINS` | localhost:3000 | Yes | CORS origins |
| `CORS_ALLOW_CREDENTIALS` | True | No | CORS credentials |
| `CORS_ALLOW_ALL_ORIGINS` | False | No | CORS all origins |
| `THROTTLE_RATE_ANON` | 100/min | No | Anon rate limit |
| `THROTTLE_RATE_USER` | 1000/min | No | User rate limit |
| `THROTTLE_RATE_BURST` | 10/sec | No | Burst rate limit |
| `SECURE_SSL_REDIRECT` | False | Yes (True) | HTTPS redirect |
| `SECURE_HSTS_SECONDS` | 0 | Yes | HSTS seconds |
| `SESSION_COOKIE_SECURE` | False | Yes (True) | Secure session cookie |
| `CSRF_COOKIE_SECURE` | False | Yes (True) | Secure CSRF cookie |
| `CSP_HEADER` | frame-ancestors 'none'... | No | CSP header |
| `X_FRAME_OPTIONS` | DENY | No | Frame options |
| `REFERRER_POLICY` | strict-origin-when-cross-origin | No | Referrer policy |
| `SECURE_PROXY_SSL_HEADER` | (empty) | No | Proxy SSL header |
| `SEARCH_ENABLED` | True | No | Enable search |
| `SEARCH_URL` | http://127.0.0.1:19200 | No* | Elasticsearch URL |
| `SEARCH_INDEX_PREFIX` | (empty) | No | Index prefix |
| `SEARCH_REQUEST_TIMEOUT` | 10 | No | ES request timeout |
| `SEARCH_VERIFY_CERTS` | True | No | Verify ES certs |
| `SEARCH_SYNC_MODE` | queue | No | Sync mode |
| `SEARCH_QUEUE_VIA_CELERY` | False | No | Queue via Celery |
| `SEARCH_QUEUE_BATCH_SIZE` | 200 | No | Queue batch size |
| `SEARCH_QUEUE_MAX_ATTEMPTS` | 5 | No | Queue max attempts |
| `METRICS_TOKEN` | (empty) | No* | Metrics token |
| `METRICS_ALLOWED_IPS` | (empty) | No* | Metrics allowed IPs |
| `READYZ_TIMEOUT_SECONDS` | 1.0 | No | Readiness timeout |
| `EMAIL_BACKEND` | dummy | Yes* | Email backend |
| `EMAIL_HOST` | (empty) | Yes* | SMTP host |
| `EMAIL_PORT` | 587 | No | SMTP port |
| `EMAIL_USE_TLS` | True | No | SMTP TLS |
| `EMAIL_HOST_USER` | (empty) | Yes* | SMTP user |
| `EMAIL_HOST_PASSWORD` | (empty) | Yes* | SMTP password |
| `REVIEW_QUEUE_NOTIFY_EMAILS` | (empty) | No | Review alert emails |
| `MAX_JSON_REQUEST_BYTES` | 1048576 | No | JSON body limit |
| `MAX_UPLOAD_REQUEST_BYTES` | 10485760 | No | Upload body limit |
| `CACHE_TTL_CARD_LIST` | 300 | No | Card list TTL |
| `CACHE_TTL_FILTER_RESULTS` | 120 | No | Filter results TTL |
| `CACHE_TTL_SEARCH_SUGGESTIONS` | 600 | No | Search suggestions TTL |
| `CACHE_TTL_ADVANCED_SEARCH` | 120 | No | Advanced search TTL |

*Required if the corresponding feature is enabled in production.

## Validation and Testing

### Required Variables
These variables must be set for the application to function:
- `SECRET_KEY`
- `OPENAI_API_KEY` (or `GEMINI_API_KEY` / `OPENROUTER_API_KEY`)
- `CELERY_BROKER_URL`
- `REDIS_CACHE_URL` (or `CACHE_BACKEND=locmem`)
- Database: either `DATABASE_URL` or all of `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`

### Optional Variables
These have sensible defaults but can be customized:
- `DEBUG` (defaults to True)
- `ENVIRONMENT` (defaults to "local")
- `THROTTLE_RATE_*` (have default rate limits)
- `CORS_*` (have default CORS settings)
- `SEARCH_*` (have defaults; SEARCH_ENABLED defaults to True)

### Testing Configuration
```bash
# Test your configuration
python manage.py check

# Test database connection
python manage.py migrate --dry-run

# Test Celery connection
celery -A credit_mate_ai inspect ping

# Test Redis connection
redis-cli ping

# Export and validate OpenAPI schema
python manage.py spectacular --file /tmp/schema.yml --validate
```

## Security Best Practices

1. **Never commit secrets to version control**
2. **Use different SECRET_KEY for each environment**
3. **Use strong, unique passwords for databases**
4. **Rotate API keys regularly**
5. **Use HTTPS in production**
6. **Keep CORS origins minimal and specific**
7. **Monitor rate limiting logs**
8. **Use environment-specific rate limits**

## Troubleshooting

### Common Issues

#### Secret Key Errors
```bash
# Error: SECRET_KEY must be set
# Solution: Set SECRET_KEY environment variable
export SECRET_KEY="your-secret-key-here"
```

#### Database Connection Issues
```bash
# Error: Database connection failed
# Solution: Check database settings and connectivity
python manage.py dbshell
```

#### Redis Connection Issues
```bash
# Error: Celery broker connection failed
# Solution: Check Redis is running and accessible
redis-cli ping
```

#### CORS Issues
```bash
# Error: CORS policy blocks request
# Solution: Add frontend domain to CORS_ALLOWED_ORIGINS
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
```

#### Search Issues
```bash
# Error: Search service unavailable
# Solution: Check SEARCH_ENABLED and SEARCH_URL
curl -s http://127.0.0.1:19200
```

#### Metrics Access Issues
```bash
# Error: 403 Forbidden on /metrics
# Solution: Set METRICS_TOKEN or METRICS_ALLOWED_IPS
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/metrics
```

#### Readiness Probe Issues
```bash
# Error: /api/readyz/ returns 503
# Solution: Check database, Redis, and Elasticsearch connectivity
curl -v http://localhost:8000/api/readyz/
```

For detailed configuration guides, see:
- [Email Configuration](./email.md)
- [CORS and Rate Limiting](./cors-and-rate-limiting.md)

## Local Development Commands

```bash
# Install dependencies
pip install uv
uv sync --dev

# Run migrations
uv run python manage.py migrate

# Create superuser
uv run python manage.py createsuperuser

# Run development server
uv run python manage.py runserver

# Run Celery worker (terminal 2)
uv run celery -A credit_mate_ai worker --loglevel=info

# Run Celery beat (terminal 3)
uv run celery -A credit_mate_ai beat --loglevel=info

# Run tests (uses Redis DB 14, PostgreSQL via docker)
REDIS_CACHE_URL=redis://127.0.0.1:6379/14 DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False DB_NAME=test_docs DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 uv run pytest

# Run specific test module
REDIS_CACHE_URL=redis://127.0.0.1:6379/14 DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False DB_NAME=test_docs DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 uv run pytest credit_cards/tests/test_typeahead.py -v

# Start PostgreSQL via Docker (unique database per task)
docker run -d --name task-63-search-db-1 -e POSTGRES_DB=test_docs -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15

# Start Redis (shared, uses DB 14 for tests)
docker run -d -p 6379:6379 redis:7-alpine
```

## Notes

- `SEARCH_ENABLED=False` disables Elasticsearch for local development; use database fallback
- Redis DB 14 is reserved for test runs; production uses DB 1
- The `METRICS_TOKEN` and `METRICS_ALLOWED_IPS` are both required for `/metrics` access (OR logic)
- `REVIEW_QUEUE_NOTIFY_EMAILS` is opt-in; empty means no email notifications
- Cache TTLs can be tuned per environment; shorter TTLs for development
