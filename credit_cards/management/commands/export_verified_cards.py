import json

from django.core.management.base import BaseCommand

from credit_cards.constants import REPORTABLE_FIELDS, VerificationStatus
from credit_cards.models import CreditCard

EXPORT_FIELDS = REPORTABLE_FIELDS + ("is_active", "verification_status")


class Command(BaseCommand):
    help = "Write verified cards (bank referenced by name) to a JSON file"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Output JSON file path")

    def handle(self, *args, **options):
        """Export every verified card as a JSON list of dicts."""
        cards = CreditCard.objects.filter(
            verification_status=VerificationStatus.VERIFIED
        ).select_related("bank")
        rows = []
        for card in cards:
            row = {"bank": card.bank.name}
            for field in EXPORT_FIELDS:
                row[field] = getattr(card, field)
            rows.append(row)
        with open(options["path"], "w", encoding="utf-8") as handle:
            # default=str serializes Decimal amounts without losing precision
            json.dump(rows, handle, indent=2, ensure_ascii=False, default=str)
        self.stdout.write(f"Exported {len(rows)} verified cards to {options['path']}")
