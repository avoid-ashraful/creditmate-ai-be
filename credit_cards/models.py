from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from banks.models import Bank
from common.models import Audit


class CreditCard(Audit):
    """Model representing a credit card product."""

    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="credit_cards")
    name = models.CharField(max_length=255)
    annual_fee = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    interest_rate_apr = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    lounge_access_international = models.PositiveIntegerField(default=0)
    lounge_access_domestic = models.PositiveIntegerField(default=0)
    cash_advance_fee = models.CharField(max_length=255, blank=True, default="")
    late_payment_fee = models.CharField(max_length=255, blank=True, default="")
    annual_fee_waiver_policy = models.JSONField(blank=True, null=True)
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
        """Check if card has any lounge access."""
        return self.lounge_access_international > 0 or self.lounge_access_domestic > 0

    @property
    def total_lounge_access(self):
        """Return total lounge access count."""
        return self.lounge_access_international + self.lounge_access_domestic

    @property
    def has_annual_fee(self):
        """Check if card has annual fee."""
        return self.annual_fee > 0
