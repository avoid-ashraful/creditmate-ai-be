"""Models for the bank-accounts vertical (savings + current accounts).

Design notes
------------
* ``AccountProduct`` mirrors the CreditCard/DepositProduct editorial
  lifecycle: only ``verified`` + active products are public, provenance
  (SOC + rate-sheet URLs, effective dates) is stored per product, and
  meaningful changes are written to ``AccountFieldHistory`` by signals.
* Savings interest is **slab-based**: ``rate_slabs`` is a JSON list of
  ``{"balance_min", "balance_max", "rate", "rate_max"?}`` and is never
  collapsed to a single headline rate — for many products the rate at a
  small balance is 0% while a larger balance earns more, and a single
  rate would misrepresent both. ``balance_max`` is exclusive; ``null``
  means open-ended. ``rate_max`` is present only when the source
  publishes a *range* (e.g. Bangladesh Bank's announced range for a bank
  that publishes no slab sheet of its own); the scenario engine always
  computes at ``rate`` (the lower bound).
* The savings maintenance fee is fixed by Bangladesh Bank on one slab
  schedule for every bank. Products store their maintenance slabs **as
  published in the bank's own schedule of charges** where the bank
  publishes one (variants may charge less). A bank that publishes no
  schedule of charges (DBBL, flagged ``bank_statement_evidence``)
  instead carries the BB regulator schedule that its published customer
  statement confirms, with that provenance disclosed on the product.
  :meth:`AccountProduct.maintenance_warnings` compares the stored slabs
  with the dated :class:`AccountFeeSchedule` config so an over-cap
  figure — a data error or a compliance breach — is flagged for review.
* Fees are stored **excluding VAT** (``fees_include_vat`` is False for
  SOC-sourced rows; SOCs quote fees exclusive of the 15% VAT). A fee of
  ``None`` means "not published in the sources we hold" — never zero.
* Islamic labelling is enforced in the schema like deposits: an Islamic
  product cannot be stored with ``rate_type='interest'``.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify

from bank_accounts.constants import (
    SCHEDULE_CURRENT_MAINTENANCE_CAP,
    SCHEDULE_SAVINGS_MAINTENANCE,
    AccountRateType,
    AccountSegment,
    AccountSourceKind,
    AccountType,
    ContractType,
    InterestBasis,
    PayoutFrequency,
)
from banks.models import Bank
from common.models import Audit
from credit_cards.constants import VerificationStatus


class AccountProductQuerySet(models.QuerySet):
    """Queryset helpers for account products."""

    def public(self):
        """Return only products visible to anonymous users."""
        return self.filter(
            is_active=True, verification_status=VerificationStatus.VERIFIED
        )


class AccountProduct(Audit):
    """A personal savings or current account product."""

    bank = models.ForeignKey(
        Bank, on_delete=models.CASCADE, related_name="account_products"
    )
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    variant_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="variants",
        null=True,
        blank=True,
        help_text="Base product when this row is a marketing/segment variant "
        "(e.g. a TARA version of a standard savings account). Variants are "
        "grouped under their base product in the API by default.",
    )
    segment = models.CharField(
        max_length=20, choices=AccountSegment.choices, default=AccountSegment.GENERAL
    )
    is_islamic = models.BooleanField(default=False)
    contract_type = models.CharField(
        max_length=20, choices=ContractType.choices, default=ContractType.INTEREST
    )
    rate_type = models.CharField(
        max_length=20,
        choices=AccountRateType.choices,
        default=AccountRateType.INTEREST,
    )

    # --- Return (interest / expected profit) -------------------------------
    rate_slabs = models.JSONField(
        default=list,
        blank=True,
        help_text='List of {"balance_min", "balance_max"|null, "rate", '
        '"rate_max"?} — balance_max exclusive, null = open-ended.',
    )
    rate_conditions_text = models.TextField(blank=True, default="")
    interest_basis = models.CharField(
        max_length=25, choices=InterestBasis.choices, default=InterestBasis.UNKNOWN
    )
    interest_payout_frequency = models.CharField(
        max_length=20,
        choices=PayoutFrequency.choices,
        default=PayoutFrequency.UNKNOWN,
    )
    min_balance_to_earn = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Published minimum balance before any interest/profit is "
        "earned (e.g. EBL Classic Savings: BDT 50,000). Null = not published.",
    )
    withdrawal_limit_for_interest = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Withdrawals per month at/above which no profit is paid "
        "(e.g. Islami Bank Mudaraba: 4). Null = no published rule.",
    )

    # --- Fees (BDT, as published, excluding VAT unless flagged) ------------
    maintenance_fee_slabs = models.JSONField(
        null=True,
        blank=True,
        help_text='List of {"balance_min", "balance_max"|null, "fee"} — '
        "half-yearly charge by average balance, as published in the bank's "
        "SOC. Bands are stored as printed: balance_max is the inclusive "
        "ceiling of the band. Null = not published in the sources we hold.",
    )
    maintenance_waiver_text = models.CharField(max_length=500, blank=True, default="")
    debit_card_fee_annual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    debit_card_first_year_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="When published separately from the steady-state annual fee.",
    )
    debit_card_waiver_text = models.CharField(max_length=500, blank=True, default="")
    debit_card_waiver_min_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Set only when the waiver is mechanical: annual card fee "
        "is waived in full at or above this average balance.",
    )
    debit_card_replacement_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    sms_fee_annual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    online_banking_fee_annual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    cheque_per_leaf = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    cheque_first_book_free = models.BooleanField(default=False)
    closure_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    statement_duplicate_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    balance_confirmation_extra_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Fee per additional balance-confirmation certificate "
        "beyond the two free per year.",
    )
    fees_include_vat = models.BooleanField(
        default=False,
        help_text="SOCs quote fees exclusive of the 15% VAT; statement-"
        "evidenced fees (DBBL) are VAT-inclusive in the source and are "
        "converted to ex-VAT at ingestion, so this stays False.",
    )
    fee_data_complete = models.BooleanField(
        default=False,
        help_text="True when every fee line used by the scenario engine "
        "(maintenance, debit card, SMS, online banking) is published.",
    )

    # --- Balance & opening --------------------------------------------------
    min_balance_required = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    opening_deposit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    cheque_book_available = models.BooleanField(default=True)
    debit_card_included = models.BooleanField(default=True)
    dormancy_terms = models.TextField(blank=True, default="")
    eligibility_notes = models.TextField(blank=True, default="")

    # --- Provenance ----------------------------------------------------------
    source_soc_url = models.URLField(max_length=500, blank=True, default="")
    source_rate_url = models.URLField(max_length=500, blank=True, default="")
    source_kind = models.CharField(
        max_length=30,
        choices=AccountSourceKind.choices,
        default=AccountSourceKind.BANK_SOC,
    )
    soc_effective_date = models.DateField(null=True, blank=True)
    rate_effective_date = models.DateField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)

    # --- Editorial lifecycle (mirrors CreditCard / DepositProduct) ----------
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.DRAFT,
        db_index=True,
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_account_products",
    )
    is_active = models.BooleanField(default=True)

    objects = AccountProductQuerySet.as_manager()

    class Meta:
        ordering = ["bank__name", "account_type", "name"]
        db_table = "bank_accounts_accountproduct"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(rate_type=AccountRateType.EXPECTED_PROFIT)
                    | models.Q(is_islamic=False)
                ),
                name="account_islamic_must_be_expected_profit",
            )
        ]

    def __str__(self):
        return f"{self.bank.name} - {self.name}"

    @property
    def is_public(self):
        return self.is_active and self.verification_status == VerificationStatus.VERIFIED

    def clean(self):
        super().clean()
        if self.is_islamic and self.rate_type != AccountRateType.EXPECTED_PROFIT:
            raise ValidationError(
                "Islamic products distribute expected profit (Mudaraba / "
                "Al-Wadiah); rate_type must be 'expected_profit', "
                "never 'interest'."
            )
        if (
            self.contract_type in (ContractType.MUDARABA, ContractType.AL_WADIAH)
            and self.rate_type != AccountRateType.EXPECTED_PROFIT
        ):
            raise ValidationError(
                "Mudaraba / Al-Wadiah contracts must use " "rate_type='expected_profit'."
            )
        if self.variant_of_id and self.variant_of_id == self.pk:
            raise ValidationError("A product cannot be a variant of itself.")
        if self.variant_of_id and self.variant_of.bank_id != self.bank_id:
            raise ValidationError("A variant must belong to the same bank.")

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.bank.name} {self.name}")[:280]
            slug = base or "account-product"
            candidate, n = slug, 2
            while (
                AccountProduct.objects.filter(slug=candidate).exclude(pk=self.pk).exists()
            ):
                candidate = f"{slug}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    # --- BB maintenance-schedule validation ---------------------------------
    def maintenance_warnings(self, on=None, params_by_key=None):
        """Compare stored maintenance slabs with the BB fee schedule.

        Returns a list of human-readable warnings. A warning fires when a
        stored half-yearly fee **exceeds the Bangladesh Bank cap** for the
        balance range it covers — either a data-entry error or a genuine
        breach; both need human review. Charging *less* than the cap is
        legitimate (student/digital variants do) and is not a warning.

        ``params_by_key`` lets a caller that validates many products
        (the admin changelist) pass schedule params it resolved once,
        instead of one query per product.
        """
        from bank_accounts.netvalue import fee_schedule_params, maintenance_cap_at

        warnings = []
        if not self.maintenance_fee_slabs:
            return warnings
        key = (
            SCHEDULE_SAVINGS_MAINTENANCE
            if self.account_type == AccountType.SAVINGS
            else SCHEDULE_CURRENT_MAINTENANCE_CAP
        )
        if params_by_key is not None and key in params_by_key:
            params = params_by_key[key]
        else:
            params = fee_schedule_params(key, on=on)
        if not params:
            return warnings
        for slab in self.maintenance_fee_slabs:
            fee = Decimal(str(slab.get("fee", "0")))
            # Check the cap at the slab's own floor and just below its
            # ceiling — the strictest points of the covered range.
            probes = [Decimal(str(slab.get("balance_min", "0")))]
            if slab.get("balance_max") is not None:
                probes.append(Decimal(str(slab["balance_max"])) - Decimal("0.01"))
            for probe in probes:
                cap = maintenance_cap_at(params, probe)
                if cap is not None and fee > cap:
                    warnings.append(
                        f"Maintenance fee BDT {fee} (half-yearly) at average "
                        f"balance BDT {probe} exceeds the Bangladesh Bank "
                        f"cap of BDT {cap}."
                    )
                    break
        return warnings


class AccountFieldHistory(Audit):
    """A meaningful change to a tracked product field.

    Mirrors DepositFieldHistory / CreditCardFieldHistory. ``rate_slabs``
    and ``maintenance_fee_slabs`` changes are recorded whole (the JSON
    list is the field).
    """

    product = models.ForeignKey(
        AccountProduct, on_delete=models.CASCADE, related_name="field_history"
    )
    field_name = models.CharField(max_length=100)
    old_value = models.JSONField(null=True)
    new_value = models.JSONField(null=True)

    class Meta:
        ordering = ["-created", "-id"]
        indexes = [models.Index(fields=["product", "created", "-id"])]
        db_table = "bank_accounts_accountfieldhistory"


class AccountFeeSchedule(Audit):
    """Dated Bangladesh Bank fee configuration — data, not code.

    Mirrors DepositTaxRule. The savings maintenance slab and the current
    account cap are set by BB instruction and can change; the scenario
    engine and the product validation read the latest row effective on
    the calculation date.
    """

    key = models.CharField(max_length=50, db_index=True)
    effective_from = models.DateField()
    params = models.JSONField(default=dict)
    description = models.TextField(blank=True, default="")
    source_note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["key", "-effective_from"]
        db_table = "bank_accounts_accountfeeschedule"
        unique_together = ["key", "effective_from"]

    def __str__(self):
        return f"{self.key} from {self.effective_from}"
