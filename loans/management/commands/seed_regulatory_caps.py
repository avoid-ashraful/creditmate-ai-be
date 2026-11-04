"""Seed the dated Bangladesh Bank regulatory ceilings for loans.

Caps are DATA (BB circulars change them — e.g. BRPD Circular Letter No.
15 of 05 May 2026 and No. 21 of 25 June 2026), never code. Idempotent.
"""

from django.core.management.base import BaseCommand

from loans.ingestion.catalogue import REGULATORY_CAPS
from loans.models import RegulatoryCap


class Command(BaseCommand):
    help = "Seed/update dated regulatory caps for loan products."

    def handle(self, *args, **options):
        created = updated = 0
        for entry in REGULATORY_CAPS:
            _, was_created = RegulatoryCap.objects.update_or_create(
                key=entry["key"],
                effective_from=entry["effective_from"],
                defaults={
                    "params": entry["params"],
                    "description": entry["description"],
                    "source_note": entry["source_note"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(f"Regulatory caps: {created} created, {updated} updated.")
