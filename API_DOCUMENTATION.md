# CreditMate AI - API Documentation

## Overview

The CreditMate AI API provides comprehensive endpoints for accessing and comparing credit card information from major Bangladeshi banks. The API is built using Django REST Framework and follows RESTful principles.

## Base URL

```
http://localhost:8000/api/v1/
```

## Authentication

Currently, the API is read-only and does not require authentication. All endpoints are publicly accessible.

## Response Format

All API responses follow a consistent JSON format:

```json
{
  "count": 123,
  "next": "http://localhost:8000/api/v1/endpoint/?page=2",
  "previous": null,
  "results": [...]
}
```

## Error Handling

Error responses include appropriate HTTP status codes and descriptive error messages:

```json
{
  "error": "Descriptive error message",
  "details": "Additional error details if applicable"
}
```

## Rate Limiting

Currently, no rate limiting is implemented. This may be added in future versions.

---

## Banks API

### List Banks

Get a list of all active banks.

**Endpoint:** `GET /api/v1/banks/`

**Query Parameters:**
- `search` (string): Search banks by name
- `name` (string): Filter by bank name (case-insensitive contains)
- `has_credit_cards` (boolean): Filter banks that have/don't have credit cards
- `is_active` (boolean): Filter by active status
- `ordering` (string): Order by fields (`name`, `created_at`, `updated_at`)

**Example Request:**
```bash
GET /api/v1/banks/?search=islami&ordering=name
```

