# Backend query performance audit

## Measured query counts

Measured with 30 banks, one card and one completed crawled-content row per bank.
The pre-change `build_dashboard()` query count was 253: 13 global queries and
8 queries per bank. After combining status, confidence-window, and missing-field
metrics into one content aggregate, and both null-card counts into one card
aggregate, the count is 98: 8 global queries and 3 per bank. The regression test
asserts this exact count and confirms all 30 bank rows are returned.

The change preserves the dashboard response fields and filtering. The content
aggregate includes conditional counts for completed, failed, pending, and
processing states, confidence averages and scored counts for the existing
7/30-day windows, and completed rows reporting each missing field.

The alert digest was measured with 30 active weekly subscriptions, 30 users,
30 cards, one eligible annual-fee history row per card, and pre-existing
notification preferences. `send_alert_digests()` sent all 30 messages using 64
queries: four bounded discovery queries, then one sent-event check and one
insert per message. The previous implementation's query shape would use 121
queries for that fixture (one subscription query plus a preference lookup and
history query per subscription, then two event queries per delivered message).
The regression test asserts the measured 64-query count and 30 sends.

## Index review and query plan

The alert digest scans active subscriptions in creation order. A PostgreSQL
partial index on `created DESC WHERE is_active` was added in
`alerts/migrations/0003_alertsubscription_active_created_index.py`, matching
that predicate and ordering. The expected query shape is:

```sql
SELECT ... FROM alerts_alertsubscription
WHERE is_active = true
ORDER BY created DESC;
```

The local shared PostgreSQL instance did not retain the task database after
pytest cleanup, and `be_perf` itself does not exist there, so no `EXPLAIN`
output was captured. The migration check confirms the model and migration
state agree. Confirm index selection with `EXPLAIN (ANALYZE, BUFFERS)` on a
migrated production-like database before drawing conclusions about its use at
deployed table sizes.

## Other audited read paths

Card list, detail, typeahead, search suggestions, advanced search, multi-ID
card fetch, saved-comparison list, and review list/summary were inspected for
relation loading and aggregation. This worktree does not yet have query-count
measurements or regression assertions for each of those paths, so the review
does not establish their counts at 30-bank scale. No response or serializer
changes were needed for them. Alert digest and dashboard query counts are
covered by populated regression fixtures above.
