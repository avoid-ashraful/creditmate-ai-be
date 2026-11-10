# ADR: Kafka event streaming for the crawl → extraction → ingestion pipeline

Status: accepted (2026-11-11). Capability 3 of the six-capability plan.

## Context
The nightly sync was a direct Celery chain: crawl → hash-check → LLM extraction → ReviewQueue draft.
It works, but stages are not replayable, there is no durable event log for downstream consumers
(embeddings, cache invalidation), and failures inside a run are hard to re-drive selectively.

## Decisions
- **Transactional outbox.** Producers never dual-write: `streaming.OutboxEvent` is written in the same
  DB transaction as the state change and a Celery relay task (beat, 5s — mirroring the existing
  `search` outbox drain) publishes with `enable.idempotence=true, acks=all`, marking rows sent only
  after publish succeeds.
- **Consumers are standalone processes, not Celery tasks.** `python manage.py run_consumer <name>`
  runs a confluent-kafka consumer with its own group, manual offset commit (only after the handler +
  `ProcessedEvent` marker commit in one DB transaction), bounded attempts (5) and DLQ routing.
  Consumer-group semantics, rebalance and lag are first-class and measurable this way.
- **Celery vs Kafka boundary.** Celery remains the scheduler/task queue (beat schedules, nightly sync
  initiation, outbox relay). Kafka is the durable, replayable event log *between pipeline stages*.
  Neither replaces the other.
- **Redpanda locally, Kafka-portable.** Redpanda is a single lightweight binary with a built-in
  Schema Registry + console, ideal for a laptop/sandbox. Only the standard Kafka protocol and the
  `confluent-kafka` client are used — no Redpanda-specific APIs — so staging/production can point
  `KAFKA_BOOTSTRAP_SERVERS` at Apache Kafka / MSK / Confluent unchanged.
- **JSON Schema + registry (BACKWARD)** over Avro for v1: payloads are document-like extraction
  results and the codebase is JSON-native (DRF). Schemas live in `streaming/schemas/`.
- **Idempotency + DLQ.** `ProcessedEvent(event_id, consumer)` unique constraint makes replays no-ops.
  After 5 attempts a message is persisted as `DeadLetterEntry` and published to
  `creditmate.streaming.dlq.v1`; `replay_dlq` re-emits entries via the outbox after a fix.
- **Draft-only invariant (hard).** Extraction/ingestion consumers may only create
  `banks.ReviewQueue` drafts. No consumer may write verified product data. Enforced by
  `streaming.guard.assert_draft_only` (source scan in tests) and by the consumers simply having
  no product-model write path.
- **Flag-gated.** `EVENT_STREAMING_ENABLED` defaults to False; when off, `emit()` is a no-op and
  the existing direct Celery pipeline is untouched.

## Consequences
Positive: replayable pipeline, a `product.changed` event for embeddings/cache consumers, selective
re-drive of failures. Cost: another local service (Redpanda) and at-least-once semantics that every
consumer must respect via `ProcessedEvent`. At today's nightly-batch volume Celery+Redis alone would
suffice operationally; Kafka is justified by replayability, downstream consumers, and the explicit
learning goal — and the flag-off path is preserved permanently.
