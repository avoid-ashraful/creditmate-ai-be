# Security review 8.5 (2026-10)

Scope: saved comparisons and collections; advanced credit card search; health and metrics; review queue notifications; REST framework throttling; CORS, CSRF, response headers, and production settings.

## Findings

| Severity | Finding and evidence | Fix status |
|---|---|---|
| Low | `/api/readyz/` returned the exception class name for failed dependencies. The public response was already excluding exception messages, but implementation at `credit_mate_ai/health.py:105-110` still serialized exception type names, which can reveal internal dependency details. | Fixed: return the generic `unavailable` value. Regression coverage verifies database, cache, and search errors. |
| Medium | Advanced search accepted arbitrary positive page numbers and passed them into a database `OFFSET` (`credit_cards/api/advanced_views.py:296-303`); malformed page values raised during `int()` conversion (`:329-338`) and became server errors. Page size was capped, but page number was not. | Fixed: validate integer pagination before cache/search work, reject pages outside 1–10,000 with HTTP 400, and keep page size capped at 100. Added invalid pagination regression cases. |
| High | Production could silently use Django’s published development `SECRET_KEY` fallback (`credit_mate_ai/settings.py:38-44`), enabling signed-cookie/session forgery if deployed without an environment secret. | Fixed: fail startup when `ENVIRONMENT=production` and no `SECRET_KEY` is configured. Regression test added. |
| Medium | Production inherited `ALLOWED_HOSTS` defaulting to testserver and loopback names (`credit_mate_ai/settings.py:46`), preventing normal production hosts from being served and encouraging unsafe wildcard workarounds. | Fixed: production startup now requires an explicit, non-wildcard `ALLOWED_HOSTS`; regression test added. |

## Reviewed controls with no finding

- Saved comparisons and collections scope owner endpoints to `request.user` (`saved/views.py:49-70`, `:118-139`); cross-owner object access returns 404 in tests. Create limits and per-comparison/per-collection card limits are enforced in `saved/services.py` and serializer validation. Public share tokens use cryptographic random bytes (`saved/models.py:17-29`) and public serializers omit IDs, owners, and tokens (`saved/serializers.py:181-185`).
- Advanced search uses ORM filters and an allowlist for ordering (`credit_cards/api/advanced_views.py:270-291`); no raw SQL interpolation or user-selected ORM field path was found. Cache keys hash normalized query values and use the validated request origin (`:341-355`).
- Metrics access checks bearer token or `REMOTE_ADDR` only (`credit_mate_ai/metrics.py:115-135`, `:158-176`); regression tests confirm spoofed `X-Forwarded-For` is ignored. HTTP metrics use resolver URL names, `unknown` for unresolved paths, and a fixed method set (`credit_mate_ai/prometheus_middleware.py:30-37`, `:94-108`), so request paths do not create arbitrary labels.
- New DRF views inherit `REST_FRAMEWORK.DEFAULT_THROTTLE_CLASSES` (`credit_mate_ai/settings.py:322-330`); the advanced viewset does not override throttle classes. Review queue email is opt-in and deferred with `transaction.on_commit` (`banks/services/review_queue.py:48-74`).
- CORS defaults to explicit local origins and credential support does not enable wildcard origins (`credit_mate_ai/settings.py:360-397`). CSRF middleware is enabled (`:127-140`), production SSL redirect and secure cookies are enabled when `DEBUG` is false (`:457-469`), and response security headers have dedicated coverage.

## Verification

- Full requested pytest invocation: 1,417 passed, 35 skipped, 2 failed. One failure was the readiness assertion changed by this review; after updating it, the focused observability/security run passed. The remaining unrelated failure is `search/tests/test_queue.py::TestAutomaticQueueScheduling::test_beat_schedule_registers_drain_task`, which raised `KeyError: 'search-index-queue-drain'`.
- Focused rerun after all changes: 46 passed, 32 warnings (`credit_mate_ai/tests/test_observability.py` and `credit_mate_ai/tests/test_security_headers.py`).
- Full `flake8` reports 3 pre-existing issues outside this task scope: `docs/user/readability_check.py:286` (C901), `docs/user/readability_textstat.py:186` (C901), and `docs/user/readability_textstat.py:227` (F541).
