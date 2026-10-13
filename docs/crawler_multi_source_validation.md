# Crawler Multi-Source Validation

Implementation of Task 2.4 from `TASK_BREAKDOWN.md`. This document describes the
contracts, the data model and the tests behind the deterministic multi-source
validation service: comparing *observations* - one value for one credit-card
field read from one concrete source (the bank's website, a bank PDF / Schedule
of Charges, a CSV, a scanned image, or a user submission) - that relate to the
**same card and field**, and deciding whether they agree, whether they
conflict, and what the field's confidence becomes.

The service is **deterministic**: the same observations in any order produce
exactly the same result, and every outcome is explainable from the rules below.

## 1. What is an observation?

An `Observation` (`banks/services/multi_source_validation.py`) is one
value-for-field read from one concrete source:

| Attribute | Meaning |
| --- | --- |
| `field` | Credit-card field name (`annual_fee`, `interest_rate_apr`, `late_payment_fee`, ...). |
| `value` | Raw value exactly as read from the source. |
| `source_type` | Broad origin class (`banks/enums.py` `SourceType`): `bank_website`, `bank_pdf`, `bank_image`, `bank_csv`, `user_submission`. |
| `source_key` | **Stable identity of the concrete source** (e.g. the data source URL, or a submission id). Independence is decided on this key. |
| `card_key` | Normalized identity of the credit card (bank + card name) the observation belongs to. Observations without one are never grouped. |
| `bank_key` | Normalized bank identity, used with `card_key` for strict grouping. |
| `confidence` | Reliability estimate for this observation (default per `source_type`, see §4). |
| `unit` | Optional explicit unit metadata (`"bdt"`, `"usd"`, `"percent_per_year"`, ...). |

## 2. Grouping: never merge unrelated cards

Observations are grouped on **`(bank_key, card_key)`** only.

- An observation with a missing `card_key` is **ignored** (counted in
  `ignored_observations`), never merged into a generic bucket.
- Two cards of the same bank are validated separately even if they share field
  names ("Gold" vs "Platinum").
- Cards at different banks are never merged, even with identical names.

## 3. What counts as evidence

| Status | Meaning | Examples |
| --- | --- | --- |
| `valid` | A normalized, in-range value was obtained | `0`, `95`, `5000`, `"TK 5,000"`, `"20% p.a."` (APR) |
| `missing` | Explicit "no value" marker | `None`, `""`, `"N/A"`, `"unknown"`, `"-"` |
| `invalid` | The value exists but cannot be trusted | `"abc"`, `True`, `NaN`, `inf`, `-50`, `"USD 100"`, `"100 per month"`, `"Waived"` |

Rules:

- **Missing and invalid values are never evidence.** They neither agree nor
  conflict against a valid value, and they are never normalized to `0`.
- **A genuine `0` is a real value.** `0`/`0.0` mean "the source states zero"
  and remain `0`; zero-equivalent wording such as `"Free"` normalizes to `0.0`
  for `annual_fee` only.
- **Units/normalization are explicit.** Critical numeric fields reuse
  `banks/validators/numeric_fields.py` (BDT fee amounts, annual APR rates,
  explicit rejection reasons). An observation that *declares* a unit that does
  not match the field's expected unit (`annual_fee` → `bdt`,
  `interest_rate_apr` → `percent_per_year`) is excluded with reason
  `unit_mismatch`; it is never compared as equal.
- **Free-text fields are not compared across sources.** Only
  `VALIDATED_FIELDS` (the critical numeric fields plus selected structured
  fees/limits) participate; reward-policy prose and similar text cannot be
  compared safely.

## 4. Independence and confidence

- **Independence is decided per concrete `source_key`.** Two crawled records
  from the same data source URL are the *same* source: they never count twice
  and never produce a boost. A webpage (`webpage`) maps to `bank_website`, a
  PDF source to `bank_pdf`, etc.
- **Duplicates of one source collapse to one representative** (the highest
  confidence observation of that source).
- **A single source reporting two different valid values is an
  inconsistency.** Its evidence is excluded from the comparison and the field
  is flagged for manual review (`inconsistent_sources`), because the source
  is internally unreliable.
- **Default per-source confidences** (used when an observation carries none):

  | Source type | Default confidence |
  | --- | --- |
  | `bank_website`, `bank_pdf`, `bank_csv` | `0.6` |
  | `bank_image` | `0.5` |
  | `user_submission` | `0.4` |

### Per-field outcome

| Situation | `status` | `validated_confidence` | Manual review |
| --- | --- | --- | --- |
| No usable evidence | `no_data` | `None` | No |
| One independent source with a value | `single_source` | that source's confidence | No |
| ≥2 independent sources, same normalized value | `agreement` | noisy-OR of all agreeing source confidences | No |
| ≥2 independent sources, different values | `conflict` | `None` | **Yes** |
| One source internally inconsistent | `no_data` (+ `inconsistent_sources`) | `None` | **Yes** |

Agreement combines confidences with the **noisy-OR** rule
`confidence = 1 - product(1 - c_i)`, which is monotone in the number of
independent agreeing sources, bounded in `0.0 - 1.0`, and never lower than the
best single source. `confidence_boost` is the difference to the best source.
On a conflict **no value is accepted** - a majority does not silently win - and
the offending values (with their source provenance) are listed in `conflicts`
for the review queue.

## 5. Collectors and crawler wiring

