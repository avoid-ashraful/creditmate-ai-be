import pytest
from streaming.envelope import deserialize, make_envelope, serialize

def test_envelope_roundtrip():
    env=make_envelope("crawl.fetched", {"source_id": 1})
    assert deserialize(serialize(env))["payload"]["source_id"]==1
    assert env["schema_version"]==1 and env["event_id"]

def test_envelope_requires_fields():
    with pytest.raises(ValueError):
        deserialize(b'{"event_id": "x"}')

@pytest.mark.django_db
def test_emit_creates_outbox_only_when_enabled(settings):
    from streaming.outbox import emit
    from streaming.models import OutboxEvent
    settings.EVENT_STREAMING_ENABLED=False
    assert emit("creditmate.crawl.fetched.v1", 1, {"source_id":1}) is None
    settings.EVENT_STREAMING_ENABLED=True
    row=emit("creditmate.crawl.fetched.v1", 1, {"source_id":1})
    assert row is not None and OutboxEvent.objects.count()==1

class FakeProducer:
    def __init__(self): self.sent=[]
    def publish(self, topic, key, value): self.sent.append((topic,key,value))
    def close(self): pass

@pytest.mark.django_db
def test_relay_marks_sent(settings):
    settings.EVENT_STREAMING_ENABLED=True
    from streaming.outbox import emit, relay_outbox
    emit("creditmate.crawl.fetched.v1", 1, {"source_id":1})
    fake=FakeProducer(); assert relay_outbox(producer=fake)==1
    from streaming.models import OutboxEvent
    assert OutboxEvent.objects.get().status=="sent" and len(fake.sent)==1

@pytest.mark.django_db
def test_consumer_idempotency_and_dlq(settings):
    settings.EVENT_STREAMING_ENABLED=True; settings.KAFKA_CONSUMER_MAX_ATTEMPTS=2; settings.KAFKA_CONSUMER_NO_SLEEP=True
    from streaming.consumers.base import BaseConsumer
    calls={"n":0}
    class Ok(BaseConsumer):
        name="test-ok"; topics=()
        def handle(self, env): calls["n"]+=1
    env=make_envelope("x", {})
    c=Ok(); assert c.process(env)=="processed"; assert c.process(env)=="duplicate"; assert calls["n"]==1
    class Bad(BaseConsumer):
        name="test-bad"; topics=()
        def handle(self, env): raise RuntimeError("boom")
    env2=make_envelope("y", {})
    assert Bad().process(env2, topic="creditmate.crawl.fetched.v1")=="dlq"
    from streaming.models import DeadLetterEntry
    assert DeadLetterEntry.objects.count()==1

def test_consumers_are_draft_only():
    from streaming.guard import scan_consumer_sources
    assert all(scan_consumer_sources().values())

def test_schemas_exist_and_parse():
    import json, pathlib
    d=pathlib.Path(__file__).resolve().parents[1]/"schemas"
    names={"envelope.schema.json","crawl.fetched.v1.schema.json","extraction.requested.v1.schema.json","extraction.completed.v1.schema.json","product.changed.v1.schema.json","streaming.dlq.v1.schema.json"}
    assert names <= {p.name for p in d.glob("*.json")}
    for p in d.glob("*.json"): json.loads(p.read_text())
