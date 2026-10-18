"""Constants shared by the credit card models, crawler safety checks and API."""

from django.db import models

# Bangladesh Bank caps credit-card interest at 25% per annum.
MAX_INTEREST_RATE_APR = 25


class VerificationStatus(models.TextChoices):
    """Editorial state of a card; only ``verified`` cards are public."""

    DRAFT = "draft", "Draft"
    VERIFIED = "verified", "Verified"
    NEEDS_REVIEW = "needs_review", "Needs review"


class CardNetwork(models.TextChoices):
    """Payment network of a card."""

    VISA = "visa", "Visa"
    MASTERCARD = "mastercard", "Mastercard"
    AMEX = "amex", "American Express"
    UNIONPAY = "unionpay", "UnionPay"
    JCB = "jcb", "JCB"
    DINERS = "diners", "Diners Club"
    OTHER = "other", "Other"


# Card fields a user may report as incorrect and the crawler may propose
# changes to (``name`` is report-only: the crawler matches cards by name).
CRAWLED_FIELDS = (
    "annual_fee",
    "interest_rate_apr",
    "lounge_access_international",
    "lounge_access_domestic",
    "cash_advance_fee",
    "late_payment_fee",
    "annual_fee_waiver_policy",
    "reward_points_policy",
    "additional_features",
    "source_url",
    "apply_url",
    "card_network",
    "is_islamic",
    "is_dual_currency",
    "min_monthly_income",
    "supplementary_card_fee",
    "foreign_transaction_fee",
)
REPORTABLE_FIELDS = ("name", "lounge_access_condition") + CRAWLED_FIELDS

# Filter for counting a bank's publicly visible cards via the ``credit_cards``
# relation (mirrors ``CreditCardQuerySet.public``).
PUBLIC_BANK_CARD_Q = models.Q(
    credit_cards__is_active=True,
    credit_cards__verification_status=VerificationStatus.VERIFIED,
)