`banks/services/validation_collectors.py` bridges the pure service to Django:

- `content_type_to_source_type` - maps a data source content type to a
  `SourceType`.
- `observations_from_crawled_content` - reads cards from one
  `CrawledContent.parsed_json`, using the data source URL as `source_key` and
  the record's `extraction_confidence` as the observation confidence.
- `latest_observations_for_bank` - the most recent **completed** crawl record
  per **active** data source of a bank, in a stable (URL-ordered) way, so the
  same URL crawled ten times is still one source.
- `observations_from_user_submissions` - accepts external submission payloads
  (dicts or attribute objects) without requiring a submission model; each
  payload's `source_key` defaults to a per-submission counter so distinct
  submissions are independent.
- `validate_crawled_content` / `run_multi_source_validation` - combine the
  record's own observations, the bank's latest observations for other sources,
  and optional user submissions; validate; persist the JSON-safe summary on
  the crawl record; raise `needs_manual_review` on real conflicts or
  inconsistencies.

The crawler (`banks/services/bank_data_crawler.py`, `_validate_multi_source`)
runs validation **after a successful database update** and is **best effort**:
a failure is logged and never breaks the crawl, and the review flag is never
cleared by a later run. A summary is persisted only when a real cross-source
comparison exists (`has_comparison`): a first single-source crawl keeps the
default empty summary until a second independent source arrives.

## 6. Data model (migration `banks/migrations/0012_...`)

`CrawledContent.multi_source_validation` - `JSONField(default=dict)` storing
the JSON-safe `batch_summary`:

```json
{
  "needs_manual_review": true,
  "conflict_field_count": 1,
  "ignored_observations": 0,
  "cards": [
    {
      "card_key": "gold",
      "bank_key": "acme bank",
      "needs_manual_review": true,
      "conflict_fields": ["annual_fee"],
      "fields": {
        "annual_fee": {
          "field": "annual_fee",
          "status": "conflict",
          "agreed_value": null,
          "base_confidence": 0.6,
          "validated_confidence": null,
          "confidence_boost": 0.0,
          "independent_source_count": 2,
          "source_types": {"bank_pdf": 1, "bank_website": 1},
          "needs_manual_review": true,
          "inconsistent_sources": [],
          "conflicts": [
            {"value": 5000.0, "sources": [{"source_key": "https://.../fees.pdf", "source_type": "bank_pdf", "confidence": 0.6}]},
            {"value": 6000.0, "sources": [{"source_key": "https://.../fees", "source_type": "bank_website", "confidence": 0.6}]}
          ],
          "reasons": ["independent_conflict"],
          "observations": []
        }
      }
    }
  ]
}
```

`apply_multi_source_validation(summary)` stores the summary and raises
`needs_manual_review = True` when the summary reports a conflict or
inconsistency; it never clears an existing flag.

## 7. Determinism and serialization

- Field/group iteration is sorted (`field`, `bank_key`, `card_key`,
  `source_key`), ties break on `source_key`, and JSON-safe conversion coerces
  `Decimal`/non-primitive values via `_json_safe`.
- `batch_summary` / `field_validation_to_dict` / `card_validation_to_dict`
  produce plain JSON-safe dictionaries with full provenance (source key, type,
  raw + normalized value, status, reason, confidence per observation).

## 8. Running and verifying offline

```bash
# New unit + integration tests (offline: no LLM keys, sockets disabled)
DATABASE_URL=postgresql:///creditmate_task24 CACHE_BACKEND=locmem DEBUG=True \
  .venv/bin/python -m pytest \
  banks/tests/test_multi_source_validation.py \
  banks/tests/test_multi_source_validation_integration.py -q -p no:cacheprovider

# Full banks suite
DATABASE_URL=postgresql:///creditmate_task24 CACHE_BACKEND=locmem DEBUG=True \
  .venv/bin/python -m pytest banks/ -q -p no:cacheprovider

# Migrations and system checks
DATABASE_URL=postgresql:///creditmate_task24 CACHE_BACKEND=locmem DEBUG=True \
  .venv/bin/python manage.py check
DATABASE_URL=postgresql:///creditmate_task24 CACHE_BACKEND=locmem DEBUG=True \
  .venv/bin/python manage.py makemigrations banks --check --dry-run
```

Test modules: `test_multi_source_validation.py` (pure service: agreement with
boost, conflicts, duplicate/same-source independence, missing fields,
zero-versus-missing, normalization, card separation, determinism,
serialization) and `test_multi_source_validation_integration.py` (collectors,
persistence, and crawler end-to-end agreement/conflict/review-flag scenarios).

## 9. Status / coordination notes

- **Implemented and tested offline.** No live crawling, no external
  submissions and no deployment is implied by these changes.
- **Depends on Task 2.3 integration** (the review queue): the service already
  raises `needs_manual_review` and persists
  `multi_source_validation` (status, agreed/conflicting values, source
  provenance per conflict) for the queue to surface, but the human
  review surface (side-by-side approve/reject/edit), email/Slack
  notifications for flagged conflicts, and live user-submission ingestion
  (there is no submission model yet; the service accepts payloads via
  `observations_from_user_submissions`) must wait for the Task 2.3 queue and
  account/submission infrastructure.
- **Migration numbering caveat:** Task 2.3 is expected to add its own
  `banks/0012_...` migration; when both land, `makemigrations --merge` may be
  required to resolve the shared leaf number.