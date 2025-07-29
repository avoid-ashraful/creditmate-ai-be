# Banks API Documentation

## Overview

The Banks API provides access to bank information and serves as the foundation for credit card discovery. Each bank can have multiple credit cards and data sources for automated content crawling.

## Base URL

```
/api/v1/banks/
```

## Endpoints

### List Banks

**Endpoint:** `GET /api/v1/banks/`

**Description:** Retrieve a paginated list of all banks in the system.

**Query Parameters:**
- `search` (string): Search banks by name
- `page` (integer): Page number for pagination
- `page_size` (integer): Number of results per page (default: 20)
- `ordering` (string): Sort results by field name (prefix with `-` for descending)
  - Available fields: `name`, `created_at`, `updated_at`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/banks/"
```

**Example Response:**
```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Chase",
      "logo": "https://example.com/chase-logo.png",
      "credit_card_count": 15,
      "is_active": true
    },
    {
      "id": 2,
      "name": "Bank of America",
      "logo": "https://example.com/boa-logo.png",
      "credit_card_count": 12,
      "is_active": true
    }
  ]
}
```

### Get Bank Details

**Endpoint:** `GET /api/v1/banks/{id}/`

**Description:** Retrieve detailed information about a specific bank.

**Path Parameters:**
- `id` (integer): The unique identifier of the bank

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/banks/1/"
```

**Example Response:**
```json
{
  "id": 1,
  "name": "Chase",
  "logo": "https://example.com/chase-logo.png",
  "website": "https://chase.com",
  "is_active": true,
  "credit_card_count": 15,
  "created": "2024-01-15T10:30:00Z",
  "modified": "2024-01-20T14:45:00Z"
}
```

## Search and Filtering

### Search by Name

```bash
curl -X GET "http://localhost:8000/api/v1/banks/?search=chase"
```

### Ordering Results

```bash
# Sort by name (A-Z)
curl -X GET "http://localhost:8000/api/v1/banks/?ordering=name"

# Sort by establishment date (newest first)
curl -X GET "http://localhost:8000/api/v1/banks/?ordering=-established"

# Sort by creation date (newest first)
curl -X GET "http://localhost:8000/api/v1/banks/?ordering=-created_at"
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique identifier for the bank |
| `name` | string | Official name of the bank |
| `logo` | string (URL) | Bank's logo URL |
| `website` | string (URL) | Bank's official website |
| `is_active` | boolean | Whether the bank is currently active |
| `credit_card_count` | integer | Number of active credit cards offered by this bank |
| `created` | datetime | When this bank record was created in our system |
| `modified` | datetime | When this bank record was last updated |

## Error Responses

### 404 Not Found

```json
{
  "detail": "Not found."
}
```

### 400 Bad Request

```json
{
  "detail": "Invalid ordering field."
}
```

## Related Endpoints

### Get Credit Cards for a Bank

To get all credit cards offered by a specific bank, use the Credit Cards API with bank filtering:

```bash
curl -X GET "http://localhost:8000/api/v1/credit-cards/?bank=1"
# or
curl -X GET "http://localhost:8000/api/v1/credit-cards/?bank__name=Chase"
```

## Usage Examples

### Get Active Banks Only

```bash
# Get only active banks
curl -X GET "http://localhost:8000/api/v1/banks/?is_active=true"
```

### Search for Specific Bank

```bash
# Case-insensitive search
curl -X GET "http://localhost:8000/api/v1/banks/?search=american+express"
```

### Recently Added Banks

```bash
# Get recently added banks (newest first)
curl -X GET "http://localhost:8000/api/v1/banks/?ordering=-created_at"
```

## Integration Notes

1. **Bank IDs are stable** - Once assigned, bank IDs do not change
2. **Credit card count is live** - The `credit_cards_count` field reflects the current number of active credit cards
3. **Search is optimized** - Bank name search uses database indexes for fast results
4. **Pagination is recommended** - Always use pagination for production applications

## Admin Features

Banks can be managed through the Django admin interface at `/admin/banks/bank/` with the following capabilities:

- Add new banks with validation
- Edit bank information
- View associated data sources
- Monitor credit card counts
- Bulk operations for multiple banks

## Data Sources Integration

Each bank can have multiple data sources (URLs) for automated credit card data crawling. This is managed through the `BankDataSource` model and is not directly exposed through the public API.

For more comprehensive API usage examples, see [API Examples](./examples.md).
