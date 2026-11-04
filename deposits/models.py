"""Models for the deposits vertical (FDR, DPS and named schemes).

Design notes
------------
* ``DepositProduct`` mirrors the CreditCard editorial lifecycle: only
  ``verified`` + active products are public, provenance (source URL, kind,
  effective date) is stored per product, and meaningful changes are written
  to ``DepositFieldHistory`` (by signals for product fields, explicitly by
  ingestion code for rate rows, which are child records).
* ``bank`` is nullable because two kinds of rows have no catalogue bank:
  the Sanchayapatra pseudo-institution (National Savings Directorate) and
  the few BB-chart banks missing from the card catalogue. Those rows carry
  ``institution_name`` instead.
* Islamic labelling is enforced in the schema: a product with
  ``is_islamic=True`` cannot be stored with ``rate_type='interest'``
  (CheckConstraint below, plus ``clean()`` for friendly errors).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify

from banks.models import Bank
from common.models import Audit
from credit_cards.constants import VerificationStatus
from deposits.constants import (
    ChartSource,
    Compounding,
    DepositKind,
    InstitutionType,
    PayoutStyle,
    RateType,
    SourceKind,
)


class DepositProductQuerySet(models.QuerySet):
    """Queryset helpers for deposit products."""

    def public(self):
        """Return only products visible to anonymous users."""
        return self.filter(
            is_active=True, verification_status=VerificationStatus.VERIFIED
        )


class DepositProduct(Audit):
    """A deposit product (FDR, DPS, monthly-benefit or named scheme)."""

    bank = models.ForeignKey(
        Bank,
        on_delete=models.CASCADE,
        related_name="deposit_products",
        null=True,
        blank=True,
    )
    institution_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name when the product has no catalogue bank "
        "(Sanchayapatra / National Savings Directorate, or a BB-chart bank "
        "missing from the bank catalogue).",
    )
    institution_type = models.CharField(
        max_length=20, choices=InstitutionType.choices, default=InstitutionType.BANK
    )
    kind = models.CharField(max_length=20, choices=DepositKind.choices)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    rate_type = models.CharField(
        max_length=20, choices=RateType.choices, default=RateType.INTEREST
    )
    is_islamic = models.BooleanField(default=False)
    is_generic = models.BooleanField(
        default=False,
        help_text="True for grid entries generated from the BB chart rather "
        "than a bank's own named scheme.",
    )
    is_benchmark = models.BooleanField(
        default=False,
        help_text="Government benchmark (Sanchayapatra): shown separately, "
        "never ranked among bank products.",
    )
    payout_style = models.CharField(
        max_length=20, choices=PayoutStyle.choices, default=PayoutStyle.AT_MATURITY
    )
    segment = models.CharField(max_length=50, blank=True, default="retail")
    min_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    max_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    min_instalment = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    max_instalment = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    instalment_step = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    tenures_months = models.JSONField(default=list, blank=True)
    compounding = models.CharField(
        max_length=20, choices=Compounding.choices, default=Compounding.ANNUAL
    )
    premature_encashment_terms = models.TextField(blank=True, default="")
    premature_encashment_rules = models.JSONField(default=list, blank=True)
    loan_against_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    loan_spread_pp = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    instalment_failure_penalty = models.CharField(max_length=255, blank=True, default="")
    insurance_bundled = models.BooleanField(default=False)
    insurance_note = models.CharField(max_length=255, blank=True, default="")
    eligibility_notes = models.TextField(blank=True, default="")
    investment_cap = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Per-person investment cap (Sanchayapatra: BDT 50 lakh).",
    )
    joint_cap = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    source_url = models.URLField(max_length=500, blank=True, default="")
    source_kind = models.CharField(
        max_length=20, choices=SourceKind.choices, default=SourceKind.BB_CHART
    )
    rate_effective_date = models.DateField(null=True, blank=True)
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
        related_name="verified_deposit_products",
    )
    is_active = models.BooleanField(default=True)

    objects = DepositProductQuerySet.as_manager()

    class Meta:
        ordering = ["institution_name", "bank__name", "name"]
        db_table = "deposits_depositproduct"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(rate_type=RateType.EXPECTED_PROFIT)
                    | models.Q(is_islamic=False)
                ),
                name="deposit_islamic_must_be_expected_profit",
            )
        ]

    def __str__(self):
        return f"{self.institution_display_name} - {self.name}"

    @property
    def institution_display_name(self):
        if self.bank_id:
            return self.bank.name
        return self.institution_name

    @property
    def is_public(self):
        return self.is_active and self.verification_status == VerificationStatus.VERIFIED

    def clean(self):
        super().clean()
        if self.is_islamic and self.rate_type != RateType.EXPECTED_PROFIT:
            raise ValidationError(
                "Islamic products distribute expected profit (Mudaraba); "
                "rate_type must be 'expected_profit', never 'interest'."
            )
        if not self.bank_id and not self.institution_name:
            raise ValidationError(
                "A deposit product needs either a bank or an institution_name."
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.institution_display_name} {self.name}")[:280]
            slug = base or "deposit-product"
            candidate, n = slug, 2
            while (
                DepositProduct.objects.filter(slug=candidate).exclude(pk=self.pk).exists()
            ):
                candidate = f"{slug}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class DepositRate(Audit):
    """One published rate cell: a tenure band × amount slab for a product.

    A published point rate is stored as ``rate_min == rate_max``; BB-chart
    ranges keep both ends. ``is_derived`` marks rates computed from a bank's
    published maturity table (the bank publishes maturity values, not a
    rate) so the UI can badge them honestly.
    """

    product = models.ForeignKey(
        DepositProduct, on_delete=models.CASCADE, related_name="rates"
    )
    tenure_months_min = models.PositiveIntegerField()
    tenure_months_max = models.PositiveIntegerField(
        null=True, blank=True, help_text="Null = open-ended band."
    )
    amount_min = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    amount_max = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    rate_min = models.DecimalField(max_digits=6, decimal_places=3)
    rate_max = models.DecimalField(max_digits=6, decimal_places=3)
    is_derived = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["tenure_months_min", "amount_min"]
        db_table = "deposits_depositrate"
        unique_together = [
            "product",
            "tenure_months_min",
            "tenure_months_max",
            "amount_min",
            "amount_max",
        ]

    def __str__(self):
        return (
            f"{self.product_id} {self.tenure_months_min}-"
            f"{self.tenure_months_max or '∞'}m @ {self.rate_min}-{self.rate_max}%"
        )

    def covers(self, months, amount):
        """True when this row applies to the given horizon and amount."""
        if months < self.tenure_months_min:
            return False
        if self.tenure_months_max is not None and months > self.tenure_months_max:
            return False
        if amount is not None:
            if amount < self.amount_min:
                return False
            if self.amount_max is not None and amount > self.amount_max:
                return False
        return True

    @property
    def tenure_span(self):
        if self.tenure_months_max is None:
            return 1200  # open-ended counts as least specific
        return self.tenure_months_max - self.tenure_months_min

    @property
    def amount_span(self):
        if self.amount_max is None:
            return Decimal("1000000000000")
        return self.amount_max - self.amount_min


class DepositFieldHistory(Audit):
    """A meaningful change to a tracked product field or rate row.

    Mirrors CreditCardFieldHistory. Rate changes are recorded with
    ``field_name`` of the form ``rate_<tenure_min>_<tenure_max>`` and
    old/new values of ``{"rate_min": ..., "rate_max": ...}`` (or null when
    a rate appears/disappears).
    """

    product = models.ForeignKey(
        DepositProduct, on_delete=models.CASCADE, related_name="field_history"
    )
    field_name = models.CharField(max_length=100)
    old_value = models.JSONField(null=True)
    new_value = models.JSONField(null=True)

    class Meta:
        ordering = ["-created", "-id"]
        indexes = [models.Index(fields=["product", "created", "-id"])]
        db_table = "deposits_depositfieldhistory"


class DepositChartSnapshot(Audit):
    """One fetched edition of a Bangladesh Bank announced-rate chart.

    The BB URLs serve only the current month, so every edition is stored
    (raw HTML + parsed rows) — this is what makes rate history derivable.
    """

    source = models.CharField(max_length=20, choices=ChartSource.choices)
    edition_label = models.CharField(
        max_length=50, help_text='As printed on the chart, e.g. "October, 2026".'
    )
    edition_month = models.DateField(help_text="First day of the edition month.")
    source_url = models.URLField(max_length=500)
    raw_html = models.TextField()
    raw_rows = models.JSONField(default=list)
    anomalies = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-edition_month", "source"]
        db_table = "deposits_depositchartsnapshot"
        unique_together = ["source", "edition_label"]


class DepositTaxRule(Audit):
    """Dated source-tax configuration — data, not code.

    Tax rules in Bangladesh flip with Finance Acts and NBR clarifications
    (the Sanchayapatra 5%/10% rule changed twice in ~13 months), so the
    maturity engine reads the latest rule effective on the calculation
    date instead of using constants scattered through the code.
    """

    key = models.CharField(max_length=50, db_index=True)
    effective_from = models.DateField()
    params = models.JSONField(default=dict)
    description = models.TextField(blank=True, default="")
    source_note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["key", "-effective_from"]
        db_table = "deposits_deposittaxrule"
        unique_together = ["key", "effective_from"]

    def __str__(self):
        return f"{self.key} from {self.effective_from}"
