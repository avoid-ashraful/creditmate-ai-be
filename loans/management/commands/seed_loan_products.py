"""Seed the hand-verified loan product catalogue.

Every product below was transcribed on 2026-11-04 from the lender's own
published pages / Annexure-A declared-rate disclosures / schedules of
charges (see loans/ingestion/catalogue.py, whose header cites the source
per lender). Nothing is invented: where a bank publishes no rate band on
the product page, the product carries its Annexure-A band or falls back
to the Bangladesh Bank lending-chart band at read time, labelled as such.

Idempotent: products are updated in place by slug.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from loans.ingestion.catalogue import LOAN_PRODUCTS
from loans.models import LoanProduct


class Command(BaseCommand):
    help = "Seed the verified loan product catalogue (idempotent by slug)."

    @transaction.atomic
    def handle(self, *args, **options):
        created = updated = 0
        missing_banks = set()
        for entry in LOAN_PRODUCTS:
            data = dict(entry)
            bank_name = data.pop("bank_name", None)
            bank = None
            if bank_name:
                bank = Bank.objects.filter(name=bank_name).first()
                if bank is None:
                    missing_banks.add(bank_name)
            product, was_created = LoanProduct.objects.update_or_create(
                slug=data.pop("slug"),
                defaults={
                    **data,
                    "bank": bank,
                    "verification_status": VerificationStatus.VERIFIED,
                    "verified_at": timezone.now(),
                    "verified_by": "seed_loan_products (hand-verified transcription)",
                    "is_active": True,
                },
            )
            _ = product
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(
            f"Loan products: {created} created, {updated} updated "
            f"({created + updated} total)."
        )
        for name in sorted(missing_banks):
            self.stdout.write(
                self.style.WARNING(f"catalogue bank not found locally: {name}")
            )
