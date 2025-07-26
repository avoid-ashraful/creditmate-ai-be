# API Usage Examples

This document provides comprehensive examples for using the Credit Mate AI REST API.

## Base URL

```
http://localhost:8000/api/v1/
```

## Authentication

Currently, the API is public and does not require authentication (MVP phase).

## Common Response Format

All API responses follow a consistent JSON format:

```json
{
  "count": 150,
  "next": "http://localhost:8000/api/v1/credit-cards/?page=2",
  "previous": null,
  "results": [...]
}
```

## Banks API Examples

### Get All Banks

```bash
curl -X GET "http://localhost:8000/api/v1/banks/"
```

**Response:**
```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Chase",
      "website": "https://chase.com",
      "established": 1799,
      "credit_cards_count": 15
    }
  ]
}
```

### Get Bank Details

```bash
curl -X GET "http://localhost:8000/api/v1/banks/1/"
```

### Filter Banks by Name

```bash
curl -X GET "http://localhost:8000/api/v1/banks/?search=chase"
```

## Credit Cards API Examples

### Get All Credit Cards

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/"
```

### Get Credit Card Details

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/1/"
```

**Response:**
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
  "has_foreign_transaction_fee": false,
  "has_balance_transfer": true,
  "has_lounge_access": false
}
```

### Filter by Multiple Credit Card IDs

```bash
# Get specific credit cards for comparison
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ids=1,2,3,4"
```

### Filter by Multiple Bank IDs

```bash
# Get credit cards from specific banks
curl -X GET "http://localhost:8000/api/v1/credit-cards/?bank_ids=1,3,5"
```

### Advanced Filtering Examples

#### No Annual Fee Cards
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee=0"
```

#### Cards with Lounge Access
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?has_lounge_access=true"
```

#### Cards by Bank Name
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?bank__name=Chase"
```

#### Annual Fee Range
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee__lte=200"
```

#### Credit Score Requirement
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?credit_score_required=Excellent"
```

### Search Examples

#### Search by Card Features
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel+rewards"
```

#### Search by Bank and Features
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=chase+cashback"
```

### Complex Query Examples

#### Travel Cards with No Foreign Transaction Fees
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel&has_foreign_transaction_fee=false"
```

#### Premium Cards (High Annual Fee) with Lounge Access
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee__gte=400&has_lounge_access=true"
```

#### Cards for Good Credit with Low Interest Rate
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?credit_score_required=Good&interest_rate__lte=18.0"
```

### Ordering Examples

#### Sort by Annual Fee (Low to High)
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=annual_fee"
```

#### Sort by Interest Rate (High to Low)
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=-interest_rate"
```

#### Multiple Sort Criteria
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ordering=annual_fee,-interest_rate"
```

### Pagination Examples

#### Custom Page Size
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?page_size=50"
```

#### Navigate Pages
```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?page=2&page_size=20"
```

### Search Suggestions

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/search-suggestions/?q=cash"
```

**Response:**
```json
{
  "suggestions": [
    "cashback",
    "cash rewards",
    "cash back bonus"
  ]
}
```

## Combined Query Examples

### Find the Best Travel Cards

```bash
# Travel cards with no foreign transaction fees, sorted by annual fee
curl -X GET "http://localhost:8000/api/v1/credit-cards/?search=travel&has_foreign_transaction_fee=false&ordering=annual_fee"
```

### Compare Specific Cards

```bash
# Get details for specific cards (for comparison features)
curl -X GET "http://localhost:8000/api/v1/credit-cards/?ids=1,5,10,15"
```

### Cards for Beginners

```bash
# No annual fee cards with good credit score requirement
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee=0&credit_score_required__in=Fair,Good"
```

### Premium Rewards Cards

```bash
# High-end cards with significant welcome bonuses
curl -X GET "http://localhost:8000/api/v1/credit-cards/?annual_fee__gte=200&search=welcome+bonus&ordering=-annual_fee"
```

## Error Handling

### Common Error Responses

#### 400 Bad Request
```json
{
  "detail": "Invalid filter value"
}
```

#### 404 Not Found
```json
{
  "detail": "Not found."
}
```

#### 500 Internal Server Error
```json
{
  "detail": "A server error occurred."
}
```

## Rate Limiting

Currently, there are no rate limits implemented (MVP phase), but consider implementing proper rate limiting in production.

## Data Freshness

Credit card data is automatically updated weekly through our AI-powered web crawling system. The last update timestamp is available through the API.

## Best Practices

1. **Use Specific Filters**: Instead of loading all data, use filters to get exactly what you need
2. **Implement Pagination**: For large datasets, always implement proper pagination
3. **Cache Responses**: Consider caching frequently accessed data
4. **Handle Errors Gracefully**: Always implement proper error handling
5. **Use Search Suggestions**: Leverage the search suggestions endpoint for better UX

## Integration Examples

### JavaScript/React Example

```javascript
// Fetch credit cards with specific criteria
const fetchCreditCards = async (filters = {}) => {
  const params = new URLSearchParams(filters);
  const response = await fetch(`/api/v1/credit-cards/?${params}`);
  return response.json();
};

// Usage
const travelCards = await fetchCreditCards({
  search: 'travel',
  has_foreign_transaction_fee: false,
  ordering: 'annual_fee'
});
```

### Python Example

```python
import requests

# Fetch credit cards
def get_credit_cards(base_url, **filters):
    response = requests.get(f"{base_url}/api/v1/credit-cards/", params=filters)
    return response.json()

# Usage
cards = get_credit_cards(
    "http://localhost:8000",
    search="cashback",
    annual_fee__lte=100,
    ordering="annual_fee"
)
```

### cURL Script Example

```bash
#!/bin/bash

BASE_URL="http://localhost:8000/api/v1"

# Function to get credit cards with filters
get_cards() {
    local query="$1"
    curl -s "${BASE_URL}/credit-cards/?${query}" | jq '.'
}

# Get no annual fee cards
get_cards "annual_fee=0&ordering=interest_rate"

# Get travel cards
get_cards "search=travel&has_foreign_transaction_fee=false"
```

## Support

For additional API support or questions:
- Check the individual app documentation: [Banks API](../banks/api_docs.md) | [Credit Cards API](../credit_cards/api_docs.md)
- Review the main project documentation
- Open an issue on GitHub
