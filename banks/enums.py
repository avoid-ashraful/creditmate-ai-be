"""Enum classes for the banks app."""

from django.db import models


class ContentType(models.TextChoices):
    """Content type choices for BankDataSource."""

    PDF = "pdf", "PDF"
    WEBPAGE = "webpage", "Webpage"
    IMAGE = "image", "Image"
    CSV = "csv", "CSV"


class SourcePurpose(models.TextChoices):
    """What a BankDataSource feeds in the nightly product sync.

    The card pipeline (LLM extraction into credit-card drafts/proposals)
    only ever consumes ``CREDIT_CARD`` sources. Bangladesh Bank chart
    sources are parsed deterministically by the deposits/loans ingestions
    and never go through the LLM. The remaining purposes are *watched*
    sources: the nightly sync change-checks them (fetch + content hash)
    and flags changes for human review instead of auto-extracting, because
    per-product LLM extractors for those verticals do not exist yet.
    """

    CREDIT_CARD = "credit_card", "Credit card data"
    BB_DEPOSIT_CHART = "bb_deposit_chart", "Bangladesh Bank deposit-rate chart"
    BB_LENDING_CHART = "bb_lending_chart", "Bangladesh Bank lending-rate chart"
    ACCOUNT_SOC = "account_soc", "Account schedule of charges"
    ACCOUNT_RATES = "account_rates", "Account rate sheet"
    DEPOSIT_RATES = "deposit_rates", "Deposit rate sheet / product page"
    LOAN_RATES = "loan_rates", "Loan Annexure-A / product page"


class SyncRunStatus(models.TextChoices):
    """Lifecycle states of one nightly sync execution."""

    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    PARTIAL = "partial", "Completed with phase errors"
    FAILED = "failed", "Failed"


class SyncTrigger(models.TextChoices):
    """How a nightly sync execution was started."""

    SCHEDULED = "scheduled", "Celery beat schedule"
    MANUAL = "manual", "Management command / manual call"


class ProcessingStatus(models.TextChoices):
    """Processing status choices for CrawledContent."""

    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class SourceType(models.TextChoices):
    """Origin class of a credit-card observation used for multi-source validation.

    An *observation* is one value for one credit-card field read from one
    concrete source. Roughly: the bank's website(s), the bank's published
    PDF/Schedule-of-Charges documents, and user submissions. Independence for
    confidence purposes is decided on the concrete ``source_key`` (see
    ``banks.services.multi_source_validation``), while this broad class is
    provenance used for reporting.
    """

    BANK_WEBSITE = "bank_website", "Bank website"
    BANK_PDF = "bank_pdf", "Bank PDF"
    BANK_IMAGE = "bank_image", "Bank image"
    BANK_CSV = "bank_csv", "Bank CSV"
    USER_SUBMISSION = "user_submission", "User submission"


class ReviewPriority(models.TextChoices):
    """Priority choices for manual review queue items."""

    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class ReviewStatus(models.TextChoices):
    """Status choices for manual review queue items."""

    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ReviewSource(models.TextChoices):
    """Origin of a manual review queue item."""

    CRAWL_QUALITY = "crawl_quality", "Low-confidence crawl"
    CRAWLER_PROPOSAL = "crawler_proposal", "Crawler proposal"
    USER_REPORT = "user_report", "User report"
