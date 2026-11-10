"""Base consumer: idempotency, bounded attempts, DLQ routing. Offsets commit only after success.

Pure logic (should_retry / route_failure) is unit-testable without a broker.
"""
import logging, time
from django.conf import settings
from django.db import transaction
logger=logging.getLogger(__name__)
MAX_ATTEMPTS=int(getattr(settings,"KAFKA_CONSUMER_MAX_ATTEMPTS",5)) if False else 5
def max_attempts(): return int(getattr(settings,"KAFKA_CONSUMER_MAX_ATTEMPTS",5))
def should_retry(attempts): return attempts < max_attempts()
def route_failure(envelope, topic, key, error, attempts):
    """Persist a DLQ entry; returns the entry."""
    from streaming.models import DeadLetterEntry
    from streaming.outbox import emit
    entry=DeadLetterEntry.objects.create(original_topic=topic, key=str(key or ""), envelope=envelope,
        error_class=type(error).__name__, error_message=str(error)[:2000], attempts=attempts)
    # Also publish to the DLQ topic via outbox (best effort; the DB row is the durable record).
    try: emit("creditmate.streaming.dlq.v1", key, {"original_topic":topic,"dlq_entry_id":entry.pk,"error_class":type(error).__name__,"attempts":attempts,"envelope":envelope}, event_type="streaming.dlq")
    except Exception: logger.exception("DLQ topic emit failed")
    return entry
class BaseConsumer:
    name="base"; topics=()
    def handle(self, envelope): raise NotImplementedError
    def process(self, envelope, topic="", key=""):
        """Idempotent processing: returns 'processed'|'duplicate'|'dlq'. Raises only after DLQ routing on final failure handled by caller loop."""
        from streaming.models import ProcessedEvent
        from streaming.metrics import events_consumed
        event_id=envelope.get("event_id")
        if ProcessedEvent.objects.filter(event_id=event_id, consumer=self.name).exists():
            events_consumed.labels(consumer=self.name, result="duplicate").inc(); return "duplicate"
        attempts=0; last_error=None
        while True:
            attempts+=1
            try:
                with transaction.atomic():
                    self.handle(envelope)
                    ProcessedEvent.objects.create(event_id=event_id, consumer=self.name)
                events_consumed.labels(consumer=self.name, result="processed").inc(); return "processed"
            except Exception as e:  # noqa: BLE001
                last_error=e; logger.warning("consumer %s attempt %s failed: %s", self.name, attempts, e)
                if should_retry(attempts):
                    time.sleep(min(2**attempts, 10) if not getattr(settings,"KAFKA_CONSUMER_NO_SLEEP",False) else 0); continue
                route_failure(envelope, topic, key, e, attempts)
                events_consumed.labels(consumer=self.name, result="dlq").inc(); return "dlq"
    def run(self, stop_after=None):
        """Blocking consumer loop using confluent-kafka (lazy import). Manual commit after process()."""
        from confluent_kafka import Consumer
        conf={"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS, "group.id": f"creditmate.{self.name}",
              "enable.auto.commit": False, "auto.offset.reset": "earliest"}
        c=Consumer(conf); c.subscribe(list(self.topics)); seen=0
        try:
            while True:
                msg=c.poll(1.0)
                if msg is None: 
                    if stop_after is not None and seen>=stop_after: break
                    continue
                if msg.error(): logger.warning("kafka error %s", msg.error()); continue
                from streaming.envelope import deserialize
                env=deserialize(msg.value())
                self.process(env, topic=msg.topic(), key=(msg.key() or b"").decode(errors="replace"))
                c.commit(message=msg, asynchronous=False); seen+=1
                if stop_after is not None and seen>=stop_after: break
        finally: c.close()
