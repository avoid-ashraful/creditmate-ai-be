"""Run the nightly all-products sync once, synchronously (ops/manual use).

The scheduled path is the Celery beat entry ``sync-all-products-nightly``
(02:00 Asia/Dhaka). This command runs the same orchestration in-process —
useful for first-run verification after bootstrap and for backfills.

Usage:
    python manage.py run_nightly_sync
"""

import json

from django.core.management.base import BaseCommand

from banks.enums import SyncTrigger
from banks.services.nightly_sync import NightlySyncService


class Command(BaseCommand):
    help = "Run one nightly all-products sync (charts + cards + watched sources)."

    def handle(self, *args, **options):
        run = NightlySyncService().run(trigger=SyncTrigger.MANUAL)
        self.stdout.write(json.dumps(run.summary, indent=2, default=str))
        self.stdout.write(
            self.style.SUCCESS(f"SyncRun {run.pk} finished with status {run.status}.")
        )
