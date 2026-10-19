"""Offline regressions for quota deferral, extraction provenance and OCR noise."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from banks.exceptions import ContentExtractionError
from banks.factories import BankDataSourceFactory, BankFactory
from banks.models import CrawledContent, ReviewQueue
from banks.services.bank_data_crawler import BankDataCrawlerService
from banks.services.content_extractor import ContentExtractor
from banks.services.extraction_provider import OrchestratorExtractionProvider
from banks.services.llm_failures import rate_limit_state
from banks.services.llm_parser import LLMContentParser
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from common.llm.exceptions import AllLLMProvidersFailedError, LLMRateLimitError
from common.llm.services import LLMOrchestrator
from credit_cards.models import CreditCard


def fake_crawler(parser=None, content="annual fee BDT 1000 credit card charges 25%"):
    """Build a crawler with no network or vendor client calls."""
    extractor = MagicMock()
    extractor.extract_content.return_value = ("raw", content)
    multi = MagicMock()
    multi.is_provider_available.return_value = True
    return BankDataCrawlerService(
        content_extractor=extractor,
        llm_parser=parser or MagicMock(),
        multi_pass_extractor=multi,
    )


@pytest.mark.django_db
class TestQuotaDeferral:
    @pytest.mark.parametrize("stage", ["multi", "legacy"])
    @pytest.mark.parametrize(
        "failure", [LLMRateLimitError("quota exceeded"), "HTTP 429", "RESOURCE_EXHAUSTED"]
    )
    def test_quota_keeps_source_healthy_and_stops_run(self, stage, failure):
        sources = [BankDataSourceFactory(failed_attempt_count=4) for _ in range(3)]
        crawler = fake_crawler()
        if stage == "multi":
            crawler.llm_parser.parse_with_multi_pass.side_effect = (
                AllLLMProvidersFailedError(failures={"fake": failure})
            )
        else:
            crawler.multi_pass_extractor.is_provider_available.return_value = False
            crawler.llm_parser.parse_comprehensive_data.side_effect = (
                AllLLMProvidersFailedError(failures={"fake": failure})
            )
        assert crawler.crawl_sources(sources) == {
            "total": 3,
            "successful": 0,
            "failed": 0,
            "skipped": 3,
        }
        for source in sources:
            source.refresh_from_db()
            assert source.failed_attempt_count == 4
            assert source.is_active
        assert crawler.content_extractor.extract_content.call_count == 1
        record = CrawledContent.objects.get()
        assert record.processing_status == "pending"
        assert record.parsed_json["reason"] == "rate_limited"
        if stage == "multi":
            crawler.llm_parser.parse_comprehensive_data.assert_not_called()

    def test_real_orchestrator_rate_limit_does_not_reach_focused_or_legacy_pass(self):
        provider = MagicMock()
        provider.is_available.return_value = True
        provider.generate_response.side_effect = LLMRateLimitError("429 quota")
        orchestrator = LLMOrchestrator(providers=[])
        orchestrator.providers = {"fake": provider}
        multi = MultiPassLLMExtractor(
            provider=OrchestratorExtractionProvider(orchestrator)
        )
        parser = LLMContentParser(multi_pass_extractor=multi)
        crawler = fake_crawler(parser=parser)
        sources = [BankDataSourceFactory() for _ in range(2)]
        assert crawler.crawl_sources(sources)["skipped"] == 2
        assert provider.generate_response.call_count == 1

    def test_mixed_failures_defer_source_without_claiming_all_providers_are_limited(self):
        error = AllLLMProvidersFailedError(
            failures={"one": "429", "two": "connection refused"}
        )
        assert rate_limit_state(error) == (True, False)

    def test_ordinary_parse_error_still_counts_as_failure(self):
        from banks.exceptions import AIParsingError

        source = BankDataSourceFactory()
        crawler = fake_crawler()
        crawler.multi_pass_extractor.is_provider_available.return_value = False
        crawler.llm_parser.parse_comprehensive_data.side_effect = AIParsingError(
            "invalid JSON"
        )
        assert not crawler.crawl_bank_data_source(source.pk)
        source.refresh_from_db()
        assert source.failed_attempt_count == 1


@pytest.mark.django_db
class TestExtractionProvenanceAndQuality:
    @pytest.mark.parametrize(
        "native,ocr,expected",
        [
            ("Credit card annual fee BDT 1000 and charges " * 5, "", "pdf_text"),
            ("", "Credit card annual fee BDT 1000", "ocr"),
        ],
    )
    def test_pdf_reports_method_that_actually_produced_text(self, native, ocr, expected):
        extractor = ContentExtractor()
        page = MagicMock()
        page.extract_text.return_value = native
        with (
            patch(
                "banks.services.content_extractor.PdfReader",
                return_value=SimpleNamespace(pages=[page]),
            ),
            patch.object(extractor, "_fetch_content", return_value=b"pdf"),
            patch.object(extractor, "_extract_pdf_with_ocr", return_value=ocr),
        ):
            extractor.extract_content("https://bank.test/schedule.pdf", "pdf")
        assert extractor.last_extraction_method == expected

    def test_corrupt_pdf_fallback_records_ocr(self):
        extractor = ContentExtractor()
        with (
            patch(
                "banks.services.content_extractor.PdfReader",
                side_effect=ValueError("bad text layer"),
            ),
            patch.object(
                extractor, "_extract_pdf_with_ocr", return_value="annual fee BDT 1000"
            ),
        ):
            assert extractor._extract_pdf_content(b"pdf") == "annual fee BDT 1000"
        assert extractor.last_extraction_method == "ocr"

    @pytest.mark.parametrize("method", ["pdf_text", "ocr", "webpage", "image_ocr"])
    def test_crawl_record_preserves_actual_method(self, method):
        crawler = fake_crawler()
        crawler.content_extractor.last_extraction_method = method
        crawler.llm_parser.parse_with_multi_pass.return_value = SimpleNamespace(
            credit_cards=[{"name": "Gold", "annual_fee": 1000, "interest_rate_apr": 25}],
            issues=[],
            passes=[],
            provider_used="fake",
            confidence=0.9,
        )
        source = BankDataSourceFactory(content_type="pdf")
        assert crawler.crawl_bank_data_source(source.pk)
        assert CrawledContent.objects.get().extraction_method == method
        assert (
            crawler.llm_parser.parse_with_multi_pass.call_args.kwargs["method"] == method
        )

    @pytest.mark.parametrize(
        "noise",
        [
            "Nr e-vtoms / SPORATS omart BSA SHA aries ear fiawr |",
            "!@#$ ^&* () 12 A //////// | | | |",
            "annual fee ///////////////////////// x x x x",
            "annual fee 1000 " + "SPORATS omart BSA SHA aries " * 100,
            "",
        ],
    )
    def test_image_only_schedule_goes_to_review_when_vision_unavailable(self, noise):
        crawler = fake_crawler(content=noise)
        crawler.content_extractor.last_extraction_method = "ocr"
        crawler.content_extractor.vision_images.side_effect = ContentExtractionError(
            "No bounded binary source available for vision"
        )
        source = BankDataSourceFactory(content_type="pdf", failed_attempt_count=4)
        assert not crawler.crawl_bank_data_source(source.pk)
        crawler.llm_parser.parse_with_multi_pass.assert_not_called()
        crawler.llm_parser.parse_comprehensive_data.assert_not_called()
        record = CrawledContent.objects.get()
        assert record.processing_status == "pending"
        assert record.parsed_json["reason"] == "needs_multimodal"
        assert record.needs_manual_review
        assert record.extracted_content == noise
        assert record.extraction_method == "ocr"
        item = ReviewQueue.objects.get(crawled_content=record)
        assert (
            item.message == "Image-only schedule; extract manually or with a vision model"
        )
        source.refresh_from_db()
        assert source.is_active and source.failed_attempt_count == 4
        assert not CreditCard.objects.exists()

    def test_partial_readable_ocr_is_usable(self):
        assert ContentExtractor.has_usable_fee_text(
            "Prime credit card charges\nGold annual fee BDT 2000\nInterest 25%"
        )


@pytest.mark.django_db
class TestTaskQuotaDeferral:
    @pytest.mark.parametrize(
        "task_name", ["crawl_bank_data_sources_by_bank", "daily_crawl_all_active_banks"]
    )
    def test_task_stops_calls_after_quota_without_reporting_source_failure(
        self, task_name
    ):
        from banks import tasks

        bank = BankFactory()
        sources = [BankDataSourceFactory(bank=bank) for _ in range(3)]
        crawler = fake_crawler()
        crawler.llm_parser.parse_with_multi_pass.side_effect = LLMRateLimitError("429")
        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            task = getattr(tasks, task_name)
            result = (
                task(bank.pk)
                if task_name == "crawl_bank_data_sources_by_bank"
                else task()
            )
        assert crawler.llm_parser.parse_with_multi_pass.call_count == 1
        for source in sources:
            source.refresh_from_db()
            assert source.failed_attempt_count == 0 and source.is_active
        if task_name == "crawl_bank_data_sources_by_bank":
            assert result["results"]["skipped"] == 3
            assert result["results"]["failed"] == 0
        else:
            assert result["sources_failed"] == 0

    def test_single_source_task_reports_deferral(self):
        from banks.tasks import crawl_bank_data_source

        source = BankDataSourceFactory()
        crawler = fake_crawler()
        crawler.llm_parser.parse_with_multi_pass.side_effect = LLMRateLimitError("quota")
        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            assert crawl_bank_data_source(source.pk)["status"] == "deferred"
