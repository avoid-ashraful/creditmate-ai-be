# Cache Layer Documentation

## Overview

The Credit Mate AI backend implements a query-aware caching layer using Django's cache framework with Redis backend (or LocMemCache for local testing). The cache layer provides significant performance improvements for read-heavy API endpoints while maintaining data freshness through atomic version-based invalidation.

## Cache Architecture

### Design Principles

1. **Query-aware keys**: Cache keys are built from canonicalized query parameters + request origin/path
2. **Atomic versioning**: Invalidation uses version counters bumped atomically inside `transaction.on_commit`
3. **Distinct TTLs**: Different cached surfaces have different TTLs based on data volatility
4. **Graceful degradation**: Cache misses fall through to database/Elasticsearch transparently

### Cache Key Structure

```
{prefix}:v{version}:{sha256_digest}
```

Example:
```
credit_cards:list:v3:a1b2c3d4e5f6g7h8...
```

Components:
- **Prefix**: Identifies the cached surface (e.g., `credit_cards:list`, `credit_cards:filter`)
- **Version**: Integer from version key, incremented on data changes
- **Digest**: SHA256 of `origin + path + canonicalized_query_params` (first 32 chars)

## Cache Surfaces & TTLs

| Surface | Prefix | Version Key | TTL (default) | Env Override |
|---------|--------|-------------|---------------|--------------|
| Card List | `credit_cards:list` | `credit_cards:list:version` | 300s (5 min) | `CACHE_TTL_CARD_LIST` |
| Filter Results | `credit_cards:filter` | `credit_cards:filter:version` | 120s (2 min) | `CACHE_TTL_FILTER_RESULTS` |
| Search Suggestions | `credit_cards:search_suggestions` | `credit_cards:search_suggestions:version` | 600s (10 min) | `CACHE_TTL_SEARCH_SUGGESTIONS` |
| Advanced Search | `credit_cards:advanced_search` | `credit_cards:advanced_search:version` | 120s (2 min) | `CACHE_TTL_ADVANCED_SEARCH` |

### TTL Rationale

- **Card List (5 min)**: Low volatility, high traffic, OK to serve slightly stale
- **Filter Results (2 min)**: Higher volatility due to search/filter params, shorter TTL
- **Search Suggestions (10 min)**: Very stable, computed from aggregates, long TTL
- **Advanced Search (2 min)**: Complex queries, facet counts change, shorter TTL

## Query Canonicalization

The `canonicalize_query_params` function ensures equivalent queries produce identical cache keys:

1. **Parameter names sorted**: `?a=1&b=2` = `?b=2&a=1`
2. **Multi-value order preserved**: Django-filter uses last-value-wins, so `bank=1&bank=2` ≠ `bank=2&bank=1`
3. **JSON encoding**: Avoids `&`/`=` ambiguity in values
4. **Empty values excluded**: `?search=` is treated as no search param

## Version-Based Invalidation

### How It Works

1. **Version keys** stored in Redis (e.g., `credit_cards:list:version`)
2. **Atomic initialization**: `cache.add(key, 1, None)` (SETNX) prevents reset
3. **Atomic increment**: `cache.incr(key)` bumps version
4. **Transaction safety**: Runs in `transaction.on_commit` so pre-commit data never re-cached under new version

### Invalidation Triggers

```python
# CreditCard changes (post_save, post_delete)
@receiver([post_save, post_delete], sender="credit_cards.CreditCard")
def invalidate_credit_card_caches(sender, **kwargs):
    bump_cache_versions()  # Bumps list, filter, suggestions versions

# Bank changes (post_save, post_delete)
@receiver([post_save, post_delete], sender="banks.Bank")
def invalidate_card_caches_on_bank_change(sender, **kwargs):
    bump_cache_versions()

# Advanced search has separate version
@receiver([post_save, post_delete], sender="credit_cards.CreditCard")
def invalidate_advanced_search_on_card_change(sender, **kwargs):
    bump_advanced_search_version()

@receiver([post_save, post_delete], sender="banks.Bank")
def invalidate_advanced_search_on_bank_change(sender, **kwargs):
    bump_advanced_search_version()
```

### Manual Invalidation

```python
from credit_mate_ai.cache import bump_cache_versions, bump_advanced_search_version

# Invalidate all card surfaces
bump_cache_versions()

# Invalidate only advanced search
bump_advanced_search_version()
```

## Cache Behavior by Endpoint

### List Endpoint (`GET /api/v1/credit-cards/`)

```python
def list(self, request, *args, **kwargs):
    has_filters = (
        any(key in request.query_params for key in filter_param_keys)
        or "search" in request.query_params
    )
    
    cache_key = build_query_cache_key(
        "credit_cards:filter" if has_filters else "credit_cards:list",
        FILTER_RESULTS_VERSION_KEY if has_filters else CARD_LIST_VERSION_KEY,
        request,
    )
    ttl = FILTER_RESULTS_TTL if has_filters else CARD_LIST_TTL
```

- **No filters**: Uses card list TTL (5 min)
- **With filters/search**: Uses filter results TTL (2 min)
- **Cache key includes**: All query params + origin + path

### Search Suggestions (`GET /api/v1/credit-cards/search-suggestions/`)

- **TTL**: 10 minutes (very stable)
- **Version key**: `credit_cards:search_suggestions:version`
- **Cache key**: Origin + path only (no query params)

