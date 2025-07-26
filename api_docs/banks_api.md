# Banks API Documentation

## Overview

The Banks API provides endpoints for browsing and searching bank information. This API is designed for read-only operations and offers filtering capabilities to help users discover banks and their basic information.

## Base URL

All endpoints are prefixed with: `/api/v1/banks/`

## Authentication

No authentication is required for these endpoints. All bank data is publicly accessible.

## Endpoints

### 1. List Banks

**GET** `/api/v1/banks/`

Retrieve a paginated list of all active banks with filtering and search capabilities.

#### Query Parameters

##### Basic Filters
- `name` (string): Filter by bank name (case-insensitive contains)
- `is_active` (boolean): Filter by active status (default: true)
- `has_credit_cards` (boolean): Filter banks that have/don't have credit cards

##### Date Filters
- `created_gte` (datetime): Filter banks created after or on this date
- `created_lte` (datetime): Filter banks created before or on this date
- `modified_gte` (datetime): Filter banks modified after or on this date
- `modified_lte` (datetime): Filter banks modified before or on this date

##### Search
- `search` (string): Search in bank names

##### Ordering
- `ordering` (string): Order results by field. Prefix with `-` for descending order.
  - Available fields: `name`, `created_at`, `updated_at`
  - Default: `name`

##### Pagination
- `page` (integer): Page number (default: 1)
- `page_size` (integer): Number of results per page (default: 20, max: 100)

#### Example Requests

```http
# Get all banks
GET /api/v1/banks/

# Search for banks by name
GET /api/v1/banks/?search=chase

# Filter banks that have credit cards
GET /api/v1/banks/?has_credit_cards=true

# Filter banks with case-insensitive name search
GET /api/v1/banks/?name=american

# Order banks by name (descending)
GET /api/v1/banks/?ordering=-name

# Filter banks created after a specific date
GET /api/v1/banks/?created_gte=2024-01-01

# Combine filters
GET /api/v1/banks/?has_credit_cards=true&ordering=name
```

#### Response Format

```json
{
  "count": 25,
  "next": "http://example.com/api/v1/banks/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Chase Bank",
      "logo": "https://example.com/logos/chase.png",
      "credit_card_count": 15,
      "is_active": true
    }
  ]
}
```

### 2. Retrieve Bank Details

**GET** `/api/v1/banks/{id}/`

Retrieve detailed information about a specific bank.

#### Path Parameters
- `id` (integer): Bank ID

#### Response Format

```json
{
  "id": 1,
  "name": "Chase Bank",
  "logo": "https://example.com/logos/chase.png",
  "website": "https://chase.com",
  "is_active": true,
  "credit_card_count": 15,
  "created": "2024-01-15T10:30:00Z",
  "modified": "2024-01-20T14:45:00Z"
}
```

## Response Fields

### List Response Fields (BankListSerializer)
- `id`: Unique identifier
- `name`: Bank name
- `logo`: URL to bank logo image
- `credit_card_count`: Number of active credit cards offered by this bank
- `is_active`: Boolean indicating if bank is active

### Detail Response Fields (BankSerializer)
- All fields from list response, plus:
- `website`: Bank's official website URL
- `created`: Creation timestamp
- `modified`: Last modification timestamp

## Filter Behavior

### has_credit_cards Filter
- `has_credit_cards=true`: Returns banks that have at least one credit card
- `has_credit_cards=false`: Returns banks that have no credit cards
- When omitted: Returns all banks regardless of credit card count

### Search Functionality
The search parameter performs case-insensitive substring matching on bank names.

## Error Responses

### 400 Bad Request
Invalid query parameters or malformed request.

```json
{
  "detail": "Invalid filter parameters provided"
}
```

### 404 Not Found
Bank with specified ID does not exist.

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

### Frontend Implementation

1. **Display bank list with credit card counts:**
```javascript
// Get all banks with their credit card counts
const response = await fetch('/api/v1/banks/');
const data = await response.json();
const banks = data.results;

// Display banks with credit card availability
banks.forEach(bank => {
  console.log(`${bank.name}: ${bank.credit_card_count} credit cards`);
});
```

2. **Filter banks that offer credit cards:**
```javascript
// Get only banks that offer credit cards
const response = await fetch('/api/v1/banks/?has_credit_cards=true');
const banksWithCards = await response.json();
```

3. **Search for specific banks:**
```javascript
// Search for banks by name
const searchTerm = 'chase';
const response = await fetch(`/api/v1/banks/?search=${encodeURIComponent(searchTerm)}`);
const searchResults = await response.json();
```

4. **Get bank details:**
```javascript
// Get detailed information about a specific bank
const bankId = 1;
const response = await fetch(`/api/v1/banks/${bankId}/`);
const bankDetails = await response.json();
```

### Integration with Credit Cards API

To get credit cards for specific banks, use the Credit Cards API with the `bank_ids` filter:

```javascript
// Get credit cards from specific banks
const bankIds = [1, 3, 5];
const response = await fetch(`/api/v1/credit-cards/?bank_ids=${bankIds.join(',')}`);
const creditCards = await response.json();
```

## Data Relationships

- Each bank can have multiple credit cards
- The `credit_card_count` field shows the number of active credit cards
- Bank logos and websites are optional fields
- Only active banks are returned by default

## Rate Limiting

Currently, no rate limiting is implemented, but it's recommended to implement reasonable request throttling in production environments.

## Data Updates

Bank data is updated through administrative interfaces and automated processes. The API reflects the most current data available in the system. Check the `modified` field on individual banks to see when data was last updated.

## Support

For API support or feature requests, please refer to the project documentation or contact the development team.
