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
