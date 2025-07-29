# Credit Cards API Documentation

## Overview

The Credit Cards API is the core component of the Credit Mate AI platform, providing comprehensive access to credit card information with advanced filtering, search, and comparison capabilities.

## Base URL

```
/api/v1/credit-cards/
```

## Endpoints

### List Credit Cards

**Endpoint:** `GET /api/v1/credit-cards/`

**Description:** Retrieve a paginated list of credit cards with comprehensive filtering options.

**Query Parameters:**

#### Filtering Parameters
- `ids` (string): Comma-separated list of credit card IDs (e.g., `1,2,3,4`)
- `bank_ids` (string): Comma-separated list of bank IDs (e.g., `1,3,5`)
- `bank` (integer): Filter by specific bank ID
- `name` (string): Filter by card name (case-insensitive)
- `bank_name` (string): Filter by bank name (case-insensitive)
- `annual_fee_min` (decimal): Annual fee greater than or equal to
- `annual_fee_max` (decimal): Annual fee less than or equal to
- `annual_fee_range` (string): Annual fee range (e.g., `0,200`)
- `interest_rate_min` (decimal): Interest rate greater than or equal to
- `interest_rate_max` (decimal): Interest rate less than or equal to
- `interest_rate_range` (string): Interest rate range
- `has_lounge_access` (boolean): Filter by any lounge access
- `has_international_lounge` (boolean): Filter by international lounge access
- `has_domestic_lounge` (boolean): Filter by domestic lounge access
- `min_international_lounge` (integer): Minimum international lounge access count
- `min_domestic_lounge` (integer): Minimum domestic lounge access count
- `has_annual_fee` (boolean): Filter by annual fee presence
- `no_annual_fee` (boolean): Filter by no annual fee
- `has_additional_features` (boolean): Filter by additional features presence
- `feature_search` (string): Search in additional features
- `has_fee_waiver` (boolean): Filter by fee waiver policy presence
- `is_active` (boolean): Filter by active status

#### Search and Ordering
- `search` (string): Full-text search across card names, descriptions, and features
- `ordering` (string): Sort results by field name (prefix with `-` for descending)
  - Available fields: `name`, `annual_fee`, `interest_rate_apr`, `lounge_access_international`, `lounge_access_domestic`, `created_at`, `updated_at`
- `page` (integer): Page number for pagination
- `page_size` (integer): Number of results per page (default: 20, max: 100)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/"
```

**Example Response:**
```json
{
  "count": 150,
  "next": "http://localhost:8000/api/v1/credit-cards/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "bank_name": "Chase",
      "name": "Sapphire Preferred",
      "annual_fee": 95.00,
      "interest_rate_apr": 21.49,
      "lounge_access_international": 0,
      "lounge_access_domestic": 0,
      "has_lounge_access": false,
      "has_annual_fee": true,
      "is_active": true
    }
  ]
}
```

### Get Credit Card Details

**Endpoint:** `GET /api/v1/credit-cards/{id}/`

**Description:** Retrieve detailed information about a specific credit card.

**Path Parameters:**
- `id` (integer): The unique identifier of the credit card

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/1/"
```

**Example Response:**
```json
{
  "id": 1,
  "bank": {
    "id": 1,
    "name": "Chase",
    "logo": "https://example.com/chase-logo.png",
    "credit_card_count": 15,
    "is_active": true
  },
  "bank_id": 1,
  "name": "Sapphire Preferred",
  "annual_fee": 95.00,
  "interest_rate_apr": 21.49,
  "lounge_access_international": 0,
  "lounge_access_domestic": 0,
  "cash_advance_fee": "5% of advance amount",
  "late_payment_fee": "Up to $40",
  "annual_fee_waiver_policy": null,
  "reward_points_policy": "2x points on travel and dining, 1x on all other purchases",
  "additional_features": ["Travel insurance", "Purchase protection"],
  "is_active": true,
  "has_lounge_access": false,
  "total_lounge_access": 0,
  "has_annual_fee": true,
  "created": "2024-01-15T10:30:00Z",
  "modified": "2024-01-20T14:45:00Z"
}
```

