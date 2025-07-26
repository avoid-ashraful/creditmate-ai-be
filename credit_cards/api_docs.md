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
- `bank__name` (string): Filter by bank name (case-insensitive)
- `annual_fee` (decimal): Exact annual fee match
- `annual_fee__lte` (decimal): Annual fee less than or equal to
- `annual_fee__gte` (decimal): Annual fee greater than or equal to
- `annual_fee__range` (string): Annual fee range (e.g., `0,200`)
- `interest_rate__lte` (decimal): Interest rate less than or equal to
- `interest_rate__gte` (decimal): Interest rate greater than or equal to
- `credit_score_required` (string): Exact credit score requirement match
- `credit_score_required__in` (string): Multiple credit score requirements (e.g., `Good,Excellent`)
- `has_foreign_transaction_fee` (boolean): Filter by foreign transaction fee presence
- `has_balance_transfer` (boolean): Filter by balance transfer availability
- `has_lounge_access` (boolean): Filter by airport lounge access

#### Search and Ordering
- `search` (string): Full-text search across card names, descriptions, and features
- `ordering` (string): Sort results by field name (prefix with `-` for descending)
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
      "name": "Chase Sapphire Preferred",
      "bank": {
        "id": 1,
        "name": "Chase"
      },
      "annual_fee": 95.00,
      "interest_rate": 21.49,
      "credit_score_required": "Good",
      "rewards_program": "Ultimate Rewards",
      "welcome_bonus": "60,000 points after spending $4,000",
      "has_foreign_transaction_fee": false,
      "has_balance_transfer": true,
      "has_lounge_access": false,
      "created": "2024-01-15T10:30:00Z",
      "updated": "2024-01-20T14:45:00Z"
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
  "name": "Chase Sapphire Preferred",
  "bank": {
    "id": 1,
    "name": "Chase"
  },
  "annual_fee": 95.00,
  "interest_rate": 21.49,
  "credit_score_required": "Good",
  "rewards_program": "Ultimate Rewards",
  "welcome_bonus": "60,000 points after spending $4,000",
  "cash_back_rate": 1.25,
  "travel_insurance": true,
  "extended_warranty": true,
  "purchase_protection": true,
  "has_foreign_transaction_fee": false,
  "has_balance_transfer": true,
  "has_lounge_access": false,
  "balance_transfer_fee": 3.0,
  "cash_advance_fee": 5.0,
  "late_payment_fee": 40.00,
  "created": "2024-01-15T10:30:00Z",
  "updated": "2024-01-20T14:45:00Z"
}
```

### Search Suggestions

**Endpoint:** `GET /api/v1/credit-cards/search-suggestions/`

**Description:** Get search suggestions based on a query prefix for autocomplete functionality.

**Query Parameters:**
- `q` (string): Query prefix for suggestions

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/search-suggestions/?q=cash"
```

**Example Response:**
```json
{
  "suggestions": [
    "cashback",
    "cash rewards",
    "cash back bonus",
    "cash advance"
  ]
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
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee=0"
```

### Travel Cards with Benefits

```bash
# Travel cards with no foreign transaction fees and lounge access
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel&has_foreign_transaction_fee=false&has_lounge_access=true"
```

### Annual Fee Range

```bash
# Cards with annual fee between $0 and $200
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee__gte=0&annual_fee__lte=200"
```

### Credit Score Requirements

```bash
# Cards for good or excellent credit
curl -X GET "http://localhost:8000/api/v1/credit-cards/?credit_score_required__in=Good,Excellent"
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
| `bank` | object | Bank information (id, name) |
| `annual_fee` | decimal | Annual fee amount |
| `interest_rate` | decimal | Annual percentage rate (APR) |
| `credit_score_required` | string | Required credit score level |
| `rewards_program` | string | Name of rewards program |
| `welcome_bonus` | string | Welcome bonus description |
| `cash_back_rate` | decimal | Cash back percentage |
| `travel_insurance` | boolean | Travel insurance coverage |
| `extended_warranty` | boolean | Extended warranty protection |
| `purchase_protection` | boolean | Purchase protection coverage |
| `has_foreign_transaction_fee` | boolean | Foreign transaction fee presence |
| `has_balance_transfer` | boolean | Balance transfer availability |
| `has_lounge_access` | boolean | Airport lounge access |
| `balance_transfer_fee` | decimal | Balance transfer fee percentage |
| `cash_advance_fee` | decimal | Cash advance fee percentage |
| `late_payment_fee` | decimal | Late payment fee amount |
| `created` | datetime | Record creation timestamp |
| `updated` | datetime | Last update timestamp |

## Credit Score Requirements

Available values for `credit_score_required`:
- `Poor` (300-579)
- `Fair` (580-669)
- `Good` (670-739)
- `Very Good` (740-799)
- `Excellent` (800+)

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

For comprehensive API usage examples across all endpoints, see [Common API Examples](../common/api_examples.md).
