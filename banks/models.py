from django.core.validators import URLValidator
from django.db import models

from common.models import Audit

from .enums import ContentType, ProcessingStatus


class Bank(Audit):
    """Model representing a bank that issues credit cards."""

    name = models.CharField(max_length=255, unique=True)
    logo = models.URLField(max_length=512, blank=True, validators=[URLValidator()])
    website = models.URLField(max_length=512, blank=True, validators=[URLValidator()])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        db_table = "banks_bank"

    def __str__(self):
        return self.name

    @property
    def credit_card_count(self):
        """Return the number of active credit cards for this bank."""
        return self.credit_cards.filter(is_active=True).count()


class BankDataSource(Audit):
    """Model representing data sources for bank credit card information."""

    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="data_sources")
    url = models.URLField(max_length=1024, validators=[URLValidator()])
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    description = models.CharField(max_length=500, blank=True, default="")
    failed_attempt_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
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
        """Check if data source has too many failed attempts."""
        return self.failed_attempt_count >= 5

    def increment_failed_attempts(self):
        """Increment failed attempt count and deactivate if needed."""
        self.failed_attempt_count += 1
        if self.failed_attempt_count >= 5:
            self.is_active = False
        self.save(update_fields=["failed_attempt_count", "is_active"])

    def reset_failed_attempts(self):
        """Reset failed attempts after successful crawl."""
        self.failed_attempt_count = 0
        self.save(update_fields=["failed_attempt_count"])


class CrawledContent(Audit):
    """Model to store extracted and parsed content from bank data sources."""

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
    parsed_json = models.JSONField(default=dict, blank=True, null=True)
    crawl_date = models.DateTimeField(auto_now_add=True)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-crawl_date"]
        db_table = "banks_crawledcontent"

    def __str__(self):
        return f"{self.data_source.bank.name} - {self.crawl_date}"
