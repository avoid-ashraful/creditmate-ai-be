# Search API Documentation

## Overview

The Search API provides Elasticsearch-backed full-text search, type-ahead suggestions, and infrastructure status. All endpoints are under `/api/search/`.

## Base URL

```
/api/search/
```

## Endpoints

### Full-Text Search

**Endpoint:** `GET /api/search/`

**Description:** Full-text search over banks and credit cards with filtering, pagination, and faceting.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (required) |
| `type` | string | Search target: `cards`, `banks`, or `all` (default: `cards`) |
| `page` | integer | Page number (1-based, default: 1) |
| `page_size` | integer | Results per page (1-100, default: 20) |
| `ordering` | string | Sort field (see below) |
| `*` | any | Additional filters (see Filterable Fields) |

**Ordering Fields (cards):**
- `annual_fee`, `-annual_fee`
- `interest_rate_apr`, `-interest_rate_apr`
- `name.keyword`, `-name.keyword`
- `bank_name.keyword`, `-bank_name.keyword`
- `created`, `-created`
- `modified`, `-modified`
- `has_lounge_access`, `has_annual_fee`

**Ordering Fields (banks):**
- `name.keyword`, `-name.keyword`
- `credit_card_count`, `-credit_card_count`
- `created`, `-created`
- `modified`, `-modified`

**Filterable Fields (cards):**
- `bank_id` (exact)
- `is_active` (boolean)
- `has_annual_fee` (boolean)
- `has_lounge_access` (boolean)
- `has_lounge_access_international` (boolean)
- `has_lounge_access_domestic` (boolean)
- `has_fee_waiver` (exists)
- `no_annual_fee` (annual_fee == 0)
- `annual_fee_unknown` (annual_fee not indexed)
- `annual_fee_min`, `annual_fee_max`, `annual_fee_exact`
- `interest_rate_min`, `interest_rate_max`
- `min_lounge_visits_international`, `min_lounge_visits_domestic`
- `bank_ids` (multi-value)
- `features` (multi-value)
- `feature_search` (match)

**Filterable Fields (banks):**
- `is_active` (boolean)
- `min_credit_card_count`, `max_credit_card_count`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/search/?q=travel&type=cards&page=1&page_size=20&has_lounge_access=true"
```

**Example Response:**
```json
{
  "query": "travel",
  "type": "cards",
  "page": 1,
  "page_size": 20,
  "results": {
    "cards": {
      "total": 42,
      "hits": [
        {
          "id": 5,
          "name": "Travel Rewards Card",
          "bank_name": "Premium Bank",
          "bank_id": 1,
          "annual_fee": 450.00,
          "interest_rate_apr": 19.99,
          "has_lounge_access": true,
          "has_annual_fee": true,
          "_score": 12.5
        }
      ],
      "facets": {
        "bank_name": {
          "buckets": [
            {"key": "Chase", "doc_count": 15},
            {"key": "American Express", "doc_count": 8}
          ]
        },
        "annual_fee_ranges": {
          "buckets": [
            {"key": "free", "from": 0, "to": 0.01, "doc_count": 5},
            {"key": "0-1000", "from": 0, "to": 1000, "doc_count": 20}
          ]
        }
      }
    }
  }
}
```

### Type-Ahead Suggestions

**Endpoint:** `GET /api/search/suggest/`

**Description:** Get type-ahead suggestions for partial queries. Uses Elasticsearch completion suggesters with edge n-grams.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Partial query (required) |
| `type` | string | `cards` or `banks` (default: `cards`) |
| `limit` | integer | Maximum suggestions (1-20, default: 8) |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/search/suggest/?q=sapp&type=cards&limit=5"
```

**Example Response:**
```json
{
  "suggestions": [
    {"id": 1, "name": "Sapphire Preferred", "bank_name": "Chase", "bank_id": 1},
    {"id": 2, "name": "Sapphire Reserve", "bank_name": "Chase", "bank_id": 1}
  ]
}
```

### Search Status

**Endpoint:** `GET /api/search/status/`

**Description:** Get search infrastructure status including engine health, index metadata, and queue depth.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/search/status/"
```

**Example Response:**
```json
{
  "engine": {
    "available": true,
    "version": {"number": "8.11.0", "build_flavor": "default", "build_type": "docker"}
  },
  "indexes_meta": {
    "banks": {
      "index": "banks",
      "filterable_fields": ["bank_id", "is_active", "has_annual_fee", ...]
    },
    "cards": {
      "index": "credit_cards",
      "filterable_fields": ["bank_id", "is_active", "has_annual_fee", ...]
    }
  },
  "queue_depth": 0,
  "sync_mode": "queue"
}
```

## Search Architecture

### Elasticsearch Configuration

```bash
# Enable/disable search
SEARCH_ENABLED=True

# Elasticsearch URL
SEARCH_URL=http://127.0.0.1:19200

