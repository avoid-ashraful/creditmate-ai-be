"""
Comprehensive tests for banks services with all new features.
"""

import hashlib
import json
from unittest.mock import Mock, patch

import pytest

from banks.enums import ContentType
from banks.exceptions import (
    AIParsingError,
    ConfigurationError,
    ContentExtractionError,
    FileFormatError,
    NetworkError,
)
from banks.factories import BankDataSourceFactory, BankFactory, CrawledContentFactory
from banks.models import CrawledContent
from banks.services import (
    BankDataCrawlerService,
    ContentExtractor,
    LLMContentParser,
    ScheduleChargeURLFinder,
)
from banks.validators import CreditCardDataValidator


@pytest.mark.django_db
class TestContentExtractorUpdated:
    """Test ContentExtractor with improved error handling."""

    def setup_method(self):
        self.extractor = ContentExtractor()

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_success(self, mock_get):
        """Test successful content extraction."""
        mock_response = Mock()
        mock_response.content = b"Test PDF content"
        mock_response.text = "Test HTML content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch("banks.services.content_extractor.PdfReader") as mock_pdf_reader:
            mock_page = Mock()
            mock_page.extract_text.return_value = "Extracted PDF text"
            mock_pdf_reader.return_value.pages = [mock_page]

            raw_content, extracted_content = self.extractor.extract_content(
                "http://example.com/test.pdf", ContentType.PDF
            )

            assert extracted_content == "Extracted PDF text"
            mock_pdf_reader.assert_called_once()

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_timeout_error(self, mock_get):
        """Test timeout error handling."""
        import requests

        mock_get.side_effect = requests.exceptions.Timeout("Timeout error")

        with pytest.raises(NetworkError) as exc_info:
            self.extractor.extract_content("http://example.com/slow.pdf", ContentType.PDF)

        assert "Timeout while fetching" in str(exc_info.value)
        assert exc_info.value.details["url"] == "http://example.com/slow.pdf"
        assert exc_info.value.details["timeout"] == 30

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_connection_error(self, mock_get):
        """Test connection error handling."""
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with pytest.raises(NetworkError) as exc_info:
            self.extractor.extract_content("http://example.com/test.pdf", ContentType.PDF)

        assert "Connection error while fetching" in str(exc_info.value)

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_404_error(self, mock_get):
        """Test 404 error handling."""
        import requests

        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.side_effect = requests.exceptions.HTTPError(response=mock_response)

        with pytest.raises(ContentExtractionError) as exc_info:
            self.extractor.extract_content(
                "http://example.com/missing.pdf", ContentType.PDF
            )

        assert "URL not found" in str(exc_info.value)
        assert exc_info.value.details["status_code"] == 404

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_server_error(self, mock_get):
        """Test server error handling."""
        import requests

        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.side_effect = requests.exceptions.HTTPError(response=mock_response)

        with pytest.raises(NetworkError) as exc_info:
            self.extractor.extract_content(
                "http://example.com/error.pdf", ContentType.PDF
            )

        assert "Server error" in str(exc_info.value)
        assert exc_info.value.details["status_code"] == 500

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_unknown_type_error(self, mock_get):
        """Test handling of unknown content types."""
        mock_response = Mock()
        mock_response.content = b"Unknown content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch.object(self.extractor, "_detect_content_type", return_value=None):
            with pytest.raises(FileFormatError) as exc_info:
                self.extractor.extract_content("http://example.com/unknown", "UNKNOWN")

            assert "Unable to detect content type" in str(exc_info.value)


