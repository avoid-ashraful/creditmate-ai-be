"""Nightly all-products sync (Phase 2, V4): bootstrap, orchestration, schedule.

Everything is verified offline: chart fetches/ingestions and the crawler are
mocked, so no live BB page or LLM provider is touched.
"""

import hashlib
import logging
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from django.conf import settings

from banks.enums import (
    ProcessingStatus,
    ReviewSource,
    SourcePurpose,
    SyncRunStatus,
)
from banks.factories import BankDataSourceFactory, BankFactory
from banks.models import Bank, BankDataSource, CrawledContent, ReviewQueue, SyncRun
from banks.services.nightly_sync import (
    QUOTA_LOG_MARKER,
    NightlySyncService,
    sync_gemini_model,
)
from banks.services.source_bootstrap import bootstrap_sync_sources
from banks.tasks import sync_all_products_nightly

DEPOSIT_REPORT = {
    "edition": "October 2026",
    "snapshot_created": True,
    "banks_seen": 61,
    "products_created": 2,
    "products_updated": 3,
    "rates_created": 4,
    "rates_updated": 5,
    "rates_deleted": 0,
    "history_rows": 6,
    "anomalies": ["flat ladder"],
}

LENDING_STATS = {
    "edition": "October 2026",
    "snapshot_created": False,
    "snapshot_refreshed": True,
    "banks_seen": 61,
    "bands_created": 1,
    "bands_updated": 2,
    "bands_removed": 0,
    "anomalies": [],
}


class TestNightlyBeatSchedule:
    """The nightly entry exists alongside (not instead of) the weekly crawl."""

    @pytest.fixture(scope="class")
    def schedule(self):
        from credit_mate_ai.celery import app

        return app.conf.beat_schedule

    def test_nightly_entry_registered_for_0200_dhaka(self, schedule):
        assert "sync-all-products-nightly" in schedule
        entry = schedule["sync-all-products-nightly"]
        assert entry["task"] == "banks.tasks.sync_all_products_nightly"
        assert entry["schedule"].hour == {2}
        assert entry["schedule"].minute == {0}
        assert entry["options"]["expires"] == 6 * 60 * 60

    def test_weekly_crawl_entry_kept(self, schedule):
        assert (
            schedule["crawl-bank-data-weekly"]["task"]
            == "banks.tasks.crawl_all_bank_data"
        )

    def test_beat_timezone_is_dhaka(self):
        from credit_mate_ai.celery import app

        assert settings.CELERY_TIMEZONE == "Asia/Dhaka"
        assert app.conf.timezone == "Asia/Dhaka"

    def test_task_registered_under_expected_name(self):
        assert sync_all_products_nightly.name == "banks.tasks.sync_all_products_nightly"


@pytest.mark.django_db
class TestBootstrapSyncSources:
    """Bootstrap registers every vertical's sources, exactly once."""

    @pytest.fixture
    def seeded_catalogues(self):
        from bank_accounts.models import AccountProduct
        from deposits.models import DepositProduct
        from loans.models import LoanProduct

        bank = BankFactory(
            name="Bootstrap Bank",
            schedule_charge_url="https://bootstrap.example/soc.pdf",
        )
        AccountProduct.objects.create(
            bank=bank,
            name="Bootstrap Savings",
            account_type="savings",
            rate_slabs=[{"balance_min": "0", "balance_max": None, "rate": "3.00"}],
            source_soc_url="https://bootstrap.example/account-soc.pdf",
            source_rate_url="https://bootstrap.example/account-rates",
        )
        DepositProduct.objects.create(
            bank=bank,
            kind="fdr",
            name="Bootstrap FDR",
            slug="bootstrap-fdr",
            source_url="https://bootstrap.example/deposit-rates",
            source_kind="bank_rates_page",
        )
        LoanProduct.objects.create(
            bank=bank,
            loan_type="personal",
            source_url="https://bootstrap.example/annexure-a.pdf",
        )
        return bank

    def test_registers_all_verticals(self, seeded_catalogues):
        counts = bootstrap_sync_sources()

        purposes = set(
            BankDataSource.objects.values_list("purpose", flat=True).distinct()
        )
        assert purposes == {
            SourcePurpose.CREDIT_CARD,
            SourcePurpose.BB_DEPOSIT_CHART,
            SourcePurpose.BB_LENDING_CHART,
            SourcePurpose.ACCOUNT_SOC,
            SourcePurpose.ACCOUNT_RATES,
            SourcePurpose.DEPOSIT_RATES,
            SourcePurpose.LOAN_RATES,
        }
        # 2 deposit charts + 1 lending chart + card SoC + account SoC +
        # account rates + deposit rates + loan rates.
        assert counts["created"] == 8
        assert counts["by_purpose"][SourcePurpose.BB_DEPOSIT_CHART.value] == 2

        bb_bank = Bank.objects.get(name="Bangladesh Bank")
        assert bb_bank.is_active is False
        assert bb_bank.data_sources.count() == 3

    def test_idempotent_second_run_creates_nothing(self, seeded_catalogues):
        first = bootstrap_sync_sources()
        second = bootstrap_sync_sources()
        assert second["created"] == 0
        assert second["existing"] == first["created"]
        assert BankDataSource.objects.count() == first["created"]

    def test_shared_url_keeps_first_purpose(self, seeded_catalogues):
        bank = seeded_catalogues
        BankDataSourceFactory(
            bank=bank,
            url="https://bootstrap.example/account-soc.pdf",
            purpose=SourcePurpose.CREDIT_CARD,
        )
        counts = bootstrap_sync_sources()
        assert counts["shared"] >= 1
        row = BankDataSource.objects.get(
            bank=bank, url="https://bootstrap.example/account-soc.pdf"
        )
        assert row.purpose == SourcePurpose.CREDIT_CARD


