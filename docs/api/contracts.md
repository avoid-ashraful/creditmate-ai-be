# Backend API contracts

Task 5.4 backend contract tests live in
`credit_cards/tests/test_api_contracts.py`. They use Django REST Framework's
`APIClient` and existing factories, without Pact or Schemathesis.

## Contract command

```bash
pytest credit_cards/tests/test_api_contracts.py
```

The tests locally verify the real response schema for:

- `GET /api/v1/credit-cards/`: paginated `count`, `next`, `previous`, and
  `results` keys; exact list-card and nested bank keys and value types; and
  no-fee versus zero-fee boolean semantics.
- `GET /api/v1/credit-cards/{id}/`: exact detail-card keys and nested bank
  shape. Detail omits the list-only denormalized `bank_id` and `bank_name`
  fields; the current response does not expose an aggregate lounge count.
- `GET /api/v1/credit-cards/?page_size=2`: page size and cursor metadata while
  preserving total count. `next` and `previous` point to different pages, so
  they are semantically distinct URLs rather than equal values.
- `GET /api/v1/credit-cards/search-suggestions/`: exact envelope, suggestion
  object keys, and popular bank value type.
- Invalid numeric filter and unknown detail requests: status and error shape.
  Unknown detail responses include the stable `detail` message; DRF attaches
  the `not_found` code to its in-process `ErrorDetail` value.

No backend throttle configuration is currently declared. Throttling is
therefore intentionally not asserted; a configured, stable contract can be
added later.

Frontend consumer adapter verification remains a separate concern. These
backend checks intentionally do not import or execute frontend adapter code.
