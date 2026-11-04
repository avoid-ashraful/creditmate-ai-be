"""Enumerations for the loans app.

Loan taxonomy (from the Phase 2 research notes): products are TYPED by
collateral/purpose family; segments (salaried, professional, doctor, women,
NRB, landlord, ...) and purposes (education, marriage, ...) are TAGS, not
types — the same product object carries them.
"""

from django.db import models


class LoanType(models.TextChoices):
    PERSONAL = "personal", "Personal loan"
    HOME = "home", "Home loan"
    CAR = "car", "Car loan"
    SECURED = "secured_against_deposit", "Loan against deposit/security"


class LenderType(models.TextChoices):
    BANK = "bank", "Bank"
    NBFI = "nbfi", "NBFI / finance company"
    GOVT = "govt", "Government institution"


class RateType(models.TextChoices):
    FIXED = "fixed", "Fixed"
    FLOATING = "floating", "Floating / variable"
    BASE_PLUS_MARGIN = "base_plus_margin", "Base rate + margin"
    FORMULA_SPREAD = "formula_spread", "Formula (spread over deposit rate)"
    UNKNOWN = "unknown", "Not published"


class RateSource(models.TextChoices):
    """Where a product's own rate band came from (provenance precedence:
    product page / schedule of charges / Annexure-A beat the BB chart;
    the chart is stored separately as a fallback band)."""

    BB_CHART = "bb_chart", "Bangladesh Bank lending chart"
    ANNEXURE_A = "annexure_a", "Bank's Annexure-A declared rates"
    PRODUCT_PAGE = "product_page", "Bank product page"
    SCHEDULE_OF_CHARGES = "schedule_of_charges", "Schedule of charges"
    MANUAL = "manual", "Manually verified publication"
    NONE = "none", "No published rate"


class ShariahMode(models.TextChoices):
    HPSM = "hpsm", "Hire Purchase under Shirkatul Melk (HPSM)"
    BAI_MUAJJAL = "bai_muajjal", "Bai-Muajjal"
    BAI_MURABAHA = "bai_murabaha", "Bai-Murabaha"


class IncomeMetric(models.TextChoices):
    GROSS = "gross", "Gross monthly income"
    NET = "net", "Net monthly income"
    MIXED = "mixed", "Mixed (varies by segment)"


class CollateralType(models.TextChoices):
    NONE = "none", "None (unsecured)"
    PERSONAL_GUARANTEE = "personal_guarantee", "Personal guarantee"
    MORTGAGE = "mortgage", "Registered mortgage of property"
    HYPOTHECATION = "hypothecation", "Hypothecation of vehicle"
    LIEN_DEPOSIT = "lien_deposit", "Lien on deposit/security"
    OTHER = "other", "Other security"


class DisbursementMode(models.TextChoices):
    LUMP_SUM = "lump_sum", "Lump sum"
    PHASED = "phased", "Phased / instalment-wise"
    SELLER_PAYEE = "seller_payee", "Payee to seller/developer"


class ChartCategory(models.TextChoices):
    """Mappable columns of the Bangladesh Bank lending chart."""

    HOUSING = "housing", "Housing loan"
    CONSUMER_CREDIT = "consumer_credit", "Consumer credit"


#: loan_type -> BB chart category used as the fallback band.
#: Secured-against-deposit is deliberately absent: those products are
#: priced off the pledged deposit (a spread), so the consumer-credit
#: band would misstate their price.
CHART_CATEGORY_FOR_TYPE = {
    LoanType.HOME: ChartCategory.HOUSING,
    LoanType.PERSONAL: ChartCategory.CONSUMER_CREDIT,
    LoanType.CAR: ChartCategory.CONSUMER_CREDIT,
}

#: Canonical segment tags (borrower segments — tags, not product types).
SEGMENT_TAGS = [
    "salaried",
    "professional",
    "professional_doctor",
    "business",
    "self_employed",
    "landlord",
    "women",
    "nrb",
    "government_employee",
    "teacher",
    "salary_account",
    "senior_citizen",
    "student_guardian",
]

#: Canonical purpose tags.
PURPOSE_TAGS = [
    "any_purpose",
    "education",
    "marriage",
    "medical",
    "travel",
    "consumer_durables",
    "digital_device",
    "flat_purchase",
    "construction",
    "renovation",
    "extension",
    "takeover",
    "vehicle_new",
    "vehicle_reconditioned",
    "vehicle_preowned",
]