def _mock_crawler(**overrides):
    crawler = MagicMock()
    crawler.crawl_sources.return_value = overrides.get(
        "crawl_results",
        {"total": 2, "successful": 1, "failed": 0, "skipped": 1},
    )
    crawler.providers_rate_limited = overrides.get("rate_limited", False)
    return crawler


@pytest.mark.django_db
class TestNightlySyncOrchestration:
    """Full run with mocked charts + crawler: summary, persistence, quota."""

    @pytest.fixture(autouse=True)
    def mock_charts(self):
        with (
            patch("deposits.ingestion.bb_chart.fetch_chart_html", return_value="<html/>"),
            patch(
                "deposits.ingestion.bb_chart.ingest_chart", return_value=DEPOSIT_REPORT
            ) as ingest_deposit,
            patch(
                "loans.ingestion.bb_lending_chart.fetch_chart_html",
                return_value="<html/>",
            ),
            patch(
                "loans.ingestion.bb_lending_chart.ingest_lending_chart",
                return_value=LENDING_STATS,
            ) as ingest_lending,
        ):
            self.ingest_deposit = ingest_deposit
            self.ingest_lending = ingest_lending
            yield

    def test_full_run_completes_and_persists_summary(self):
        run = NightlySyncService(crawler=_mock_crawler()).run()

        assert run.status == SyncRunStatus.COMPLETED
        assert run.finished_at is not None
        assert run.summary["charts"]["deposit_conventional"]["banks_seen"] == 61
        assert run.summary["charts"]["deposit_islamic_window"]["rates_updated"] == 5
        assert run.summary["charts"]["lending"]["bands_updated"] == 2
        assert run.summary["cards"]["sources_checked"] == 2
        assert run.summary["cards"]["draft_cards_created"] == 0
        assert run.summary["llm"]["model"] == settings.NIGHTLY_SYNC_GEMINI_MODEL
        assert run.summary["llm"]["budget_limit"] == settings.LLM_MAX_CALLS_PER_RUN
        assert run.summary["llm"]["calls_used"] == 0
        assert run.summary["llm"]["quota_exhausted"] is False
        assert run.summary["watch"]["checked"] == 0
        assert run.summary["errors"] == []
        assert SyncRun.objects.count() == 1

    def test_quota_exhaustion_degrades_gracefully(self, caplog):
        crawler = _mock_crawler(
            rate_limited=True,
            crawl_results={"total": 3, "successful": 0, "failed": 0, "skipped": 3},
        )
        with caplog.at_level(logging.WARNING, logger="banks.services.nightly_sync"):
            run = NightlySyncService(crawler=crawler).run()

        # The run still completes: deterministic phases are unaffected.
        assert run.status == SyncRunStatus.COMPLETED
        assert run.summary["llm"]["quota_exhausted"] is True
        assert run.summary["cards"]["sources_skipped"] == 3
        assert QUOTA_LOG_MARKER in caplog.text

    def test_chart_failure_marks_run_partial_and_continues(self):
        with patch(
            "deposits.ingestion.bb_chart.fetch_chart_html",
            side_effect=RuntimeError("bb unreachable"),
        ):
            run = NightlySyncService(crawler=_mock_crawler()).run()

        assert run.status == SyncRunStatus.PARTIAL
        assert "bb unreachable" in run.summary["charts"]["deposit_conventional"]["error"]
        assert (
            "bb unreachable" in run.summary["charts"]["deposit_islamic_window"]["error"]
        )
        # Lending chart and the card/watch phases still ran.
        assert run.summary["charts"]["lending"]["banks_seen"] == 61
        assert run.summary["cards"]["sources_checked"] == 2
        assert len(run.summary["errors"]) == 2

    def test_task_wrapper_returns_run_status(self):
        with patch(
            "banks.services.nightly_sync.NightlySyncService.run",
            return_value=MagicMock(pk=7, status="completed", summary={"errors": []}),
        ):
            result = sync_all_products_nightly.run()
        assert result["status"] == "completed"
        assert result["sync_run_id"] == 7


