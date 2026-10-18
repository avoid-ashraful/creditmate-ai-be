"""LLM call budget: counting in the orchestrator and stopping the crawl run."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from django.core.management import CommandError, call_command

from banks.factories import BankDataSourceFactory, BankFactory
from banks.models import BankDataSource
from banks.services.bank_data_crawler import BankDataCrawlerService
from banks.tasks import daily_crawl_all_active_banks
from common.llm.budget import current_budget, llm_budget_exhausted, llm_call_budget
from common.llm.exceptions import (
    AllLLMProvidersFailedError,
    LLMBudgetExhaustedError,
    LLMError,
)
from common.llm.services import LLMOrchestrator


def orchestrator(provider):
    """Orchestrator with a single fake provider (no real client is built)."""
    instance = LLMOrchestrator(providers=[])
    instance.providers = {"fake": provider}
    return instance


def fake_provider(side_effect=None):
    provider = MagicMock()
    provider.is_available.return_value = True
    provider.validate_response.return_value = True
    provider.generate_response.side_effect = side_effect or (lambda **kw: "ok")
    return provider


class TestBudgetObject:
    def test_defaults_to_setting(self, settings):
        settings.LLM_MAX_CALLS_PER_RUN = 7
        with llm_call_budget() as budget:
            assert budget.limit == 7
            assert current_budget() is budget
        assert current_budget() is None

    def test_default_setting_is_200(self):
        from django.conf import settings

        assert settings.LLM_MAX_CALLS_PER_RUN == 200

    def test_nested_run_reuses_outer_budget(self):
        with llm_call_budget(3) as outer, llm_call_budget(99) as inner:
            assert inner is outer and inner.limit == 3

    def test_zero_means_unlimited(self):
        with llm_call_budget(0) as budget:
            for _ in range(1000):
                assert budget.consume()
            assert not budget.exhausted

    def test_consume_stops_at_limit(self):
        with llm_call_budget(2) as budget:
            assert budget.consume() and budget.consume()
            assert not budget.consume()
            assert budget.used == 2 and llm_budget_exhausted()


class TestOrchestratorCounting:
    def test_counts_every_provider_call_including_retries(self):
        provider = fake_provider(side_effect=LLMError("boom"))
        with llm_call_budget(10) as budget:
            with pytest.raises(AllLLMProvidersFailedError):
                orchestrator(provider).generate_response("p", max_retries=2)
        assert budget.used == 3

    def test_raises_when_spent_without_calling_the_provider(self):
        provider = fake_provider()
        llm = orchestrator(provider)
        with llm_call_budget(1):
            assert llm.generate_response("p")["response"] == "ok"
            with pytest.raises(LLMBudgetExhaustedError):
                llm.generate_response("p")
        assert provider.generate_response.call_count == 1

    def test_no_budget_outside_a_run(self):
        provider = fake_provider()
        for _ in range(5):
            orchestrator(provider).generate_response("p")
        assert provider.generate_response.call_count == 5


@pytest.mark.django_db
class TestCrawlStopsWhenBudgetIsSpent:
    @pytest.fixture()
    def sources(self):
        bank = BankFactory(name="Alpha Bank")
        return [BankDataSourceFactory(bank=bank, is_active=True) for _ in range(4)]

    def crawler(self, spend):
        crawler = BankDataCrawlerService(
            multi_pass_extractor=MagicMock(),
            content_extractor=MagicMock(),
            llm_parser=MagicMock(),
            data_service=MagicMock(),
        )

        def crawl(source_id):
            current_budget().used += spend
            return True

        crawler.crawl_bank_data_source = MagicMock(side_effect=crawl)
        return crawler

    def test_remaining_sources_are_left_for_next_run(self, sources, settings, caplog):
        settings.LLM_MAX_CALLS_PER_RUN = 5
        crawler = self.crawler(spend=3)

        results = crawler.crawl_all_active_sources()

        assert crawler.crawl_bank_data_source.call_count == 2  # 3, then 6 >= 5
        assert results == {"total": 4, "successful": 2, "failed": 0, "skipped": 2}
        assert "budget exhausted" in caplog.text

    def test_unspent_budget_crawls_everything(self, sources, settings):
        settings.LLM_MAX_CALLS_PER_RUN = 100
        results = self.crawler(spend=1).crawl_all_active_sources()
        assert results["successful"] == 4 and results["skipped"] == 0

    def test_inactive_banks_are_not_crawled(self, sources):
        BankDataSourceFactory(bank=BankFactory(is_active=False), is_active=True)
        assert self.crawler(spend=0).crawl_all_active_sources()["total"] == 4

    def test_daily_task_also_respects_budget(self, sources, settings):
        settings.LLM_MAX_CALLS_PER_RUN = 1
        crawler = self.crawler(spend=1)
        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            summary = daily_crawl_all_active_banks()
        assert crawler.crawl_bank_data_source.call_count == 1
        assert summary["sources_total"] == 1
        assert summary["banks"][0]["status"] == "partial"


@pytest.mark.django_db
class TestCrawlCommand:
    @pytest.fixture()
    def banks(self):
        brac = BankFactory(name="BRAC Bank")
        city = BankFactory(name="The City Bank")
        other = BankFactory(name="Dutch-Bangla Bank")
        return {
            "brac": BankDataSourceFactory(bank=brac, is_active=True),
            "city": BankDataSourceFactory(bank=city, is_active=True),
            "other": BankDataSourceFactory(bank=other, is_active=True),
        }

    def run(self, **options):
        out = StringIO()
        call_command("crawl_bank_data", stdout=out, **options)
        return out.getvalue()

    def crawled_ids(self, **options):
        crawled = []

        def fake_crawl(self, source_id):
            crawled.append(source_id)
            return True

        with patch.object(BankDataCrawlerService, "crawl_bank_data_source", fake_crawl):
            self.run(**options)
        return crawled

    def test_bank_names_is_case_insensitive_contains(self, banks):
        ids = self.crawled_ids(bank_names="brac, CITY")
        assert sorted(ids) == sorted([banks["brac"].id, banks["city"].id])

    def test_unknown_name_is_an_error(self, banks):
        with pytest.raises(CommandError):
            self.run(bank_names="nonexistent")

    def test_dry_run_crawls_nothing(self, banks):
        assert self.crawled_ids(bank_names="brac", dry_run=True) == []

    def test_max_llm_calls_caps_the_run(self, banks):
        crawled = []

        def fake_crawl(self, source_id):
            crawled.append(source_id)
            current_budget().used += 1
            return True

        with patch.object(BankDataCrawlerService, "crawl_bank_data_source", fake_crawl):
            output = self.run(max_llm_calls=2)

        assert len(crawled) == 2
        assert "1 left for the next run" in output
        assert "LLM calls used: 2" in output
        assert BankDataSource.objects.count() == 3
