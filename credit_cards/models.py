from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from banks.models import Bank
from common.models import Audit


class BenefitCategory(models.Model):
    """Model representing a benefit category for credit cards.

    Benefit categories are predefined types of merchant rewards aligned
    with ISO 18245 Merchant Category Codes (MCC) where applicable.
    Examples: Restaurant, Healthcare, Shopping, Travel, Fuel, Entertainment.
    """

    CATEGORY_CHOICES = [
        ("RESTAURANT", "Restaurant & Dining"),
        ("HEALTHCARE", "Healthcare & Hospital"),
        ("SHOPPING", "Shopping & Retail"),
        ("TRAVEL", "Travel & Transportation"),
        ("FUEL", "Fuel & Gas Stations"),
        ("ENTERTAINMENT", "Entertainment & Recreation"),
        ("GROCERY", "Grocery & Supermarket"),
        ("ONLINE", "Online Shopping"),
        ("UTILITIES", "Utilities & Bills"),
        ("EDUCATION", "Education & Learning"),
        ("OTHER", "Other Benefits"),
    ]

    name = models.CharField(max_length=100, unique=True)
    category_type = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="OTHER"
    )
    description = models.TextField(blank=True)
    mcc_codes = models.JSONField(
        default=list,
        blank=True,
        help_text="List of Merchant Category Codes (MCC) aligned with this category",
    )
    icon = models.CharField(max_length=50, blank=True, help_text="Icon name or emoji")
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0, help_text="Order for UI display")

    class Meta:
        verbose_name = "Benefit Category"
        verbose_name_plural = "Benefit Categories"
        ordering = ["display_order", "name"]
        db_table = "credit_cards_benefit_category"

    def __str__(self):
        return self.name


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

    # Enhanced filtering fields
    WAIVER_DIFFICULTY_CHOICES = [
        ("EASY", "Easy to Waive"),
        ("MODERATE", "Moderate Conditions"),
        ("DIFFICULT", "Difficult to Waive"),
        ("NOT_AVAILABLE", "No Waiver Available"),
        ("UNKNOWN", "Unknown"),
    ]

    SPENDING_TIER_CHOICES = [
        ("ENTRY", "Entry Level"),
        ("MID", "Mid-Range"),
        ("PREMIUM", "Premium"),
        ("ULTRA_PREMIUM", "Ultra Premium"),
    ]

    annual_fee_waiver_difficulty = models.CharField(
        max_length=20,
        choices=WAIVER_DIFFICULTY_CHOICES,
        default="UNKNOWN",
        help_text="AI-classified difficulty of waiving the annual fee",
    )
    spending_tier = models.CharField(
        max_length=20,
        choices=SPENDING_TIER_CHOICES,
        default="MID",
        help_text="Card tier classification",
    )
    best_for_tags = models.JSONField(
        default=list,
        blank=True,
        help_text="AI-generated use case tags (e.g., 'Cashback', 'Travel Miles')",
    )

    # Many-to-many relationship with benefit categories
    benefit_categories = models.ManyToManyField(
        BenefitCategory,
        through="CreditCardBenefit",
        related_name="credit_cards",
        blank=True,
    )

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


class CreditCardBenefit(models.Model):
    """Through model linking credit cards to benefit categories with metadata.

    This model stores the relationship between credit cards and benefit
    categories along with specific reward rates, conditions, and AI
    confidence scores for each benefit.
    """

    credit_card = models.ForeignKey(
        CreditCard, on_delete=models.CASCADE, related_name="card_benefits"
    )
    benefit_category = models.ForeignKey(
        BenefitCategory, on_delete=models.CASCADE, related_name="category_benefits"
    )
    reward_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Reward rate percentage (e.g., 5.0 for 5% cashback)",
    )
    reward_description = models.TextField(
        blank=True, help_text="Human-readable reward description"
    )
    conditions = models.TextField(
        blank=True, help_text="Conditions or restrictions for this benefit"
    )
    confidence_score = models.IntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="AI confidence score (0-100) for this classification",
    )
    is_primary = models.BooleanField(
        default=False, help_text="Whether this is a primary benefit of the card"
    )

    class Meta:
        unique_together = ["credit_card", "benefit_category"]
        ordering = ["-is_primary", "-reward_rate", "benefit_category__name"]
        db_table = "credit_cards_creditcard_benefit"
        verbose_name = "Credit Card Benefit"
        verbose_name_plural = "Credit Card Benefits"

    def __str__(self):
        return f"{self.credit_card.name} - {self.benefit_category.name}"
