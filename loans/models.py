"""Models for loan comparison (Phase 2, vertical 2).

Design notes (from the Phase 2 roadmap §2/§3 and the loans research notes):

* Rates are BANDS, never fake point rates: Bangladeshi banks publish
  ranges (Bangladesh Bank chart, Annexure-A declared rates) or mechanisms
  (base rate + margin, spread over deposit rate) — almost never a single
  price on a product page. ``rate_min``/``rate_max`` hold the product's own
  published band; when a product publishes no band, the bank-level band
  from the BB lending chart (``LoanChartBand``) is the provenance-labelled
  fallback at read time. Products priced purely by formula (spread over a
  deposit rate) carry ``spread_over_deposit_rate`` and no band.
* Islamic products are investments/financings: their rate is an EXPECTED
  PROFIT rate and is never rendered as "interest" (see ``rate_label``).
* BHBFC (government housing finance) charges SIMPLE interest, unlike the
  amortising EMI convention everywhere else — modelled explicitly with
  ``uses_simple_interest``.
* Provenance mirrors deposits/cards: product-level source fields plus a
  field-history table; only VERIFIED + active products are public.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from banks.models import Bank
from common.models import Audit
from credit_cards.constants import VerificationStatus

from .constants import (
    ChartCategory,
    CollateralType,
    DisbursementMode,
    IncomeMetric,
    LenderType,
    LoanType,
    RateSource,
    RateType,
    ShariahMode,
)

#: Fields whose changes are recorded in LoanFieldHistory (mirrors the
#: deposits tracked-field list, adapted to loan terms).
TRACKED_FIELDS = (
    "name",
    "rate_min",
    "rate_max",
    "rate_type",
    "amount_min_bdt",
    "amount_max_bdt",
    "tenure_min_months",
    "tenure_max_months",
    "ltv_percent",
    "processing_fee_percent",
    "processing_fee_cap_bdt",
    "early_settlement_percent",
    "partial_prepayment_percent",
    "is_active",
    "verification_status",
)


class LoanProductQuerySet(models.QuerySet):
    def public(self):
        """Only active + verified products are ever public."""
        return self.filter(
            is_active=True,
            verification_status=VerificationStatus.VERIFIED,
        )


class LoanProduct(Audit):
    """A named retail loan product from a bank, NBFI or BHBFC."""

    bank = models.ForeignKey(
        Bank,
        on_delete=models.CASCADE,
        related_name="loan_products",
        null=True,
        blank=True,
        help_text="Null for lenders outside the bank catalogue (IDLC, BHBFC).",
    )
    institution_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Display name used when the lender is not a catalogue bank.",
    )
    lender_type = models.CharField(
        max_length=10, choices=LenderType.choices, default=LenderType.BANK
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)

    loan_type = models.CharField(max_length=30, choices=LoanType.choices)
    segment_tags = models.JSONField(default=list, blank=True)
    purpose_tags = models.JSONField(default=list, blank=True)

    is_islamic = models.BooleanField(default=False)
    shariah_mode = models.CharField(
        max_length=20, choices=ShariahMode.choices, blank=True
    )

    # --- Rate (band) -------------------------------------------------------
    rate_min = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Lower end of the published annual rate band (%).",
    )
    rate_max = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Upper end of the published annual rate band (%).",
    )
    rate_type = models.CharField(
        max_length=20, choices=RateType.choices, default=RateType.UNKNOWN
    )
    rate_basis_text = models.TextField(
        blank=True,
        help_text="How the rate is set, e.g. base rate + margin methodology.",
    )
    rate_source = models.CharField(
        max_length=25, choices=RateSource.choices, default=RateSource.NONE
    )
    spread_over_deposit_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="For formula-priced loans: % added to the lien deposit's rate.",
    )
    uses_simple_interest = models.BooleanField(
        default=False,
        help_text="BHBFC-style simple interest instead of amortising EMI.",
    )

    # --- Amount & tenure ---------------------------------------------------
    amount_min_bdt = models.BigIntegerField(null=True, blank=True)
    amount_max_bdt = models.BigIntegerField(null=True, blank=True)
    amount_notes = models.TextField(blank=True)
    tenure_min_months = models.PositiveIntegerField(null=True, blank=True)
    tenure_max_months = models.PositiveIntegerField(null=True, blank=True)
    grace_period_months = models.PositiveIntegerField(null=True, blank=True)

    # --- Loan-to-value ------------------------------------------------------
    ltv_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum loan share of the asset/deposit value (%).",
    )

    # --- Fees (percentages are of loan amount / outstanding as published) --
    processing_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    processing_fee_percent_max = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Upper end when the bank publishes a processing-fee range.",
    )
    processing_fee_cap_bdt = models.BigIntegerField(null=True, blank=True)
    processing_fee_notes = models.TextField(blank=True)
    early_settlement_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    early_settlement_notes = models.TextField(blank=True)
    partial_prepayment_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    partial_prepayment_rules = models.TextField(blank=True)
    penal_charge_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    penal_charge_notes = models.TextField(blank=True)
    supervision_charge_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    # --- Eligibility ---------------------------------------------------------
    min_income_by_segment = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"salaried": 30000, "business": 50000} — monthly BDT.',
    )
    income_metric = models.CharField(
        max_length=10, choices=IncomeMetric.choices, default=IncomeMetric.GROSS
    )
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age_at_maturity = models.PositiveIntegerField(null=True, blank=True)
    experience_requirements = models.JSONField(default=dict, blank=True)
    guarantor_required = models.BooleanField(default=False)
    guarantor_count = models.PositiveIntegerField(null=True, blank=True)
    guarantor_rules = models.TextField(blank=True)
    collateral_type = models.CharField(
        max_length=20, choices=CollateralType.choices, default=CollateralType.NONE
    )
    collateral_rules = models.TextField(blank=True)
    dbr_max_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    documents_checklist = models.JSONField(default=list, blank=True)

    # --- Structure -----------------------------------------------------------
    disbursement_mode = models.CharField(
        max_length=15, choices=DisbursementMode.choices, blank=True
    )
    joint_application_allowed = models.BooleanField(default=False)
    insurance_required = models.BooleanField(default=False)
    insurance_bundled = models.BooleanField(default=False)
    insurance_notes = models.TextField(blank=True)
    regulatory_flags = models.JSONField(default=list, blank=True)

    # --- Type-specific: personal --------------------------------------------
    unsecured_max_bdt = models.BigIntegerField(null=True, blank=True)
    income_multiple_max = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    secured_by = models.CharField(max_length=255, blank=True)

    # --- Type-specific: secured against deposit ------------------------------
    deposit_type = models.CharField(max_length=255, blank=True)
    ltv_of_deposit_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    # --- Type-specific: home ---------------------------------------------------
    property_types = models.JSONField(default=list, blank=True)
    max_amount_by_purpose = models.JSONField(default=dict, blank=True)
    takeover_allowed = models.BooleanField(default=False)
    nrb_eligible = models.BooleanField(default=False)
    registration_cost_included = models.BooleanField(default=False)

    # --- Type-specific: car -----------------------------------------------------
    vehicle_conditions = models.JSONField(default=list, blank=True)
    ltv_by_vehicle_type = models.JSONField(default=dict, blank=True)
    brta_registration_required = models.BooleanField(default=False)

    # --- Provenance & lifecycle (mirrors deposits) ------------------------------
    source_url = models.URLField(max_length=1000, blank=True)
    source_kind = models.CharField(max_length=50, blank=True)
    source_effective_date = models.DateField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.CharField(max_length=255, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.DRAFT,
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = LoanProductQuerySet.as_manager()

    class Meta:
        ordering = ["bank__name", "institution_name", "name"]
        indexes = [
            models.Index(fields=["loan_type", "verification_status", "is_active"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return f"{self.lender_display_name} — {self.name}"

    @property
    def lender_display_name(self):
        return self.bank.name if self.bank_id else self.institution_name

    @property
    def rate_label(self):
        """Islamic products are priced in EXPECTED PROFIT, never interest."""
        return "expected_profit" if self.is_islamic else "interest"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.lender_display_name} {self.name}")[:280]
            slug = base
            counter = 2
            while LoanProduct.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.bank_id and not self.institution_name:
            raise ValidationError("Either a bank or an institution_name is required.")
        if (
            self.rate_min is not None
            and self.rate_max is not None
            and self.rate_min > self.rate_max
        ):
            raise ValidationError("rate_min cannot exceed rate_max.")
        if (
            self.amount_min_bdt is not None
            and self.amount_max_bdt is not None
            and self.amount_min_bdt > self.amount_max_bdt
        ):
            raise ValidationError("amount_min_bdt cannot exceed amount_max_bdt.")
        if (
            self.tenure_min_months is not None
            and self.tenure_max_months is not None
            and self.tenure_min_months > self.tenure_max_months
        ):
            raise ValidationError("tenure_min_months cannot exceed tenure_max_months.")
        if self.spread_over_deposit_rate is not None:
            self.rate_type = RateType.FORMULA_SPREAD


class LoanFieldHistory(Audit):
    """Field-level change history for a loan product (mirrors deposits)."""

    product = models.ForeignKey(
        LoanProduct, on_delete=models.CASCADE, related_name="field_history"
    )
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    source = models.CharField(max_length=50, blank=True)
    changed_by = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["product", "field_name", "-created"])]

    def __str__(self):
        return f"{self.product_id}:{self.field_name} {self.old_value} -> {self.new_value}"


class LendingChartSnapshot(Audit):
    """One parsed edition of the Bangladesh Bank lending chart.

    BB serves only the current edition, so every edition is snapshotted
    (raw HTML + raw parsed rows) before it is gone.
    """

    edition_label = models.CharField(max_length=50, unique=True)
    edition_month = models.DateField(null=True, blank=True)
    source_url = models.URLField(max_length=1000)
    raw_html = models.TextField(blank=True)
    raw_rows = models.JSONField(default=list, blank=True)
    anomalies = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"Lending chart {self.edition_label}"


class LoanChartBand(Audit):
    """Bank-level rate band from the BB lending chart (fallback band store).

    A product's displayed band prefers its own published band; this is the
    provenance-labelled fallback (precedence: BB chart > nothing — the
    chart is regulator-published, so it auto-verifies).
    """

    bank = models.ForeignKey(
        Bank,
        on_delete=models.CASCADE,
        related_name="loan_chart_bands",
        null=True,
        blank=True,
    )
    institution_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=20, choices=ChartCategory.choices)
    rate_min = models.DecimalField(max_digits=6, decimal_places=2)
    rate_max = models.DecimalField(max_digits=6, decimal_places=2)
    edition_label = models.CharField(max_length=50, blank=True)
    edition_month = models.DateField(null=True, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)

    class Meta:
        ordering = ["bank__name", "institution_name", "category"]
        constraints = [
            models.UniqueConstraint(
                fields=["bank", "category"],
                condition=models.Q(bank__isnull=False),
                name="uniq_chart_band_bank_category",
            ),
            models.UniqueConstraint(
                fields=["institution_name", "category"],
                condition=models.Q(bank__isnull=True),
                name="uniq_chart_band_institution_category",
            ),
        ]

    def __str__(self):
        name = self.bank.name if self.bank_id else self.institution_name
        return f"{name} {self.category}: {self.rate_min}-{self.rate_max}"

    @property
    def lender_display_name(self):
        return self.bank.name if self.bank_id else self.institution_name


class RegulatoryCap(Audit):
    """Dated regulatory rules (BB circular ceilings) — data, not code.

    Mirrors deposits' ``DepositTaxRule``: rows take effect from a date and
    carry their circular reference, so a ceiling change is a data edit,
    not a deploy. ``params`` holds the structured values per key.
    """

    key = models.CharField(max_length=100)
    effective_from = models.DateField()
    params = models.JSONField(default=dict)
    description = models.TextField(blank=True)
    source_note = models.TextField(blank=True)

    class Meta:
        ordering = ["key", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["key", "effective_from"], name="uniq_reg_cap_key_date"
            )
        ]

    def __str__(self):
        return f"{self.key} from {self.effective_from}"

    @classmethod
    def latest(cls, key, on=None):
        """Most recent rule for ``key`` effective on/before ``on`` (today)."""
        from django.utils import timezone

        on = on or timezone.localdate()
        return (
            cls.objects.filter(key=key, effective_from__lte=on)
            .order_by("-effective_from")
            .first()
        )
