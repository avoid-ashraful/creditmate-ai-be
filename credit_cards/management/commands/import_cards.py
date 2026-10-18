import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from banks.models import Bank
from credit_cards.constants import REPORTABLE_FIELDS, VerificationStatus
from credit_cards.models import CreditCard

IMPORT_FIELDS = set(REPORTABLE_FIELDS) | {"is_active", "verification_status"}


class Command(BaseCommand):
    help = (
        "Upsert cards from a JSON file (as written by export_verified_cards), "
        "matching by bank name + card name; verification_status comes from the file"
    )

    def add_arguments(self, parser):
        parser.add_argument("path", help="Input JSON file path")

    @transaction.atomic
    def handle(self, *args, **options):
        """Create or update each card in the file; any invalid row aborts the import."""
        with open(options["path"], encoding="utf-8") as handle:
            rows = json.load(handle)
        if not isinstance(rows, list):
            raise CommandError("Expected a JSON list of card objects")

        for index, row in enumerate(rows):
            bank_name = row.get("bank")
            name = row.get("name")
            unknown = set(row) - IMPORT_FIELDS - {"bank"}
            if not bank_name or not name or unknown:
                raise CommandError(
                    f"Row {index}: needs 'bank' and 'name' and only known fields "
                    f"(unknown: {sorted(unknown)})"
                )
            defaults = {k: v for k, v in row.items() if k not in {"bank", "name"}}
            if defaults.get("verification_status") == VerificationStatus.VERIFIED:
                defaults["verified_at"] = timezone.now()
            bank, _ = Bank.objects.get_or_create(name=bank_name)
            try:
                card, _ = CreditCard.objects.update_or_create(
                    bank=bank, name=name, defaults=defaults
                )
                card.full_clean()
            except ValidationError as exc:
                raise CommandError(f"Row {index} ({bank_name} / {name}): {exc}") from exc
        self.stdout.write(f"Imported {len(rows)} cards")
