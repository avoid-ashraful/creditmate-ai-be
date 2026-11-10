"""Producer wrapper around confluent-kafka. Import is lazy so the app works (flag off) without the wheel."""
import logging
from django.conf import settings
logger=logging.getLogger(__name__)
class ProducerError(RuntimeError): pass
class KafkaProducerWrapper:
    def __init__(self, bootstrap_servers=None, client_id="creditmate-be"):
        try:
            from confluent_kafka import Producer
        except ImportError as e: raise ProducerError("confluent-kafka not installed") from e
        self._p=Producer({"bootstrap.servers": bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS,
                          "enable.idempotence": True, "acks": "all", "client.id": client_id})
    def publish(self, topic, key, value_bytes):
        from streaming.metrics import producer_errors
        try:
            self._p.produce(topic=topic, key=(key or "").encode(), value=value_bytes)
            self._p.flush(timeout=float(getattr(settings,"KAFKA_PRODUCER_FLUSH_TIMEOUT",10)))
        except Exception as e:
            producer_errors.labels(topic=topic).inc(); raise ProducerError(str(e)) from e
    def close(self):
        try: self._p.flush(timeout=5)
        except Exception: pass
