"""Seed DPS / named-scheme products hand-verified from bank publications.

V1 launch data transcribed from the banks' own published pages/sheets
(research notes: ~/workspace/research_notes/creditmate-phase2-deposits):

* DBBL Deposit Plus / CHESS / Millionaire — maturity tables fetched from
  dutchbanglabank.com on 2026-11-04. The Deposit Plus table is reproduced
  exactly by 9.50% annuity-due monthly compounding; CHESS's table implies
  9.70% (marked derived).
* BRAC DPS — ALCO rate sheet effective 1 Oct 2026 (7.00% at 1 year rising
  to 8.25% at 10 years; only the published anchor tenures are stored).
* EBL Confidence — the bank publishes maturity values, not a rate; the
  stored rates are derived per tenure from its published table and are
  flagged ``is_derived``.
* Islami Bank MTDR — provisional profit 10.00% (12-month, eff. 01.01.2026).
* City Bank term deposit — bank's published rates page w.e.f. 01-Nov-2026
  (3-month, amount slabs).

Idempotent (update_or_create by slug).
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from deposits.constants import (
    Compounding,
    DepositKind,
    PayoutStyle,
    RateType,
    SourceKind,
)
from deposits.models import DepositProduct, DepositRate

FETCH_DATE = date(2026, 11, 4)


def _rate(
    product,
    t_min,
    t_max,
    rate_min,
    rate_max=None,
    amount_min="0",
    amount_max=None,
    derived=False,
    note="",
):
    DepositRate.objects.update_or_create(
        product=product,
        tenure_months_min=t_min,
        tenure_months_max=t_max,
        amount_min=Decimal(amount_min),
        amount_max=Decimal(amount_max) if amount_max is not None else None,
        defaults={
            "rate_min": Decimal(rate_min),
            "rate_max": Decimal(rate_max if rate_max is not None else rate_min),
            "is_derived": derived,
            "note": note,
        },
    )


def _product(bank_name, **defaults):
    bank = Bank.objects.get(name=bank_name)
    slug = slugify(f"{bank.name} {defaults['name']}")[:280]
    product, created = DepositProduct.objects.update_or_create(
        slug=slug, defaults={"bank": bank, **defaults}
    )
    return product, created


COMMON = {
    "verification_status": VerificationStatus.VERIFIED,
    "is_islamic": False,
    "rate_type": RateType.INTEREST,
}


class Command(BaseCommand):
    help = "Seed hand-verified DPS and named deposit schemes for top banks."

    def handle(self, *args, **options):
        now = timezone.now()
        made = []

        # --- DBBL Deposit Plus Scheme (DPS) -------------------------------
        p, c = _product(
            "Dutch-Bangla Bank PLC",
            name="Deposit Plus Scheme (DPS)",
            kind=DepositKind.DPS,
            min_instalment=Decimal("500"),
            max_instalment=Decimal("50000"),
            instalment_step=Decimal("500"),
            tenures_months=[36, 60, 96, 120],
            compounding=Compounding.MONTHLY,
            loan_against_percent=Decimal("90"),
            loan_spread_pp=Decimal("3"),
            premature_encashment_terms=(
                "Premature encashment follows the bank's scheme rules; a "
                "loan/overdraft of up to 90% of the deposited amount is "
                "available at the scheme rate + 3% instead."
            ),
            source_url="https://www.dutchbanglabank.com/personal-banking/future-line.html",
            source_kind=SourceKind.BANK_PRODUCT_PAGE,
            rate_effective_date=FETCH_DATE,
            verified_at=now,
            **COMMON,
        )
        _rate(
            p,
            36,
            120,
            "9.50",
            amount_min="500",
            amount_max="50000",
            note="Published scheme rate; the bank's maturity table "
            "(BDT 500/month -> 20,897 at 3y, 100,328 at 10y) is "
            "reproduced exactly by this rate.",
        )
        made.append(("DBBL Deposit Plus", c))

        # --- DBBL CHESS ----------------------------------------------------
        p, c = _product(
            "Dutch-Bangla Bank PLC",
            name="Children Education Savings Scheme (CHESS)",
            kind=DepositKind.DPS,
            segment="children",
            min_instalment=Decimal("500"),
            max_instalment=Decimal("50000"),
            instalment_step=Decimal("500"),
            tenures_months=[36, 60, 96, 120],
            compounding=Compounding.MONTHLY,
            source_url="https://www.dutchbanglabank.com/personal-banking/future-line.html",
            source_kind=SourceKind.BANK_PRODUCT_PAGE,
            rate_effective_date=FETCH_DATE,
            verified_at=now,
            **COMMON,
        )
        _rate(
            p,
            36,
            120,
            "9.70",
            amount_min="500",
            amount_max="50000",
            derived=True,
            note="Derived from the bank's published maturity table "
            "(BDT 500/month -> 20,964 at 3y); reproduces every published "
            "tenor within BDT 1.",
        )
        made.append(("DBBL CHESS", c))

        # --- DBBL Millionaire Deposit Scheme -------------------------------
        p, c = _product(
            "Dutch-Bangla Bank PLC",
            name="Millionaire Deposit Scheme",
            kind=DepositKind.DPS,
            payout_style=PayoutStyle.TARGET_AMOUNT,
            tenures_months=[36, 48, 60, 72, 84, 96, 108, 120],
            compounding=Compounding.MONTHLY,
            eligibility_notes=(
                "Target-based: save toward BDT 10 lakh at maturity. "
                "Published monthly instalments for the 10-lakh target: "
                "BDT 23,927 (3y), 17,072 (4y), 12,983 (5y), 10,278 (6y), "
                "8,362 (7y), 6,940 (8y), 5,847 (9y), 4,984 (10y). "
                "Maturity figure is before tax."
            ),
            source_url="https://www.dutchbanglabank.com/personal-banking/future-line.html",
            source_kind=SourceKind.BANK_PRODUCT_PAGE,
            rate_effective_date=FETCH_DATE,
            verified_at=now,
            **COMMON,
        )
        _rate(
            p,
            36,
            120,
            "9.50",
            note="Same published scheme rate as Deposit Plus; instalments "
            "are set by the target table (see eligibility notes).",
        )
        made.append(("DBBL Millionaire", c))

        # --- BRAC Bank DPS ---------------------------------------------------
        p, c = _product(
            "BRAC Bank PLC",
            name="BRAC Bank DPS",
            kind=DepositKind.DPS,
            min_instalment=Decimal("500"),
            tenures_months=[12, 24, 36, 60, 84, 120],
            compounding=Compounding.MONTHLY,
            loan_against_percent=Decimal("90"),
            premature_encashment_terms=(
                "Per the Oct 2026 ALCO sheet: below 180 days no interest; "
                "180-360 days savings rate; above 360 days the contract "
                "rate minus 2%. DPS instalments earn an income-tax rebate "
                "on yearly instalments up to BDT 120,000."
            ),
            source_url="https://www.bracbank.com/",
            source_kind=SourceKind.BANK_RATE_SHEET,
            rate_effective_date=date(2026, 10, 1),
            verified_at=now,
            **COMMON,
        )
        _rate(p, 12, 12, "7.00", note="ALCO rate sheet effective 1 Oct 2026.")
        _rate(
            p,
            120,
            120,
            "8.25",
            note="ALCO rate sheet effective 1 Oct 2026. Intermediate "
            "tenures are published in the sheet's full table; only the "
            "researched anchor tenures are stored in v1.",
        )
        made.append(("BRAC DPS", c))

        # --- EBL Confidence --------------------------------------------------
        p, c = _product(
            "Eastern Bank PLC",
            name="EBL Confidence",
            kind=DepositKind.DPS,
            min_instalment=Decimal("500"),
            max_instalment=Decimal("20000"),
            tenures_months=[12, 24, 36, 60, 84, 120, 180],
            compounding=Compounding.MONTHLY,
            loan_against_percent=Decimal("90"),
            premature_encashment_terms=(
                "Closed before 1 year: no interest. Closed after 1 year "
                "but before 3 years: interest at the prevailing savings "
                "rate. Closed after 3 years: booked rate minus 2%."
            ),
            premature_encashment_rules=[
                {"min_months_held": 0, "rate_basis": "none"},
                {"min_months_held": 12, "rate_basis": "savings_rate"},
                {"min_months_held": 36, "rate_basis": "booked_rate_minus_pp", "pp": 2},
            ],
            source_url="https://www.ebl.com.bd/retail-deposit/EBL-Confidence",
            source_kind=SourceKind.BANK_PRODUCT_PAGE,
            rate_effective_date=FETCH_DATE,
            verified_at=now,
            **COMMON,
        )
        for months, rate in [
            (12, "7.370"),
            (24, "7.471"),
            (36, "7.496"),
            (60, "7.500"),
            (84, "7.248"),
            (120, "7.249"),
            (180, "7.250"),
        ]:
            _rate(
                p,
                months,
                months,
                rate,
                derived=True,
                note="Derived from the bank's published maturity table "
                "(bank publishes maturity values, not a headline rate).",
            )
        made.append(("EBL Confidence", c))

        # --- Islami Bank MTDR ------------------------------------------------
        p, c = _product(
            "Islami Bank Bangladesh Limited",
            name="Mudaraba Term Deposit Receipt (MTDR)",
            kind=DepositKind.FDR,
            is_islamic=True,
            rate_type=RateType.EXPECTED_PROFIT,
            tenures_months=[12],
            compounding=Compounding.ANNUAL,
            eligibility_notes=(
                "Mudaraba product: the rate is a provisional expected "
                "profit rate; the final rate is declared after year-end "
                "and payouts are adjusted."
            ),
            source_url="https://www.islamibankbd.com/deposit",
            source_kind=SourceKind.BANK_PRODUCT_PAGE,
            rate_effective_date=date(2026, 1, 1),
            verified_at=now,
            verification_status=VerificationStatus.VERIFIED,
        )
        _rate(
            p,
            12,
            12,
            "10.00",
            note="Provisional expected profit rate for the 12-month "
            "tenure, effective 01 Jan 2026.",
        )
        made.append(("Islami MTDR", c))

        # --- City Bank term deposit (published rates page) -------------------
        p, c = _product(
            "City Bank PLC",
            name="Term Deposit (published rates)",
            kind=DepositKind.FDR,
            tenures_months=[3],
            compounding=Compounding.ANNUAL,
            eligibility_notes=(
                "From the bank's published conventional deposit rates, "
                "w.e.f. 01-Nov-2026: 3-month term deposit. Top slabs reach "
                "7.50% (individual) / 8.00% (non-individual) at the largest "
                "amounts."
            ),
            source_url="https://www.citybankplc.com/gsi/conventional-banking-products",
            source_kind=SourceKind.BANK_RATES_PAGE,
            rate_effective_date=date(2026, 11, 1),
            verified_at=now,
            **COMMON,
        )
        _rate(
            p,
            3,
            3,
            "7.00",
            amount_min="0",
            amount_max="5000000",
            note="Below BDT 50 lakh, individual, 90 days.",
        )
        _rate(
            p,
            3,
            3,
            "7.50",
            amount_min="5000000",
            amount_max=None,
            note="BDT 50 lakh and above (individual).",
        )
        made.append(("City term deposit", c))

        for label, created in made:
            self.stdout.write(f"{label}: {'created' if created else 'updated'}")
