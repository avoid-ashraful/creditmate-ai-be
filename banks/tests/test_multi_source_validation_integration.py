"""Integration tests for multi-source validation with the data model.

Uses the factories and the real crawler pipeline against the test database.
No live crawling: the crawler's content extraction and LLM parsing are mocked,
exactly like the existing crawler-quality integration tests.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from banks.enums import ProcessingStatus, SourceType
from banks.factories import BankDataSourceFactory, BankFactory, CrawledContentFactory
from banks.models import CrawledContent
from banks.services.bank_data_crawler import BankDataCrawlerService
from banks.services.llm_parser import LLMContentParser
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from banks.services.multi_source_validation import (
    STATUS_AGREEMENT,
    STATUS_CONFLICT,
    STATUS_SINGLE_SOURCE,
)
from banks.services.validation_collectors import (
    content_type_to_source_type,
    latest_observations_for_bank,
    observations_from_crawled_content,
    observations_from_user_submissions,
    run_multi_source_validation,
    validate_crawled_content,
)
from credit_cards.models import CreditCard

DOCUMENT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | "
) * 30


class FakeProvider:
    """Offline LLM stand-in returning canned JSON (see crawler e2e tests)."""

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
    """Build a crawler whose parser runs the offline multi-pass pipeline."""
    extractor = MultiPassLLMExtractor(provider=FakeProvider(responses, available))
    parser = LLMContentParser(multi_pass_extractor=extractor)
    crawler = BankDataCrawlerService(multi_pass_extractor=extractor, llm_parser=parser)
    crawler.content_extractor.extract_content = MagicMock(
        return_value=("raw content", DOCUMENT)
    )
    return crawler


def completed_content(parsed_json, **overrides):
    """Create a completed CrawledContent row with deterministic card JSON."""
    defaults = {
        "parsed_json": parsed_json,
        "processing_status": ProcessingStatus.COMPLETED,
        "extraction_confidence": 0.8,
        "extraction_method": "pdf_text",
    }
    defaults.update(overrides)
    return CrawledContentFactory(**defaults)


@pytest.mark.django_db
class TestCollectors:
    """Observations are built with explicit source provenance."""

    def test_content_type_maps_to_source_type(self):
        assert content_type_to_source_type("webpage") == SourceType.BANK_WEBSITE
        assert content_type_to_source_type("pdf") == SourceType.BANK_PDF
        assert content_type_to_source_type("csv") == SourceType.BANK_CSV
        assert content_type_to_source_type("image") == SourceType.BANK_IMAGE

    def test_observations_from_crawled_content(self):
        pdf = BankDataSourceFactory(content_type="pdf")
        content = completed_content(
            {
                "credit_cards": [
                    {
                        "name": "Gold",
                        "annual_fee": "TK 5,000",
                        "interest_rate_apr": 20,
                        "reward_points_policy": "long prose",
                    },
                ]
            },
            data_source=pdf,
            extraction_confidence=0.77,
        )
        observations = observations_from_crawled_content(content)
        assert observations
        for observation in observations:
            assert observation.source_key == content.data_source.url
            assert observation.source_type == SourceType.BANK_PDF
            assert observation.card_key == "Gold"
            assert observation.bank_key == content.data_source.bank.name
            assert observation.confidence == 0.77
        # Free-text fields are excluded from cross-source comparison.
        assert not any(obs.field == "reward_points_policy" for obs in observations)
        assert {obs.field for obs in observations} >= {"annual_fee", "interest_rate_apr"}

    def test_unnamed_card_uses_positional_identity(self):
        content = completed_content({"credit_cards": [{"annual_fee": 95}]})
        observations = observations_from_crawled_content(content)
        assert observations
        assert all(obs.card_key == "card-1" for obs in observations)

    def test_latest_observations_per_source(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")
        completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=pdf,
        )
        completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=web,
        )
        observations = latest_observations_for_bank(bank)
        source_keys = {obs.source_key for obs in observations}
        assert source_keys == {pdf.url, web.url}

    def test_user_submission_observations(self):
        observations = observations_from_user_submissions(
            [
                {
                    "bank_key": "Acme Bank",
                    "card_key": "Gold",
                    "field": "annual_fee",
                    "value": 5000,
                    "confidence": 0.4,
                },
                {
                    "card_key": "Platinum",
                    "field": "late_payment_fee",
                    "value": "700 BDT",
                },
            ]
        )
        assert len(observations) == 2
        assert observations[0].source_type == SourceType.USER_SUBMISSION
        assert observations[0].source_key == "submission-1"
        assert observations[0].card_key == "Gold"
        assert observations[1].source_key == "submission-2"

    def test_user_submission_without_card_is_dropped(self):
        observations = observations_from_user_submissions(
            [{"field": "annual_fee", "value": 5000}]
        )
        assert observations == []


@pytest.mark.django_db
class TestCrossSourceAgreement:
    """Website + PDF observations for the same card agree and boost."""

    def test_validate_crawled_content_finds_agreement(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")
        pdf_content = completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": "TK 5,000", "interest_rate_apr": 20}
                ]
            },
            data_source=pdf,
        )
        completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=web,
        )

        batch = validate_crawled_content(pdf_content)
        batch_field = batch.cards[0].fields["annual_fee"]
        assert batch_field.status == STATUS_AGREEMENT
        assert batch_field.agreed_value == 5000.0
        assert batch_field.source_type_counts == {
            SourceType.BANK_PDF: 1,
            SourceType.BANK_WEBSITE: 1,
        }
        assert batch_field.confidence_boost > 0
        assert batch.needs_manual_review is False

    def test_run_multi_source_validation_persists_summary(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")
        pdf_content = completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=pdf,
        )
        completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=web,
        )

        run_multi_source_validation(pdf_content)
        pdf_content.refresh_from_db()
        summary = pdf_content.multi_source_validation
        assert summary is not None
        assert summary["needs_manual_review"] is False
        assert summary["cards"][0]["fields"]["annual_fee"]["status"] == STATUS_AGREEMENT


@pytest.mark.django_db
class TestCrossSourceConflict:
    """Conflicting independent sources flag the record for manual review."""

    def test_validate_crawled_content_finds_conflict(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")
        pdf_content = completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=pdf,
        )
        completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 6000, "interest_rate_apr": 20}
                ]
            },
            data_source=web,
        )

        batch = validate_crawled_content(pdf_content)
        batch_field = batch.cards[0].fields["annual_fee"]
        assert batch_field.status == STATUS_CONFLICT
        assert batch.needs_manual_review is True

    def test_conflict_from_user_submission_flags_review(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        pdf_content = completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=pdf,
        )
        run_multi_source_validation(
            pdf_content,
            user_submissions=[
                {
                    "bank_key": bank.name,
                    "card_key": "Gold",
                    "field": "annual_fee",
                    "value": 7500,
                },
            ],
        )
        pdf_content.refresh_from_db()
        assert pdf_content.needs_manual_review is True
        summary = pdf_content.multi_source_validation
        assert summary["conflict_field_count"] == 1
        field_summary = summary["cards"][0]["fields"]["annual_fee"]
        assert field_summary["status"] == STATUS_CONFLICT
        assert {conflict["value"] for conflict in field_summary["conflicts"]} == {
            5000.0,
            7500.0,
        }

    def test_missing_fee_does_not_conflict(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")
        pdf_content = completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20}
                ]
            },
            data_source=pdf,
        )
        completed_content(
            {
                "credit_cards": [
                    {"name": "Gold", "annual_fee": None, "interest_rate_apr": 20}
                ]
            },
            data_source=web,
        )
        batch = validate_crawled_content(pdf_content)
        batch_field = batch.cards[0].fields["annual_fee"]
        assert batch_field.status == STATUS_SINGLE_SOURCE
        assert batch.needs_manual_review is False


@pytest.mark.django_db
class TestCrawlerIntegration:
    """The enhanced crawler flags a real cross-source conflict end to end."""

    def test_second_crawling_source_flags_conflict_for_review(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")

        crawler_one = build_crawler(
            [
                json.dumps(
                    [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
                )
            ]
        )
        assert crawler_one.crawl_bank_data_source(pdf.id) is True

        crawler_two = build_crawler(
            [
                json.dumps(
                    [{"name": "Gold", "annual_fee": 6000, "interest_rate_apr": 20.0}]
                )
            ]
        )
        assert crawler_two.crawl_bank_data_source(web.id) is True

        contents = CrawledContent.objects.filter(data_source__bank=bank).order_by(
            "crawled_at"
        )
        assert contents.count() == 2
        first, second = contents
        # A single independent source does not trigger review...
        assert first.needs_manual_review is False
        assert first.multi_source_validation == {}
        # ...but the second source now conflicts with the first, so it is
        # flagged and the conflict details are persisted.
        assert second.needs_manual_review is True
        summary = second.multi_source_validation
        assert summary["needs_manual_review"] is True
        assert summary["conflict_field_count"] >= 1
        assert summary["cards"][0]["fields"]["annual_fee"]["status"] == STATUS_CONFLICT

    def test_agreeing_crawl_stays_out_of_review(self):
        bank = BankFactory()
        pdf = BankDataSourceFactory(bank=bank, content_type="pdf")
        web = BankDataSourceFactory(bank=bank, content_type="webpage")

        crawler_one = build_crawler(
            [
                json.dumps(
                    [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
                )
            ]
        )
        assert crawler_one.crawl_bank_data_source(pdf.id) is True

        crawler_two = build_crawler(
            [
                json.dumps(
                    [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
                )
            ]
        )
        assert crawler_two.crawl_bank_data_source(web.id) is True

        second = CrawledContent.objects.filter(data_source__bank=bank).latest(
            "crawled_at"
        )
        assert second.needs_manual_review is False
        summary = second.multi_source_validation
        assert summary["cards"][0]["fields"]["annual_fee"]["status"] == STATUS_AGREEMENT
        assert summary["cards"][0]["fields"]["annual_fee"]["confidence_boost"] > 0

    @patch(
        "banks.services.validation_collectors.run_multi_source_validation",
        side_effect=RuntimeError("boom"),
    )
    def test_failing_validation_never_breaks_the_crawl(self, _mock_validation):
        crawler = build_crawler(
            [
                json.dumps(
                    [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
                )
            ]
        )
        source = BankDataSourceFactory(content_type="pdf")
        assert crawler.crawl_bank_data_source(source.id) is True
        content = CrawledContent.objects.get(data_source=source)
        assert content.processing_status == ProcessingStatus.COMPLETED
        assert CreditCard.objects.get(bank=source.bank).annual_fee == 5000
