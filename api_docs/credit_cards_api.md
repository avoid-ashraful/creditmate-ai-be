# Credit Cards API Documentation

## Overview

The Credit Cards API provides comprehensive endpoints for browsing, searching, and filtering credit card products. This API is designed for read-only operations and offers advanced filtering capabilities to help users find credit cards that match their specific requirements.

## Base URL

All endpoints are prefixed with: `/api/v1/credit-cards/`

## Authentication

No authentication is required for these endpoints. All credit card data is publicly accessible.

## Endpoints

### 1. List Credit Cards

**GET** `/api/v1/credit-cards/`

Retrieve a paginated list of all active credit cards with comprehensive filtering and search capabilities.

#### Query Parameters

##### Basic Filters
- `bank` (integer): Filter by bank ID
- `name` (string): Filter by credit card name (case-insensitive contains)
- `bank_name` (string): Filter by bank name (case-insensitive contains)
- `is_active` (boolean): Filter by active status (default: true)

##### IDs Filters
- `ids` (string): Comma-separated list of credit card IDs to filter by
  - Example: `ids=1,2,3,4`
  - Use this to retrieve specific credit cards for comparison or display
- `bank_ids` (string): Comma-separated list of bank IDs to filter by
  - Example: `bank_ids=1,3,5`
  - Use this to retrieve credit cards from specific banks only

##### Annual Fee Filters
- `annual_fee_min` (decimal): Minimum annual fee
- `annual_fee_max` (decimal): Maximum annual fee
- `annual_fee_range` (string): Range filter in format "min,max"
- `has_annual_fee` (boolean): Filter cards with/without annual fee
- `no_annual_fee` (boolean): Filter cards with no annual fee

##### Interest Rate Filters
- `interest_rate_min` (decimal): Minimum interest rate (APR)
- `interest_rate_max` (decimal): Maximum interest rate (APR)
- `interest_rate_range` (string): Range filter in format "min,max"

##### Lounge Access Filters
- `has_lounge_access` (boolean): Filter cards with any lounge access
- `has_international_lounge` (boolean): Filter cards with international lounge access
- `has_domestic_lounge` (boolean): Filter cards with domestic lounge access
- `min_international_lounge` (integer): Minimum international lounge access count
- `min_domestic_lounge` (integer): Minimum domestic lounge access count

##### Feature Filters
- `has_additional_features` (boolean): Filter cards with additional features
- `feature_search` (string): Search within additional features text
- `has_fee_waiver` (boolean): Filter cards with fee waiver policy

##### Search
- `search` (string): Search across multiple fields:
  - Credit card name
  - Bank name
  - Reward points policy
  - Cash advance fee
  - Late payment fee

##### Ordering
- `ordering` (string): Order results by field. Prefix with `-` for descending order.
  - Available fields: `name`, `annual_fee`, `interest_rate_apr`, `lounge_access_international`, `lounge_access_domestic`, `created_at`, `updated_at`
  - Default: `bank__name,name`

##### Pagination
- `page` (integer): Page number (default: 1)
- `page_size` (integer): Number of results per page (default: 20, max: 100)

#### Example Requests

```http
# Get all credit cards
GET /api/v1/credit-cards/

# Filter cards with no annual fee
GET /api/v1/credit-cards/?no_annual_fee=true

# Filter cards with international lounge access and annual fee under 2000
GET /api/v1/credit-cards/?has_international_lounge=true&annual_fee_max=2000

# Search for Visa cards
GET /api/v1/credit-cards/?search=visa

# Get specific cards by IDs
GET /api/v1/credit-cards/?ids=1,5,10,15

# Filter cards from specific banks
GET /api/v1/credit-cards/?bank_ids=1,3,5

# Filter by annual fee range and order by fee
GET /api/v1/credit-cards/?annual_fee_min=1000&annual_fee_max=5000&ordering=annual_fee
```

#### Response Format

```json
{
  "count": 125,
  "next": "http://example.com/api/v1/credit-cards/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "bank_name": "Chase Bank",
      "name": "Chase Sapphire Preferred",
      "annual_fee": "95.00",
      "interest_rate_apr": "15.99",
      "lounge_access_international": 10,
      "lounge_access_domestic": 15,
      "has_lounge_access": true,
      "has_annual_fee": true,
      "is_active": true
    }
  ]
}
```

### 2. Retrieve Credit Card Details

**GET** `/api/v1/credit-cards/{id}/`

Retrieve detailed information about a specific credit card.

#### Path Parameters
- `id` (integer): Credit card ID

#### Response Format

