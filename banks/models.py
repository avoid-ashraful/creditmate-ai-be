from django.core.validators import URLValidator
from django.db import models
from django.utils import timezone

from banks.enums import ContentType, ProcessingStatus
from common.models import Audit


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
    - Extraction quality scoring and multi-pass extraction provenance
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
    # Quality tracking fields (see docs/crawler_quality_scoring.md)
    extraction_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "Bounded confidence score (0.0-1.0) for extraction quality. "
            "NULL means the content has not been scored yet."
        ),
    )
    missing_critical_fields = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of critical fields that could not be extracted "
            "(e.g. 'annual_fee', 'interest_rate_apr')"
        ),
    )
    extraction_method = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Method used to obtain extracted_content: 'pdf_text', 'ocr', 'webpage', 'csv', 'image_ocr'",
    )
    needs_manual_review = models.BooleanField(
        default=False,
        help_text="Flag for content requiring manual review (low confidence/missing fields)",
    )
    extraction_passes = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Ordered multi-pass extraction provenance: one record per LLM pass with "
            "pass name, provider, cards found and per-pass confidence"
        ),
    )
    multi_source_validation = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Multi-source validation outcome (Task 2.4): per-card-field agreement/"
            "conflict status, independent source counts and validated confidences. "
            "Empty dict when no cross-source comparison has run."
        ),
    )
    quality_scored_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last extraction quality scoring run",
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

    def apply_quality_score(
        self, confidence, missing_critical_fields=None, needs_manual_review=None, extraction_passes=None
    ):
        """Store an extraction quality score on this record.

        The confidence value is clamped into the documented [0.0, 1.0] range so
        stored scores are always bounded and comparable across passes.

        Parameters
        ----------
        confidence : float or None
            Extraction confidence in the inclusive range 0.0-1.0. ``None``
            means "not scored yet" and is stored as NULL.
        missing_critical_fields : list of str, optional
            Critical fields that could not be extracted.
        needs_manual_review : bool, optional
            Manual review flag. Defaults to ``confidence < 0.5`` when omitted.
        extraction_passes : list of dict, optional
            Multi-pass extraction provenance records.

        Returns
        -------
        CrawledContent
            The saved instance.
        """
        self.extraction_confidence = self._clamp_confidence(confidence)
        if missing_critical_fields is not None:
            self.missing_critical_fields = list(missing_critical_fields)
        if needs_manual_review is None:
            needs_manual_review = (
                self.extraction_confidence is not None
                and self.extraction_confidence < 0.5
            )
        self.needs_manual_review = bool(needs_manual_review)
        if extraction_passes is not None:
            self.extraction_passes = list(extraction_passes)
        self.quality_scored_at = timezone.now()
        self.save(
            update_fields=[
                "extraction_confidence",
                "missing_critical_fields",
                "needs_manual_review",
                "extraction_passes",
                "quality_scored_at",
            ]
        )
        return self

    def apply_multi_source_validation(self, summary):
        """Store a multi-source validation summary and raise the review flag.

        The summary is the JSON-safe output of
        :mod:`banks.services.multi_source_validation`. When it reports a real
        conflict or same-source inconsistency the record's
        ``needs_manual_review`` flag is set to ``True``; an existing flag is
        never cleared by a validation run.

        Parameters
        ----------
        summary : dict
            Serialized validation batch (see ``batch_summary``).

        Returns
        -------
        CrawledContent
            The saved instance.
        """
        self.multi_source_validation = dict(summary or {})
        if (summary or {}).get("needs_manual_review"):
            self.needs_manual_review = True
        self.save(update_fields=["multi_source_validation", "needs_manual_review"])
        return self

    @staticmethod
    def _clamp_confidence(confidence):
        """Clamp a confidence value into the bounded [0.0, 1.0] range.

        Parameters
        ----------
        confidence : float or None
            Raw confidence value.

        Returns
        -------
        float or None
            Value clamped to 0.0-1.0 (rounded to 4 decimals), or None when
            the input is None (``None`` means "not scored yet", which is
            distinct from a genuine 0.0 score).
        """
        if confidence is None:
            return None
        return round(min(1.0, max(0.0, float(confidence))), 4)

    @property
    def is_scored(self):
        """Return True when this content has an extraction confidence score."""
        return self.extraction_confidence is not None

    @property
    def is_low_confidence(self):
        """Return True when the extraction confidence is below the review threshold."""
        return self.extraction_confidence is not None and self.extraction_confidence < 0.5
