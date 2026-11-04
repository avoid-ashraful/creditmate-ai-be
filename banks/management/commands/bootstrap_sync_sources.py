"""Register the BankDataSource rows the nightly product sync needs.

Fresh deployments used to crawl nothing — the sources table started
empty. This command registers the Bangladesh Bank charts, every bank's
Schedule of Charges (card crawl), and the per-bank provenance URLs stored
on the accounts/deposits/loans catalogues (watched sources). Idempotent:
safe to re-run after reseeding a catalogue.

Usage:
    python manage.py bootstrap_sync_sources
"""

import json

from django.core.management.base import BaseCommand

from banks.services.source_bootstrap import bootstrap_sync_sources


class Command(BaseCommand):
    help = "Create the BankDataSource registry rows used by the nightly sync."

    def handle(self, *args, **options):
        counts = bootstrap_sync_sources()
        self.stdout.write(json.dumps(counts, indent=2, default=str))
        self.stdout.write(
            self.style.SUCCESS(
                f"Sync sources ready: {counts['total_active_sources']} active sources "
                f"({counts['created']} created, {counts['existing']} already registered, "
                f"{counts['shared']} shared across verticals)."
            )
        )