@pytest.mark.django_db
class TestLLMContentParserUpdated:
    """Test LLMContentParser with improved error handling and validation."""

    def setup_method(self):
        self.parser = LLMContentParser()

    def test_parse_credit_card_data_missing_genai(self):
        """Test handling when genai is not available."""
        with patch("banks.services.llm_parser.genai", None):
            parser = LLMContentParser()

            with pytest.raises(ConfigurationError) as exc_info:
                parser.parse_credit_card_data("test content", "Test Bank")

            assert "Google Generative AI library not installed" in str(exc_info.value)

    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "")
    def test_parse_credit_card_data_missing_api_key(self):
        """Test handling when API key is not configured."""
        with pytest.raises(ConfigurationError) as exc_info:
            self.parser.parse_credit_card_data("test content", "Test Bank")

        assert "Gemini API key not configured" in str(exc_info.value)

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_success_with_validation(self, mock_model_class):
        """Test successful parsing with data validation."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = json.dumps(
            [
                {
                    "name": "Test Card",
                    "annual_fee": 95,
                    "interest_rate_apr": 18.99,
                    "lounge_access_international": 2,
                    "lounge_access_domestic": 4,
                    "cash_advance_fee": "3% of amount",
                    "late_payment_fee": "$25",
                    "annual_fee_waiver_policy": {"minimum_spend": 5000},
                    "reward_points_policy": "1 point per $1 spent",
                    "additional_features": ["Travel Insurance"],
                }
            ]
        )
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        content = "Test credit card content"
        result = self.parser.parse_credit_card_data(content, "Test Bank")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "Test Card"
        assert result[0]["annual_fee"] == 95.0  # Should be sanitized to float

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_validation_errors(self, mock_model_class):
        """Test handling of validation errors."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = json.dumps(
            [
                {
                    "name": "",  # Invalid: empty name
                    "annual_fee": -50,  # Invalid: negative fee
                    "interest_rate_apr": 150,  # Invalid: unrealistic APR
                }
            ]
        )
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        content = "Test content with invalid data"
        result = self.parser.parse_credit_card_data(content, "Test Bank")

        assert "validation_errors" in result
        assert "data" in result
        assert len(result["validation_errors"]) > 0

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_empty_response(self, mock_model_class):
        """Test handling of empty AI response."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = ""
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        with pytest.raises(AIParsingError) as exc_info:
            self.parser.parse_credit_card_data("test content", "Test Bank")

        assert "Empty response from Gemini API" in str(exc_info.value)

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_invalid_json(self, mock_model_class):
        """Test handling of invalid JSON response."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = "Invalid JSON response"
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        with pytest.raises(AIParsingError) as exc_info:
            self.parser.parse_credit_card_data("test content", "Test Bank")

        assert "Invalid JSON response from Gemini API" in str(exc_info.value)
        assert "raw_response" in exc_info.value.details

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_markdown_cleanup(self, mock_model_class):
        """Test cleanup of markdown code blocks."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = '```json\n[{"name": "Test Card", "annual_fee": 0}]\n```'
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        result = self.parser.parse_credit_card_data("test content", "Test Bank")

        assert isinstance(result, list)
        assert result[0]["name"] == "Test Card"


@pytest.mark.django_db
class TestCreditCardDataValidatorNew:
    """Test the new CreditCardDataValidator."""

    def test_validate_credit_card_data_valid(self):
        """Test validation of valid credit card data."""
        data = [
            {
                "name": "Test Card",
                "annual_fee": 95,
                "interest_rate_apr": 18.99,
                "lounge_access_international": 2,
                "lounge_access_domestic": 4,
                "cash_advance_fee": "3% of amount",
                "late_payment_fee": "$25",
                "annual_fee_waiver_policy": {"minimum_spend": 5000},
                "reward_points_policy": "1 point per $1 spent",
                "additional_features": ["Travel Insurance"],
            }
        ]

        is_valid, errors = CreditCardDataValidator.validate_credit_card_data(data)
        assert is_valid
        assert len(errors) == 0

    def test_validate_credit_card_data_invalid(self):
        """Test validation of invalid credit card data."""
        data = [
            {
                "name": "",  # Invalid: empty name
                "annual_fee": -50,  # Invalid: negative fee
                "interest_rate_apr": 150,  # Invalid: unrealistic APR
                "lounge_access_international": -1,  # Invalid: negative
                "additional_features": "not a list",  # Invalid: should be list
            }
        ]

        is_valid, errors = CreditCardDataValidator.validate_credit_card_data(data)
        assert not is_valid
        assert len(errors) > 0
        assert any("name is required" in error for error in errors)
        assert any("negative" in error for error in errors)

    def test_sanitize_credit_card_data(self):
        """Test data sanitization."""
        data = [
            {
                "name": "  Test Card  ",  # Should be trimmed
                "annual_fee": "95.50",  # Should be converted to float
                "interest_rate_apr": "18.99%",  # Should remove %
                "lounge_access_international": "2.7",  # Should be converted to int
                "additional_features": [
                    "  Feature 1  ",
                    "",
                    "Feature 2",
                ],  # Should be cleaned
            }
        ]

        sanitized = CreditCardDataValidator.sanitize_credit_card_data(data)

        assert sanitized[0]["name"] == "Test Card"
        assert sanitized[0]["annual_fee"] == 95.5
        assert sanitized[0]["lounge_access_international"] == 2
        assert sanitized[0]["additional_features"] == ["Feature 1", "Feature 2"]


@pytest.mark.django_db
class TestBankDataCrawlerServiceUpdated:
    """Test BankDataCrawlerService with all new features."""

    def setup_method(self):
        self.service = BankDataCrawlerService()
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(
            bank=self.bank,
            url="http://example.com/cards.pdf",
            content_type=ContentType.PDF,
        )

    def test_crawl_bank_data_source_no_changes_detected(self):
        """Test crawling when no changes are detected."""
        # Create existing crawled content with hash
        test_content = "Test extracted content"
        content_hash = hashlib.sha256(test_content.encode("utf-8")).hexdigest()

        CrawledContentFactory(
            data_source=self.data_source,
            content_hash=content_hash,
            processing_status="completed",
        )

        with patch.object(
            self.service.content_extractor, "extract_content"
        ) as mock_extract:
            mock_extract.return_value = ("raw content", test_content)

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is True
            # Should not call LLM parser when no changes detected
            mock_extract.assert_called_once()

            # Should create a new record indicating no changes
            latest_crawl = (
                CrawledContent.objects.filter(data_source=self.data_source)
                .order_by("-crawl_date")
                .first()
            )

            assert latest_crawl.parsed_json == {"skipped": "no_changes_detected"}

    def test_crawl_bank_data_source_content_extraction_error(self):
        """Test handling of content extraction errors."""
        with patch.object(
            self.service.content_extractor, "extract_content"
        ) as mock_extract:
            mock_extract.side_effect = ContentExtractionError(
                "Extraction failed", {"url": self.data_source.url}
            )

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is False

            # Should increment failed attempts
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 1

            # Should create failed crawl record
            crawl_record = CrawledContent.objects.filter(
                data_source=self.data_source, processing_status="failed"
            ).first()
            assert crawl_record is not None
            assert "Extraction failed" in crawl_record.error_message

    def test_crawl_bank_data_source_ai_parsing_error(self):
        """Test handling of AI parsing errors."""
        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(self.service.llm_parser, "parse_credit_card_data") as mock_parse,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.side_effect = AIParsingError(
                "AI parsing failed", {"bank_name": self.bank.name}
            )

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is False

            # Should increment failed attempts for AI errors
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 1

    def test_crawl_bank_data_source_configuration_error(self):
        """Test handling of configuration errors."""
        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(self.service.llm_parser, "parse_credit_card_data") as mock_parse,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.side_effect = ConfigurationError("Missing API key")

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is False

            # Should NOT increment failed attempts for configuration errors
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 0

    def test_crawl_bank_data_source_validation_errors_but_success(self):
        """Test handling when data has validation errors but processing continues."""
        parsed_data_with_errors = {
            "validation_errors": ["Some validation issue"],
            "data": [{"name": "Test Card", "annual_fee": 95}],
        }

        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(self.service.llm_parser, "parse_credit_card_data") as mock_parse,
            patch.object(
                self.service.data_service, "update_credit_card_data"
            ) as mock_update,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.return_value = parsed_data_with_errors
            mock_update.return_value = 1

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is True
            # Should use the data despite validation errors
            mock_update.assert_called_once_with(
                self.bank.id, [{"name": "Test Card", "annual_fee": 95}]
            )

    def test_crawl_bank_data_source_database_update_error(self):
        """Test handling of database update errors."""
        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(self.service.llm_parser, "parse_credit_card_data") as mock_parse,
            patch.object(
                self.service.data_service, "update_credit_card_data"
            ) as mock_update,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.return_value = [{"name": "Test Card", "annual_fee": 95}]
            mock_update.side_effect = Exception("Database error")

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is False

            # Should increment failed attempts
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 1

            # Should record the database error
            crawl_record = CrawledContent.objects.filter(
                data_source=self.data_source, processing_status="failed"
            ).first()
            assert "Database update failed" in crawl_record.error_message

    def test_crawl_bank_data_source_success_with_changes(self):
        """Test successful crawling with content changes."""
        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(self.service.llm_parser, "parse_credit_card_data") as mock_parse,
            patch.object(
                self.service.data_service, "update_credit_card_data"
            ) as mock_update,
        ):
            mock_extract.return_value = ("raw content", "new extracted content")
            mock_parse.return_value = [{"name": "Test Card", "annual_fee": 95}]
            mock_update.return_value = 1

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is True

            # Should reset failed attempts on success
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 0
            assert self.data_source.last_successful_crawl_at is not None

            # Should create successful crawl record with hash
            crawl_record = CrawledContent.objects.filter(
                data_source=self.data_source, processing_status="completed"
            ).first()
            assert crawl_record.content_hash
            assert crawl_record.extracted_content == "new extracted content"


@pytest.mark.django_db
class TestScheduleChargeURLFinderUpdated:
    """Test ScheduleChargeURLFinder with better error handling."""

    def setup_method(self):
        self.finder = ScheduleChargeURLFinder()

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_find_schedule_charge_url_network_error(self, mock_get):
        """Test handling of network errors."""
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        result = self.finder.find_schedule_charge_url("http://example.com")

        assert result["found"] is False
        assert result["method"] == "error"
        assert "Connection failed" in result["error"]

    @patch("banks.services.content_extractor.requests.Session.get")
    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_find_schedule_charge_url_success_current_page(
        self, mock_model_class, mock_get
    ):
        """Test successful detection of charges on current page."""
        html_content = """
        <html>
            <body>
                <h1>Credit Card Fees</h1>
                <p>Annual Fee: $95</p>
                <p>Interest Rate: 18.99% APR</p>
            </body>
        </html>
        """

        mock_response = Mock()
        mock_response.text = html_content
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        mock_model = Mock()
        mock_ai_response = Mock()
        mock_ai_response.text = "current_page"
        mock_model.generate_content.return_value = mock_ai_response
        mock_model_class.return_value = mock_model

        with patch("banks.services.schedule_charge_finder.BeautifulSoup") as mock_bs:
            mock_soup = Mock()
            mock_soup.find_all.return_value = []
            mock_soup.get_text.return_value = html_content
            mock_bs.return_value = mock_soup

            result = self.finder.find_schedule_charge_url("http://example.com")

            assert result["found"] is True
            assert result["url"] == "http://example.com"
            assert result["content_type"] == "WEBPAGE"
            assert result["note"] == "Charges displayed directly on the webpage"

    @patch("banks.services.schedule_charge_finder.requests.Session.get")
    @patch("banks.services.schedule_charge_finder.genai.GenerativeModel")
    @patch("banks.services.schedule_charge_finder.settings.GEMINI_API_KEY", "test-key")
    def test_find_schedule_charge_url_success_pdf_link(self, mock_model_class, mock_get):
        """Test successful detection of PDF link."""
        html_content = "<html><body><a href='/charges.pdf'>Fee Schedule</a></body></html>"

        mock_response = Mock()
        mock_response.text = html_content
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        mock_model = Mock()
        mock_ai_response = Mock()
        mock_ai_response.text = "http://example.com/charges.pdf"
        mock_model.generate_content.return_value = mock_ai_response
        mock_model_class.return_value = mock_model

        with patch("banks.services.schedule_charge_finder.BeautifulSoup") as mock_bs:
            mock_soup = Mock()
            mock_link = Mock()
            mock_link.get.side_effect = lambda attr, default=None: (
                "/charges.pdf" if attr == "href" else (default or "Fee Schedule")
            )
            mock_link.get_text.return_value = "Fee Schedule"
            mock_soup.find_all.return_value = [mock_link]
            mock_soup.get_text.return_value = html_content
            mock_bs.return_value = mock_soup

            result = self.finder.find_schedule_charge_url("http://example.com")

            assert result["found"] is True
            assert result["url"] == "http://example.com/charges.pdf"
            assert result["content_type"] == "PDF"
