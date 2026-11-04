"""Constants for the bank-accounts vertical (savings + current accounts).

The app is named ``bank_accounts`` because ``accounts`` is the existing
user-auth app. The API is exposed at ``/api/v1/account-products/``.
"""

from django.db import models


class AccountType(models.TextChoices):
    """Product class of a bank account."""

    SAVINGS = "savings", "Savings account"
    CURRENT = "current", "Current account"
    SND = "snd", "Special notice deposit (SND)"


class AccountSegment(models.TextChoices):
    """Audience segment a product is sold to.

    Salary/payroll products are B2B-priced (employer MOU) and are excluded
    from the default scenario ranking; they are listed and labelled.
    """

    GENERAL = "general", "General"
    WOMEN = "women", "Women"
    STUDENT = "student", "Student"
    SENIOR = "senior", "Senior citizen"
    SALARY = "salary", "Salary / payroll"
    NRB = "nrb", "NRB / Probashi"
    DIGITAL = "digital", "Digital"
    MINOR = "minor", "Minor"
    INCLUSION = "inclusion", "Financial inclusion"
    PREMIUM = "premium", "Premium"


class ContractType(models.TextChoices):
    """Shariah/contract basis of the account."""

    INTEREST = "interest", "Interest-bearing"
    MUDARABA = "mudaraba", "Mudaraba"
    AL_WADIAH = "al_wadiah", "Al-Wadiah"


class AccountRateType(models.TextChoices):
    """How a product's return must be labelled.

    Islamic (Mudaraba/Al-Wadiah) products distribute *expected profit*;
    they must never be rendered as "interest". Enforced again at the
    database level (see AccountProduct's CheckConstraint).
    """

    INTEREST = "interest", "Interest"
    EXPECTED_PROFIT = "expected_profit", "Expected profit"


class InterestBasis(models.TextChoices):
    """Balance basis on which interest/profit is calculated.

    ``unknown`` is an explicit state: the bank does not publish its basis
    in the sources we hold, and the scenario engine discloses the
    assumption it makes instead of silently picking one.
    """

    DAILY_BALANCE = "daily_balance", "Daily balance"
    DAY_END_BALANCE = "day_end_balance", "Day-end balance"
    LOWEST_MONTHLY = "lowest_monthly_balance", "Lowest monthly balance"
    MONTHLY_MINIMUM = "monthly_minimum", "Monthly minimum balance"
    MONTHLY_AVERAGE = "monthly_average", "Monthly average balance"
    DAILY_PRODUCT = "daily_product", "Daily product"
    UNKNOWN = "unknown", "Not published"


class PayoutFrequency(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    HALF_YEARLY = "half_yearly", "Half-yearly"
    ANNUALLY = "annually", "Annually"
    UNKNOWN = "unknown", "Not published"


class AccountSourceKind(models.TextChoices):
    BANK_SOC = "bank_soc", "Bank schedule of charges"
    BANK_RATE_SHEET = "bank_rate_sheet", "Bank rate sheet"
    BANK_PRODUCT_PAGE = "bank_product_page", "Bank product page"
    BANK_STATEMENT_EVIDENCE = (
        "bank_statement_evidence",
        "Published account statement evidence (SOC not public)",
    )
    BB_CHART = "bb_chart", "Bangladesh Bank announced-rate chart"


#: AccountProduct fields whose changes are written to AccountFieldHistory
#: by signals (mirrors deposits' TRACKED_PRODUCT_FIELDS).
TRACKED_PRODUCT_FIELDS = {
    "name",
    "segment",
    "rate_slabs",
    "interest_basis",
    "min_balance_to_earn",
    "maintenance_fee_slabs",
    "debit_card_fee_annual",
    "sms_fee_annual",
    "online_banking_fee_annual",
    "cheque_per_leaf",
    "closure_fee",
    "verification_status",
    "is_active",
}

#: Keys of AccountFeeSchedule rows (dated BB fee configuration).
SCHEDULE_SAVINGS_MAINTENANCE = "savings_maintenance"
SCHEDULE_CURRENT_MAINTENANCE_CAP = "current_maintenance_cap"