**Example Response:**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Islami Bank Bangladesh Limited",
      "logo": "https://example.com/logo.png",
      "credit_card_count": 5,
      "is_active": true
    }
  ]
}
```

### Get Bank Details

Get detailed information about a specific bank.

**Endpoint:** `GET /api/v1/banks/{id}/`

**Example Response:**
```json
{
  "id": 1,
  "name": "Islami Bank Bangladesh Limited",
  "logo": "https://example.com/logo.png",
  "website": "https://islamibankbd.com",
  "is_active": true,
  "credit_card_count": 5,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Get Bank's Credit Cards

Get all credit cards issued by a specific bank.

**Endpoint:** `GET /api/v1/banks/{id}/credit_cards/`

**Example Response:**
```json
{
  "bank": {
    "id": 1,
    "name": "Islami Bank Bangladesh Limited",
    "logo": "https://example.com/logo.png",
    "website": "https://islamibankbd.com",
    "is_active": true,
    "credit_card_count": 2,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  },
  "credit_cards": [
    {
      "id": 1,
      "bank_name": "Islami Bank Bangladesh Limited",
      "name": "Islami Platinum Card",
      "annual_fee": "2500.00",
      "interest_rate_apr": "28.50",
      "lounge_access_international": 8,
      "lounge_access_domestic": 12,
      "has_lounge_access": true,
      "has_annual_fee": true,
      "is_active": true
    }
  ]
}
```

---

## Credit Cards API

### List Credit Cards

Get a list of all active credit cards with comprehensive filtering options.

**Endpoint:** `GET /api/v1/credit-cards/`

**Query Parameters:**

**Basic Filters:**
- `search` (string): Search by card name, bank name, or policy text
- `name` (string): Filter by card name (case-insensitive contains)
- `bank_name` (string): Filter by bank name (case-insensitive contains)
- `bank` (integer): Filter by bank ID

**Price Range Filters:**
- `annual_fee_min` (decimal): Minimum annual fee
- `annual_fee_max` (decimal): Maximum annual fee
- `annual_fee_range` (string): Fee range (e.g., "1000,5000")

**Interest Rate Filters:**
- `interest_rate_min` (decimal): Minimum interest rate
- `interest_rate_max` (decimal): Maximum interest rate
- `interest_rate_range` (string): Rate range (e.g., "20.0,30.0")

**Lounge Access Filters:**
- `has_lounge_access` (boolean): Cards with any lounge access
- `has_international_lounge` (boolean): Cards with international lounge access
- `has_domestic_lounge` (boolean): Cards with domestic lounge access
- `min_international_lounge` (integer): Minimum international lounge count
- `min_domestic_lounge` (integer): Minimum domestic lounge count

**Fee Filters:**
- `has_annual_fee` (boolean): Cards with annual fee
- `no_annual_fee` (boolean): Cards without annual fee
- `has_fee_waiver` (boolean): Cards with fee waiver policy

**Feature Filters:**
- `has_additional_features` (boolean): Cards with additional features
- `feature_search` (string): Search in additional features

**Ordering:**
- `ordering` (string): Order by fields (`name`, `annual_fee`, `interest_rate_apr`, `lounge_access_international`, `lounge_access_domestic`, `created_at`, `updated_at`)

**Example Request:**
```bash
GET /api/v1/credit-cards/?has_lounge_access=true&annual_fee_max=3000&ordering=annual_fee
```

**Example Response:**
```json
{
  "count": 15,
  "next": "http://localhost:8000/api/v1/credit-cards/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "bank_name": "Islami Bank Bangladesh Limited",
      "name": "Islami Platinum Card",
      "annual_fee": "2500.00",
      "interest_rate_apr": "28.50",
      "lounge_access_international": 8,
      "lounge_access_domestic": 12,
      "has_lounge_access": true,
      "has_annual_fee": true,
      "is_active": true
    }
  ]
}
```

### Get Credit Card Details

Get detailed information about a specific credit card.

**Endpoint:** `GET /api/v1/credit-cards/{id}/`

**Example Response:**
```json
{
  "id": 1,
  "bank": {
    "id": 1,
    "name": "Islami Bank Bangladesh Limited",
    "logo": "https://example.com/logo.png",
    "credit_card_count": 5,
    "is_active": true
  },
  "name": "Islami Platinum Card",
  "annual_fee": "2500.00",
  "interest_rate_apr": "28.50",
  "lounge_access_international": 8,
  "lounge_access_domestic": 12,
  "cash_advance_fee": "3% of transaction amount, minimum BDT 500",
  "late_payment_fee": "BDT 600 or 5% of minimum payment due, whichever is higher",
  "annual_fee_waiver_policy": {
    "minimum_spend": 150000,
    "waiver_period": "first_year",
    "conditions": ["Spend BDT 150,000 in first year", "Maintain minimum balance"]
  },
  "reward_points_policy": "Earn 1 point for every BDT 100 spent on general purchases, 2 points for every BDT 100 spent on dining and fuel.",
  "additional_features": [
    "travel_insurance",
    "purchase_protection",
    "extended_warranty"
  ],
  "source_url": "https://islamibankbd.com/cards/platinum",
  "is_active": true,
  "has_lounge_access": true,
  "total_lounge_access": 20,
  "has_annual_fee": true,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Compare Credit Cards

Compare up to 4 credit cards side by side.

**Endpoint:** `GET /api/v1/credit-cards/compare/`

**Query Parameters:**
- `ids` (string): Comma-separated list of credit card IDs (max 4)

**Example Request:**
```bash
GET /api/v1/credit-cards/compare/?ids=1,2,3,4
```

**Example Response:**
```json
{
  "comparison_count": 4,
  "cards": [
    {
      "id": 1,
      "bank_name": "Islami Bank Bangladesh Limited",
      "bank_logo": "https://example.com/logo.png",
      "name": "Islami Platinum Card",
      "annual_fee": "2500.00",
      "interest_rate_apr": "28.50",
      "lounge_access_international": 8,
      "lounge_access_domestic": 12,
      "cash_advance_fee": "3% of transaction amount, minimum BDT 500",
      "late_payment_fee": "BDT 600 or 5% of minimum payment due",
      "annual_fee_waiver_policy": {
        "minimum_spend": 150000,
        "waiver_period": "first_year"
      },
      "reward_points_policy": "Earn 1 point for every BDT 100 spent",
      "additional_features": ["travel_insurance", "purchase_protection"],
      "has_lounge_access": true,
      "total_lounge_access": 20,
      "has_annual_fee": true
    }
  ]
}
```

### Get Featured Credit Cards

Get featured credit cards with good value propositions.

**Endpoint:** `GET /api/v1/credit-cards/featured/`

**Example Response:**
```json
{
  "message": "Featured credit cards with good value propositions",
  "cards": [
    {
      "id": 1,
      "bank_name": "Islami Bank Bangladesh Limited",
      "name": "Islami Gold Card",
      "annual_fee": "1500.00",
      "interest_rate_apr": "26.50",
      "lounge_access_international": 4,
      "lounge_access_domestic": 6,
      "has_lounge_access": true,
      "has_annual_fee": true,
      "is_active": true
    }
  ]
}
```

### Get No Annual Fee Credit Cards

Get credit cards with no annual fee.

**Endpoint:** `GET /api/v1/credit-cards/no_annual_fee/`

**Example Response:**
```json
{
  "message": "Credit cards with no annual fee",
  "count": 3,
  "cards": [
    {
      "id": 5,
      "bank_name": "Dutch-Bangla Bank",
      "name": "DBBL Classic Card",
      "annual_fee": "0.00",
      "interest_rate_apr": "32.00",
      "lounge_access_international": 0,
      "lounge_access_domestic": 2,
      "has_lounge_access": true,
      "has_annual_fee": false,
      "is_active": true
    }
  ]
}
```

### Get Premium Credit Cards

Get premium credit cards with exclusive benefits.

**Endpoint:** `GET /api/v1/credit-cards/premium/`

**Example Response:**
```json
{
  "message": "Premium credit cards with exclusive benefits",
  "count": 2,
  "cards": [
    {
      "id": 10,
      "bank_name": "Standard Chartered Bank",
      "name": "Priority Platinum Credit Card",
      "annual_fee": "8000.00",
      "interest_rate_apr": "25.00",
      "lounge_access_international": 15,
      "lounge_access_domestic": 20,
      "has_lounge_access": true,
      "has_annual_fee": true,
      "is_active": true
    }
  ]
}
```

### Get Search Suggestions

Get search suggestions and popular filter options.

**Endpoint:** `GET /api/v1/credit-cards/search_suggestions/`

**Example Response:**
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
    "Islami Bank Bangladesh Limited",
    "Dutch-Bangla Bank",
    "Standard Chartered Bank",
    "BRAC Bank",
    "City Bank"
  ]
}
```

---

## Data Models

### Bank Model

```json
{
  "id": 1,
  "name": "Bank Name",
  "logo": "https://example.com/logo.png",
  "website": "https://example.com",
  "is_active": true,
  "credit_card_count": 5,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Credit Card Model

```json
{
  "id": 1,
  "bank": {
    "id": 1,
    "name": "Bank Name",
    "logo": "https://example.com/logo.png",
    "credit_card_count": 5,
    "is_active": true
  },
  "name": "Card Name",
  "annual_fee": "2500.00",
  "interest_rate_apr": "28.50",
  "lounge_access_international": 8,
  "lounge_access_domestic": 12,
  "cash_advance_fee": "Fee description",
  "late_payment_fee": "Fee description",
  "annual_fee_waiver_policy": {
    "minimum_spend": 150000,
    "waiver_period": "first_year",
    "conditions": ["condition1", "condition2"]
  },
  "reward_points_policy": "Reward policy description",
  "additional_features": ["feature1", "feature2"],
  "source_url": "https://example.com/card-details",
  "is_active": true,
  "has_lounge_access": true,
  "total_lounge_access": 20,
  "has_annual_fee": true,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

---

## Example Usage Scenarios

### 1. Find Cards with No Annual Fee

```bash
GET /api/v1/credit-cards/?no_annual_fee=true&ordering=interest_rate_apr
```

### 2. Find Premium Cards with International Lounge Access

```bash
GET /api/v1/credit-cards/?has_international_lounge=true&annual_fee_min=5000&ordering=-lounge_access_international
```

### 3. Compare Specific Cards

```bash
GET /api/v1/credit-cards/compare/?ids=1,5,10,15
```

### 4. Search for Travel-Friendly Cards

```bash
GET /api/v1/credit-cards/?feature_search=travel&has_international_lounge=true
```

### 5. Find Budget-Friendly Cards

```bash
GET /api/v1/credit-cards/?annual_fee_max=1000&interest_rate_max=30&ordering=annual_fee
```

---

## Status Codes

- `200 OK`: Successful request
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: Resource not found
- `405 Method Not Allowed`: HTTP method not allowed
- `500 Internal Server Error`: Server error

---

## Changelog

### Version 1.0.0 (Initial Release)
- Banks API with filtering and search
- Credit Cards API with comprehensive filtering
- Comparison functionality
- Featured, premium, and no-fee card endpoints
- Search suggestions endpoint

---

## Support

For API support or questions, please contact the development team or create an issue in the project repository.
