# Data Quality Dashboard

A read-only, staff-only JSON snapshot of crawl-and-extraction quality, served
by the Django backend at `GET /admin/data-quality/`.

## Access

The endpoint uses Django's own admin gate:

| Caller                | Result                                              |
|-----------------------|-----------------------------------------------------|
| Anonymous             | `302` redirect to `/admin/login/?next=/admin/data-quality/` |
| Logged in, not staff  | `302` redirect to the admin login (the admin's own behavior) |
| Logged in, staff      | `200` with the JSON snapshot                        |

Signed-in staff can call it with cookies; e.g. from the admin session:

```bash
curl -b cookies.txt http://localhost:8000/admin/data-quality/
```

Only `GET`/`HEAD` are allowed (anything else returns `405`).

## Snapshot shape

```json
{
  "generated_at": "2026-10-13T08:00:00+00:00",
  "totals": { "...": "see below" },
  "banks": [ { "...": "per-bank block" } ],
  "methods": { "text": {...}, "ocr": {...}, "unknown": {...} },
  "alerts": [ { "scope": "bank", "kind": "low_confidence", "value": 0.42, "...": "..." } ]
}
```

## Metric definitions

Metrics are computed from the existing models
(`CrawledContent`, `BankDataSource`, `CreditCard`) - no new columns or
migrations are required.

- **Per-bank (`banks[]`)**: status counts (`total_contents`, `completed`,
  `failed`, `pending`, `processing`), `success_rate`, 7/30-day confidence
  averages (`average_confidence_7d` / `average_confidence_30d` with
  `scored_7d` / `scored_30d` sample sizes), missing-field counts
  (`content_missing_annual_fee`, `content_missing_apr` - completed rows whose
  `missing_critical_fields` names the field), and null-numeric card counts
  (`cards_null_annual_fee`, `cards_null_apr` - `CreditCard` rows joined to the
  bank whose `annual_fee` / `interest_rate_apr` column is NULL).
- **Success rate**: `completed / (completed + failed)`. Only terminal states
  count; `pending`/`processing` rows are reported but excluded from the rate.
- **Confidence windows**: mean of non-null `extraction_confidence` over
  content crawled in the last 7 / 30 days.
- **Methods**: `text` bundles `pdf_text`, `webpage`, `csv`; `ocr` bundles
  `ocr`, `image_ocr`; everything else (including the blank default) lands in
  `unknown`. Each bucket reports `completion_rate` (`completed / total`) and
  `success_rate`.

### No data is never "0%"

Any rate without a denominator is `null`, not `0`, so the dashboard can
always distinguish "there is no data yet" from "everything failed":

- `success_rate` is `null` when nothing has completed or failed;
- confidence averages are `null` when no scored content exists in the window;
- method rates are `null` for empty buckets.

## Alerts

| Kind                 | Condition                                |
|----------------------|------------------------------------------|
| `low_confidence`     | most recent confidence average (7d, falling back to 30d) `< 0.5` |
| `low_success_rate`   | `success_rate` `< 0.7` (70%)             |

Alerts are emitted at `overall` scope and, when a specific bank is affected,
at `bank` scope with `bank_id`/`bank_name`. Missing denominators never
trigger an alert.

## Implementation

- `banks/services/quality_dashboard.py` - pure query helpers over the ORM
  (`build_dashboard()`, `bank_summary()`, `totals_summary()`,
  `method_comparison()`, `build_alerts()`).
- `banks/views.py` - the `staff_member_required` JSON view.
- `credit_mate_ai/urls.py` - route registration at `/admin/data-quality/`
  (listed before the `admin/` include so the admin URLconf cannot shadow it).
- `banks/tests/test_quality_dashboard.py` - metric and access-control tests.

## Local development / testing note

Verification used a pre-existing sibling venv that already contained the
project dependencies:

```
/home/ubuntu/credit-workers/opencode-stream-6/creditmate-ai-be/.venv/bin/python -m pytest banks/tests/test_quality_dashboard.py
```

The interpreter named in the task
(`/home/ubuntu/credit-workers/integration/creditmate-ai-be/.venv/bin/python`)
was checked first but its venv is empty - it contains no Django, pytest or
project packages (`import django` /
`import pytest` both raise `ModuleNotFoundError`), so it cannot run the test
suite without installing dependencies, which was out of scope. The limitation
is therefore recorded here rather than hidden; the metric logic is pure ORM
aggregation and is covered by the tests above.