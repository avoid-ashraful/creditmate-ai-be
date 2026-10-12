# Crawler Extraction Quality Scoring

Implementation of `docs/improvements.md` Phases 1-3 for Task 2.1. This document
describes the contracts, the data model and the tests behind extraction quality
scoring. Every score produced by the system is a float in the inclusive range
**0.0 - 1.0**, and every score can be explained from the rules below.

## 1. Critical field statuses: valid / missing / invalid

`banks/validators/numeric_fields.py` is the single source of truth for how the
two critical numeric fields (`annual_fee`, `interest_rate_apr`) are interpreted.
It never imports services (no cycles); everything upstream depends on it.

| Status | Meaning | Examples |
| --- | --- | --- |
| `valid` | A normalized, in-range number was obtained | `0`, `95`, `"TK 5,000"`, `"$95.00"`, `"20% p.a."`, `"Free"` (fee only) |
| `missing` | The document gave an explicit "no value" marker | `None`, `""`, `"N/A"`, `"unknown"`, `"-"`, `"not mentioned"` |
| `invalid` | A value exists but cannot be trusted | `"abc"`, `"12abc"`, `True`/`False`, `NaN`, `inf`, `-50`, `150` (APR), `[1,2]`, `{...}` |

Rules:

- **A genuine `0` is always `valid`.** `0`/`0.0` mean "the document states the
  value is zero" - they are never converted to `NULL`.
- **Zero-equivalent wording is normalized to `0.0` for `annual_fee` only**
  (`"Free"`, `"Nil"`, `"Waived"`, `"No annual fee"`). The APR has no such
  wording: `"Free"` as an APR is `invalid`, not `0`.
- **Bad values stay unknown.** `invalid` values are normalized to `None` before
  scoring and storage - they are *never* turned into `0`. `NULL` therefore means
  "we do not know", while `0` means "genuinely zero".
- **Bounds** (`FIELD_BOUNDS`): `annual_fee ∈ [0, 100000]`,
  `interest_rate_apr ∈ [0, 100]`. Out-of-range values are `invalid`.

Helpers: `parse_numeric_value`, `critical_field_status`, `is_valid_critical_value`,
`normalize_critical_fields`, `normalize_cards`.

## 2. Confidence scoring (`banks/services/quality_scoring.py`)

```
extraction_confidence = content_score × cards_completeness × coverage_factor   (clamped to 0.0-1.0)
```

- **`content_score`** = `length_factor × keyword_factor × structure_factor ×
  method_factor` - how trustworthy the extracted *text* is (Phase 3). OCR is
  discounted (`method_factor("ocr") = 0.85`) relative to native PDF text (`1.0`).
- **`cards_completeness`** = average over cards of the fraction of critical
  fields whose status is **`valid`**. Missing *and* invalid fields count as not
  extracted; genuine zeros count as extracted.
- **`coverage_factor`** = `0.0` with no cards, `0.9` with exactly one card,
  `1.0` with two or more.

Issue codes are machine-readable and distinguish causes:

| Code | Meaning |
| --- | --- |
| `missing_<field>` | Field had an explicit "no value" marker |
| `invalid_<field>` | Field held a malformed value (reported instead of `missing_<field>`) |
| `no_extracted_content` | No text was extracted |
| `no_cards_extracted` | No credit cards were found |
| `validation_error: ...` | Rejected by the real validation stage |

**Manual review** (`needs_manual_review`) is `True` when
`confidence < 0.5` **or** the issue list has more than 1 entry
(`MANUAL_REVIEW_CONFIDENCE_THRESHOLD`, `MANUAL_REVIEW_ISSUE_LIMIT`).

## 3. Multi-pass extraction (`banks/services/multi_pass_extractor.py`)

| Pass | Purpose |
| --- | --- |
| `standard` | Bank-specific prompt, extracts all card fields |
| `focused` | Runs **only** when pass 1 scores below `confidence_threshold` (default `0.8`); asks only for the critical fields and fills gaps without overwriting good values |
| `validation` | Runs the real validation stage (`CreditCardDataValidator`), then the final score |

- Provider access goes through the narrow `ExtractionProvider` protocol
  (`banks/services/extraction_provider.py`). Production uses
  `OrchestratorExtractionProvider` (OpenRouter/Gemini); tests inject fakes.
- **No provider → `AIParsingError` at the extractor, and the crawler silently
  degrades to the legacy single-pass parser** (`parse_comprehensive_data`), so
  existing behaviour and tests stay intact.
- Pass provenance (pass name, provider, cards found, per-pass confidence,
  errors) is stored on the crawl record (see §5).

