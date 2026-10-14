# Advanced Search API Documentation

## Overview

The Advanced Search API provides a unified, high-performance search endpoint with Elasticsearch-backed full-text search, faceted navigation, multi-category OR filtering, and graceful database fallback. It is designed for complex credit card discovery workflows.

## Base URL

```
/api/v1/credit-cards/advanced-search/
```

## Endpoints

### Advanced Search

**Endpoint:** `GET /api/v1/credit-cards/advanced-search/`

**Description:** Execute advanced search with filtering, faceting, and sorting. Automatically falls back to database search when Elasticsearch is unavailable.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `search` | string | Full-text search query across card name, bank, rewards, features |
| `categories` | string | Comma-separated category slugs for OR filtering: `travel,cashback,premium,student,business,no-annual-fee` |
| `annual_fee_min` | number | Minimum annual fee |
| `annual_fee_max` | number | Maximum annual fee |
| `interest_rate_min` | number | Minimum APR |
| `interest_rate_max` | number | Maximum APR |
| `has_lounge_access` | boolean | Filter cards with any lounge access |
| `has_international_lounge` | boolean | Filter cards with international lounge access |
| `has_domestic_lounge` | boolean | Filter cards with domestic lounge access |
| `no_annual_fee` | boolean | Filter cards with no annual fee |
| `has_fee_waiver` | boolean | Filter cards with fee waiver policy |
| `feature_search` | string | Search within additional features |
| `bank_ids` | string | Comma-separated bank IDs to filter |
| `ordering` | string | Sort field (see Sort Options below) |
| `page` | integer | Page number (1-based, default: 1) |
| `page_size` | integer | Results per page (1-100, default: 20) |
| `facets` | string | Comma-separated facet names to include: `bank,category,annual_fee_range,interest_rate_range,lounge_access,fee_waiver,has_annual_fee` |

