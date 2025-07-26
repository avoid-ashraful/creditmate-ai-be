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
      "website": "https://chase.com",
      "established": 1799,
      "credit_cards_count": 15,
      "created": "2024-01-15T10:30:00Z",
      "updated": "2024-01-20T14:45:00Z"
    },
    {
      "id": 2,
      "name": "Bank of America",
      "website": "https://bankofamerica.com",
      "established": 1904,
      "credit_cards_count": 12,
      "created": "2024-01-15T10:35:00Z",
      "updated": "2024-01-19T16:20:00Z"
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
  "website": "https://chase.com",
  "established": 1799,
  "credit_cards_count": 15,
  "created": "2024-01-15T10:30:00Z",
  "updated": "2024-01-20T14:45:00Z"
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

# Sort by credit card count (highest first)
curl -X GET "http://localhost:8000/api/v1/banks/?ordering=-credit_cards_count"
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique identifier for the bank |
| `name` | string | Official name of the bank |
| `website` | string (URL) | Bank's official website |
| `established` | integer | Year the bank was established |
| `credit_cards_count` | integer | Number of credit cards offered by this bank |
| `created` | datetime | When this bank record was created in our system |
| `updated` | datetime | When this bank record was last updated |

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

### Get Major Banks

```bash
# Get banks established before 1900 (historical banks)
curl -X GET "http://localhost:8000/api/v1/banks/?established__lt=1900&ordering=established"
```

### Search for Specific Bank

```bash
# Case-insensitive search
curl -X GET "http://localhost:8000/api/v1/banks/?search=american+express"
```

### Banks with Most Credit Cards

```bash
# Get banks with the most credit card offerings
curl -X GET "http://localhost:8000/api/v1/banks/?ordering=-credit_cards_count"
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

For more comprehensive API usage examples, see [Common API Examples](../common/api_examples.md).
