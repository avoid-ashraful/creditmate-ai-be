"""Emit + relay for the transactional outbox."""
import logging, uuid
from django.db import transaction
from django.utils import timezone
from streaming.envelope import make_envelope, serialize
from streaming.models import OutboxEvent
logger=logging.getLogger(__name__)
def emit(topic, key, payload, event_type=None, trace_id=""):
    """Create an outbox row in the caller's transaction. Returns the row (None if streaming disabled)."""
    from django.conf import settings
    if not getattr(settings,"EVENT_STREAMING_ENABLED",False): return None
    env=make_envelope(event_type or topic, payload, trace_id=trace_id)
    return OutboxEvent.objects.create(event_id=env["event_id"], topic=topic, key=str(key or ""), envelope=env)
def emit_on_commit(topic, key, payload, **kw):
    transaction.on_commit(lambda: emit(topic, key, payload, **kw))
def relay_outbox(producer=None, batch_size=100):
    """Publish pending rows in order; mark sent only after publish succeeds. Returns count sent."""
    from streaming.metrics import events_published, refresh_gauges
    rows=list(OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING).order_by("created","id")[:batch_size])
    if not rows: 
        refresh_gauges(); return 0
    own=False
    if producer is None:
        from streaming.producer import KafkaProducerWrapper; producer=KafkaProducerWrapper(); own=True
    sent=0
    try:
        for row in rows:
            try:
                producer.publish(row.topic, row.key, serialize(row.envelope))
                row.status=OutboxEvent.STATUS_SENT; row.sent_at=timezone.now(); row.attempts+=1; row.save(update_fields=["status","sent_at","attempts","modified"])
                events_published.labels(topic=row.topic).inc(); sent+=1
            except Exception as e:
                row.attempts+=1; row.last_error=str(e)[:2000]
                if row.attempts>=5: row.status=OutboxEvent.STATUS_FAILED
                row.save(update_fields=["attempts","last_error","status","modified"]); logger.warning("outbox relay failed %s: %s", row.event_id, e)
    finally:
        if own: producer.close()
        refresh_gauges()
    return sent
