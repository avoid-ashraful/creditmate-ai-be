import hashlib
import logging

from django.utils import timezone

from banks.exceptions import (
    AIParsingError,
    ConfigurationError,
    ContentExtractionError,
    FileFormatError,
    NetworkError,
)
from banks.models import BankDataSource, CrawledContent
from banks.services.content_extractor import ContentExtractor
from banks.services.credit_card_data_service import CreditCardDataService
from banks.services.llm_parser import LLMContentParser
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from banks.services.quality_scoring import coalesce_cards
from banks.services.quality_validator import ExtractionQualityValidator

logger = logging.getLogger(__name__)


class BankDataCrawlerService:
    """Main service orchestrating the bank data crawling process.

    This service coordinates the entire crawling pipeline including content
    extraction, LLM parsing, change detection, and database updates for
    bank credit card data sources.

    Extraction uses the multi-pass LLM pipeline when an LLM provider is
    configured (bank-specific prompt -> focused critical-field pass when the
    first pass scores below the threshold -> validation stage), and falls back
    to the legacy single-pass parser when no provider is available or the
    multi-pass run produced no cards. Every completed record is scored with
    :class:`banks.services.quality_validator.ExtractionQualityValidator` and
    stores its confidence, missing fields, method and pass provenance.
    """

    def __init__(
        self,
        multi_pass_extractor=None,
        content_extractor=None,
        llm_parser=None,
        data_service=None,
    ):
        """Initialize the crawler service with its components.

        Parameters
        ----------
        multi_pass_extractor : MultiPassLLMExtractor, optional
            Extractor used for multi-pass parsing. A default extractor backed
            by the configured LLM orchestrator is created when omitted.
        content_extractor : ContentExtractor, optional
            Content extraction service.
        llm_parser : LLMContentParser, optional
            Legacy single-pass parser used as fallback.
        data_service : CreditCardDataService, optional
            Service that writes parsed cards to the database.

        Returns
        -------
        None
        """
        self.content_extractor = content_extractor or ContentExtractor()
        self.llm_parser = llm_parser or LLMContentParser()
        self.data_service = data_service or CreditCardDataService()
        self.multi_pass_extractor = multi_pass_extractor or MultiPassLLMExtractor()

    def crawl_bank_data_source(self, data_source_id):
        """Crawl a single bank data source with change detection.

        Parameters
        ----------
        data_source_id : int
            ID of the BankDataSource to crawl

        Returns
        -------
        bool
            True if crawling was successful, False if any step failed
        """
        try:
            data_source = self._get_data_source(data_source_id)
            logger.info(f"Starting crawl for {data_source.bank.name} - {data_source.url}")

            # Update crawl timestamp
            self._update_crawl_timestamp(data_source)

            # Extract content with error handling (multi-source with fallback)
            extraction_result = self._extract_content_safely(data_source)
            if not extraction_result:
                return False
            raw_content, extracted_content, extraction_context = extraction_result
            if not extracted_content:
                return False

            # Check for content changes
            content_hash = self._generate_content_hash(extracted_content)
            if self._should_skip_processing(data_source, content_hash):
                return True

            # Process changed content
            return self._process_changed_content(
                data_source,
                raw_content,
                extracted_content,
                content_hash,
                extraction_context,
            )

        except BankDataSource.DoesNotExist:
            logger.error(f"BankDataSource with id {data_source_id} not found")
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error crawling data source {data_source_id}: {str(e)}"
            )
            self._record_unexpected_error(data_source_id, str(e))
            return False

    def crawl_all_active_sources(self):
        """Crawl all active bank data sources.

        Parameters
        ----------
        None

        Returns
        -------
        dict
            Summary dictionary with keys 'total', 'successful', 'failed'
            containing counts of crawling results
        """
        active_sources = BankDataSource.objects.filter(is_active=True)
        results = {"total": active_sources.count(), "successful": 0, "failed": 0}

        for data_source in active_sources:
            if self.crawl_bank_data_source(data_source.id):
                results["successful"] += 1
            else:
                results["failed"] += 1

        logger.info(f"Crawling completed: {results}")
        return results

    def _get_data_source(self, data_source_id):
        """Get active data source by ID.

        Parameters
        ----------
        data_source_id : int
            Database ID of the BankDataSource to retrieve

        Returns
        -------
        BankDataSource
            The requested data source instance

        Raises
        ------
        BankDataSource.DoesNotExist
            If the data source ID does not exist or is inactive
        """
        return BankDataSource.objects.get(id=data_source_id, is_active=True)

    def _update_crawl_timestamp(self, data_source):
        """Update the last crawled timestamp for a data source.

        Parameters
        ----------
        data_source : BankDataSource
            Data source instance to update with current timestamp

        Returns
        -------
        None
        """
        data_source.last_crawled_at = timezone.now()
        data_source.save(update_fields=["last_crawled_at"])

    def _extract_content_safely(self, data_source):
        """Safely extract content with error handling and multi-source rescue.

        The regular single-method extraction runs first (it is also what tests
        mock). When it fails - or succeeds but yields no usable text - the
        multi-source extractor (Phase 3) rescues the crawl: every candidate
        method is scored with the bounded confidence function and the highest
        scoring result wins, with ``method``/``confidence``/``attempts``
        recorded as provenance.

        Parameters
        ----------
        data_source : BankDataSource
            Data source to extract content from

        Returns
        -------
        tuple of (str, str, dict) or None
            ``(raw_content, extracted_content, extraction_context)`` where the
            context carries ``method`` (plus ``confidence`` and ``attempts``
            when the multi-source path produced them). ``None`` when extraction
            failed and the failure was recorded.
        """
        url = data_source.url
        content_type = data_source.content_type
        fallback_method = self._extraction_method(data_source)
        primary_error = None

        try:
            raw_content, extracted_content = self.content_extractor.extract_content(
                url, content_type
            )
            if extracted_content:
                return raw_content, extracted_content, {"method": fallback_method}
            logger.info(
                "Primary extraction produced no text for %s - trying multi-source "
                "extraction",
                data_source.bank.name,
            )
        except (ContentExtractionError, NetworkError, FileFormatError) as exc:
            primary_error = exc
            logger.info(
                "Primary extraction failed for %s (%s) - trying multi-source "
                "extraction",
                data_source.bank.name,
                exc.message,
            )

        rescue = None
        if not isinstance(primary_error, NetworkError):
            # A connectivity problem will also break the rescue attempt, so
            # only extraction-level problems are worth retrying.
            rescue = self._rescue_with_multi_source(data_source, fallback_method)
        if rescue is not None:
            return rescue

        if primary_error is not None:
            logger.error(
                f"Content extraction failed for {data_source.bank.name}: "
                f"{primary_error.message}"
            )
            data_source.increment_failed_attempts()
            self._create_failed_crawl_record(
                data_source, primary_error.message, fallback_method
            )
            return None

        # Primary extraction returned empty content and the rescue failed too.
        logger.error(
            f"Content extraction produced no content for {data_source.bank.name}"
        )
        data_source.increment_failed_attempts()
        self._create_failed_crawl_record(
            data_source,
            "Content extraction produced no content",
            fallback_method,
        )
        return None

    def _rescue_with_multi_source(self, data_source, fallback_method):
        """Run multi-source extraction and return its best attempt.

        Parameters
        ----------
        data_source : BankDataSource
            Data source being crawled.
        fallback_method : str
            Method name used when the rescue result does not carry one.

        Returns
        -------
        tuple of (str, str, dict) or None
            ``(raw_content, extracted_content, extraction_context)`` on
            success, ``None`` when every method failed.
        """
        try:
            result = self.content_extractor.extract_with_validation(
                data_source.url, data_source.content_type
            )
            content = result.get("content")
            if not content:
                return None
            return (
                result.get("raw_content") or "",
                content,
                {
                    "method": result.get("method") or fallback_method,
                    "confidence": result.get("confidence"),
                    "attempts": result.get("attempts") or [],
                },
            )
        except Exception as exc:  # noqa: BLE001 - rescue is best effort only
            logger.warning(
                "Multi-source extraction could not rescue %s: %s",
                data_source.bank.name,
                exc,
            )
            return None

    def _generate_content_hash(self, content):
        """Generate SHA256 hash for content change detection.

        Parameters
        ----------
        content : str
            Text content to generate hash for change detection

        Returns
        -------
        str
            SHA256 hash of the content as hexadecimal string
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _should_skip_processing(self, data_source, content_hash):
        """Check if content processing should be skipped due to no changes.

        Parameters
        ----------
        data_source : BankDataSource
            Data source to check for existing content
        content_hash : str
            Hash of current content to compare against previous crawls

        Returns
        -------
        bool
            True if processing should be skipped (no changes detected),
            False if content has changed and should be processed
        """
        last_successful_crawl = (
            CrawledContent.objects.filter(
                data_source=data_source, processing_status="completed"
            )
            .order_by("-crawled_at")
            .first()
        )

        if last_successful_crawl and last_successful_crawl.content_hash == content_hash:
            logger.info(
                f"No changes detected for {data_source.bank.name} - {data_source.url}"
            )
            self._record_no_changes(data_source, content_hash)
            return True

        return False

    def _record_no_changes(self, data_source, content_hash):
        """Record a successful crawl with no content changes by updating sync timestamps.

        Parameters
        ----------
        data_source : BankDataSource
            Data source instance to update
        content_hash : str
            SHA256 hash of the unchanged content

        Returns
        -------
        None
        """
        # Update successful crawl timestamp
        current_time = timezone.now()
        data_source.last_successful_crawl_at = current_time
        data_source.save(update_fields=["last_successful_crawl_at"])

        # Find the latest completed crawl record with matching hash
        latest_crawl = (
            CrawledContent.objects.filter(
                data_source=data_source,
                content_hash=content_hash,
                processing_status="completed",
            )
            .order_by("-crawled_at")
            .first()
        )

        if latest_crawl:
            # Append current timestamp to sync_timestamps list
            sync_timestamps = latest_crawl.sync_timestamps or []
            sync_timestamps.append(current_time.isoformat())
            latest_crawl.sync_timestamps = sync_timestamps
            latest_crawl.save(update_fields=["sync_timestamps"])
        else:
            # Fallback: create new record if no existing one found (shouldn't happen)
            CrawledContent.objects.create(
                data_source=data_source,
                raw_content="",
                extracted_content="",
                content_hash=content_hash,
                parsed_json={"info": "no_existing_record_found"},
                processing_status="completed",
                sync_timestamps=[current_time.isoformat()],
            )

    def _process_changed_content(
        self,
        data_source,
        raw_content,
        extracted_content,
        content_hash,
        content_extraction_context=None,
    ):
        """Process content that has changed since last crawl.

        Parameters
        ----------
        data_source : BankDataSource
            Data source being processed
        raw_content : str
            Raw content from the source
        extracted_content : str
            Extracted and cleaned text content
        content_hash : str
            SHA256 hash of the content for change tracking
        content_extraction_context : dict, optional
            Content extraction provenance (``method``, ``confidence``,
            ``attempts``) returned by the extractor.

        Returns
        -------
        bool
            True if processing completed successfully, False if any step failed
        """
        logger.info(
            f"Content changes detected for {data_source.bank.name}, processing..."
        )
        content_extraction_context = content_extraction_context or {}

        # Parse content with AI (multi-pass first, legacy single-pass fallback)
        parsing_result = self._parse_content_safely(data_source, extracted_content)
        if not parsing_result:
            return False

        structured_data, raw_comprehensive_data, extraction_context = parsing_result
        extraction_method = (
            content_extraction_context.get("method")
            or self._extraction_method(data_source)
        )

        # Store crawled content with both parsed data types
        crawled_content = self._create_crawl_record(
            data_source,
            raw_content,
            extracted_content,
            content_hash,
            structured_data,
            raw_comprehensive_data,
            extraction_method=extraction_method,
        )

        # Score extraction quality (confidence, missing fields, manual review)
        self._apply_quality_score(
            crawled_content, structured_data, extraction_context, extraction_method
        )
        if content_extraction_context.get("confidence") is not None:
            logger.info(
                "Content extraction confidence for crawled content %s: %.3f "
                "(method=%s, attempts=%d)",
                crawled_content.id,
                content_extraction_context["confidence"],
                extraction_method,
                len(content_extraction_context.get("attempts") or []),
            )

        # Update database
        return self._update_database_safely(data_source, structured_data, crawled_content)

    @staticmethod
    def _extraction_method(data_source):
        """Map a data source to its extraction method name.

        Parameters
        ----------
        data_source : BankDataSource
            Data source being crawled.

        Returns
        -------
        str
            Extraction method name (``pdf_text``, ``webpage``, ``csv``,
            ``image_ocr``) used for confidence scoring and provenance.
        """
        return ContentExtractor._method_for_content_type(data_source.content_type)

    def _apply_quality_score(
        self, crawled_content, parsed_data, extraction_context, extraction_method
    ):
        """Score and store extraction quality on a crawled content record.

        Parameters
        ----------
        crawled_content : CrawledContent
            Record to score (already saved).
        parsed_data : dict or list
            Structured parse result containing the extracted cards.
        extraction_context : dict
            Multi-pass provenance (``passes``, ``issues``, ``provider``) or an
            empty dictionary for the legacy single-pass path.
        extraction_method : str
            Extraction method that produced ``extracted_content``.

        Returns
        -------
        ExtractionQuality
            The stored quality outcome.
        """
        cards = coalesce_cards(parsed_data)
        passes = extraction_context.get("passes") or []
        quality = ExtractionQualityValidator.score_crawled_content(
            crawled_content, cards=cards, extraction_passes=passes
        )
        logger.info(
            "Quality score for crawled content %s: confidence=%.3f method=%s "
            "missing=%s review=%s",
            crawled_content.id,
            quality.confidence,
            extraction_method,
            quality.missing_critical_fields,
            crawled_content.needs_manual_review,
        )
        invalid_reasons = dict(quality.invalid_reasons) or dict(
            extraction_context.get("invalid_reasons") or {}
        )
        if invalid_reasons:
            logger.warning(
                "Critical values rejected for crawled content %s: %s "
                "(stored as NULL, never as 0)",
                crawled_content.id,
                invalid_reasons,
            )
        return quality

    def _parse_content_safely(self, data_source, content):
        """Safely parse content with AI, handling errors.

        Runs the multi-pass pipeline first when an LLM provider is configured
        and falls back to the legacy single-pass parser when no provider is
        available, the multi-pass run failed, or it produced no cards.

        Parameters
        ----------
        data_source : BankDataSource
            Data source being processed for context
        content : str
            Extracted text content to parse with LLM

        Returns
        -------
        tuple of (dict, dict, dict) or None
            ``(structured_data, raw_comprehensive_data, extraction_context)``
            on success, ``None`` on parsing failure.
        """
        multi_pass_result = self._extract_multi_pass(data_source, content)
        if multi_pass_result is not None:
            return multi_pass_result

        try:
            structured_data, raw_comprehensive_data = (
                self.llm_parser.parse_comprehensive_data(
                    content, data_source.bank.name
                )
            )
            return structured_data, raw_comprehensive_data, {}
        except (ConfigurationError, AIParsingError) as e:
            logger.error(f"AI parsing failed for {data_source.bank.name}: {e.message}")

            # For configuration errors, don't increment failed attempts
            if not isinstance(e, ConfigurationError):
                data_source.increment_failed_attempts()

            return None

    def _extract_multi_pass(self, data_source, content):
        """Run multi-pass extraction for one document.

        Parameters
        ----------
        data_source : BankDataSource
            Data source being crawled.
        content : str
            Extracted text content to parse.

        Returns
        -------
        tuple of (dict, dict, dict) or None
            ``(structured_data, raw_comprehensive_data, extraction_context)``
            when multi-pass extraction succeeded, ``None`` when it should be
            skipped (no provider configured) or it produced no usable cards.
        """
        if not self.multi_pass_extractor.is_provider_available():
            return None

        method = self._extraction_method(data_source)
        bank_name = data_source.bank.name

        try:
            result = self.llm_parser.parse_with_multi_pass(
                content, bank_name, method=method
            )
        except (ConfigurationError, AIParsingError) as exc:
            logger.warning(
                "Multi-pass extraction unavailable for %s: %s - falling back "
                "to single-pass parsing",
                bank_name,
                getattr(exc, "message", str(exc)),
            )
            return None
        except Exception as exc:  # noqa: BLE001 - never let extraction kill the crawl
            logger.warning(
                "Multi-pass extraction failed for %s: %s - falling back to "
                "single-pass parsing",
                bank_name,
                exc,
            )
            return None

        cards = getattr(result, "credit_cards", None)
        if not isinstance(cards, list) or not cards:
            logger.warning(
                "Multi-pass extraction returned no cards for %s - falling back "
                "to single-pass parsing",
                bank_name,
            )
            return None

        structured_data = {
            "credit_cards": cards,
            "provider_used": getattr(result, "provider_used", None),
            "extraction_confidence": getattr(result, "confidence", None),
            "missing_critical_fields": list(
                getattr(result, "missing_critical_fields", []) or []
            ),
            "invalid_reasons": dict(getattr(result, "invalid_reasons", None) or {}),
            "extraction_passes": list(getattr(result, "passes", []) or []),
            "validation_errors": list(getattr(result, "issues", []) or []),
        }
        raw_comprehensive_data = {
            "cards": cards,
            "source": "multi_pass_llm",
            "provider_used": getattr(result, "provider_used", None),
            "extraction_passes": list(getattr(result, "passes", []) or []),
        }
        extraction_context = {
            "passes": list(getattr(result, "passes", []) or []),
            "issues": list(getattr(result, "issues", []) or []),
            "provider_used": getattr(result, "provider_used", None),
            "confidence": getattr(result, "confidence", None),
            "extraction_method": "multi_pass_llm",
            "invalid_reasons": dict(getattr(result, "invalid_reasons", None) or {}),
        }
        return structured_data, raw_comprehensive_data, extraction_context

    def _create_crawl_record(
        self,
        data_source,
        raw_content,
        extracted_content,
        content_hash,
        parsed_data,
        raw_comprehensive_data,
        extraction_method="",
    ):
        """Create a crawled content record with both structured and raw comprehensive data.

        Parameters
        ----------
        data_source : BankDataSource
            Data source instance
        raw_content : str
            Raw content from the source
        extracted_content : str
            Extracted text content
        content_hash : str
            SHA256 hash for change detection
        parsed_data : dict
            Structured parsed data from LLM
        raw_comprehensive_data : dict
            Raw comprehensive data with all extracted fields
        extraction_method : str, optional
            Method used to obtain ``extracted_content`` (``pdf_text``,
            ``ocr``, ``webpage``, ``csv``, ``image_ocr``).

        Returns
        -------
        CrawledContent
            Created database record for the crawled content
        """
        return CrawledContent.objects.create(
            data_source=data_source,
            raw_content=raw_content,
            extracted_content=extracted_content,
            content_hash=content_hash,
            parsed_json=parsed_data,
            parsed_json_raw=raw_comprehensive_data,
            processing_status="processing",
            extraction_method=extraction_method,
        )

    def _update_database_safely(self, data_source, parsed_data, crawled_content):
        """Safely update database with parsed data.

        Parameters
        ----------
        data_source : BankDataSource
            Data source instance
        parsed_data : dict
            Parsed credit card data from LLM processing
        crawled_content : CrawledContent
            Crawled content record to update with results

        Returns
        -------
        bool
            True if database update was successful, False otherwise
        """
        # Handle validation errors in parsed data
        actual_data = self._extract_actual_data(parsed_data, data_source.bank.name)

        if not actual_data or "error" in actual_data:
            self._record_parsing_failure(crawled_content, actual_data, data_source)
            return False

        try:
            updated_count = self.data_service.update_credit_card_data(
                data_source.bank.id, actual_data
            )

            self._record_successful_update(crawled_content, data_source, updated_count)
            return True

        except Exception as e:
            self._record_database_failure(crawled_content, data_source, str(e))
            return False

    def _extract_actual_data(self, parsed_data, bank_name):
        """Extract actual data from parsed response, handling validation errors.

        Parameters
        ----------
        parsed_data : dict
            Raw parsed data that may contain validation errors
        bank_name : str
            Bank name for logging context

        Returns
        -------
        dict
            Cleaned data ready for database processing
        """
        if "validation_errors" in parsed_data:
            logger.warning(
                f"Data validation issues for {bank_name}: {parsed_data['validation_errors']}"
            )
            return parsed_data.get("data", parsed_data)
        return parsed_data

    def _record_successful_update(self, crawled_content, data_source, updated_count):
        """Record successful database update.

        Parameters
        ----------
        crawled_content : CrawledContent
            Content record to mark as completed
        data_source : BankDataSource
            Data source to reset failure counters
        updated_count : int
            Number of credit cards updated in the database

        Returns
        -------
        None
        """
        crawled_content.processing_status = "completed"
        crawled_content.save(update_fields=["processing_status"])
        crawled_content.enqueue_for_manual_review()

        # Reset failed attempts on success
        data_source.reset_failed_attempts()
        data_source.last_successful_crawl_at = timezone.now()
        data_source.save(update_fields=["last_successful_crawl_at"])

        logger.info(
            f"Successfully updated {updated_count} credit cards for {data_source.bank.name}"
        )

    def _record_parsing_failure(self, crawled_content, actual_data, data_source):
        """Record parsing failure.

        Parameters
        ----------
        crawled_content : CrawledContent
            Content record to mark as failed
        actual_data : dict or None
            Failed or empty parsing data
        data_source : BankDataSource
            Data source to increment failure counter

        Returns
        -------
        None
        """
        error_msg = (
            actual_data.get("error", "Failed to parse data")
            if actual_data
            else "No data parsed"
        )

        crawled_content.processing_status = "failed"
        crawled_content.error_message = error_msg
        crawled_content.save(update_fields=["processing_status", "error_message"])

        data_source.increment_failed_attempts()
        logger.error(f"Failed to parse data for {data_source.bank.name}: {error_msg}")

    def _record_database_failure(self, crawled_content, data_source, error):
        """Record database update failure.

        Parameters
        ----------
        crawled_content : CrawledContent
            Content record to mark as failed
        data_source : BankDataSource
            Data source to increment failure counter
        error : str
            Error message describing the database failure

        Returns
        -------
        None
        """
        crawled_content.processing_status = "failed"
        crawled_content.error_message = f"Database update failed: {error}"
        crawled_content.save(update_fields=["processing_status", "error_message"])

        data_source.increment_failed_attempts()
        logger.error(f"Database update failed for {data_source.bank.name}: {error}")

    def _create_failed_crawl_record(self, data_source, error_message, extraction_method=""):
        """Create a failed crawl record.

        Parameters
        ----------
        data_source : BankDataSource
            Data source that failed to be crawled
        error_message : str
            Error message describing the failure
        extraction_method : str, optional
            Extraction method that produced the attempt (provenance).

        Returns
        -------
        None
        """
        CrawledContent.objects.create(
            data_source=data_source,
            processing_status="failed",
            error_message=error_message,
            extraction_method=extraction_method or self._extraction_method(data_source),
        )

    def _record_unexpected_error(self, data_source_id, error):
        """Record unexpected error during crawling.

        Parameters
        ----------
        data_source_id : int
            ID of the data source that encountered an error
        error : str
            Error message describing the unexpected failure

        Returns
        -------
        None
        """
        try:
            data_source = BankDataSource.objects.get(id=data_source_id)
            data_source.increment_failed_attempts()
            self._create_failed_crawl_record(data_source, f"Unexpected error: {error}")
        except Exception:
            logger.error(f"Failed to record error for data source {data_source_id}")