class TestSyncGeminiModel:
    """The nightly crawl pins the lite model unless GEMINI_MODEL is set."""

    def test_model_swapped_inside_context_and_restored(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "GEMINI_MODEL", "gemini-flash-latest")
            mp.setattr(settings, "NIGHTLY_SYNC_GEMINI_MODEL", "gemini-3.5-flash-lite")
            with sync_gemini_model() as model:
                assert model == "gemini-3.5-flash-lite"
                assert settings.GEMINI_MODEL == "gemini-3.5-flash-lite"
            assert settings.GEMINI_MODEL == "gemini-flash-latest"

    def test_default_sync_model_is_the_verified_lite_model(self):
        # With GEMINI_MODEL unset in the environment, settings pin the lite
        # model for the sync (see settings.py rationale).
        if "GEMINI_MODEL" in os.environ:
            pytest.skip("GEMINI_MODEL is explicitly configured in this environment")
        assert settings.NIGHTLY_SYNC_GEMINI_MODEL == "gemini-3.5-flash-lite"


@pytest.mark.django_db
class TestWatchedSources:
    """Change-gated watch: baseline -> unchanged -> changed -> not re-flagged."""

    @pytest.fixture
    def source(self):
        bank = BankFactory(name="Watched Bank")
        return BankDataSourceFactory(
            bank=bank,
            url="https://watched.example/soc.pdf",
            purpose=SourcePurpose.ACCOUNT_SOC,
        )

    @pytest.fixture
    def crawler(self):
        """A real crawler with stubbed components; extraction is faked per test."""
        from banks.services.bank_data_crawler import BankDataCrawlerService

        extractor = MagicMock()
        extractor.last_binary_hash = ""
        service = BankDataCrawlerService(
            multi_pass_extractor=MagicMock(),
            content_extractor=extractor,
            llm_parser=MagicMock(),
            data_service=MagicMock(),
        )
        return service

    def _run_watch(self, crawler, source, text):
        crawler._extract_content_safely = MagicMock(
            return_value=(text, text, {"method": "pdf_text"})
        )
        summary = {}
        NightlySyncService(crawler=crawler)._sync_watch_sources(summary)
        return summary["watch"]

    def test_baseline_then_unchanged_then_changed(self, crawler, source):
        stats = self._run_watch(crawler, source, "soc v1")
        assert stats == {
            "checked": 1,
            "unchanged": 0,
            "changed": 0,
            "baselined": 1,
            "failed": 0,
            "review_items_created": 0,
        }
        baseline = CrawledContent.objects.get(data_source=source)
        assert baseline.processing_status == ProcessingStatus.COMPLETED
        assert baseline.content_hash == hashlib.sha256(b"soc v1").hexdigest()
        assert ReviewQueue.objects.count() == 0

        stats = self._run_watch(crawler, source, "soc v1")
        assert stats["unchanged"] == 1
        assert CrawledContent.objects.filter(data_source=source).count() == 1
        assert ReviewQueue.objects.count() == 0

        stats = self._run_watch(crawler, source, "soc v2 with new fees")
        assert stats["changed"] == 1
        assert stats["review_items_created"] == 1
        pending = CrawledContent.objects.filter(
            data_source=source, processing_status=ProcessingStatus.PENDING
        ).get()
        assert pending.needs_manual_review is True
        item = ReviewQueue.objects.get()
        assert item.crawled_content == pending
        assert item.source == ReviewSource.CRAWLER_PROPOSAL
        assert "changed" in item.message

        # The same changed content must not be flagged twice.
        stats = self._run_watch(crawler, source, "soc v2 with new fees")
        assert stats["unchanged"] == 1
        assert ReviewQueue.objects.count() == 1

    def test_failed_fetch_counts_failed(self, crawler, source):
        crawler._extract_content_safely = MagicMock(return_value=None)
        summary = {}
        NightlySyncService(crawler=crawler)._sync_watch_sources(summary)
        assert summary["watch"]["failed"] == 1
        assert ReviewQueue.objects.count() == 0


@pytest.mark.django_db
class TestProposalApprovalBumpsVerifiedAt:
    """Roadmap caveat fix: approving a proposal re-verifies the card."""

    def test_approve_proposal_sets_verified_at(self):
        from banks.services import ReviewQueueService
        from credit_cards.factories import CreditCardFactory

        card = CreditCardFactory(annual_fee="100", interest_rate_apr="18")
        assert card.verified_at is None
        item = ReviewQueue.objects.create(
            bank=card.bank,
            credit_card=card,
            field_name="annual_fee",
            proposed_value=250,
            source=ReviewSource.CRAWLER_PROPOSAL,
        )
        ReviewQueueService().approve(item)
        card.refresh_from_db()
        assert card.annual_fee == Decimal("250")
        assert card.verified_at is not None
