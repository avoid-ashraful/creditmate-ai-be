import json
from unittest.mock import Mock, patch

import pytest

from banks.enums import ContentType
from banks.factories import BankDataSourceFactory, BankFactory
from banks.services import (
    BankDataCrawlerService,
    ContentExtractor,
    CreditCardDataService,
    LLMContentParser,
)
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


@pytest.mark.django_db
class TestContentExtractor:
    """Test ContentExtractor service functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.extractor = ContentExtractor()

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_pdf_content(self, mock_get):
        """Test PDF content extraction."""
        # Mock PDF response
        mock_response = Mock()
        mock_response.content = b"Mock PDF content"
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
    def test_extract_webpage_content(self, mock_get):
        """Test webpage content extraction."""
        html_content = """
        <html>
            <body>
                <h1>Credit Card Information</h1>
                <p>Annual Fee: $95</p>
                <script>alert('test');</script>
            </body>
        </html>
        """

        mock_response = Mock()
        mock_response.content = html_content.encode()
        mock_response.text = html_content
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch("banks.services.content_extractor.BeautifulSoup") as mock_bs:
            mock_soup = Mock()
            mock_soup.get_text.return_value = "Credit Card Information\nAnnual Fee: $95"
            mock_bs.return_value = mock_soup

            raw_content, extracted_content = self.extractor.extract_content(
                "http://example.com/cards.html", ContentType.WEBPAGE
            )

            assert "Credit Card Information" in extracted_content

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_csv_content(self, mock_get):
        """Test CSV content extraction."""
        csv_content = (
            "Card Name,Annual Fee,APR\nPlatinum Card,95,18.99\nGold Card,0,21.99"
        )

        mock_response = Mock()
        mock_response.content = csv_content.encode()
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        raw_content, extracted_content = self.extractor.extract_content(
            "http://example.com/cards.csv", ContentType.CSV
        )

        assert "Platinum Card" in extracted_content
        assert "95" in extracted_content

    @patch("banks.services.content_extractor.requests.Session.get")
    def test_extract_content_failure(self, mock_get):
        """Test content extraction failure handling."""
        mock_get.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            self.extractor.extract_content("http://example.com/test.pdf", ContentType.PDF)

    @pytest.mark.parametrize(
        "mime_type,expected_type",
        [
            ("application/pdf", ContentType.PDF),
            ("text/html", ContentType.WEBPAGE),
            ("image/png", ContentType.IMAGE),
            ("text/csv", ContentType.CSV),
        ],
    )
    def test_detect_content_type(self, mime_type, expected_type):
        """Test content type detection."""
        with patch("banks.services.content_extractor.magic.from_buffer") as mock_magic:
            mock_magic.return_value = mime_type
            content_type = self.extractor._detect_content_type(b"test content")
            assert content_type == expected_type


@pytest.mark.django_db
class TestLLMContentParser:
    """Test LLMContentParser service functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.parser = LLMContentParser()

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_success(self, mock_model_class):
        """Test successful credit card data parsing."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = json.dumps(
            {
                "credit_cards": [
                    {
                        "name": "Platinum Card",
                        "annual_fee": 95,
                        "interest_rate_apr": 18.99,
                        "lounge_access_international": "2 visits",
                        "lounge_access_domestic": "4 visits",
                        "cash_advance_fee": "3% of amount",
                        "late_payment_fee": "$35",
                        "annual_fee_waiver_policy": {"minimum_spend": 12000},
                        "reward_points_policy": "1 point per $1 spent",
                        "additional_features": ["Travel Insurance"],
                    }
                ]
            }
        )
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        content = "Test credit card content"
        result = self.parser.parse_credit_card_data(content, "Test Bank")

        assert isinstance(result, dict)
        # Result might have "data" or "credit_cards" key depending on validation
        if "data" in result:
            data = result["data"]
        elif "credit_cards" in result:
            data = result["credit_cards"]
        else:
            data = result

        # Data might be a list or a single item depending on processing
        if not isinstance(data, list):
            data = [data]
        assert len(data) == 1
        assert data[0]["name"] == "Platinum Card"
        assert data[0]["annual_fee"] == 95

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_invalid_json(self, mock_model_class):
        """Test handling of invalid JSON response."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = "Invalid JSON response"
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        content = "Test credit card content"

        with pytest.raises(Exception):  # Should raise AIParsingError
            self.parser.parse_credit_card_data(content, "Test Bank")

    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "")
    def test_parse_credit_card_data_no_api_key(self):
        """Test handling when Gemini API key is not configured."""
        content = "Test credit card content"

        with pytest.raises(Exception):  # Should raise ConfigurationError
            self.parser.parse_credit_card_data(content, "Test Bank")

    @patch("banks.services.llm_parser.genai.GenerativeModel")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_api_error(self, mock_model_class):
        """Test handling of Gemini API errors."""
        mock_model = Mock()
        mock_model.generate_content.side_effect = Exception("API Error")
        mock_model_class.return_value = mock_model

        content = "Test credit card content"

        with pytest.raises(Exception):  # Should raise AIParsingError
            self.parser.parse_credit_card_data(content, "Test Bank")


