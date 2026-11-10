from django.contrib import admin
from streaming.models import DeadLetterEntry, OutboxEvent, ProcessedEvent
@admin.register(OutboxEvent)
class OutboxAdmin(admin.ModelAdmin): list_display=("event_id","topic","status","attempts","created"); list_filter=("status","topic")
@admin.register(ProcessedEvent)
class ProcessedAdmin(admin.ModelAdmin): list_display=("event_id","consumer","processed_at")
@admin.register(DeadLetterEntry)
class DLQAdmin(admin.ModelAdmin): list_display=("original_topic","error_class","attempts","replayed_at","created")
