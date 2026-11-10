# streaming — Kafka/Redpanda event streaming

Flag-gated (`EVENT_STREAMING_ENABLED`, default **False** — flag off is exactly the pre-streaming pipeline).

## Topics
| Topic | Key | Payload |
|---|---|---|
| `creditmate.crawl.fetched.v1` | source_id | source_id, url, content_hash, fetched_at, sync_run_id |
| `creditmate.extraction.requested.v1` | source_id | crawled_content_id, purpose, model_hint |
| `creditmate.extraction.completed.v1` | source_id | crawled_content_id, draft_payload_ref, confidence, provider, token_usage |
| `creditmate.product.changed.v1` | product_type:id | change_type, changed_fields[], version |
| `creditmate.streaming.dlq.v1` | original key | original_topic, error_class, attempts, envelope |

Schemas: `streaming/schemas/*.schema.json` (JSON Schema, BACKWARD compatibility in the registry).
Envelope: `{event_id, event_type, schema_version, occurred_at, producer, trace_id, payload}`.

## Running locally
```bash
docker compose -f docker-compose.streaming.yml up -d   # Redpanda + console (localhost only)
EVENT_STREAMING_ENABLED=True KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092 python manage.py run_consumer extraction
EVENT_STREAMING_ENABLED=True KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092 python manage.py run_consumer ingestion
python manage.py replay_dlq --all
```
Outbox relay runs via Celery beat every `KAFKA_RELAY_INTERVAL` seconds (default 5).
See `docs/adr/kafka-streaming.md`.