@pytest.mark.django_db
class TestCreditCardDataService:
    """Test CreditCardDataService functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.service = CreditCardDataService()
        self.bank = BankFactory()

    def test_update_credit_card_data_success(self):
        """Test successful credit card data update."""
        parsed_data = [
            {
                "name": "Platinum Card",
                "annual_fee": 95,
                "interest_rate_apr": 18.99,
                "lounge_access_international": 2,
                "lounge_access_domestic": 4,
                "cash_advance_fee": "3% of amount",
                "late_payment_fee": "$35",
                "annual_fee_waiver_policy": {"minimum_spend": 12000},
                "reward_points_policy": "1 point per $1 spent",
                "additional_features": ["Travel Insurance"],
            }
        ]

        updated_count = self.service.update_credit_card_data(self.bank.id, parsed_data)

        assert updated_count == 1
        assert CreditCard.objects.filter(bank=self.bank, name="Platinum Card").exists()

    def test_update_credit_card_data_update_existing(self):
        """Test updating existing credit card."""
        # Create existing card
        card = CreditCardFactory(bank=self.bank, name="Platinum Card", annual_fee=50)

        parsed_data = [
            {
                "name": "Platinum Card",
                "annual_fee": 95,
                "interest_rate_apr": 18.99,
            }
        ]

        updated_count = self.service.update_credit_card_data(self.bank.id, parsed_data)

        assert updated_count == 1
        card.refresh_from_db()
        assert float(card.annual_fee) == 95.0

    def test_update_credit_card_data_invalid_format(self):
        """Test handling of invalid data format."""
        parsed_data = {"invalid": "format"}

        updated_count = self.service.update_credit_card_data(self.bank.id, parsed_data)

        assert updated_count == 0

    @pytest.mark.parametrize(
        "value,expected",
        [
            (95, 95.0),
            (18.99, 18.99),
            ("$95.00", 95.0),
            ("18.99%", 18.99),
            ("invalid", 0.0),
        ],
    )
    def test_parse_decimal_values(self, value, expected):
        """Test decimal value parsing."""
        assert self.service._parse_decimal(value) == expected


@pytest.mark.django_db
class TestBankDataCrawlerService:
    """Test BankDataCrawlerService functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.service = BankDataCrawlerService()
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(
            bank=self.bank,
            url="http://example.com/cards.pdf",
            content_type=ContentType.PDF,
        )

    def test_crawl_bank_data_source_success(self):
        """Test successful bank data source crawling."""
        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(
                self.service.llm_parser, "parse_comprehensive_data"
            ) as mock_parse,
            patch.object(
                self.service.data_service, "update_credit_card_data"
            ) as mock_update,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.return_value = (
                [{"name": "Test Card", "annual_fee": 95}],  # structured data
                [
                    {"name": "Test Card", "annual_fee": 95, "Processing Fee": "2%"}
                ],  # raw comprehensive data
            )
            mock_update.return_value = 1

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is True
            mock_extract.assert_called_once()
            mock_parse.assert_called_once()
            mock_update.assert_called_once()

    def test_crawl_bank_data_source_not_found(self):
        """Test crawling non-existent data source."""
        result = self.service.crawl_bank_data_source(99999)
        assert result is False

    def test_crawl_bank_data_source_inactive(self):
        """Test crawling inactive data source."""
        self.data_source.is_active = False
        self.data_source.save()

        result = self.service.crawl_bank_data_source(self.data_source.id)
        assert result is False

    def test_crawl_with_extraction_failure(self):
        """Test crawling when content extraction fails."""
        with patch.object(
            self.service.content_extractor, "extract_content"
        ) as mock_extract:
            mock_extract.side_effect = Exception("Extraction failed")

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is False

            # Check that failed attempt was recorded
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 1

    def test_crawl_updates_timestamps(self):
        """Test that crawling updates timestamps correctly."""
        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(
                self.service.llm_parser, "parse_comprehensive_data"
            ) as mock_parse,
            patch.object(
                self.service.data_service, "update_credit_card_data"
            ) as mock_update,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.return_value = (
                [{"name": "Test Card", "annual_fee": 95}],  # structured data
                [
                    {"name": "Test Card", "annual_fee": 95, "Processing Fee": "2%"}
                ],  # raw comprehensive data
            )
            mock_update.return_value = 1

            initial_crawled_at = self.data_source.last_crawled_at
            initial_successful_at = self.data_source.last_successful_crawl_at

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is True
            self.data_source.refresh_from_db()
            assert self.data_source.last_crawled_at is not None
            assert self.data_source.last_successful_crawl_at is not None
            assert self.data_source.last_crawled_at != initial_crawled_at
            assert self.data_source.last_successful_crawl_at != initial_successful_at

    def test_failed_attempts_increment_and_deactivation(self):
        """Test that failed attempts are incremented and source is deactivated after 5 failures."""
        # Set up data source with 4 failed attempts
        self.data_source.failed_attempt_count = 4
        self.data_source.save()

        with patch.object(
            self.service.content_extractor, "extract_content"
        ) as mock_extract:
            mock_extract.side_effect = Exception("Extraction failed")

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is False
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 5
            assert self.data_source.is_active is False

    def test_successful_crawl_resets_failed_attempts(self):
        """Test that successful crawl resets failed attempt count."""
        # Set up data source with some failed attempts
        self.data_source.failed_attempt_count = 3
        self.data_source.save()

        with (
            patch.object(
                self.service.content_extractor, "extract_content"
            ) as mock_extract,
            patch.object(
                self.service.llm_parser, "parse_comprehensive_data"
            ) as mock_parse,
            patch.object(
                self.service.data_service, "update_credit_card_data"
            ) as mock_update,
        ):
            mock_extract.return_value = ("raw content", "extracted content")
            mock_parse.return_value = (
                [{"name": "Test Card", "annual_fee": 95}],  # structured data
                [
                    {"name": "Test Card", "annual_fee": 95, "Processing Fee": "2%"}
                ],  # raw comprehensive data
            )
            mock_update.return_value = 1

            result = self.service.crawl_bank_data_source(self.data_source.id)

            assert result is True
            self.data_source.refresh_from_db()
            assert self.data_source.failed_attempt_count == 0

    @patch("banks.models.BankDataSource.objects.filter")
    def test_crawl_all_active_sources(self, mock_filter):
        """Test crawling all active sources."""
        mock_sources = [Mock(id=1), Mock(id=2)]
        mock_queryset = Mock()
        mock_queryset.__iter__ = lambda x: iter(mock_sources)
        mock_queryset.count.return_value = 2
        mock_filter.return_value = mock_queryset

        with patch.object(self.service, "crawl_bank_data_source") as mock_crawl:
            mock_crawl.side_effect = [True, False]  # First succeeds, second fails

            results = self.service.crawl_all_active_sources()

            assert results["total"] == 2
            assert results["successful"] == 1
            assert results["failed"] == 1
