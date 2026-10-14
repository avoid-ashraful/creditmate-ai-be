# Troubleshooting Guide

This guide covers common issues and their solutions for the Credit Mate AI backend.

## Quick Diagnostics

### Health Checks

```bash
# Liveness (process alive)
curl -fsS http://localhost:8000/api/healthz/

# Readiness (dependencies healthy)
curl -sS http://localhost:8000/api/readyz/ | jq .

# Metrics (if authorized)
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/metrics | head -20

# OpenAPI schema
curl -sS http://localhost:8000/api/v1/schema/ | jq '.info'
```

### Service Status

```bash
# Django check
uv run python manage.py check

# Database connection
uv run python manage.py dbshell -c "SELECT 1;"

# Redis connection
redis-cli ping

# Celery workers
uv run celery -A credit_mate_ai inspect active

# Elasticsearch (if enabled)
curl -sS http://127.0.0.1:19200/_cluster/health
```

## Common Issues

### 1. Database Connection Issues

**Symptoms:**
- `psycopg2.OperationalError: connection to server failed`
- `/api/readyz/` returns 503 with database check failed
- Migrations fail

**Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| PostgreSQL not running | `sudo systemctl start postgresql` (Linux) / `brew services start postgresql` (macOS) |
| Wrong credentials in `.env` | Check `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` |
| Database doesn't exist | `sudo -u postgres createdb creditmate_db` |
| User lacks privileges | `GRANT ALL PRIVILEGES ON DATABASE creditmate_db TO creditmate_user;` |
| Wrong host (Docker vs local) | Use `localhost` for local, `db` for Docker Compose |

**Debug:**
```bash
# Test connection directly
psql -U postgres -h localhost -d creditmate_db

# Check environment
echo $DB_HOST $DB_NAME $DB_USER

# Verify Django sees it
uv run python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('OK')"
```

### 2. Redis Connection Issues

**Symptoms:**
- `Connection refused` on port 6379
- Celery worker fails to start
- Cache operations fail
- `/api/readyz/` returns 503 with cache check failed

**Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| Redis not running | `sudo systemctl start redis-server` / `brew services start redis` |
| Wrong URL in `.env` | Check `REDIS_CACHE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| Wrong database number | Tests use `/14`, production uses `/1`, cache uses `/1` |
| Redis password required | Add `:password@` to URL: `redis://:password@host:6379/1` |

**Debug:**
```bash
# Test Redis
redis-cli ping

# Check connection
redis-cli -u redis://127.0.0.1:6379/1 INFO

# Check Celery broker
uv run celery -A credit_mate_ai inspect ping
```

### 3. Elasticsearch Issues

**Symptoms:**
- `/api/search/` returns 503
- `/api/readyz/` returns 503 with elasticsearch check failed
- Advanced search falls back to database (check `source` field)

**Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| `SEARCH_ENABLED=False` | Set `SEARCH_ENABLED=True` in `.env` |
| Elasticsearch not running | Start container: `docker run -d -p 19200:9200 -e "discovery.type=single-node" docker.elastic.co/elasticsearch/elasticsearch:8.11.0` |
| Wrong URL | Check `SEARCH_URL=http://127.0.0.1:19200` |
| Certificate verification | Set `SEARCH_VERIFY_CERTS=False` for self-signed certs |
| Index missing | Run `uv run python manage.py search_index --rebuild` |

**Debug:**
```bash
# Check Elasticsearch health
curl -sS http://127.0.0.1:19200/_cluster/health | jq .

# Test ping
curl -sS http://127.0.0.1:19200/_cluster/health?pretty

# Check indices
curl -sS http://127.0.0.1:19200/_cat/indices?v

# Django search client
uv run python manage.py shell -c "
from search.client import is_enabled, ping, get_client
print('Enabled:', is_enabled())
print('Ping:', ping())
try:
    client = get_client()
    print('Client:', client.info())
except Exception as e:
    print('Error:', e)
"
```

### 4. CORS Issues

**Symptoms:**
- Browser console: "CORS policy: No 'Access-Control-Allow-Origin' header"
- Frontend requests blocked

**Solutions:**
```bash
# Add frontend origin to .env
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://yourdomain.com

# For development only (NEVER in production)
CORS_ALLOW_ALL_ORIGINS=True

# Verify headers
curl -H "Origin: http://localhost:3000" -X OPTIONS http://localhost:8000/api/v1/credit-cards/ -v
```

### 5. Rate Limiting Issues

**Symptoms:**
- 429 Too Many Responses
- `X-RateLimit-Remaining: 0`

