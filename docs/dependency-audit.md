# Backend dependency vulnerability audit

Audit date: 2026-10-13  
Lockfile: `uv.lock` (116 resolved packages; 115 evaluated for this platform)  
Source: `uv audit --locked` using the OSV service.

## Results

The initial audit reported 279 advisory records across 20 package/version pairs. OSV includes duplicate GHSA/PYSEC records for the same issues, so the record count is not a count of distinct flaws. `uv export --format requirements-txt --no-hashes` succeeded. `uvx pip-audit --requirement /tmp/beaudit-requirements.txt` installed pip-audit but stalled while creating its temporary environment; it did not produce an audit result. `uv audit --locked` completed successfully and was used for the findings below.

| Package | Before | After | Triage |
| --- | --- | --- | --- |
| Django | 5.2.5 | 5.2.18 | Runtime, reachable through normal request, auth, ORM, middleware and file handling. Updated within the 5.2 line. |
| djangorestframework | 3.16.1 | 3.17.2 | Runtime, reachable through API request parsing and optional browsable admin rendering. Updated to advisory-fixed minor line. |
| djangorestframework-simplejwt | 5.3.1 | 5.5.1 | Runtime, reachable wherever JWT authentication is enabled. Updated within major version 5. |
| requests | 2.32.5 | 2.33.1 | Runtime, used by bank content and schedule fetchers. Advisory is for a helper that extracts zipped paths; ordinary HTTP use is not itself the vulnerable path. Updated to fixed minor line. |
| urllib3 | 2.5.0 | 2.8.0 | Runtime dependency of requests; streaming and proxy paths are conditional on how callers configure HTTP requests. |
| pillow | 11.3.0 | 12.3.0 | Runtime, used in image and PDF OCR extraction; malformed input can reach image decoders. |
| pypdf | 6.0.0 | 6.20.1 | Runtime, parses downloaded bank PDFs in `banks/services/content_extractor.py`; malformed PDF paths are reachable. |
| sqlparse | 0.5.3 | 0.6.0 | Runtime Django dependency. Relevant parser/formatting flaws depend on parsing attacker-controlled SQL or formatting calls; ORM use is indirect. |
| anyio | 4.10.0 | 4.14.2 | Runtime transitive dependency. Process-pool and TLSStream advisories require those specific APIs/configurations; no direct project imports found. |
| filelock | 3.19.1 | 3.32.7 | Development transitive dependency; fixed within major 3. |
| httplib2 | 0.30.0 | 0.32.0 | Runtime transitive dependency, used by Google client libraries; affected HTTP behavior depends on the relevant call path. |
| idna | 3.10 | 3.20 | Runtime transitive dependency of HTTP clients. |
| protobuf | 5.29.5 | 5.29.6 | Runtime transitive dependency of Google libraries; affected parsing requires crafted protobuf input. |
| pyasn1 | 0.6.1 | 0.6.4 | Runtime transitive dependency of Google/auth libraries; affected ASN.1 decoding requires crafted input. |
| pygments | 2.19.2 | 2.21.0 | Development/test rendering dependency; no production reachability identified. |
| python-dotenv | 1.1.1 | 1.2.4 | Runtime configuration helper. Issues require attacker-controlled dotenv input; deployment config is normally trusted. |
| soupsieve | 2.8 | 2.10 | Runtime transitive dependency of Beautiful Soup; selector complexity issues require attacker-controlled selectors. Constrained below 3 to stay on the current major line. |
| virtualenv | 20.34.0 | 20.39.1 | Development-only transitive dependency. Constrained below 21 to retain the existing major line. |
| black | 24.10.0 | 24.10.0 | Development-only formatter. OSV fixes require Black 26.3.1; retained because that is a major upgrade outside this safe patch/minor pass. |
| pytest | 8.4.1 | 8.4.1 | Test-only. OSV lists pytest 9.0.3 as fixed; retained because that is a major upgrade outside this pass. |

The lockfile also reports `rsa` as archived (not a vulnerability). It remains a transitive dependency; no replacement was made as part of this vulnerability-only lock update.

## Remaining findings

The final audit reports 13 advisory records: three for Black 24.10.0, two for pytest 8.4.1, and eight for virtualenv 20.39.1. These tools are not part of production request handling. OSV lists fixed versions only on the next major lines (Black 26.3.1, pytest 9.0.3, and virtualenv 21.7.13 or later). They are left for a separately tested tooling-major upgrade. The remaining `rsa` adverse status is archival metadata, not an advisory.

## Verification

- `uv lock --check`: passed.
- `manage.py check`: passed, no issues.
- `manage.py makemigrations --check`: passed, no changes detected. The task database `creditmate_audit` was created in the configured PostgreSQL container after the first invocation reported it missing.
- Requested pytest suites: initial serialized run collected 1,556 tests and finished with 1,520 passed, 35 skipped, and 1 failed in 442.82 seconds. The failure was `TestAutomaticQueueScheduling.test_beat_schedule_registers_drain_task`, because the required shared test environment had `SEARCH_ENABLED=False`, which intentionally disables that schedule. Rerun alone with `SEARCH_ENABLED=True`: 1 passed in 3.79 seconds. All requested suites were included in the initial run; no failures remain after the configuration-corrected rerun.
