from django.core.management.base import BaseCommand
from django.utils import timezone
class Command(BaseCommand):
    help="Re-publish dead-letter entries to their original topics via the outbox."
    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, default=None); parser.add_argument("--all", action="store_true")
    def handle(self, *a, **kw):
        from streaming.models import DeadLetterEntry
        from streaming.outbox import emit
        qs=DeadLetterEntry.objects.filter(replayed_at__isnull=True)
        if kw["id"]: qs=qs.filter(pk=kw["id"])
        n=0
        for e in qs:
            emit(e.original_topic, e.key, (e.envelope or {}).get("payload") or {}, event_type=(e.envelope or {}).get("event_type") or e.original_topic)
            e.replayed_at=timezone.now(); e.save(update_fields=["replayed_at","modified"]); n+=1
        self.stdout.write(f"replayed {n} DLQ entries")
