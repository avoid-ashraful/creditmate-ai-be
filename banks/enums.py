"""Enum classes for the banks app."""

from django.db import models


class ContentType(models.TextChoices):
    """Content type choices for BankDataSource."""

    PDF = "pdf", "PDF"
    WEBPAGE = "webpage", "Webpage"
    IMAGE = "image", "Image"
    CSV = "csv", "CSV"


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
