# Celery task safety review

Inventory checked with `rg -n 'shared_task|@app\.task|beat_schedule' --glob '*.py'` on 2026-10-13. Static beat entries are in `credit_mate_ai/settings.py`; the search drain entry is added conditionally by `credit_mate_ai/celery.py`.

No Celery-wide `acks_late`, task time limit, soft time limit, or worker-loss redelivery setting is configured. Tasks therefore use Celery's normal early acknowledgement behavior and have no configured hard/soft runtime limit. `max_retries` does not cause a retry by itself: tasks need to call `retry` or use autoretry. Beat expiry is a broker message expiry, not a task runtime limit.

| Task | Trigger | Idempotent under retry, duplicate delivery, and concurrent runs? Why | Retries | Limits |
| --- | --- | --- | --- | --- |
| `banks.tasks.crawl_bank_data_source` | On demand | Mostly. Content hashes skip unchanged extraction, and parsed cards use `update_or_create` keyed by bank/name. Concurrent changed-content crawls can still both create `CrawledContent` rows; there is no per-source lock or transaction around the pipeline. | 3 retries, exponential countdown 60s, 120s, 240s for raised exceptions; ordinary `False` results are returned without retry. | None |
| `banks.tasks.crawl_all_bank_data` | Weekly beat; can be called directly | Mostly, with the same crawler behavior. Re-running does not repeat card creation for the same bank/name, but crawl records and external extraction calls can repeat. | None; catches and returns errors. | Beat expiry 24h; no runtime limit |
| `banks.tasks.crawl_bank_data_sources_by_bank` | On demand | Mostly, with the same crawler behavior. No task lock; source content checks and card upserts provide partial protection. | None; catches and returns errors. | None |
| `banks.tasks.daily_crawl_all_active_banks` | Daily 02:00 UTC beat | Mostly, with the same crawler behavior and partial database-write caveat. | None; catches and returns errors. | Beat expiry 6h; no runtime limit |
| `banks.tasks.cleanup_old_crawled_content` | On demand (no beat entry found) | Yes for deletion: deleting already deleted/old rows is harmless. The returned count can differ on a repeated run. | None; catches and returns errors. | None |
| `banks.tasks.find_and_update_schedule_charge_urls` | On demand (no beat entry found) | Mostly. Existing sources are updated, and `(bank, url)` has a database uniqueness constraint. Lookup then create can race; a concurrent duplicate can raise and is retried. | 3 retries, exponential countdown 60s, 120s, 240s. Per-bank errors are logged and counted, not retried. | None |
| `banks.tasks.find_schedule_charge_url_for_bank` | On demand | Mostly. Existing source rows are updated and `(bank, url)` is unique; lookup then create can race. | None; catches and returns errors. | None |
| `banks.tasks.monthly_data_quality_check` | Monthly beat | Yes; read-only checks and result construction. | 3 retries, exponential countdown 60s, 120s, 240s. | Beat expiry 24h; no runtime limit |
| `banks.tasks.monthly_schedule_charge_url_discovery` | Monthly beat | Mostly; delegates to the URL-discovery logic, which updates existing rows and has a unique `(bank, url)` constraint. | 2 task retries at 600s exponential countdown; inner task has its own maximum of 3 but retries only when an exception escapes. | Beat expiry 24h; no runtime limit |
| `banks.tasks.monthly_comprehensive_crawl` | On demand (not scheduled) | Mostly, with the crawler's content-hash and card-upsert protection; crawl records can repeat under concurrency. | 2 retries at 600s exponential countdown. | Beat expiry 24h; no runtime limit |
| `search.process_search_index_queue` (`search.tasks.process_search_index_queue`) | Conditional beat (`SEARCH_ENABLED`, mode not `off`, positive interval); optionally dispatched after commit | Yes for DB queue ownership; drainers claim disjoint rows with row locks and lease tokens. Engine writes are replay-safe upserts/deletes. Queue rows carry their own bounded attempt count (default 5), backoff, and lease recovery. | Celery task declares max 3 / 60s but does not call retry. Engine failures are persisted by the queue for bounded retries, then marked failed. | Beat expiry is `max(60, interval * 4)`; no runtime limit |
| `search.rebuild_index` (`search.tasks.rebuild_search_index`) | On demand | No guarantee for concurrent runs: each rebuild can drop/recreate the same indexes, and there is no lock. A completed rebuild is repeatable; interrupted rebuilds can leave partial external state. | 1 retry declared; no custom backoff or catch. | None |
| `alerts.tasks.send_alert_digests` | Hourly beat | Sequential duplicate deliveries are suppressed by unique `SentAlert.event_key` records. Concurrent deliveries can race between existence check and insert; the unique constraint prevents both from claiming the key. A worker crash after SMTP accepts an email but before the task completes has the usual external-send ambiguity. | 3 retries, bounded exponential delay (300s, 600s, 1200s); failures are logged with traceback. | Beat expiry 1h; no runtime limit |

## Beat entries

| Entry | Schedule | Expiry |
| --- | --- | --- |
| `send-alert-digests-hourly` | 3600s | 3600s |
| `crawl-bank-data-weekly` (the only scheduled crawl: active banks' active sources, unchanged content skipped, capped by `LLM_MAX_CALLS_PER_RUN`) | 604800s | 86400s |
| `monthly-data-quality-check` | 30 days | 86400s |
| `monthly-schedule-charge-discovery` | 30 days | 86400s |
| `search-index-queue-drain` | `SEARCH_QUEUE_DRAIN_INTERVAL` seconds, when enabled | `max(60, 4 * interval)` |

## Transactions, acknowledgements, and failure reporting

- Search model signals enqueue outbox rows in `transaction.on_commit`; the broker dispatch is optional. Queue claiming and row state changes use database transactions. Engine I/O happens outside a DB transaction, and failures are logged with traceback and stored in `last_error`.
- The crawler does not wrap the whole fetch/extract/parse/save pipeline in one database transaction. Card writes use `update_or_create`, while crawl history rows are append-only and can duplicate under a crash or concurrent crawl. Crawl service catches many failures and returns `False`, so the Celery task does not retry those failures.
- Alert sending has no encompassing database transaction because SMTP cannot participate in one. A `SentAlert` claim is created before send and deleted if send raises; task-level exceptions are logged and retried. If SMTP accepts a message and then reports a failure, a later retry can send it again. There is no transaction or `on_commit` boundary for sending.
- No task is configured for late acknowledgement. Consequently, a worker crash after early acknowledgement can lose the current task delivery; periodic beat entries will publish the next scheduled run, while search outbox rows remain durable for the next drain.

## Changes in this review

Added expiry to the hourly alert digest and weekly crawl beat messages to avoid stale queued work. Alert digest exceptions now have traceback logging and a bounded retry policy; its existing per-event sent log is removed when sending raises. Added tests for alert retry cleanup and both new expiry windows.