**Sort Options (ordering parameter):**
- `relevance` - Best match first (default with search query)
- `annual_fee` / `-annual_fee` - Annual fee ascending/descending
- `interest_rate_apr` / `-interest_rate_apr` - APR ascending/descending
- `-lounge_access_international` - International lounge access (most first)
- `-lounge_access_domestic` - Domestic lounge access (most first)
- `name` / `-name` - Card name A-Z / Z-A
- `-created` / `created` - Newest/oldest first

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/?search=travel&categories=travel,cashback&annual_fee_min=100&ordering=-annual_fee&facets=bank,category&page_size=20"
```

**Example Response:**
```json
{
  "query": "travel",
  "total": 42,
  "page": 1,
  "page_size": 20,
  "results": [
    {
      "id": 5,
      "name": "Travel Rewards Card",
      "bank_name": "Premium Bank",
      "annual_fee": 450.00,
      "interest_rate_apr": 19.99,
      "lounge_access_international": "Unlimited",
      "lounge_access_domestic": "4 per year",
      "additional_features": ["Travel insurance", "Priority Pass"],
      "reward_points_policy": "3x points on travel",
      "has_lounge_access": true,
      "has_annual_fee": true
    }
  ],
  "facets": {
    "bank": {
      "label": "Bank",
      "type": "terms",
      "buckets": [
        {"key": "Chase", "count": 15},
        {"key": "American Express", "count": 8}
      ]
    },
    "category": {
      "label": "Category",
      "type": "category",
      "buckets": [
        {"key": "travel", "label": "Travel", "count": 20, "filter": "categories=travel"},
        {"key": "cashback", "label": "Cashback", "count": 15, "filter": "categories=cashback"}
      ]
    },
    "annual_fee_range": {
      "label": "Annual Fee Range",
      "type": "range",
      "buckets": [
        {"key": "free", "label": "Free", "from": null, "to": 0.01, "count": 5},
        {"key": "low", "label": "1 - 1,000", "from": 0, "to": 1000, "count": 20},
        {"key": "medium", "label": "1,001 - 3,000", "from": 1000, "to": 3000, "count": 12},
        {"key": "high", "label": "3,001 - 5,000", "from": 3000, "to": 5000, "count": 5}
      ]
    }
  },
  "took": 15,
  "source": "elasticsearch",
  "cached": false,
  "sort_options": [...],
  "categories": [...],
  "normalized_query": {
    "search": "travel",
    "categories": "cashback,travel",
    "annual_fee_min": "100",
    "ordering": "-annual_fee",
    "facets": "bank,category"
  }
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Echo of the search query |
| `total` | integer | Total matching results |
| `page` | integer | Current page number |
| `page_size` | integer | Results per page |
| `results` | array | Array of credit card objects (same as list serializer) |
| `facets` | object | Facet counts for filter refinement |
| `took` | integer | Elasticsearch query time in ms (0 for DB fallback) |
| `source` | string | `"elasticsearch"` or `"database"` |
| `cached` | boolean | Whether response was served from cache |
| `sort_options` | array | Available sort options with descriptions |
| `categories` | array | Canonical category taxonomy |
| `normalized_query` | object | Canonicalized query parameters |

### Advanced Search: Sort Options

**Endpoint:** `GET /api/v1/credit-cards/advanced-search/sort-options/`

**Description:** Get available sort options with descriptions for UI select/dropdown.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/sort-options/"
```

**Example Response:**
```json
{
  "sort_options": [
    {"key": "relevance", "label": "Relevance", "description": "Best match first (default with search query)"},
    {"key": "annual_fee", "label": "Annual Fee (Low to High)", "description": "Sort by annual fee ascending"},
    {"key": "-annual_fee", "label": "Annual Fee (High to Low)", "description": "Sort by annual fee descending"},
    {"key": "interest_rate_apr", "label": "APR (Low to High)", "description": "Sort by interest rate ascending"},
    {"key": "-interest_rate_apr", "label": "APR (High to Low)", "description": "Sort by interest rate descending"},
    {"key": "-lounge_access_international", "label": "Lounge Access (Most First)", "description": "Sort by international lounge access descending"},
    {"key": "-lounge_access_domestic", "label": "Domestic Lounge (Most First)", "description": "Sort by domestic lounge access descending"},
    {"key": "name", "label": "Name (A-Z)", "description": "Sort by card name ascending"},
    {"key": "-name", "label": "Name (Z-A)", "description": "Sort by card name descending"},
    {"key": "-created", "label": "Newest First", "description": "Sort by creation date descending"},
    {"key": "created", "label": "Oldest First", "description": "Sort by creation date ascending"}
  ]
}
```

### Advanced Search: Categories

**Endpoint:** `GET /api/v1/credit-cards/advanced-search/categories/`

**Description:** Get canonical category taxonomy for multi-category filtering UI.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/categories/"
```

**Example Response:**
```json
{
  "categories": [
    {"slug": "travel", "name": "Travel"},
    {"slug": "cashback", "name": "Cashback"},
    {"slug": "premium", "name": "Premium"},
    {"slug": "student", "name": "Student"},
    {"slug": "business", "name": "Business"},
    {"slug": "no-annual-fee", "name": "No Annual Fee"}
  ]
}
```

### Advanced Search: Normalize Query

**Endpoint:** `GET /api/v1/credit-cards/advanced-search/normalize/`

**Description:** Normalize query parameters for saved search compatibility and deduplication. Returns a canonical representation that can be stored and compared.

**Query Parameters:** Same as the main advanced search endpoint.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/normalize/?search=travel&categories=travel,cashback&annual_fee_min=100&ordering=-annual_fee"
```

**Example Response:**
```json
{
  "normalized_query": {
    "search": "travel",
    "categories": "cashback,travel",
    "annual_fee_min": "100",
    "ordering": "-annual_fee"
  },
  "query_hash": "a1b2c3d4e5f6g7h8",
  "canonical_string": "annual_fee_min=100&categories=cashback,travel&ordering=-annual_fee&search=travel"
}
```

## Multi-Category Filtering (OR Logic)

The `categories` parameter accepts comma-separated slugs and applies OR logic:
- `categories=travel,cashback` returns cards matching Travel OR Cashback
- Categories are matched against canonical definitions:
  - `travel`: reward_points_policy or additional_features contains "travel"
  - `cashback`: reward_points_policy contains "cashback"
  - `premium`: annual_fee >= 2000 OR has international lounge access
  - `student`: reward_points_policy/additional_features contains "student" OR annual_fee <= 500
  - `business`: reward_points_policy/additional_features contains "business"
  - `no-annual-fee`: annual_fee = 0

Invalid category slugs are ignored. If no valid slugs provided, returns empty results.

## Faceted Navigation

Facets are returned when requested via the `facets` parameter. Available facets:

| Facet | Type | Description |
|-------|------|-------------|
| `bank` | terms | Top banks by result count |
| `category` | category | Canonical categories with counts and filter strings |
| `annual_fee_range` | range | Predefined annual fee buckets |
| `interest_rate_range` | range | Predefined APR buckets |
| `lounge_access` | boolean | International, domestic, any lounge access |
| `fee_waiver` | boolean | Has fee waiver policy |
| `has_annual_fee` | boolean | Has annual fee (computed) |

Each facet bucket includes a `filter` string that can be passed directly to the list endpoint.

## Caching

Responses are cached for 2 minutes (`ADVANCED_SEARCH_TTL`). Cache keys include:
- Normalized query parameters (sorted for consistency)
- Request origin and path (for absolute URL consistency)
- Cache version (incremented on card/bank changes)

Cache invalidation happens automatically when:
- A `CreditCard` is created, updated, or deleted
- A `Bank` is created, updated, or deleted

The advanced search cache uses its own version key: `credit_cards:advanced_search:version`.

## Elasticsearch Fallback

When Elasticsearch is unavailable (disabled, connection failure, or query error), the endpoint gracefully falls back to database search using Django ORM. The `source` field in the response indicates which backend was used.

Database fallback supports the same query parameters but:
- No relevance scoring (defaults to bank/name ordering)
- Facets computed via Django aggregations
- `took` is always 0

## Query Normalization

The `normalize` endpoint and `normalize_query_params` utility canonicalize queries for saved search deduplication:

- Scalar parameters: trimmed and included as-is
- Boolean parameters: only included when explicitly `true`
- Multi-value parameters (categories, ids, bank_ids): split, deduplicated, sorted, re-joined
- Parameters sorted alphabetically for consistent canonical string

## Usage Examples

### Find Travel Cards with Lounge Access

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/?search=travel&has_lounge_access=true&facets=bank,category,lounge_access"
```

### Premium Cards (High Annual Fee) with Fee Waiver

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/?annual_fee_min=400&has_fee_waiver=true&ordering=-annual_fee&facets=bank,annual_fee_range"
```

### Student Cards with No Annual Fee

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/?categories=student,no-annual-fee&ordering=annual_fee&facets=category,has_annual_fee"
```

### Multi-Bank Comparison with Facets

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/?bank_ids=1,2,3&facets=bank,category,annual_fee_range&page_size=50"
```

### Feature Search within Cards

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/advanced-search/?feature_search=travel+insurance&facets=category"
```

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Invalid value for annual_fee_min. Must be a valid number."
}
```

### 503 Service Unavailable

Returned only if both Elasticsearch and database are unavailable (extremely rare).

## Performance Notes

- Elasticsearch queries typically complete in 10-50ms
- Database fallback typically completes in 50-200ms
- First request after cache invalidation may be slower
- Facets add minimal overhead when requested
- Page size capped at 100 for performance

## Rate Limiting

Subject to standard API rate limits:
- Anonymous: 100/min (configurable via `THROTTLE_RATE_ANON`)
- Authenticated: 1000/min (configurable via `THROTTLE_RATE_USER`)
- Burst: 10/sec (configurable via `THROTTLE_RATE_BURST`)

## Related Endpoints

- **Standard list**: `GET /api/v1/credit-cards/` - simpler filtering, no faceting
- **Typeahead**: `GET /api/v1/credit-cards/typeahead/` - autocomplete for search boxes
- **Search suggestions**: `GET /api/v1/credit-cards/search-suggestions/` - UI filter hints
- **Field history**: `GET /api/v1/credit-cards/{id}/field-history/` - modification history
