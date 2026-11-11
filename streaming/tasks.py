import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="streaming.relay_outbox", ignore_result=True)
def relay_outbox_task(batch_size=None):
    from django.conf import settings

    if not getattr(settings, "EVENT_STREAMING_ENABLED", False):
        return 0
    from streaming.outbox import relay_outbox

    return relay_outbox(
        batch_size=batch_size or int(getattr(settings, "KAFKA_RELAY_BATCH_SIZE", 100))
    )