### Search Suggestions

**Endpoint:** `GET /api/v1/credit-cards/search-suggestions/`

**Description:** Get search suggestions and filter options for building user interfaces.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/search-suggestions/"
```

**Example Response:**
```json
{
  "annual_fee_ranges": [
    {"label": "Free", "filter": "annual_fee=0"},
    {"label": "Low (1-1000)", "filter": "annual_fee_min=1&annual_fee_max=1000"},
    {"label": "Medium (1001-3000)", "filter": "annual_fee_min=1001&annual_fee_max=3000"},
    {"label": "Premium (3000+)", "filter": "annual_fee_min=3000"}
  ],
  "benefits": [
    {"label": "International Lounge Access", "filter": "has_international_lounge=true"},
    {"label": "Domestic Lounge Access", "filter": "has_domestic_lounge=true"},
    {"label": "No Annual Fee", "filter": "no_annual_fee=true"},
    {"label": "Fee Waiver Available", "filter": "has_fee_waiver=true"}
  ],
  "popular_banks": ["Chase", "Bank of America", "Citi", "American Express"]
}
```

## Advanced Filtering Examples

### Filter by Multiple IDs (Comparison Feature)

```bash
# Get specific credit cards for comparison
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ids=1,2,3,4"
```

### Filter by Multiple Bank IDs

```bash
# Get credit cards from Chase, Bank of America, and Citi
curl -X GET "http://localhost:8000/api/v1/credit-cards/?bank_ids=1,2,3"
```

### No Annual Fee Cards

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?no_annual_fee=true"
```

### Travel Cards with Benefits

```bash
# Travel cards with lounge access
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel&has_lounge_access=true"
```

### Annual Fee Range

```bash
# Cards with annual fee between $0 and $200
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee_min=0&annual_fee_max=200"
```

### Feature Search

```bash
# Cards with specific features
curl -X GET "http://localhost:8000/api/v1/credit-cards/?feature_search=travel+insurance"
```

## Search Examples

### Basic Search

```bash
# Search for cashback cards
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=cashback"
```

### Multi-term Search

```bash
# Search for travel rewards with no annual fee
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel+rewards&annual_fee=0"
```

### Bank-specific Search

```bash
# Search for Chase travel cards
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel&bank__name=Chase"
```

## Ordering Examples

### Sort by Annual Fee

```bash
# Low to high annual fee
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=annual_fee"

# High to low annual fee
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=-annual_fee"
```

### Sort by Interest Rate

```bash
# Lowest interest rate first
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=interest_rate"
```

### Multiple Sort Criteria

```bash
# Sort by annual fee, then by interest rate (descending)
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=annual_fee,-interest_rate"
```

## Pagination Examples

### Custom Page Size

```bash
# Get 50 results per page
curl -X GET "http://localhost:8000/api/v1/credit-cards/?page_size=50"
```

### Navigate Pages

```bash
# Get page 2 with 20 results per page
curl -X GET "http://localhost:8000/api/v1/credit-cards/?page=2&page_size=20"
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique identifier |
| `name` | string | Credit card name |
| `bank` | object | Bank information (id, name, logo, credit_card_count, is_active) |
| `bank_id` | integer | Bank ID (write-only) |
| `annual_fee` | decimal | Annual fee amount |
| `interest_rate_apr` | decimal | Annual percentage rate (APR) |
| `lounge_access_international` | integer | Number of international lounge access |
| `lounge_access_domestic` | integer | Number of domestic lounge access |
| `cash_advance_fee` | string | Cash advance fee description |
| `late_payment_fee` | string | Late payment fee description |
| `annual_fee_waiver_policy` | object | Annual fee waiver policy details |
| `reward_points_policy` | string | Reward points policy description |
| `additional_features` | array | List of additional features |
| `is_active` | boolean | Whether the card is active |
| `has_lounge_access` | boolean | Whether card has any lounge access (computed) |
| `total_lounge_access` | integer | Total lounge access count (computed) |
| `has_annual_fee` | boolean | Whether card has annual fee (computed) |
| `created` | datetime | Record creation timestamp |
| `modified` | datetime | Last update timestamp |

## Filter Examples by Feature

### Annual Fee Filters
```bash
# No annual fee cards
curl -X GET "http://localhost:8000/api/v1/credit-cards/?no_annual_fee=true"

