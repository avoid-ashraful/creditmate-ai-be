"""Main service orchestrating the bank data crawling process."""

import hashlib
import logging
from typing import Any, Dict

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
    """Main service orchestrating the bank data crawling process."""

    def __init__(self):
        """Initialize the crawler service with its components."""
        self.content_extractor = ContentExtractor()
        self.llm_parser = LLMContentParser()
        self.data_service = CreditCardDataService()

    def crawl_bank_data_source(self, data_source_id: int) -> bool:
        """
        Crawl a single bank data source with change detection.

        Args:
            data_source_id (int): ID of the data source to crawl

        Returns:
            bool: True if crawling was successful, False otherwise
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

    def crawl_all_active_sources(self) -> Dict[str, int]:
        """
        Crawl all active bank data sources.

        Returns:
            Dict[str, int]: Summary of crawling results
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

    def _get_data_source(self, data_source_id: int) -> BankDataSource:
        """
        Get active data source by ID.

        Args:
            data_source_id (int): Data source ID

        Returns:
            BankDataSource: The data source object

        Raises:
            BankDataSource.DoesNotExist: If data source not found or inactive
        """
        return BankDataSource.objects.get(id=data_source_id, is_active=True)

    def _update_crawl_timestamp(self, data_source: BankDataSource) -> None:
        """
        Update the last crawled timestamp for a data source.

        Args:
            data_source (BankDataSource): Data source to update
        """
        data_source.last_crawled_at = timezone.now()
        data_source.save(update_fields=["last_crawled_at"])

    def _extract_content_safely(self, data_source: BankDataSource) -> tuple:
        """
        Safely extract content with error handling.

        Args:
            data_source (BankDataSource): Data source to extract from

        Returns:
            tuple: (raw_content, extracted_content) or (None, None) on failure
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

    def _generate_content_hash(self, content: str) -> str:
        """
        Generate SHA256 hash for content change detection.

        Args:
            content (str): Content to hash

        Returns:
            str: SHA256 hash
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _should_skip_processing(
        self, data_source: BankDataSource, content_hash: str
    ) -> bool:
        """
        Check if content processing should be skipped due to no changes.

        Args:
            data_source (BankDataSource): Data source to check
            content_hash (str): Hash of current content

        Returns:
            bool: True if processing should be skipped
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

    def _record_no_changes(self, data_source: BankDataSource, content_hash: str) -> None:
        """
        Record a successful crawl with no content changes.

        Args:
            data_source (BankDataSource): Data source
            content_hash (str): Content hash
        """
        # Update successful crawl timestamp
        data_source.last_successful_crawl_at = timezone.now()
        data_source.save(update_fields=["last_successful_crawl_at"])

        # Create record to track this check
        CrawledContent.objects.create(
            data_source=data_source,
            raw_content="",  # Don't store duplicate content
            extracted_content="",
            content_hash=content_hash,
            parsed_json={"skipped": "no_changes_detected"},
            processing_status="completed",
        )

    def _process_changed_content(
        self,
        data_source: BankDataSource,
        raw_content: str,
        extracted_content: str,
        content_hash: str,
    ) -> bool:
        """
        Process content that has changed since last crawl.

        Args:
            data_source (BankDataSource): Data source
            raw_content (str): Raw content
            extracted_content (str): Extracted text content
            content_hash (str): Content hash

        Returns:
            bool: True if processing was successful
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

    def _parse_content_safely(
        self, data_source: BankDataSource, content: str
    ) -> tuple[Dict[str, Any], Dict[str, Any]] | None:
        """
        Safely parse content with AI, handling errors.

        Args:
            data_source (BankDataSource): Data source
            content (str): Content to parse

        Returns:
            tuple[Dict[str, Any], Dict[str, Any]] | None: Tuple of (structured_data, raw_data) or None on failure
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
        data_source: BankDataSource,
        raw_content: str,
        extracted_content: str,
        content_hash: str,
        parsed_data: Dict[str, Any],
        raw_comprehensive_data: Dict[str, Any],
    ) -> CrawledContent:
        """
        Create a crawled content record with both structured and raw comprehensive data.

        Args:
            data_source (BankDataSource): Data source
            raw_content (str): Raw content
            extracted_content (str): Extracted content
            content_hash (str): Content hash
            parsed_data (Dict[str, Any]): Structured parsed data
            raw_comprehensive_data (Dict[str, Any]): Raw comprehensive parsed data

        Returns:
            CrawledContent: Created record
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

    def _update_database_safely(
        self,
        data_source: BankDataSource,
        parsed_data: Dict[str, Any],
        crawled_content: CrawledContent,
    ) -> bool:
        """
        Safely update database with parsed data.

        Args:
            data_source (BankDataSource): Data source
            parsed_data (Dict[str, Any]): Parsed data
            crawled_content (CrawledContent): Crawled content record

        Returns:
            bool: True if update was successful
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

    def _extract_actual_data(
        self, parsed_data: Dict[str, Any], bank_name: str
    ) -> Dict[str, Any]:
        """
        Extract actual data from parsed response, handling validation errors.

        Args:
            parsed_data (Dict[str, Any]): Raw parsed data
            bank_name (str): Bank name for logging

        Returns:
            Dict[str, Any]: Actual data to process
        """
        if "validation_errors" in parsed_data:
            logger.warning(
                f"Data validation issues for {bank_name}: {parsed_data['validation_errors']}"
            )
            return parsed_data.get("data", parsed_data)
        return parsed_data

    def _record_successful_update(
        self,
        crawled_content: CrawledContent,
        data_source: BankDataSource,
        updated_count: int,
    ) -> None:
        """
        Record successful database update.

        Args:
            crawled_content (CrawledContent): Content record to update
            data_source (BankDataSource): Data source
            updated_count (int): Number of cards updated
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

    def _record_parsing_failure(
        self,
        crawled_content: CrawledContent,
        actual_data: Dict[str, Any],
        data_source: BankDataSource,
    ) -> None:
        """
        Record parsing failure.

        Args:
            crawled_content (CrawledContent): Content record to update
            actual_data (Dict[str, Any]): Failed data
            data_source (BankDataSource): Data source
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

    def _record_database_failure(
        self, crawled_content: CrawledContent, data_source: BankDataSource, error: str
    ) -> None:
        """
        Record database update failure.

        Args:
            crawled_content (CrawledContent): Content record to update
            data_source (BankDataSource): Data source
            error (str): Error message
        """
        crawled_content.processing_status = "failed"
        crawled_content.error_message = f"Database update failed: {error}"
        crawled_content.save(update_fields=["processing_status", "error_message"])

        data_source.increment_failed_attempts()
        logger.error(f"Database update failed for {data_source.bank.name}: {error}")

    def _create_failed_crawl_record(
        self, data_source: BankDataSource, error_message: str
    ) -> None:
        """
        Create a failed crawl record.

        Args:
            data_source (BankDataSource): Data source
            error_message (str): Error message
        """
        CrawledContent.objects.create(
            data_source=data_source,
            processing_status="failed",
            error_message=error_message,
        )

    def _record_unexpected_error(self, data_source_id: int, error: str) -> None:
        """
        Record unexpected error during crawling.

        Args:
            data_source_id (int): Data source ID
            error (str): Error message
        """
        try:
            data_source = BankDataSource.objects.get(id=data_source_id)
            data_source.increment_failed_attempts()
            self._create_failed_crawl_record(data_source, f"Unexpected error: {error}")
        except Exception:
            logger.error(f"Failed to record error for data source {data_source_id}")
