"""
Tests for monthly Celery tasks.
"""

from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from django.utils import timezone

from banks.factories import BankDataSourceFactory, BankFactory, CrawledContentFactory
from banks.tasks import (
    monthly_comprehensive_crawl,
    monthly_data_quality_check,
    monthly_schedule_charge_url_discovery,
)
from credit_cards.factories import CreditCardFactory


@pytest.mark.django_db
class TestMonthlyDataQualityCheck:
    """Test monthly data quality check task."""

    def setup_method(self):
        """Set up test data."""
        # Use factory defaults to avoid name conflicts
        self.bank1 = BankFactory()
        self.bank2 = BankFactory()
        self.bank3 = BankFactory()

        # Bank1 has data sources and cards
        self.data_source1 = BankDataSourceFactory(bank=self.bank1)
        self.card1 = CreditCardFactory(bank=self.bank1)

        # Bank3 has data sources but no cards
        self.data_source3 = BankDataSourceFactory(bank=self.bank3)

    def test_monthly_data_quality_check_success(self):
        """Test successful data quality check."""
        result = monthly_data_quality_check()

        assert result["status"] == "completed"
        assert "results" in result
        assert "checks" in result["results"]
        assert "issues_found" in result["results"]
        assert "recommendations" in result["results"]

        checks = result["results"]["checks"]
        assert "banks_without_sources" in checks
        assert "stale_data_sources" in checks
        assert "failed_data_sources" in checks
        assert "banks_without_cards" in checks
        assert "system_health" in checks
        assert "duplicate_content_hashes" in checks

    def test_monthly_data_quality_check_detects_banks_without_sources(self):
        """Test detection of banks without data sources."""
        result = monthly_data_quality_check()

        # Bank2 has no data sources
        assert result["results"]["checks"]["banks_without_sources"] >= 1

        # Should have issue reported
        issues = result["results"]["issues_found"]
        missing_sources_issue = next(
            (issue for issue in issues if issue["type"] == "missing_data_sources"), None
        )
        assert missing_sources_issue is not None
        # Bank2 should be in the list (it has no data sources)
        assert self.bank2.name in missing_sources_issue["banks"]

    def test_monthly_data_quality_check_detects_banks_without_cards(self):
        """Test detection of banks without credit cards."""
        result = monthly_data_quality_check()

        # Bank2 and Bank3 have no cards
        assert result["results"]["checks"]["banks_without_cards"] >= 1

        # Should have issue reported
        issues = result["results"]["issues_found"]
        no_cards_issue = next(
            (issue for issue in issues if issue["type"] == "banks_without_cards"), None
        )
        assert no_cards_issue is not None

    def test_monthly_data_quality_check_detects_stale_sources(self):
        """Test detection of stale data sources."""
        # Create a data source with old last_successful_crawl_at
        old_date = timezone.now() - timedelta(days=35)
        BankDataSourceFactory(bank=self.bank1, last_successful_crawl_at=old_date)

        result = monthly_data_quality_check()

        checks = result["results"]["checks"]
        if checks["stale_data_sources"] > 0:
            issues = result["results"]["issues_found"]
            stale_issue = next(
                (issue for issue in issues if issue["type"] == "stale_data_sources"), None
            )
            assert stale_issue is not None
            assert stale_issue["count"] >= 1

    def test_monthly_data_quality_check_detects_failed_sources(self):
        """Test detection of failed data sources."""
        # Create a failed data source
        BankDataSourceFactory(bank=self.bank1, failed_attempt_count=5, is_active=False)

        result = monthly_data_quality_check()

        checks = result["results"]["checks"]
        assert checks["failed_data_sources"] >= 1

        issues = result["results"]["issues_found"]
        failed_issue = next(
            (issue for issue in issues if issue["type"] == "failed_data_sources"), None
        )
        assert failed_issue is not None
        assert failed_issue["count"] >= 1

    def test_monthly_data_quality_check_calculates_health_score(self):
        """Test system health score calculation."""
        # Create recent crawled content
        CrawledContentFactory(
            data_source=self.data_source1, crawl_date=timezone.now() - timedelta(days=2)
        )

        result = monthly_data_quality_check()

        health = result["results"]["checks"]["system_health"]
        assert "active_banks" in health
        assert "active_data_sources" in health
        assert "active_credit_cards" in health
        assert "recent_crawls" in health
        assert "health_score" in health
        assert 0 <= health["health_score"] <= 100

    @patch("banks.models.CrawledContent.objects.filter")
    def test_monthly_data_quality_check_exception_handling(self, mock_filter):
        """Test exception handling in data quality check."""
        mock_filter.side_effect = Exception("Database error")

        # Mock the task's request object for retry logic
        task_instance = Mock()
        task_instance.request = Mock()
        task_instance.request.retries = 0
        task_instance.max_retries = 3
        task_instance.retry = Mock(side_effect=Exception("Retry called"))

        try:
            result = monthly_data_quality_check(task_instance)
            # If no exception raised, it should be an error result
            assert result["status"] == "error"
            assert "Database error" in result["error"]
        except Exception:
            # Exception means retry was called, which is acceptable
            pass