```json
{
  "id": 1,
  "bank": {
    "id": 1,
    "name": "Chase Bank",
    "website": "https://chase.com"
  },
  "name": "Chase Sapphire Preferred",
  "annual_fee": "95.00",
  "interest_rate_apr": "15.99",
  "lounge_access_international": 10,
  "lounge_access_domestic": 15,
  "cash_advance_fee": "Either $10 or 5% of the amount",
  "late_payment_fee": "Up to $40",
  "annual_fee_waiver_policy": {
    "conditions": ["First year waived"],
    "requirements": ["New customers only"]
  },
  "reward_points_policy": "2x points on travel and dining, 1x on everything else",
  "additional_features": [
    "Travel insurance",
    "Purchase protection",
    "Extended warranty"
  ],
  "is_active": true,
  "has_lounge_access": true,
  "total_lounge_access": 25,
  "has_annual_fee": true,
  "created": "2024-01-15T10:30:00Z",
  "modified": "2024-01-20T14:45:00Z"
}
```

### 3. Search Suggestions

**GET** `/api/v1/credit-cards/search_suggestions/`

Get search suggestions and filter options to help users discover relevant filters.

#### Response Format

```json
{
  "annual_fee_ranges": [
    {
      "label": "Free",
      "filter": "annual_fee=0"
    },
    {
      "label": "Low (1-1000)",
      "filter": "annual_fee_min=1&annual_fee_max=1000"
    },
    {
      "label": "Medium (1001-3000)",
      "filter": "annual_fee_min=1001&annual_fee_max=3000"
    },
    {
      "label": "Premium (3000+)",
      "filter": "annual_fee_min=3000"
    }
  ],
  "benefits": [
    {
      "label": "International Lounge Access",
      "filter": "has_international_lounge=true"
    },
    {
      "label": "Domestic Lounge Access",
      "filter": "has_domestic_lounge=true"
    },
    {
      "label": "No Annual Fee",
      "filter": "no_annual_fee=true"
    },
    {
      "label": "Fee Waiver Available",
      "filter": "has_fee_waiver=true"
    }
  ],
  "popular_banks": [
    "Chase Bank",
    "American Express",
    "Capital One",
    "Citibank"
  ]
}
```

## Response Fields

### List Response Fields (CreditCardListSerializer)
- `id`: Unique identifier
- `bank_name`: Name of the issuing bank
- `name`: Credit card name
- `annual_fee`: Annual fee amount (decimal)
- `interest_rate_apr`: Annual percentage rate (decimal)
- `lounge_access_international`: Number of international lounge access
- `lounge_access_domestic`: Number of domestic lounge access
- `has_lounge_access`: Boolean indicating any lounge access
- `has_annual_fee`: Boolean indicating if annual fee exists
- `is_active`: Boolean indicating if card is active

### Detail Response Fields (CreditCardSerializer)
- All fields from list response, plus:
- `bank`: Full bank object with id, name, and website
- `cash_advance_fee`: Cash advance fee description
- `late_payment_fee`: Late payment fee description
- `annual_fee_waiver_policy`: JSON object with waiver conditions
- `reward_points_policy`: Reward points description
- `additional_features`: Array of additional features
- `total_lounge_access`: Sum of international and domestic lounge access
- `created`: Creation timestamp
- `modified`: Last modification timestamp

## Error Responses

### 400 Bad Request
Invalid query parameters or malformed request.

```json
{
  "detail": "Invalid filter parameters provided"
}
```

### 404 Not Found
Credit card with specified ID does not exist.

```json
{
  "detail": "Not found."
}
```

### 500 Internal Server Error
Server error occurred while processing the request.

```json
{
  "detail": "A server error occurred."
}
```

## Usage Examples

### Frontend Implementation for Credit Card Comparison

To implement credit card comparison in your frontend:

1. **Get specific cards by IDs:**
```javascript
// Get cards with IDs 1, 5, and 10 for comparison
const response = await fetch('/api/v1/credit-cards/?ids=1,5,10');
const data = await response.json();
const cardsForComparison = data.results;
```

2. **Filter and display results:**
```javascript
// Filter cards with no annual fee
const response = await fetch('/api/v1/credit-cards/?no_annual_fee=true');
const freeCards = await response.json();

// Filter premium cards with lounge access
const premiumResponse = await fetch('/api/v1/credit-cards/?has_international_lounge=true&annual_fee_min=5000');
const premiumCards = await premiumResponse.json();

// Filter cards from specific banks
const bankResponse = await fetch('/api/v1/credit-cards/?bank_ids=1,3,5');
const bankCards = await bankResponse.json();
```

3. **Search functionality:**
```javascript
// Search for cards by name or bank
const searchResponse = await fetch(`/api/v1/credit-cards/?search=${encodeURIComponent(searchTerm)}`);
const searchResults = await searchResponse.json();
```

## Rate Limiting

Currently, no rate limiting is implemented, but it's recommended to implement reasonable request throttling in production environments.

## Data Updates

Credit card data is updated through automated crawling processes. The API reflects the most current data available in the system. Check the `modified` field on individual cards to see when data was last updated.

## Support

For API support or feature requests, please refer to the project documentation or contact the development team.
