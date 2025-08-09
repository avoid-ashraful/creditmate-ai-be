from django.core.validators import URLValidator
from django.db import models

from common.models import Audit

from .enums import ContentType, ProcessingStatus


class Bank(Audit):
    """Model representing a bank that issues credit cards.

    This model stores information about financial institutions in Bangladesh
    that issue credit cards, including their basic information and data sources
    for crawling credit card information.
    """

    name = models.CharField(max_length=255, unique=True)
    logo = models.URLField(max_length=512, blank=True, validators=[URLValidator()])
    website = models.URLField(max_length=512, blank=True, validators=[URLValidator()])
    schedule_charge_url = models.URLField(
        max_length=1024,
        blank=True,
        validators=[URLValidator()],
        help_text="Base URL where schedule of charges/fee documents can be found",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        db_table = "banks_bank"

    def __str__(self):
        return self.name

    @property
    def credit_card_count(self):
        """Return the number of active credit cards for this bank.

        Returns
        -------
        int
            Number of active credit cards associated with this bank
        """
        return self.credit_cards.filter(is_active=True).count()


class BankDataSource(Audit):
    """Model representing data sources for bank credit card information.

    This model stores URLs and metadata for various sources where credit card
    information can be extracted, including PDFs, webpages, images, and CSV files.
    """

    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="data_sources")
    url = models.URLField(max_length=1024, validators=[URLValidator()])
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    description = models.CharField(max_length=500, blank=True, default="")
    failed_attempt_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    last_successful_crawl_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["bank__name", "url"]
        unique_together = ["bank", "url"]
        db_table = "banks_bankdatasource"

    def __str__(self):
        return f"{self.bank.name} - {self.url}"

    @property
    def is_failing(self):
        """Check if data source has too many failed attempts.

        Returns
        -------
        bool
            True if failed attempt count is 5 or more, False otherwise
        """
        return self.failed_attempt_count >= 5

    def increment_failed_attempts(self):
        """Increment failed attempt count and deactivate if needed.

        Increases the failed attempt counter by 1 and automatically
        deactivates the data source if it reaches 5 failed attempts.

        Returns
        -------
        None
        """
        self.failed_attempt_count += 1
        if self.failed_attempt_count >= 5:
            self.is_active = False
        self.save(update_fields=["failed_attempt_count", "is_active"])

    def reset_failed_attempts(self):
        """Reset failed attempts after successful crawl.

        Sets the failed attempt counter back to 0, typically called
        after a successful data extraction.

        Returns
        -------
        None
        """
        self.failed_attempt_count = 0
        self.save(update_fields=["failed_attempt_count"])


class CrawledContent(Audit):
    """Model to store extracted and parsed content from bank data sources.

    This model stores the complete pipeline of content processing including:
    - Raw content from the source URL
    - Extracted text content after processing
    - Parsed JSON data from LLM processing
    - Processing status and error information
    """

    data_source = models.ForeignKey(
        BankDataSource, on_delete=models.CASCADE, related_name="crawled_contents"
    )
    credit_card = models.ForeignKey(
        "credit_cards.CreditCard",
        on_delete=models.CASCADE,
        related_name="crawled_contents",
        null=True,
        blank=True,
    )
    raw_content = models.TextField(blank=True, default="")
    extracted_content = models.TextField(blank=True, default="")
    content_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA256 hash of extracted content for change detection",
    )
    parsed_json = models.JSONField(default=dict, blank=True, null=True)
    parsed_json_raw = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Raw extracted data with all fields including non-standard ones",
    )
    crawled_at = models.DateTimeField(auto_now_add=True)
    sync_timestamps = models.JSONField(
        default=list,
        blank=True,
        help_text="List of timestamps when this content was re-crawled and found unchanged",
    )
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-crawled_at"]
        db_table = "banks_crawledcontent"

    def __str__(self):
        return f"{self.data_source.bank.name} - {self.crawled_at}"
