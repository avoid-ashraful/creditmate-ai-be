from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from banks.models import Bank
from common.models import Audit


class CreditCard(Audit):
    """Model representing a credit card product.

    This model stores comprehensive information about credit card products
    offered by banks in Bangladesh, including fees, interest rates,
    benefits, and features extracted from various data sources.
    """

    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="credit_cards")
    name = models.CharField(max_length=255)
    annual_fee = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    annual_fee_waiver_policy = models.JSONField(blank=True, null=True)
    interest_rate_apr = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    lounge_access_international = models.CharField(max_length=255, blank=True, default="")
    lounge_access_domestic = models.CharField(max_length=255, blank=True, default="")
    lounge_access_condition = models.CharField(max_length=500, blank=True, default="")
    cash_advance_fee = models.CharField(max_length=255, blank=True, default="")
    late_payment_fee = models.CharField(max_length=255, blank=True, default="")
    reward_points_policy = models.TextField(blank=True, default="")
    additional_features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["bank__name", "name"]
        unique_together = ["bank", "name"]
        db_table = "credit_cards_creditcard"

    def __str__(self):
        return f"{self.bank.name} - {self.name}"

    @property
    def has_lounge_access(self):
        """Check if card has any lounge access.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            True if card has either international or domestic lounge access,
            False otherwise
        """
        return bool(self.lounge_access_international.strip()) or bool(
            self.lounge_access_domestic.strip()
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
            Formatted string summarizing all lounge access benefits,
            or 'No lounge access' if none available
        """
        access_list = []
        if self.lounge_access_international.strip():
            access_list.append(f"International: {self.lounge_access_international}")
        if self.lounge_access_domestic.strip():
            access_list.append(f"Domestic: {self.lounge_access_domestic}")
        return "; ".join(access_list) if access_list else "No lounge access"

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
        return self.annual_fee > 0
