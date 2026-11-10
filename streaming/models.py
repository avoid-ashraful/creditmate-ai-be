from django.db import models
from django.utils import timezone
from common.models import Audit
class OutboxEvent(Audit):
    """Transactional outbox row: written in the same DB txn as the state change, relayed to Kafka."""
    STATUS_PENDING="pending"; STATUS_SENT="sent"; STATUS_FAILED="failed"
    STATUS_CHOICES=[(STATUS_PENDING,"Pending"),(STATUS_SENT,"Sent"),(STATUS_FAILED,"Failed")]
    event_id=models.UUIDField(unique=True, db_index=True)
    topic=models.CharField(max_length=128, db_index=True)
    key=models.CharField(max_length=255, blank=True, default="")
    envelope=models.JSONField(default=dict)
    status=models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempts=models.PositiveSmallIntegerField(default=0)
    last_error=models.TextField(blank=True, default="")
    sent_at=models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table="streaming_outboxevent"; ordering=["created","id"]
        indexes=[models.Index(fields=["status","created"], name="streaming_outbox_pending_idx")]
class ProcessedEvent(Audit):
    """Idempotency marker: handler + marker commit in one transaction; replays are no-ops."""
    event_id=models.UUIDField()
    consumer=models.CharField(max_length=128)
    processed_at=models.DateTimeField(default=timezone.now)
    class Meta:
        db_table="streaming_processedevent"
        constraints=[models.UniqueConstraint(fields=["event_id","consumer"], name="streaming_processed_unique")]
class DeadLetterEntry(Audit):
    original_topic=models.CharField(max_length=128)
    key=models.CharField(max_length=255, blank=True, default="")
    envelope=models.JSONField(default=dict)
    error_class=models.CharField(max_length=255, blank=True, default="")
    error_message=models.TextField(blank=True, default="")
    attempts=models.PositiveSmallIntegerField(default=0)
    replayed_at=models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table="streaming_deadletterentry"; ordering=["created","id"]
