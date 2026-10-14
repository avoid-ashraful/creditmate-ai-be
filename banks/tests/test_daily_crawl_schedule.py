"""Daily crawl scheduling tests (acceptance: daily cron for all active banks).

The Celery beat entry and the task are verified offline: the schedule is read
from the app configuration and the task runs with a mocked crawler, so no live
crawl or external service is touched.
"""

from unittest.mock import MagicMock, patch

import pytest
from celery.schedules import crontab

from banks.factories import BankDataSourceFactory, BankFactory
from banks.models import Bank
from banks.tasks import daily_crawl_all_active_banks

DAILY_TASK_NAME = "banks.tasks.daily_crawl_all_active_banks"
BEAT_ENTRY_NAME = "daily-crawl-all-active-banks"


class TestBeatSchedule:
    """The beat configuration must schedule the task once per day."""

    @pytest.fixture(scope="class")
    def beat_entry(self):
        from credit_mate_ai.celery import app

        schedule = app.conf.beat_schedule
        assert BEAT_ENTRY_NAME in schedule, "daily beat entry missing"
        return schedule[BEAT_ENTRY_NAME]

    def test_entry_targets_the_daily_task(self, beat_entry):
        assert beat_entry["task"] == DAILY_TASK_NAME

    def test_entry_uses_a_daily_crontab(self, beat_entry):
        schedule = beat_entry["schedule"]
        assert isinstance(schedule, crontab)
        # Daily at 02:00 UTC
        assert 2 in schedule.hour
        assert 0 in schedule.minute

    def test_entry_has_expiry_window(self, beat_entry):
        options = beat_entry.get("options") or {}
        assert options.get("expires", 0) > 0

    def test_task_is_registered_under_the_expected_name(self):
        assert daily_crawl_all_active_banks.name == DAILY_TASK_NAME

    def test_weekly_entry_still_present(self):
        from credit_mate_ai.celery import app

        assert "crawl-bank-data-weekly" in app.conf.beat_schedule
        assert app.conf.beat_schedule["crawl-bank-data-weekly"]["options"]["expires"] > 0


@pytest.mark.django_db
class TestDailyCrawlTask:
    """daily_crawl_all_active_banks must reach every active bank."""

    @pytest.fixture
    def banks_and_sources(self):
        active_with_sources = BankFactory(name="Active Bank With Sources")
        active_no_sources = BankFactory(name="Active Bank Without Sources")
        inactive = BankFactory(name="Inactive Bank", is_active=False)

        source_a = BankDataSourceFactory(bank=active_with_sources, is_active=True)
        source_b = BankDataSourceFactory(bank=active_with_sources, is_active=True)
        BankDataSourceFactory(bank=active_with_sources, is_active=False)
        BankDataSourceFactory(bank=inactive, is_active=True)

        return {
            "active_with_sources": active_with_sources,
            "active_no_sources": active_no_sources,
            "inactive": inactive,
            "active_sources": [source_a, source_b],
        }

    def test_crawls_every_active_bank_source(self, banks_and_sources):
        crawler = MagicMock()
        crawler.crawl_bank_data_source.return_value = True

        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            summary = daily_crawl_all_active_banks()

        assert summary["status"] == "completed"
        assert summary["banks_total"] == 2  # inactive bank excluded
        assert summary["banks_crawled"] == 1
        assert summary["banks_skipped"] == 1
        assert summary["sources_total"] == 2  # inactive source excluded
        assert summary["sources_successful"] == 2
        assert summary["sources_failed"] == 0

        crawled_ids = {
            call.args[0] for call in crawler.crawl_bank_data_source.call_args_list
        }
        expected_ids = {source.id for source in banks_and_sources["active_sources"]}
        assert crawled_ids == expected_ids

    def test_reports_failed_sources(self, banks_and_sources):
        crawler = MagicMock()
        crawler.crawl_bank_data_source.return_value = False

        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            summary = daily_crawl_all_active_banks()

        assert summary["sources_successful"] == 0
        assert summary["sources_failed"] == 2
        assert summary["status"] == "completed"

    def test_per_bank_detail_is_reported(self, banks_and_sources):
        crawler = MagicMock()
        crawler.crawl_bank_data_source.return_value = True

        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            summary = daily_crawl_all_active_banks()

        details = {entry["bank"]: entry for entry in summary["banks"]}
        assert "Active Bank With Sources" in details
        assert details["Active Bank With Sources"]["status"] == "completed"
        assert details["Active Bank With Sources"]["sources"] == 2
        assert details["Active Bank Without Sources"]["status"] == "skipped"
        assert "Inactive Bank" not in details

    def test_no_active_banks_returns_completed_summary(self):
        Bank.objects.all().delete()
        crawler = MagicMock()

        with patch("banks.tasks.BankDataCrawlerService", return_value=crawler):
            summary = daily_crawl_all_active_banks()

        assert summary["status"] == "completed"
        assert summary["banks_total"] == 0
        crawler.crawl_bank_data_source.assert_not_called()

    def test_crawler_failure_is_reported_as_error(self, banks_and_sources):
        with patch(
            "banks.tasks.BankDataCrawlerService",
            side_effect=RuntimeError("boom"),
        ):
            summary = daily_crawl_all_active_banks()

        assert summary["status"] == "error"
        assert "boom" in summary["error"]
        assert summary["timestamp"]

    def test_timestamp_is_returned(self, banks_and_sources):
        with patch("banks.tasks.BankDataCrawlerService") as crawler_cls:
            crawler_cls.return_value.crawl_bank_data_source.return_value = True
            summary = daily_crawl_all_active_banks()
        assert summary["timestamp"]


@pytest.mark.django_db
class TestDailyCrawlHelper:
    """_crawl_bank_for_daily_schedule counts sources per bank."""

    def test_counts_sources(self):
        from banks.tasks import _crawl_bank_for_daily_schedule

        bank = BankFactory(name="Helper Bank")
        BankDataSourceFactory(bank=bank, is_active=True)
        BankDataSourceFactory(bank=bank, is_active=False)

        crawler = MagicMock()
        crawler.crawl_bank_data_source.return_value = True
        summary = {
            "sources_total": 0,
            "sources_successful": 0,
            "sources_failed": 0,
            "banks_crawled": 0,
            "banks_skipped": 0,
        }

        detail = _crawl_bank_for_daily_schedule(bank, crawler, summary)

        assert detail["sources"] == 1
        assert detail["successful"] == 1
        assert summary["sources_total"] == 1
        assert summary["banks_crawled"] == 1

    def test_bank_without_sources_is_skipped(self):
        from banks.tasks import _crawl_bank_for_daily_schedule

        bank = BankFactory(name="No Sources Bank")
        crawler = MagicMock()
        summary = {"banks_skipped": 0}

        detail = _crawl_bank_for_daily_schedule(bank, crawler, summary)

        assert detail["status"] == "skipped"
        assert summary["banks_skipped"] == 1
        crawler.crawl_bank_data_source.assert_not_called()