# Cards with annual fee
curl -X GET "http://localhost:8000/api/v1/credit-cards/?has_annual_fee=true"

# Annual fee range
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee_min=100&annual_fee_max=500"
```

### Lounge Access Filters
```bash
# Cards with any lounge access
curl -X GET "http://localhost:8000/api/v1/credit-cards/?has_lounge_access=true"

# Cards with international lounge access
curl -X GET "http://localhost:8000/api/v1/credit-cards/?has_international_lounge=true"

# Cards with domestic lounge access
curl -X GET "http://localhost:8000/api/v1/credit-cards/?has_domestic_lounge=true"

# Minimum lounge access counts
curl -X GET "http://localhost:8000/api/v1/credit-cards/?min_international_lounge=5"
```

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Invalid filter value for annual_fee. Must be a valid decimal."
}
```

### 404 Not Found

```json
{
  "detail": "Not found."
}
```

### 422 Validation Error

```json
{
  "ids": ["Invalid format. Use comma-separated integers (e.g., 1,2,3)"]
}
```

## Complex Query Examples

### Best Travel Cards for Good Credit

```bash
# Travel cards with no foreign fees, for good credit, sorted by annual fee
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel&has_foreign_transaction_fee=false&credit_score_required=Good&ordering=annual_fee"
```

### Premium Cards Comparison

```bash
# High-end cards with lounge access and high annual fees
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee__gte=400&has_lounge_access=true&ordering=-annual_fee"
```

### No Annual Fee Cashback Cards

```bash
# Cashback cards with no annual fee, sorted by cash back rate
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=cashback&annual_fee=0&ordering=-cash_back_rate"
```

### Bank Comparison

```bash
# Compare Chase and Bank of America cards
curl -X GET "http://localhost:8000/api/v1/credit-cards/?bank_ids=1,2&ordering=bank__name,annual_fee"
```

## Rate Limiting

Currently, no rate limiting is implemented (MVP phase). In production, consider:
- 1000 requests per hour per IP
- 100 requests per minute per IP
- Higher limits for authenticated users

## Data Freshness

Credit card data is automatically updated weekly through our AI-powered crawling system. Check the `updated` field for the last modification timestamp.

## Integration Best Practices

1. **Use Specific Filters**: Always filter results to minimize data transfer
2. **Implement Pagination**: Handle large result sets properly
3. **Cache Frequently Accessed Data**: Reduce API calls for common queries
4. **Handle Errors Gracefully**: Implement proper error handling and retry logic
5. **Use Search Suggestions**: Enhance user experience with autocomplete
6. **Monitor Rate Limits**: Implement proper rate limiting in production

## Migration from Removed Endpoints

The following endpoints have been removed in favor of filtering:

### Old: `/api/v1/credit-cards/compare/`
**New:** Use `ids` filter
```bash
# Old way (removed)
POST /api/v1/credit-cards/compare/ {"ids": [1, 2, 3]}

# New way
GET /api/v1/credit-cards/?ids=1,2,3
```

### Old: `/api/v1/credit-cards/featured/`
**New:** Use appropriate filters
```bash
# Get high-quality cards (example criteria)
GET /api/v1/credit-cards/?annual_fee__lte=200&credit_score_required__in=Good,Excellent
```

### Old: `/api/v1/credit-cards/no-annual-fee/`
**New:** Use annual fee filter
```bash
GET /api/v1/credit-cards/?annual_fee=0
```

### Old: `/api/v1/credit-cards/premium/`
**New:** Use annual fee and feature filters
```bash
# Premium cards with high annual fees and exclusive features
GET /api/v1/credit-cards/?annual_fee__gte=400&has_lounge_access=true
```

For comprehensive API usage examples across all endpoints, see [API Examples](./examples.md).