# Index prefix (for multi-tenancy)
SEARCH_INDEX_PREFIX=

# Request timeout
SEARCH_REQUEST_TIMEOUT=10

# Verify certificates
SEARCH_VERIFY_CERTS=True
```

### Sync Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `queue` | Signal writes to outbox, worker drains | Production (default) |
| `sync` | Signal writes and drains inline | Development, testing |
| `off` | Signals not connected | No search needed |

```bash
SEARCH_SYNC_MODE=queue  # default
```

### Queue Processing

```bash
# Route queue through Celery (requires Redis)
SEARCH_QUEUE_VIA_CELERY=False

# Batch size
SEARCH_QUEUE_BATCH_SIZE=200

# Max retry attempts
SEARCH_QUEUE_MAX_ATTEMPTS=5
```

### Index Mappings

The search indexes use multi-language analyzers:
- **multilang**: Primary analyzer for mixed English/Bengali content
- **english**: English-specific sub-fields
- **bengali**: Bengali-specific sub-fields

Fields use `keyword` sub-fields for exact filtering and aggregations.

### Full-Text Search Behavior

1. **Multi-match query** across weighted fields:
   - Cards: `name^3`, `bank_name^2`, `content`, `reward_points_policy`, `additional_features.text`, lounge fields, fee fields
   - Banks: `name^3`, `content`

2. **Language detection**: Bengali queries route to Bengali analyzer
3. **Fuzziness**: AUTO fuzziness with prefix_length=2 for typo tolerance
4. **Operator**: AND (all terms must match)

### Faceted Search

Aggregations are pre-defined in `search/queries.py`:

**Card Aggregations:**
- `bank_name` (terms, top 50)
- `bank_ids` (terms, top 50)
- `is_active` (terms)
- `has_annual_fee` (terms)
- `annual_fee_known` (terms)
- `has_lounge_access` (terms)
- `additional_features` (terms, top 30)
- `annual_fee_ranges` (range: free, 0-1000, 1000-3000, 3000-5000, 5000+)
- `interest_rate_apr_ranges` (range: under_20, 20-25, 25-30, 30+)

**Bank Aggregations:**
- `is_active` (terms)
- `credit_card_count_ranges` (range: none, 1-5, 5-10, 10+)

## Error Handling

### 503 Service Unavailable

Returned when Elasticsearch is unavailable:

```json
{
  "detail": "Search service is temporarily unavailable"
}
```

This happens when:
- `SEARCH_ENABLED=False`
- Elasticsearch connection fails
- Elasticsearch ping fails

### 404 Not Found

Returned for unknown search types:

```json
{
  "detail": "Unknown search type: invalid"
}
```

## Rate Limiting

Subject to standard API rate limits:
- Anonymous: 100/min (configurable via `THROTTLE_RATE_ANON`)
- Authenticated: 1000/min (configurable via `THROTTLE_RATE_USER`)
- Burst: 10/sec (configurable via `THROTTLE_RATE_BURST`)

## Usage Examples

### Search Travel Cards with Filters

```bash
curl -X GET "http://localhost:8000/api/search/?q=travel&type=cards&has_lounge_access=true&annual_fee_max=500&ordering=annual_fee"
```

### Search Banks with Minimum Cards

```bash
curl -X GET "http://localhost:8000/api/search/?q=chase&type=banks&min_credit_card_count=10"
```

### Get Suggestions for Autocomplete

```bash
curl -X GET "http://localhost:8000/api/search/suggest/?q=visa&type=cards&limit=10"
```

### Check Search Health

```bash
curl -X GET "http://localhost:8000/api/search/status/" | jq .
```

## Multi-Language Support

The search supports both English and Bengali queries:

- **English queries**: Use `english` analyzer on dedicated sub-fields
- **Bengali queries**: Detected by Unicode range, use `bengali` analyzer
- **Mixed queries**: Both analyzers applied via `should` clauses

## Implementation Details

### Query Building (`search/queries.py`)

Pure functions for testable query construction:
- `build_body()` - Complete search request body
- `build_query()` - Query section with language clauses
- `build_filters()` - Filter clauses from request params
- `build_ordering()` - Sort payload
- `build_suggest_body()` - Suggest request body

### Service Layer (`search/service.py`)

`SearchService` class handles:
- Client lifecycle management
- Index resolution
- Search execution
- Suggest execution
- Status reporting

### Client Management (`search/client.py`)

- Lazy client creation
- `is_enabled()` check
- `ping()` for health checks
- `reset_client()` for tests

## Related Documentation

- [Advanced Search API](../api/advanced-search.md) - Unified advanced search endpoint
- [Environment Variables](../configuration/environment-variables.md) - Search configuration
- [Observability](../operations/observability.md) - Metrics and health probes
- [Cache Layer](../operations/cache-layer.md) - Caching strategy