**Solutions:**
```bash
# Check current limits
echo "Anon: $THROTTLE_RATE_ANON"
echo "User: $THROTTLE_RATE_USER"
echo "Burst: $THROTTLE_RATE_BURST"

# Increase for development
THROTTLE_RATE_ANON=10000/hour
THROTTLE_RATE_USER=20000/hour
THROTTLE_RATE_BURST=1000/min

# Check cache backend (required for throttling)
redis-cli ping
```

### 6. Metrics Access Denied (403)

**Symptoms:**
- `curl http://localhost:8000/metrics` returns 403

**Solutions:**
```bash
# Option 1: Set bearer token
export METRICS_TOKEN="your-secret-token"
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/metrics

# Option 2: Allow your IP
export METRICS_ALLOWED_IPS="127.0.0.1,10.0.0.0/8"
curl http://localhost:8000/metrics

# Check settings
uv run python manage.py shell -c "
from django.conf import settings
print('Token:', bool(settings.METRICS_TOKEN))
print('Allowed IPs:', settings.METRICS_ALLOWED_IPS)
"
```

### 7. Readiness Probe Failures (503)

**Symptoms:**
- Kubernetes pod not ready
- `/api/readyz/` returns 503

**Debug:**
```bash
# Full response
curl -sS http://localhost:8000/api/readyz/ | jq .

# Individual checks
uv run python manage.py shell -c "
import time
from django.db import connection
from django.core.cache import cache
from search.client import ping

# Database
start = time.perf_counter()
with connection.cursor() as c:
    c.execute('SELECT 1')
print('DB:', (time.perf_counter() - start) * 1000, 'ms')

# Cache
start = time.perf_counter()
cache.set('test', 'ok', 10)
print('Cache:', cache.get('test'), (time.perf_counter() - start) * 1000, 'ms')

# Elasticsearch
print('ES:', ping())
"
```

**Common Fixes:**
- Increase `READYZ_TIMEOUT_SECONDS` if network latency is high
- Ensure PostgreSQL `statement_timeout` > `READYZ_TIMEOUT_SECONDS`
- Check Redis socket timeouts

### 8. Migration Issues

**Symptoms:**
- `django.db.migrations.exceptions.InconsistentMigrationHistory`
- `django.db.utils.OperationalError: relation already exists`

**Solutions:**
```bash
# Check migration status
uv run python manage.py showmigrations

# Show planned migrations
uv run python manage.py migrate --plan

# Fake migration (if table exists)
uv run python manage.py migrate <app> <migration> --fake

# Reset migrations (DANGEROUS - data loss)
uv run python manage.py migrate <app> zero
uv run python manage.py migrate <app>
```

### 9. OpenAPI Schema Export Warnings

**Symptoms:**
- `Warning: unable to resolve type hint for function "credit_card_count"`

**This is expected and non-blocking.** The warnings are for `BankSerializer` and `BankListSerializer` where `credit_card_count` is a property without type hints.

**To suppress (if needed):**
```python
# In serializers.py
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

@extend_schema_field(OpenApiTypes.INT)
def credit_card_count(self, obj):
    return obj.credit_cards.filter(is_active=True).count()
```

### 10. Celery Tasks Not Executing

**Symptoms:**
- Tasks queued but not processed
- `celery inspect active` returns empty

**Solutions:**
```bash
# Check worker is running
ps aux | grep celery

# Check queue length
redis-cli LLEN celery

# Check worker logs
uv run celery -A credit_mate_ai worker --loglevel=debug

# Restart worker
pkill -f "celery.*worker"
uv run celery -A credit_mate_ai worker --loglevel=info

# Check beat scheduler
ps aux | grep beat
uv run celery -A credit_mate_ai beat --loglevel=info
```

### 11. Static Files Not Serving

**Symptoms:**
- 404 for CSS/JS in admin
- WhiteNoise not collecting

**Solutions:**
```bash
# Collect static files
uv run python manage.py collectstatic --noinput

# Check STATIC_ROOT
echo $STATIC_ROOT

# Verify WhiteNoise in MIDDLEWARE (after SecurityMiddleware, before CorsMiddleware)
```

### 12. Test Failures

**Symptoms:**
- Tests fail with database errors
- Flaky tests due to shared Redis

