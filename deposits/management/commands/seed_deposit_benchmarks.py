"""Seed the dated tax rules and the four Sanchayapatra benchmark products.

Sanchayapatra is a government benchmark, not a bank: the products are
flagged ``is_benchmark`` and live under the pseudo-institution
"National Savings Directorate (Sanchayapatra)". Rates are the
July–December 2026 schedule (reviewed half-yearly). Idempotent.
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from credit_cards.constants import VerificationStatus
from deposits.constants import (
    Compounding,
    DepositKind,
    InstitutionType,
    PayoutStyle,
    RateType,
    SourceKind,
)
from deposits.models import DepositProduct, DepositRate, DepositTaxRule

NSD_NAME = "National Savings Directorate (Sanchayapatra)"
NSD_URL = "https://nationalsavings.gov.bd/"

TAX_RULES = [
    {
        "key": "bank_interest_source_tax",
        "effective_from": date(2024, 7, 1),
        "params": {"with_tin": "10", "without_tin": "15"},
        "description": "Source tax (AIT) on bank deposit interest/profit: "
        "10% for TIN holders, 15% without TIN.",
        "source_note": "Finance Act schedule; deducted at source by banks.",
    },
    {
        "key": "sanchayapatra_source_tax",
        "effective_from": date(2026, 2, 1),
        "params": {
            "threshold": "500000",
            "at_or_below_threshold": "5",
            "above_threshold": "10",
            "pensioner_exempt_up_to": "500000",
        },
        "description": "Sanchayapatra source tax: 5% when total investment "
        "is at most BDT 5 lakh, else 10%; pensioner certificates exempt "
        "up to BDT 5 lakh.",
        "source_note": "NBR clarification, February 2026.",
    },
]

# name, rate, tenure months, payout, eligibility, is_pensioner_scheme
SCHEMES = [
    (
        "5-Year Bangladesh Sanchayapatra",
        "11.83",
        60,
        PayoutStyle.AT_MATURITY,
        "Any adult Bangladeshi citizen. TIN is mandatory above the "
        "prescribed thresholds and a tax return is required for purchases "
        "above BDT 5 lakh.",
        False,
    ),
    (
        "3-Monthly Profit Sanchayapatra",
        "11.82",
        36,
        PayoutStyle.QUARTERLY,
        "Any adult Bangladeshi citizen. Profit is paid every three months.",
        False,
    ),
    (
        "Paribar (Family) Sanchayapatra",
        "11.93",
        60,
        PayoutStyle.MONTHLY,
        "Women, persons with disabilities, and citizens aged 65+. "
        "Profit is paid monthly.",
        False,
    ),
    (
        "Pensioner Sanchayapatra",
        "11.98",
        60,
        PayoutStyle.QUARTERLY,
        "Retired government and autonomous-body employees only. Profit is "
        "paid quarterly.",
        True,
    ),
]


class Command(BaseCommand):
    help = "Seed deposit tax rules and Sanchayapatra benchmark products."

    def handle(self, *args, **options):
        for rule in TAX_RULES:
            obj, created = DepositTaxRule.objects.update_or_create(
                key=rule["key"],
                effective_from=rule["effective_from"],
                defaults={
                    "params": rule["params"],
                    "description": rule["description"],
                    "source_note": rule["source_note"],
                },
            )
            self.stdout.write(
                f"tax rule {obj.key}: {'created' if created else 'updated'}"
            )

        for name, rate, months, payout, eligibility, is_pensioner in SCHEMES:
            cap = Decimal("10000000") if is_pensioner else Decimal("5000000")
            product, created = DepositProduct.objects.update_or_create(
                slug=_slug(name),
                defaults={
                    "bank": None,
                    "institution_name": NSD_NAME,
                    "institution_type": InstitutionType.GOVERNMENT_SCHEME,
                    "kind": DepositKind.SCHEME,
                    "name": name,
                    "rate_type": RateType.INTEREST,
                    "is_islamic": False,
                    "is_benchmark": True,
                    "is_pensioner_scheme": is_pensioner,
                    "payout_style": payout,
                    "tenures_months": [months],
                    "compounding": Compounding.AT_MATURITY,
                    "investment_cap": cap,
                    "joint_cap": Decimal("10000000"),
                    "eligibility_notes": eligibility,
                    "premature_encashment_terms": (
                        "No profit if encashed within 1 year; reduced rates "
                        "per completed year thereafter (published NSD table)."
                    ),
                    "source_url": NSD_URL,
                    "source_kind": SourceKind.NSD,
                    "rate_effective_date": date(2026, 7, 1),
                    "verification_status": VerificationStatus.VERIFIED,
                    "verified_at": timezone.now(),
                },
            )
            DepositRate.objects.update_or_create(
                product=product,
                tenure_months_min=months,
                tenure_months_max=months,
                amount_min=Decimal("0"),
                amount_max=None,
                defaults={
                    "rate_min": Decimal(rate),
                    "rate_max": Decimal(rate),
                    "note": "Headline (first-slab) rate, July–December 2026 "
                    "schedule. Rates step down on holdings above ~BDT 7.5 lakh.",
                },
            )
            self.stdout.write(
                f"sanchayapatra {name}: {'created' if created else 'updated'}"
            )


def _slug(name):
    from django.utils.text import slugify

    return slugify(f"{NSD_NAME} {name}")[:280]
