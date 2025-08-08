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
        # Mock requests to avoid import errors during testing
        with patch("banks.services.content_extractor.requests") as mock_requests:
            mock_session = Mock()
            mock_requests.Session.return_value = mock_session
            self.extractor = ContentExtractor()
            self.extractor.session = mock_session

    def test_extract_pdf_content(self):
        """Test PDF content extraction."""
        # Mock PDF response
        mock_response = Mock()
        mock_response.content = b"Mock PDF content"
        mock_response.raise_for_status.return_value = None
        self.extractor.session.get.return_value = mock_response

        with patch("banks.services.content_extractor.PdfReader") as mock_pdf_reader:
            mock_page = Mock()
            mock_page.extract_text.return_value = "Extracted PDF text"
            mock_pdf_reader.return_value.pages = [mock_page]

            raw_content, extracted_content = self.extractor.extract_content(
                "http://example.com/test.pdf", ContentType.PDF
            )

            assert extracted_content == "Extracted PDF text"
            mock_pdf_reader.assert_called_once()

    def test_extract_webpage_content(self):
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
        self.extractor.session.get.return_value = mock_response

        with patch("banks.services.content_extractor.BeautifulSoup") as mock_bs:
            mock_soup = Mock()
            mock_soup.get_text.return_value = "Credit Card Information\nAnnual Fee: $95"
            mock_bs.return_value = mock_soup

            raw_content, extracted_content = self.extractor.extract_content(
                "http://example.com/cards.html", ContentType.WEBPAGE
            )

            assert "Credit Card Information" in extracted_content

    def test_extract_csv_content(self):
        """Test CSV content extraction."""
        csv_content = (
            "Card Name,Annual Fee,APR\nPlatinum Card,95,18.99\nGold Card,0,21.99"
        )

        mock_response = Mock()
        mock_response.content = csv_content.encode()
        mock_response.raise_for_status.return_value = None
        self.extractor.session.get.return_value = mock_response

        raw_content, extracted_content = self.extractor.extract_content(
            "http://example.com/cards.csv", ContentType.CSV
        )

        assert "Platinum Card" in extracted_content
        assert "95" in extracted_content

    def test_extract_content_failure(self):
        """Test content extraction failure handling."""
        self.extractor.session.get.side_effect = Exception("Network error")

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
        with patch("banks.services.content_extractor.magic") as mock_magic:
            mock_magic.from_buffer.return_value = mime_type
            content_type = self.extractor._detect_content_type(b"test content")
            assert content_type == expected_type


@pytest.mark.django_db
class TestLLMContentParser:
    """Test LLMContentParser service functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.parser = LLMContentParser()

    @patch("banks.services.llm_parser.genai")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_success(self, mock_genai):
        """Test successful credit card data parsing."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = json.dumps(
            [
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
        )
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        content = "Test credit card content"
        result = self.parser.parse_credit_card_data(content, "Test Bank")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "Platinum Card"
        assert result[0]["annual_fee"] == 95

    @patch("banks.services.llm_parser.genai")
    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "test-key")
    def test_parse_credit_card_data_invalid_json(self, mock_genai):
        """Test handling of invalid JSON response."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = "Invalid JSON response"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        content = "Test credit card content"
        with pytest.raises(Exception):  # Should raise AIParsingError
            self.parser.parse_credit_card_data(content, "Test Bank")

    def test_parse_credit_card_data_no_genai(self):
        """Test handling when Gemini AI is not available."""
        with patch("banks.services.llm_parser.genai", None):
            parser = LLMContentParser()
            content = "Test credit card content"
            with pytest.raises(Exception):  # Should raise ConfigurationError
                parser.parse_credit_card_data(content, "Test Bank")

    @patch("banks.services.llm_parser.settings.GEMINI_API_KEY", "")
    def test_parse_credit_card_data_no_api_key(self):
        """Test handling when Gemini API key is not configured."""
        content = "Test credit card content"
        with pytest.raises(Exception):  # Should raise ConfigurationError
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
        # Mock the services to avoid import errors during testing
        with (
            patch(
                "banks.services.content_extractor.ContentExtractor"
            ) as mock_extractor_class,
            patch("banks.services.llm_parser.LLMContentParser") as mock_parser_class,
            patch(
                "banks.services.credit_card_data_service.CreditCardDataService"
            ) as mock_data_service_class,
        ):
            mock_extractor_class.return_value = Mock()
            mock_parser_class.return_value = Mock()
            mock_data_service_class.return_value = Mock()

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