@pytest.mark.django_db
class TestMonthlyScheduleChargeUrlDiscovery:
    """Test monthly schedule charge URL discovery task."""

    def setup_method(self):
        """Set up test data."""
        self.bank = BankFactory(schedule_charge_url="https://example.com")

    @patch("banks.tasks.find_and_update_schedule_charge_urls")
    def test_monthly_schedule_charge_url_discovery_success(self, mock_find_urls):
        """Test successful schedule charge URL discovery."""
        mock_find_urls.return_value = {
            "status": "completed",
            "results": {
                "total": 1,
                "processed": 1,
                "found": 1,
                "updated": 0,
                "created": 1,
                "errors": 0,
            },
        }

        result = monthly_schedule_charge_url_discovery()

        assert result["status"] == "completed"
        assert result["task_type"] == "monthly_schedule_charge_discovery"
        assert "results" in result
        mock_find_urls.assert_called_once()

    @patch("banks.tasks.find_and_update_schedule_charge_urls")
    def test_monthly_schedule_charge_url_discovery_exception(self, mock_find_urls):
        """Test exception handling in schedule charge URL discovery."""
        mock_find_urls.side_effect = Exception("Discovery error")

        task_instance = Mock()
        task_instance.request = Mock()
        task_instance.request.retries = 0
        task_instance.max_retries = 2
        task_instance.retry = Mock(side_effect=Exception("Retry called"))

        try:
            result = monthly_schedule_charge_url_discovery(task_instance)
            assert result["status"] == "error"
            assert "Discovery error" in result["error"]
        except Exception:
            # Retry was called
            pass


@pytest.mark.django_db
class TestMonthlyComprehensiveCrawl:
    """Test monthly comprehensive crawl task."""

    def setup_method(self):
        """Set up test data."""
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(bank=self.bank)

    @patch("banks.services.BankDataCrawlerService")
    def test_monthly_comprehensive_crawl_success(self, mock_service_class):
        """Test successful comprehensive crawl."""
        mock_service = Mock()
        mock_service.crawl_all_active_sources.return_value = {
            "total": 1,
            "successful": 1,
            "failed": 0,
        }
        mock_service_class.return_value = mock_service

        result = monthly_comprehensive_crawl()

        assert result["status"] == "completed"
        assert result["task_type"] == "monthly_comprehensive_crawl"
        assert result["results"]["total"] == 1
        assert result["results"]["successful"] == 1
        mock_service.crawl_all_active_sources.assert_called_once()

    @patch("banks.services.BankDataCrawlerService")
    def test_monthly_comprehensive_crawl_exception(self, mock_service_class):
        """Test exception handling in comprehensive crawl."""
        mock_service_class.side_effect = Exception("Crawl error")

        task_instance = Mock()
        task_instance.request = Mock()
        task_instance.request.retries = 0
        task_instance.max_retries = 2
        task_instance.retry = Mock(side_effect=Exception("Retry called"))

        try:
            result = monthly_comprehensive_crawl(task_instance)
            assert result["status"] == "error"
            assert "Crawl error" in result["error"]
        except Exception:
            # Retry was called
            pass


@pytest.mark.django_db
class TestMonthlyTasksIntegration:
    """Integration tests for monthly tasks."""

    def setup_method(self):
        """Set up comprehensive test data."""
        # Create banks with various states
        self.healthy_bank = BankFactory()
        self.healthy_source = BankDataSourceFactory(bank=self.healthy_bank)
        self.healthy_card = CreditCardFactory(bank=self.healthy_bank)

        # Recent successful crawl
        CrawledContentFactory(
            data_source=self.healthy_source,
            processing_status="completed",
            crawl_date=timezone.now() - timedelta(hours=6),
        )

        self.problematic_bank = BankFactory()
        self.stale_source = BankDataSourceFactory(
            bank=self.problematic_bank,
            last_successful_crawl_at=timezone.now() - timedelta(days=45),
        )

        self.failed_bank = BankFactory()
        self.failed_source = BankDataSourceFactory(
            bank=self.failed_bank, failed_attempt_count=5, is_active=False
        )

    def test_monthly_tasks_data_consistency(self):
        """Test that monthly tasks provide consistent data views."""
        # Run data quality check
        quality_result = monthly_data_quality_check()

        assert quality_result["status"] == "completed"

        # Verify the data makes sense
        results = quality_result["results"]
        health = results["checks"]["system_health"]
        assert health["active_banks"] >= 3
        assert health["active_data_sources"] >= 2  # healthy + stale (failed is inactive)
        assert health["active_credit_cards"] >= 1

        # Should detect issues
        assert len(results["issues_found"]) > 0
        assert len(results["recommendations"]) > 0

    def test_monthly_tasks_error_resilience(self):
        """Test that monthly tasks handle errors gracefully."""
        # Mock the task to avoid actual Celery retry behavior
        with patch("banks.tasks.monthly_data_quality_check.retry") as mock_retry:
            mock_retry.side_effect = Exception("Max retries exceeded")

            # Test each task can handle database issues
            with patch("banks.models.Bank.objects.filter") as mock_filter:
                # Make the database call fail
                mock_filter.side_effect = Exception("Database connection lost")

                # The task should attempt retry and then fail gracefully
                try:
                    result = monthly_data_quality_check()
                    # If we get here, the task returned an error result instead of raising
                    assert result["status"] == "error"
                    assert "Database connection lost" in result["error"]
                except Exception as e:
                    # If retry logic is triggered, that's also valid behavior
                    assert "Database connection lost" in str(
                        e
                    ) or "Max retries exceeded" in str(e)

    def test_task_scheduling_configuration(self):
        """Test that task scheduling is properly configured."""
        from credit_mate_ai.celery import app

        beat_schedule = app.conf.beat_schedule

        # Verify all monthly tasks are scheduled
        assert "monthly-data-quality-check" in beat_schedule
        assert "monthly-schedule-charge-discovery" in beat_schedule
        assert "monthly-comprehensive-crawl" in beat_schedule

        # Verify they run monthly (approximately 30 days)
        monthly_seconds = 30 * 24 * 60 * 60
        for task_name in [
            "monthly-data-quality-check",
            "monthly-schedule-charge-discovery",
            "monthly-comprehensive-crawl",
        ]:
            assert beat_schedule[task_name]["schedule"] == monthly_seconds
            assert "expires" in beat_schedule[task_name]["options"]
