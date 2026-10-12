"""End-to-end crawler tests for quality scoring (offline, fixture driven).

The whole pipeline runs against the test database with a fake LLM provider:
content extraction -> multi-pass extraction -> validation stage -> confidence
scoring -> CrawledContent quality fields -> CreditCard rows. No live crawl, no
API key and no paid model call is involved.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from banks.enums import ProcessingStatus
from banks.factories import BankDataSourceFactory, BankFactory
from banks.models import CrawledContent
from banks.services.bank_data_crawler import BankDataCrawlerService
from banks.services.llm_parser import LLMContentParser
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from credit_cards.models import CreditCard

DOCUMENT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | "
) * 30


class FakeProvider:
    """Offline LLM stand-in returning canned JSON."""

    def __init__(self, responses, available=True):
        self.responses = list(responses)
        self.available = available
        self.prompts = []

    def is_available(self):
        return self.available

    def generate_response(self, prompt, **kwargs):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.responses) - 1)
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return {"response": response, "provider": "fake-provider"}


def build_crawler(responses, available=True):
    """Build a crawler whose parser runs the multi-pass pipeline offline."""
    extractor = MultiPassLLMExtractor(provider=FakeProvider(responses, available))
    parser = LLMContentParser(multi_pass_extractor=extractor)
    crawler = BankDataCrawlerService(
        multi_pass_extractor=extractor, llm_parser=parser
    )
    crawler.content_extractor.extract_content = MagicMock(
        return_value=("raw content", DOCUMENT)
    )
    return crawler


@pytest.mark.django_db
class TestMultiPassCrawlEndToEnd:
    """A full crawl stores cards, scores, method and pass provenance."""

    def test_successful_crawl_records_quality_fields(self):
        responses = [
            json.dumps(
                [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
            )
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(content_type="pdf")

        assert crawler.crawl_bank_data_source(source.id) is True

        content = CrawledContent.objects.get(data_source=source)
        assert content.processing_status == ProcessingStatus.COMPLETED
        assert content.extraction_method == "pdf_text"
        assert content.extraction_confidence is not None
        assert 0.0 <= content.extraction_confidence <= 1.0
        assert content.quality_scored_at is not None
        assert content.missing_critical_fields == []
        pass_names = [record["pass"] for record in content.extraction_passes]
        assert "standard" in pass_names
        assert "validation" in pass_names

        card = CreditCard.objects.get(bank=source.bank)
        assert card.annual_fee == 5000
        assert card.interest_rate_apr == 20

    def test_invalid_fee_is_stored_as_null_and_flagged(self):
        responses = [
            json.dumps([{"name": "Broken", "annual_fee": "abc", "interest_rate_apr": 20.0}])
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(content_type="pdf")

        assert crawler.crawl_bank_data_source(source.id) is True

        card = CreditCard.objects.get(bank=source.bank)
        assert card.annual_fee is None  # NULL, not 0

        content = CrawledContent.objects.get(data_source=source)
        assert "annual_fee" in content.missing_critical_fields
        assert content.needs_manual_review is True

    def test_missing_fee_is_null_and_zero_fee_is_zero(self):
        responses = [
            json.dumps(
                [
                    {"name": "No Data Card", "annual_fee": None, "interest_rate_apr": 20.0},
                    {"name": "Free Card", "annual_fee": 0, "interest_rate_apr": 18.0},
                ]
            )
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(content_type="pdf")

        assert crawler.crawl_bank_data_source(source.id) is True

        no_data = CreditCard.objects.get(bank=source.bank, name="No Data Card")
        free = CreditCard.objects.get(bank=source.bank, name="Free Card")
        assert no_data.annual_fee is None
        assert free.annual_fee == 0

        content = CrawledContent.objects.get(data_source=source)
        assert content.missing_critical_fields == ["annual_fee"]

    def test_bank_specific_prompt_is_sent(self):
        responses = [
            json.dumps([{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}])
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(
            bank=BankFactory(name="Sonali Bank PLC"), content_type="pdf"
        )

        crawler.crawl_bank_data_source(source.id)

        extractor = crawler.multi_pass_extractor
        assert extractor.provider.prompts
        assert "Sonali Bank PLC" in extractor.provider.prompts[0]

    def test_focus_pass_runs_when_first_pass_is_incomplete(self):
        responses = [
            json.dumps([{"name": "Gold", "annual_fee": None, "interest_rate_apr": None}]),
            json.dumps(
                {"cards": [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]}
            ),
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(content_type="pdf")

        assert crawler.crawl_bank_data_source(source.id) is True

        content = CrawledContent.objects.get(data_source=source)
        pass_names = [record["pass"] for record in content.extraction_passes]
        assert pass_names == ["standard", "focused", "validation"]
        card = CreditCard.objects.get(bank=source.bank)
        assert card.annual_fee == 5000

    def test_multi_pass_failure_falls_back_to_legacy_parser(self):
        """Provider failures must not break the crawl."""
        crawler = build_crawler([RuntimeError("llm exploded")])
        source = BankDataSourceFactory(content_type="pdf")

        with patch.object(
            crawler.llm_parser,
            "parse_comprehensive_data",
            return_value=(
                [{"name": "Legacy Card", "annual_fee": 95.0}],
                [{"name": "Legacy Card", "annual_fee": 95.0}],
            ),
        ) as legacy:
            assert crawler.crawl_bank_data_source(source.id) is True

        legacy.assert_called_once()
        content = CrawledContent.objects.get(data_source=source)
        assert content.extraction_confidence is not None
        assert content.extraction_passes == []  # legacy path has no provenance
        assert CreditCard.objects.get(bank=source.bank).annual_fee == 95

    def test_no_provider_uses_legacy_parser_immediately(self):
        crawler = build_crawler([], available=False)
        source = BankDataSourceFactory(content_type="pdf")

        with patch.object(
            crawler.llm_parser,
            "parse_comprehensive_data",
            return_value=(
                [{"name": "Legacy Card", "annual_fee": 0}],
                [{"name": "Legacy Card", "annual_fee": 0}],
            ),
        ) as legacy:
            assert crawler.crawl_bank_data_source(source.id) is True

        legacy.assert_called_once()
        assert crawler.multi_pass_extractor.provider.prompts == []
        card = CreditCard.objects.get(bank=source.bank)
        assert card.annual_fee == 0  # genuine zero kept

        content = CrawledContent.objects.get(data_source=source)
        assert content.extraction_confidence is not None

    def test_empty_multi_pass_result_falls_back_to_legacy(self):
        crawler = build_crawler(["[]"])
        source = BankDataSourceFactory(content_type="pdf")

        with patch.object(
            crawler.llm_parser,
            "parse_comprehensive_data",
            return_value=([{"name": "Legacy", "annual_fee": 10}], [{"name": "Legacy"}]),
        ) as legacy:
            assert crawler.crawl_bank_data_source(source.id) is True

        legacy.assert_called_once()


@pytest.mark.django_db
class TestLegacyCrawlStillScores:
    """The legacy path (no provider) also produces quality fields."""

    def test_legacy_crawl_gets_confidence_and_method(self):
        crawler = BankDataCrawlerService()
        source = BankDataSourceFactory(content_type="webpage")

        with (
            patch.object(
                crawler.content_extractor,
                "extract_content",
                return_value=("raw", DOCUMENT),
            ),
            patch.object(
                crawler.llm_parser,
                "parse_comprehensive_data",
                return_value=(
                    [{"name": "Web Card", "annual_fee": 5000, "interest_rate_apr": 20.0}],
                    [{"name": "Web Card", "annual_fee": 5000}],
                ),
            ),
        ):
            assert crawler.crawl_bank_data_source(source.id) is True

        content = CrawledContent.objects.get(data_source=source)
        assert content.extraction_method == "webpage"
        assert 0.0 <= content.extraction_confidence <= 1.0
        assert content.quality_scored_at is not None
        assert content.needs_manual_review is False

    def test_multi_source_rescue_when_primary_extraction_fails(self):
        """Phase 3: a failed primary extraction is rescued by multi-source."""
        from banks.exceptions import ContentExtractionError

        crawler = BankDataCrawlerService()
        source = BankDataSourceFactory(content_type="pdf")

        rescue_result = {
            "raw_content": "<BINARY_CONTENT_PDF_SIZE_10>",
            "content": DOCUMENT,
            "confidence": 0.75,
            "method": "ocr",
            "attempts": [
                {"method": "pdf_text", "content": "", "confidence": 0.0, "error": "x"},
                {"method": "ocr", "content": DOCUMENT, "confidence": 0.75, "error": None},
            ],
        }

        with (
            patch.object(
                crawler.content_extractor,
                "extract_content",
                side_effect=ContentExtractionError("no text layer", {}),
            ),
            patch.object(
                crawler.content_extractor,
                "extract_with_validation",
                return_value=rescue_result,
            ),
            patch.object(
                crawler.llm_parser,
                "parse_comprehensive_data",
                return_value=(
                    [{"name": "Rescued", "annual_fee": 100, "interest_rate_apr": 15.0}],
                    [{"name": "Rescued", "annual_fee": 100}],
                ),
            ),
        ):
            assert crawler.crawl_bank_data_source(source.id) is True

        content = CrawledContent.objects.get(data_source=source)
        assert content.extraction_method == "ocr"
        assert content.extracted_content == DOCUMENT