## 4. Bank-specific prompt templates

`banks/services/prompt_templates.py` + `prompt_templates_base.py` register 16
bank keys (Sonali, Janata, Agrani, Rupali, BRAC, City, Dutch-Bangla, Islami -
PLC and Limited variants) plus aliases and a **generic fallback** for unknown
banks. Every template shares the same output contract from
`BASE_EXTRACTION_INSTRUCTIONS`: JSON only, `null` for values the document never
states, `0` for genuine zeros, no invented defaults.

## 5. Data model (`banks/models.py`, migration `banks/migrations/0011_...`)

New fields on `CrawledContent`:

| Field | Type | Notes |
| --- | --- | --- |
| `extraction_confidence` | `FloatField(null=True)` | `NULL` = "not scored yet" (distinct from a genuine `0.0`) |
| `missing_critical_fields` | `JSONField(default=list)` | Critical fields not extracted |
| `extraction_method` | `CharField` | `pdf_text`, `ocr`, `webpage`, `csv`, `image_ocr` |
| `needs_manual_review` | `BooleanField(default=False)` | Low confidence / multiple issues |
| `extraction_passes` | `JSONField(default=list)` | Multi-pass provenance records |
| `quality_scored_at` | `DateTimeField(null=True)` | When scoring ran |

`apply_quality_score()` clamps the value into `0.0-1.0`, stamps
`quality_scored_at` and derives `needs_manual_review` when it is not given
explicitly. `None` is stored as `NULL` (unscored), never as `0.0`.

## 6. Content extraction (Phase 3)

`ContentExtractor.extract_with_validation()` scores every candidate method for a
source and returns the best attempt with its `method`, `confidence` and
`attempts` provenance. `calculate_extraction_confidence()` reuses the same
bounded `score_content()` rules.

The crawler (`bank_data_crawler.py`) runs the regular single-method extraction
first; when it **fails or yields no text**, the multi-source path is used as a
rescue and its method/confidence are recorded on the crawl record. Connectivity
failures skip the rescue (it would fail the same way).

## 7. Daily schedule

- Task: `banks.tasks.daily_crawl_all_active_banks` - iterates every **active**
  bank, skips banks with no active data source, reports per-bank counts, and
  returns `{"status": "completed"|"error", ...}`.
- Beat entry: `daily-crawl-all-active-banks` in `credit_mate_ai/celery.py`,
  `crontab(hour=2, minute=0)` with `expires=3600`.
- The beat entry only takes effect when a Celery beat worker is actually
  running with this app's settings (see §9).

## 8. Storage rules (zero vs missing)

`banks/services/credit_card_data_service.py` and
`banks/validators/credit_card_validator.py` share the §1 rules:

- `0` / `"Free"` → stored as `0.00`
- `None` / `"N/A"` / `"abc"` / `True` / `-50` → stored as `NULL`
- The validator rejects booleans, `NaN`/`inf`, negatives and out-of-range
  values, accepts documented zero wording and currency strings, and never
  invents a default value.

## 9. Running and verifying offline

```bash
# Full suite (offline: no LLM keys, sockets disabled by pytest.ini)
DATABASE_URL=postgresql:///creditmate_opencode2 DEBUG=True \
  .venv/bin/python -m pytest banks common credit_cards -q -p no:cacheprovider

# Migration checks
DATABASE_URL=postgresql:///creditmate_opencode2 DEBUG=True \
  .venv/bin/python manage.py migrate
DATABASE_URL=postgresql:///creditmate_opencode2 DEBUG=True \
  .venv/bin/python manage.py makemigrations banks --check --dry-run
```

Dedicated test modules: `test_numeric_fields.py`, `test_quality_scoring.py`,
`test_quality_validator.py`, `test_quality_fields.py`,
`test_multi_pass_extraction.py`, `test_prompt_templates.py`,
`test_content_extraction_confidence.py`, `test_null_fee_preservation.py`,
`test_daily_crawl_schedule.py`, `test_crawler_quality_integration.py`.

## 10. Status / operational notes

- **Implemented and tested offline.** No live crawl, no LLM call and no
  deployment is implied by these code changes.
- **Pending:** running the daily schedule in production requires Celery
  beat/worker settings that backend worker1 owns; coordinate that glue before
  enabling the entry in the deployed environment.
- Pre-existing (not introduced here): `manage.py makemigrations --check` reports
  a pending `credit_cards.0006_alter_creditcard_interest_rate_apr` change; the
  same warning exists at baseline commit `6f842c2`. The `banks` app reports no
  pending changes.
