"""Prometheus metrics for streaming (safe against duplicate registration in tests)."""

from prometheus_client import Counter, Gauge


def _m(cls, name, doc, labels=()):
    try:
        return cls(name, doc, labels)
    except ValueError:
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors[name]


outbox_depth = _m(Gauge, "creditmate_streaming_outbox_depth", "Pending outbox events")
dlq_depth = _m(
    Gauge, "creditmate_streaming_dlq_depth", "Dead-letter entries not yet replayed"
)
producer_errors = _m(
    Counter,
    "creditmate_streaming_producer_errors_total",
    "Producer publish errors",
    ["topic"],
)
events_published = _m(
    Counter,
    "creditmate_streaming_events_published_total",
    "Events published by relay",
    ["topic"],
)
events_consumed = _m(
    Counter,
    "creditmate_streaming_events_consumed_total",
    "Events consumed",
    ["consumer", "result"],
)


def refresh_gauges():
    from streaming.models import DeadLetterEntry, OutboxEvent

    outbox_depth.set(
        OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING).count()
    )
    dlq_depth.set(DeadLetterEntry.objects.filter(replayed_at__isnull=True).count())