### Typeahead (`GET /api/v1/credit-cards/typeahead/`)

- **No caching**: Real-time autocomplete, always hits database
- **Reason**: Low latency requirement, query-dependent results

### Advanced Search (`GET /api/v1/credit-cards/advanced-search/`)

```python
cache_key = _build_cache_key("credit_cards:advanced_search", normalized_params, request)
cached_response = cache.get(cache_key)
```

- **TTL**: 2 minutes (`ADVANCED_SEARCH_TTL`)
- **Version key**: `credit_cards:advanced_search:version` (separate from main surfaces)
- **Normalization**: Uses `normalize_query_params` for consistent keys
- **Includes**: Sort options, categories, normalized query in response

### Field History (`GET /api/v1/credit-cards/{id}/field-history/`)

- **No caching**: Requires authentication, user-specific data

## Cache Backend Configuration

### Redis (Production)

```python
# settings.py
CACHE_BACKEND = "redis"  # default
REDIS_CACHE_URL = "redis://127.0.0.1:6379/1"

_REDIS_CACHE_CONFIG = {
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": REDIS_CACHE_URL,
    "KEY_PREFIX": "creditmate",
}
```

### LocMemCache (Local Testing)

```bash
# Environment variable
CACHE_BACKEND=locmem
```

```python
# settings.py
_LOCMEM_CACHE_CONFIG = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "creditmate-cache",
}
```

## Monitoring & Debugging

### Check Cache Status

```bash
# Redis CLI - check keys
redis-cli KEYS "creditmate:credit_cards:*"

# Check version keys
redis-cli GET creditmate:credit_cards:list:version
redis-cli GET creditmate:credit_cards:filter:version
redis-cli GET creditmate:credit_cards:advanced_search:version

# Check TTL
redis-cli TTL "creditmate:credit_cards:list:v3:a1b2c3d4..."
```

### Cache Hit/Miss Logging

Enable debug logging for cache operations:

```python
# settings.py
LOGGING = {
    "loggers": {
        "credit_mate_ai.cache": {"level": "DEBUG"},
        "credit_cards.api.views": {"level": "DEBUG"},
    }
}
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Stale data after update | Version not bumped | Check signals are connected, transaction committed |
| Cache not working | Redis unavailable | Check `REDIS_CACHE_URL`, Redis connectivity |
| Memory pressure | Too many cache entries | Reduce TTLs, monitor key count |
| Inconsistent results | Query canonicalization bug | Check `canonicalize_query_params` logic |

## Testing Cache Behavior

```bash
# Run cache tests
REDIS_CACHE_URL=redis://127.0.0.1:6379/14 DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False DB_NAME=test_docs DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 uv run pytest credit_cards/tests/test_cache.py -v
```

### Test Coverage

- Cache key generation consistency
- Version bumping on model changes
- TTL adherence
- Cache invalidation on save/delete
- Separate advanced search version
- Query canonicalization edge cases

## Performance Tuning

### TTL Adjustments

For high-traffic production:
```bash
# Increase TTLs if data changes infrequently
CACHE_TTL_CARD_LIST=600      # 10 min
CACHE_TTL_FILTER_RESULTS=300 # 5 min
CACHE_TTL_ADVANCED_SEARCH=300 # 5 min
```

For frequently changing data:
```bash
# Decrease TTLs
CACHE_TTL_CARD_LIST=60       # 1 min
CACHE_TTL_FILTER_RESULTS=30  # 30 sec
```

### Redis Configuration

```bash
# Redis memory policy (evict least recently used)
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Monitor memory usage
redis-cli INFO memory
```

### Connection Pooling

Django's RedisCache uses a connection pool automatically. For high concurrency:

```python
# settings.py - customize pool
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "KEY_PREFIX": "creditmate",
        "OPTIONS": {
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 50,
            }
        }
    }
}
```

## Cache Key Examples

### Card List (no filters)
```
Origin: http://localhost:8000
Path: /api/v1/credit-cards/
Query: {}
Canonical: "[]"
Digest: sha256("http://localhost:8000/api/v1/credit-cards/:[]")
Key: credit_cards:list:v1:abc123...
```

### Filtered List (with search)
```
Origin: http://localhost:8000
Path: /api/v1/credit-cards/
Query: {"search": "travel", "page": "1"}
Canonical: '[["page",["1"]],["search",["travel"]]]'
Digest: sha256("http://localhost:8000/api/v1/credit-cards/:[[\"page\",[\"1\"]],[\"search\",[\"travel\"]]]")
Key: credit_cards:filter:v1:def456...
```

### Advanced Search
```
Origin: http://localhost:8000
Path: /api/v1/credit-cards/advanced-search/
Query: {"search": "travel", "categories": "travel,cashback"}
Normalized: {"search": "travel", "categories": "cashback,travel"}
Digest: sha256("http://localhost:8000/api/v1/credit-cards/advanced-search/:[[\"categories\",[\"cashback,travel\"]],[\"search\",[\"travel\"]]]")
Key: credit_cards:advanced_search:v1:ghi789...
```

## Related Documentation

- [Environment Variables](../configuration/environment-variables.md) - Cache TTL overrides
- [Advanced Search API](../api/advanced-search.md) - Advanced search caching details
- [Rate Limiting](../configuration/cors-and-rate-limiting.md) - Throttling (uses same cache)