**Solutions:**
```bash
# Use dedicated test database
export DB_NAME=test_unique_name

# Use Redis DB 14 for tests
export REDIS_CACHE_URL=redis://127.0.0.1:6379/14

# Run one test module at a time
uv run pytest credit_cards/tests/test_typeahead.py -v

# Disable search for tests
export SEARCH_ENABLED=False

# Full test command
REDIS_CACHE_URL=redis://127.0.0.1:6379/14 DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False DB_NAME=test_docs DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 uv run pytest credit_cards/tests/ -v
```

### 13. Search Index Out of Sync

**Symptoms:**
- Search returns stale data
- New cards not appearing in search

**Solutions:**
```bash
# Check sync mode
echo $SEARCH_SYNC_MODE

# Rebuild index
uv run python manage.py search_index --rebuild

# Check queue depth
curl -sS http://localhost:8000/api/search/status/ | jq .queue_depth

# Process queue manually
uv run python manage.py search_index --process-queue
```

### 14. Data Quality Dashboard Access

**Symptoms:**
- 302 redirect to login
- 403 Forbidden

**Solution:**
- Requires staff user (`is_staff=True`)
- Access via admin session cookies:
```bash
# Login to admin first, then:
curl -b cookies.txt http://localhost:8000/admin/data-quality/
```

### 15. Review Queue Email Notifications

**Symptoms:**
- High-priority items not triggering emails

**Check:**
```bash
# Verify setting
echo $REVIEW_QUEUE_NOTIFY_EMAILS

# Check email backend (production only)
echo $EMAIL_BACKEND
echo $ENVIRONMENT

# Test email
uv run python manage.py shell -c "
from django.core.mail import send_mail
send_mail('Test', 'Body', None, ['test@example.com'], fail_silently=False)
"
```

## Performance Issues

### Slow API Responses

**Diagnostics:**
```bash
# Check metrics for latency
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/metrics | grep django_http_requests_latency_seconds

# Check slow queries
uv run python manage.py shell -c "
from django.db import connection
print(connection.queries[-5:])  # Last 5 queries (DEBUG=True only)
"
```

**Solutions:**
- Enable caching (verify `CACHE_BACKEND=redis`)
- Increase cache TTLs for stable data
- Add database indexes for filtered fields
- Use `select_related`/`prefetch_related` in querysets
- Check Elasticsearch vs database fallback (`source` field in advanced search)

### High Memory Usage

**Diagnostics:**
```bash
# Check process memory
ps aux | grep python

# Check Redis memory
redis-cli INFO memory | grep used_memory_human

# Check Celery worker memory
uv run celery -A credit_mate_ai inspect stats | grep pool
```

**Solutions:**
- Reduce Celery concurrency: `uv run celery -A credit_mate_ai worker -c 2`
- Set Redis memory policy: `redis-cli CONFIG SET maxmemory-policy allkeys-lru`
- Limit page_size in API requests
- Enable compression in WhiteNoise

## Deployment Issues

### Docker Build Failures

```bash
# Clean build
docker-compose build --no-cache

# Check Dockerfile syntax
docker build -t test . --dry-run
```

### Environment Variable Issues

```bash
# Verify all required vars
uv run python manage.py shell -c "
import os
required = ['SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'CELERY_BROKER_URL', 'REDIS_CACHE_URL']
for var in required:
    val = os.getenv(var)
    print(f'{var}: {\"SET\" if val else \"MISSING\"}' + (f' = {val[:10]}...' if val else ''))
"
```

## Getting Help

1. **Check logs**: `docker-compose logs -f web` or `journalctl -u gunicorn`
2. **Enable debug logging**: Set `LOG_LEVEL=DEBUG` in `.env`
3. **Run health checks**: Verify all three endpoints (`/healthz/`, `/readyz/`, `/metrics`)
4. **Verify schema**: `uv run python manage.py spectacular --validate`
5. **Run tests**: Ensure test suite passes before deploying

## Useful Commands Reference

```bash
# Full health check
curl -sS http://localhost:8000/api/healthz/ && echo " | " && curl -sS http://localhost:8000/api/readyz/ | jq .

# Test all API endpoints
curl -sS http://localhost:8000/api/v1/banks/ | jq '.count'
curl -sS http://localhost:8000/api/v1/credit-cards/ | jq '.count'
curl -sS http://localhost:8000/api/search/?q=test | jq '.results.cards.total'
curl -sS http://localhost:8000/api/v1/credit-cards/typeahead/?q=visa | jq '.suggestions | length'

# Cache stats
redis-cli INFO stats | grep keyspace

# Celery queue
redis-cli LLEN celery

# Database size
psql -U postgres -d creditmate_db -c "SELECT pg_size_pretty(pg_database_size('creditmate_db'));"
```
