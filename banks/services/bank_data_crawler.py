import hashlib
import logging

from django.utils import timezone

from ..exceptions import (
    AIParsingError,
    ConfigurationError,
    ContentExtractionError,
    FileFormatError,
    NetworkError,
)
from ..models import BankDataSource, CrawledContent
from .content_extractor import ContentExtractor
from .credit_card_data_service import CreditCardDataService
from .llm_parser import LLMContentParser

logger = logging.getLogger(__name__)


class BankDataCrawlerService:
    """Main service orchestrating the bank data crawling process.

    This service coordinates the entire crawling pipeline including content
    extraction, LLM parsing, change detection, and database updates for
    bank credit card data sources.
    """

    def __init__(self):
        """Initialize the crawler service with its components.

        Sets up the content extraction, LLM parsing, and data service
        components required for the crawling pipeline.

        Returns
        -------
        None
        """
        self.content_extractor = ContentExtractor()
        self.llm_parser = LLMContentParser()
        self.data_service = CreditCardDataService()

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

            # Extract content with error handling
            raw_content, extracted_content = self._extract_content_safely(data_source)
            if not extracted_content:
                return False

            # Check for content changes
            content_hash = self._generate_content_hash(extracted_content)
            if self._should_skip_processing(data_source, content_hash):
                return True

            # Process changed content
            return self._process_changed_content(
                data_source, raw_content, extracted_content, content_hash
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
        """Safely extract content with error handling.

        Parameters
        ----------
        data_source : BankDataSource
            Data source to extract content from

        Returns
        -------
        tuple of (str, str) or (None, None)
            First element is raw content, second is extracted content.
            Returns (None, None) on extraction failure.
        """
        try:
            raw_content, extracted_content = self.content_extractor.extract_content(
                data_source.url, data_source.content_type
            )
            return raw_content, extracted_content
        except (ContentExtractionError, NetworkError, FileFormatError) as e:
            logger.error(
                f"Content extraction failed for {data_source.bank.name}: {e.message}"
            )
            data_source.increment_failed_attempts()
            self._create_failed_crawl_record(data_source, e.message)
            return None, None

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
        self, data_source, raw_content, extracted_content, content_hash
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

        Returns
        -------
        bool
            True if processing completed successfully, False if any step failed
        """
        logger.info(
            f"Content changes detected for {data_source.bank.name}, processing..."
        )

        # Parse content with AI
        parsing_result = self._parse_content_safely(data_source, extracted_content)
        if not parsing_result:
            return False

        # Unpack the tuple (structured_data, raw_comprehensive_data)
        structured_data, raw_comprehensive_data = parsing_result

        # Store crawled content with both parsed data types
        crawled_content = self._create_crawl_record(
            data_source,
            raw_content,
            extracted_content,
            content_hash,
            structured_data,
            raw_comprehensive_data,
        )

        # Update database
        return self._update_database_safely(data_source, structured_data, crawled_content)

    def _parse_content_safely(self, data_source, content):
        """Safely parse content with AI, handling errors.

        Parameters
        ----------
        data_source : BankDataSource
            Data source being processed for context
        content : str
            Extracted text content to parse with LLM

        Returns
        -------
        tuple of (dict, dict) or None
            Tuple of (structured_data, raw_comprehensive_data) on success,
            None on parsing failure
        """
        try:
            return self.llm_parser.parse_comprehensive_data(
                content, data_source.bank.name
            )
        except (ConfigurationError, AIParsingError) as e:
            logger.error(f"AI parsing failed for {data_source.bank.name}: {e.message}")

            # For configuration errors, don't increment failed attempts
            if not isinstance(e, ConfigurationError):
                data_source.increment_failed_attempts()

            return None

    def _create_crawl_record(
        self,
        data_source,
        raw_content,
        extracted_content,
        content_hash,
        parsed_data,
        raw_comprehensive_data,
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

    def _create_failed_crawl_record(self, data_source, error_message):
        """Create a failed crawl record.

        Parameters
        ----------
        data_source : BankDataSource
            Data source that failed to be crawled
        error_message : str
            Error message describing the failure

        Returns
        -------
        None
        """
        CrawledContent.objects.create(
            data_source=data_source,
            processing_status="failed",
            error_message=error_message,
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
