from django.core.management.base import BaseCommand, CommandError
CONSUMERS={}
def _registry():
    from streaming.consumers.extraction import ExtractionConsumer
    from streaming.consumers.ingestion import IngestionConsumer
    return {"extraction": ExtractionConsumer, "ingestion": IngestionConsumer}
class Command(BaseCommand):
    help="Run a streaming consumer (standalone process; not a Celery task)."
    def add_arguments(self, parser):
        parser.add_argument("name"); parser.add_argument("--stop-after", type=int, default=None)
    def handle(self, *a, **kw):
        reg=_registry()
        if kw["name"] not in reg: raise CommandError(f"unknown consumer {kw['name']}; choose {sorted(reg)}")
        reg[kw["name"]]().run(stop_after=kw["stop_after"])
