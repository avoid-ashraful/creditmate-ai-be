"""Constants for the deposits vertical (FDR / DPS / schemes)."""

from django.db import models


class DepositKind(models.TextChoices):
    """Product family of a deposit product."""

    FDR = "fdr", "Fixed deposit (FDR)"
    DPS = "dps", "Deposit pension scheme (DPS)"
    MONTHLY_BENEFIT = "monthly_benefit", "Monthly benefit / profit scheme"
    SCHEME = "scheme", "Named deposit scheme"


class RateType(models.TextChoices):
    """How a product's return must be labelled.

    Islamic (Mudaraba) products distribute *expected profit* that is only
    finalised after year-end; they must never be rendered as "interest".
    This is enforced again at the database level (see DepositProduct's
    CheckConstraint) so a mislabelled row cannot be stored at all.
    """

    INTEREST = "interest", "Interest"
    EXPECTED_PROFIT = "expected_profit", "Expected profit (Mudaraba)"


class InstitutionType(models.TextChoices):
    BANK = "bank", "Bank"
    ISLAMIC_BANK = "islamic_bank", "Islamic bank"
    ISLAMIC_WINDOW = "islamic_window", "Islamic window of a conventional bank"
    GOVERNMENT_SCHEME = "government_scheme", "Government scheme (Sanchayapatra)"


class PayoutStyle(models.TextChoices):
    AT_MATURITY = "at_maturity", "At maturity"
    MONTHLY = "monthly", "Monthly payout"
    QUARTERLY = "quarterly", "Quarterly payout"
    INTEREST_FIRST = "interest_first", "Interest first"
    TARGET_AMOUNT = "target_amount", "Target amount (e.g. millionaire scheme)"


class Compounding(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annual"
    AT_MATURITY = "at_maturity", "Simple / at maturity"


class SourceKind(models.TextChoices):
    BB_CHART = "bb_chart", "Bangladesh Bank announced-rate chart"
    BANK_RATE_SHEET = "bank_rate_sheet", "Bank rate sheet"
    BANK_RATES_PAGE = "bank_rates_page", "Bank published rates page"
    BANK_PRODUCT_PAGE = "bank_product_page", "Bank product page"
    NSD = "nsd", "National Savings Directorate"


class ChartSource(models.TextChoices):
    CONVENTIONAL = "conventional", "Conventional banking chart"
    ISLAMIC_WINDOW = "islamic_window", "Islamic banking window chart"


BB_DEPOSIT_CHART_URLS = {
    ChartSource.CONVENTIONAL: (
        "https://www.bb.org.bd/en/index.php/financialactivity/interestdeposit"
    ),
    ChartSource.ISLAMIC_WINDOW: (
        "https://www.bb.org.bd/en/index.php/financialactivity/intdepo_bankislamic"
    ),
}

#: Fixed-deposit tenure bands of the BB chart, as (months_min, months_max).
#: The last band ("3 years and above") is open-ended.
BB_FD_TENURE_BANDS = [(3, 6), (6, 12), (12, 24), (24, 36), (36, None)]

#: Product fields whose changes are written to DepositFieldHistory by signals.
TRACKED_PRODUCT_FIELDS = {
    "name",
    "min_amount",
    "max_amount",
    "min_instalment",
    "max_instalment",
    "premature_encashment_terms",
    "compounding",
    "verification_status",
    "is_active",
}
