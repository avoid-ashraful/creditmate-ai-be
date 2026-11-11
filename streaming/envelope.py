"""Event envelope helpers: {event_id, event_type, schema_version, occurred_at, producer, trace_id, payload}."""

import json
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def make_envelope(event_type, payload, producer="creditmate-be", trace_id=""):
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer,
        "trace_id": trace_id or "",
        "payload": payload,
    }


def serialize(envelope):
    return json.dumps(envelope, default=str).encode("utf-8")


def deserialize(raw):
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    env = json.loads(raw)
    for k in ("event_id", "event_type", "schema_version", "occurred_at", "payload"):
        if k not in env:
            raise ValueError(f"envelope missing {k}")
    return env
