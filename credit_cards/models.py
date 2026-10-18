from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from banks.models import Bank
from common.models import Audit
from credit_cards.constants import CardNetwork, VerificationStatus
from credit_cards.lounge import card_has_lounge_access, direction_has_access


class CreditCardQuerySet(models.QuerySet):
    """Queryset helpers for credit cards."""

    def public(self):
        """Return only cards visible to anonymous users.

        Returns
        -------
        CreditCardQuerySet
            Active cards whose data has been verified by staff.
        """
        return self.filter(
            is_active=True, verification_status=VerificationStatus.VERIFIED
        )


class CreditCard(Audit):
    """Model representing a credit card product.

    This model stores comprehensive information about credit card products
    offered by banks in Bangladesh, including fees, interest rates,
    benefits, and features extracted from various data sources.
    """

    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="credit_cards")
    name = models.CharField(max_length=255)
    annual_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    annual_fee_waiver_policy = models.JSONField(blank=True, null=True)
    interest_rate_apr = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    lounge_access_international = models.CharField(
        max_length=1000, blank=True, default=""
    )
    lounge_access_domestic = models.CharField(max_length=1000, blank=True, default="")
    lounge_access_condition = models.CharField(max_length=500, blank=True, default="")
    cash_advance_fee = models.CharField(max_length=255, blank=True, default="")
    late_payment_fee = models.CharField(max_length=255, blank=True, default="")
    reward_points_policy = models.TextField(blank=True, default="")
    additional_features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    source_url = models.URLField(max_length=500, blank=True, default="")
    apply_url = models.URLField(max_length=500, blank=True, default="")
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
        related_name="verified_credit_cards",
    )
    card_network = models.CharField(
        max_length=20, choices=CardNetwork.choices, blank=True, default=""
    )
    is_islamic = models.BooleanField(default=False)
    is_dual_currency = models.BooleanField(null=True, blank=True)
    min_monthly_income = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum monthly income in BDT",
    )
    supplementary_card_fee = models.CharField(max_length=255, blank=True, default="")
    foreign_transaction_fee = models.CharField(max_length=255, blank=True, default="")

    objects = CreditCardQuerySet.as_manager()

    class Meta:
        ordering = ["bank__name", "name"]
        unique_together = ["bank", "name"]
        db_table = "credit_cards_creditcard"

    def __str__(self):
        return f"{self.bank.name} - {self.name}"

    @property
    def is_public(self):
        """Return True when anonymous users may see this card."""
        return self.is_active and self.verification_status == VerificationStatus.VERIFIED

    @property
    def has_lounge_access(self):
        """Check if card has any lounge access.

        Parameters
        ----------
        None

        Returns
        -------
        bool or None
            True if either direction grants lounge access, False if both
            directions state there is none, and None if the card's lounge
            access is unknown. See ``credit_cards.lounge`` for the rules.
        """
        return card_has_lounge_access(
            self.lounge_access_international, self.lounge_access_domestic
        )

    @property
    def lounge_access_summary(self):
        """Return summary of lounge access benefits.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Formatted string summarizing the directions that grant access.
            Returns 'No lounge access' when both directions are a known
            none, and 'Lounge access not specified' when the value is unknown.
        """
        access_list = []
        if direction_has_access(self.lounge_access_international):
            access_list.append(
                f"International: {self.lounge_access_international.strip()}"
            )
        if direction_has_access(self.lounge_access_domestic):
            access_list.append(f"Domestic: {self.lounge_access_domestic.strip()}")
        if access_list:
            return "; ".join(access_list)
        if self.has_lounge_access is False:
            return "No lounge access"
        return "Lounge access not specified"

    @property
    def has_annual_fee(self):
        """Check if card has annual fee.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            True if card has an annual fee greater than 0, False otherwise
        """
        return self.annual_fee is not None and self.annual_fee > 0


class CreditCardFieldHistory(Audit):
    """A meaningful change to a tracked CreditCard field."""

    card = models.ForeignKey(
        CreditCard,
        on_delete=models.CASCADE,
        related_name="field_history",
        db_column="credit_card_id",
    )
    field_name = models.CharField(max_length=100)
    old_value = models.JSONField(null=True)
    new_value = models.JSONField(null=True)

    class Meta:
        ordering = ["-created", "-id"]
        indexes = [models.Index(fields=["card", "created", "-id"])]
        db_table = "credit_cards_creditcardfieldhistory"
