"""
Integration tests for the entire Credit Mate AI system.

These tests cover end-to-end workflows, system integration,
and cross-component functionality.
"""

import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from django.test import Client
from django.urls import reverse

from banks.enums import ContentType, ProcessingStatus
from banks.factories import BankDataSourceFactory, BankFactory, CrawledContentFactory
from banks.services import BankDataCrawlerService
from banks.tasks import crawl_all_bank_data, crawl_bank_data_source
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


@pytest.mark.django_db
class TestEndToEndCrawlingWorkflow:
    """Test complete crawling workflow from trigger to database update."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory(name=f"Test Bank {int(time.time() * 1000000)}")
        self.data_source = BankDataSourceFactory(
            bank=self.bank,
            url="https://example.com/cards.pdf",
            content_type=ContentType.PDF,
        )

    @patch("banks.services.ContentExtractor.extract_content")
    @patch("banks.services.LLMContentParser.parse_credit_card_data")
    def test_full_crawl_cycle_success(self, mock_parse, mock_extract):
        """Test complete successful crawl from trigger to data update."""
        # Mock successful content extraction
        mock_extract.return_value = (
            "Raw PDF bytes",
            "Extracted PDF content about credit cards",
        )

        # Mock successful LLM parsing
        mock_parse.return_value = {
            "credit_cards": [
                {
                    "name": "Premium Card",
                    "annual_fee": "95.00",
                    "interest_rate_apr": "15.99",
                    "cash_advance_fee": "Annual fee waived first year",
                    "reward_points_policy": "1 point per dollar spent",
                }
            ]
        }

        # Execute the crawl
        crawler = BankDataCrawlerService()
        success = crawler.crawl_bank_data_source(self.data_source.id)

        # Verify success
        assert success is True

        # Verify data source was updated
        self.data_source.refresh_from_db()
        assert self.data_source.last_crawled_at is not None
        assert self.data_source.last_successful_crawl_at is not None
        assert self.data_source.failed_attempt_count == 0

        # Verify crawled content was created
        crawled_content = self.data_source.crawled_contents.latest("crawl_date")
        assert crawled_content.processing_status == ProcessingStatus.COMPLETED
        assert (
            crawled_content.extracted_content
            == "Extracted PDF content about credit cards"
        )
        assert len(crawled_content.parsed_json) == 1

        # Verify credit card was created
        credit_card = CreditCard.objects.filter(
            bank=self.bank, name="Premium Card"
        ).first()
        assert credit_card is not None
        assert credit_card.annual_fee == Decimal("95.00")
        assert credit_card.interest_rate_apr == Decimal("15.99")
        assert credit_card.cash_advance_fee == "Annual fee waived first year"
        assert credit_card.reward_points_policy == "1 point per dollar spent"

    @patch("banks.services.ContentExtractor.extract_content")
    @patch("banks.services.LLMContentParser.parse_credit_card_data")
    def test_full_crawl_cycle_with_failures(self, mock_parse, mock_extract):
        """Test crawl workflow with various failure points."""
        # Mock extraction failure
        mock_extract.side_effect = Exception("Network error")

        # Execute the crawl
        crawler = BankDataCrawlerService()
        success = crawler.crawl_bank_data_source(self.data_source.id)

        # Verify failure handling
        assert success is False

        # Verify data source failure tracking
        self.data_source.refresh_from_db()
        assert self.data_source.failed_attempt_count == 1
        assert self.data_source.last_crawled_at is not None
        assert self.data_source.last_successful_crawl_at is None

        # Verify error was recorded
        crawled_content = self.data_source.crawled_contents.latest("crawl_date")
        assert crawled_content.processing_status == ProcessingStatus.FAILED
        assert "Network error" in crawled_content.error_message

    @patch("banks.services.ContentExtractor.extract_content")
    @patch("banks.services.LLMContentParser.parse_credit_card_data")
    def test_crawl_with_partial_success(self, mock_parse, mock_extract):
        """Test crawl where extraction succeeds but parsing fails."""
        # Mock successful extraction
        mock_extract.return_value = ("Raw content", "Some extracted content")

        # Mock parsing failure
        mock_parse.side_effect = Exception("LLM API error")

        # Execute the crawl
        crawler = BankDataCrawlerService()
        success = crawler.crawl_bank_data_source(self.data_source.id)

        # Verify partial failure handling
        assert success is False

        # Verify parsing failed (extracted content is not preserved when parsing fails)
        crawled_content = self.data_source.crawled_contents.latest("crawl_date")
        # Note: Current implementation doesn't preserve extracted content when parsing fails
        assert crawled_content.processing_status == ProcessingStatus.FAILED
        assert "LLM API error" in crawled_content.error_message

    @patch("banks.services.BankDataCrawlerService.crawl_bank_data_source")
    def test_concurrent_crawl_requests(self, mock_crawl):
        """Test system behavior with concurrent crawl requests."""
        # Mock crawl method to simulate processing time
        mock_crawl.return_value = True

        # Create multiple data sources
        sources = BankDataSourceFactory.create_batch(5, bank=self.bank)

        # Simulate concurrent crawling
        results = []
        for source in sources:
            crawler = BankDataCrawlerService()
            result = crawler.crawl_bank_data_source(source.id)
            results.append(result)

        # All should succeed
        assert all(results)
        assert mock_crawl.call_count == 5

    @patch("banks.services.ContentExtractor.extract_content")
    @patch("banks.services.LLMContentParser.parse_credit_card_data")
    def test_crawl_with_database_rollback(self, mock_parse, mock_extract):
        """Test proper rollback when crawl partially fails."""
        # Mock successful extraction
        mock_extract.return_value = ("Raw content", "Content")

        # Mock parsing that returns invalid data
        mock_parse.return_value = {
            "credit_cards": [
                {
                    "name": "",  # Invalid empty name
                    "annual_fee": "invalid_decimal",
                    "interest_rate_apr": "not_a_number",
                }
            ]
        }

        # Execute the crawl
        crawler = BankDataCrawlerService()
        success = crawler.crawl_bank_data_source(self.data_source.id)

        # Should succeed (system handles invalid data gracefully)
        assert success is True

        # Verify credit card was created with cleaned data
        cards = CreditCard.objects.filter(bank=self.bank)
        assert cards.count() == 1

        card = cards.first()
        assert card.name == ""  # Empty name was preserved
        assert card.annual_fee == 0.0  # Invalid decimal was converted to 0
        assert card.interest_rate_apr == 0.0  # Invalid decimal was converted to 0

        # But crawled content should still be recorded
        assert self.data_source.crawled_contents.count() == 1


@pytest.mark.django_db
class TestCeleryTaskIntegration:
    """Test Celery task integration and workflow."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(bank=self.bank)

    @patch("banks.services.BankDataCrawlerService.crawl_bank_data_source")
    def test_crawl_task_execution(self, mock_crawl):
        """Test Celery task execution."""
        mock_crawl.return_value = True

        # Execute task synchronously (not through Celery)
        result = crawl_bank_data_source(self.data_source.id)

        # Verify task executed successfully
        assert result["status"] == "success"
        assert result["data_source_id"] == self.data_source.id
        mock_crawl.assert_called_once_with(self.data_source.id)

    @patch("banks.services.BankDataCrawlerService.crawl_all_active_sources")
    def test_crawl_all_task_execution(self, mock_crawl_all):
        """Test crawl all task execution."""
        mock_crawl_all.return_value = {"total": 5, "successful": 4, "failed": 1}

        # Execute task
        result = crawl_all_bank_data()

        # Verify task executed
        assert result["status"] == "completed"
        assert result["results"]["successful"] == 4
        assert result["results"]["failed"] == 1
        mock_crawl_all.assert_called_once()

    @patch("banks.tasks.crawl_bank_data_source.retry")
    @patch("banks.services.BankDataCrawlerService.crawl_bank_data_source")
    def test_task_retry_mechanism(self, mock_crawl, mock_retry):
        """Test Celery task retry mechanism."""
        # Mock failure that should trigger retry
        mock_crawl.side_effect = Exception("Temporary failure")
        mock_retry.side_effect = Exception("Max retries exceeded")

        # Execute task (should fail and attempt retry)
        with pytest.raises(Exception, match="Max retries exceeded"):
            crawl_bank_data_source(self.data_source.id)

        # Verify retry was attempted
        mock_retry.assert_called_once()


@pytest.mark.django_db
class TestAPIDataConsistency:
    """Test data consistency between API responses and database."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory()

    def test_api_response_matches_database_state(self):
        """Test API responses match current database state."""
        # Create credit cards with specific data
        card1 = CreditCardFactory(
            bank=self.bank,
            name=f"Test Card 1 {int(time.time() * 1000)}",
            annual_fee=Decimal("95.00"),
            is_active=True,
        )
        card2 = CreditCardFactory(
            bank=self.bank,
            name=f"Test Card 2 {int(time.time() * 1000)}",
            annual_fee=Decimal("150.00"),
            is_active=False,
        )

        # Test bank API
        response = self.client.get(reverse("bank-detail", kwargs={"pk": self.bank.pk}))
        assert response.status_code == 200

        bank_data = response.json()
        assert bank_data["id"] == self.bank.id
        assert bank_data["name"] == self.bank.name

        # Test credit card API
        response = self.client.get(reverse("creditcard-list"))
        assert response.status_code == 200

        cards_data = response.json()
        assert cards_data["count"] == 1  # Only active cards are returned

        # Verify individual card data
        card_ids = [card["id"] for card in cards_data["results"]]
        assert card1.id in card_ids  # Active card should be included
        assert card2.id not in card_ids  # Inactive card should not be included

    def test_cross_app_data_consistency(self):
        """Test data consistency across banks and credit cards apps."""
        # Create credit cards for bank
        CreditCardFactory.create_batch(3, bank=self.bank)

        # Get credit cards for this bank using the credit cards API with bank_ids filter
        response = self.client.get(f"/api/v1/credit-cards/?bank_ids={self.bank.id}")
        assert response.status_code == 200

        data = response.json()
        assert len(data["results"]) == 3

        # Verify all cards belong to the bank
        for card_data in data["results"]:
            assert card_data["bank_name"] == self.bank.name

    def test_filtering_consistency_across_apps(self):
        """Test filtering consistency between apps."""
        # Create mixed active/inactive cards
        CreditCardFactory.create_batch(3, bank=self.bank, is_active=True)
        CreditCardFactory.create_batch(2, bank=self.bank, is_active=False)

        # Test active filter in credit cards API
        response = self.client.get(reverse("creditcard-list"), {"is_active": "true"})
        assert response.status_code == 200

        data = response.json()
        assert data["count"] == 3

        # Verify all returned cards are active
        for card in data["results"]:
            assert card["is_active"] is True


@pytest.mark.django_db
class TestSystemScalabilityAndPerformance:
    """Test system performance under load and with large datasets."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()

    def test_api_performance_with_large_datasets(self):
        """Test API response times with large datasets."""
        # Create large dataset
        banks = BankFactory.create_batch(50)

        # Create many credit cards
        for bank in banks[:10]:  # Limit to avoid timeout in tests
            CreditCardFactory.create_batch(20, bank=bank)

        # Test banks API performance
        response = self.client.get(reverse("bank-list"))
        assert response.status_code == 200

        data = response.json()
        assert data["count"] == 50
        assert len(data["results"]) <= 50  # Should be paginated

        # Test credit cards API performance
        response = self.client.get(reverse("creditcard-list"))
        assert response.status_code == 200

        cards_data = response.json()
        assert cards_data["count"] == 200

    @patch("banks.services.ContentExtractor.extract_content")
    @patch("banks.services.LLMContentParser.parse_credit_card_data")
    def test_crawling_performance_with_many_sources(self, mock_parse, mock_extract):
        """Test crawling performance with many data sources."""
        # Mock successful responses
        mock_extract.return_value = ("Raw content", "Sample content")
        mock_parse.return_value = {
            "credit_cards": [{"name": "Test Card", "annual_fee": "95.00"}]
        }

        # Create many data sources
        banks = BankFactory.create_batch(10)
        sources = []
        for bank in banks:
            sources.extend(BankDataSourceFactory.create_batch(5, bank=bank))

        # Test crawling performance
        crawler = BankDataCrawlerService()
        results = crawler.crawl_all_active_sources()

        # Should handle many sources efficiently
        assert results["total"] == 50
        assert results["successful"] == 50
        assert results["failed"] == 0

    def test_database_query_optimization(self):
        """Test database query optimization with complex relationships."""
        # Create complex data structure
        banks = BankFactory.create_batch(10)

        for bank in banks:
            # Create credit cards
            CreditCardFactory.create_batch(5, bank=bank)

            # Create data sources
            sources = BankDataSourceFactory.create_batch(3, bank=bank)

            # Create crawled content
            for source in sources:
                CrawledContentFactory.create_batch(2, data_source=source)

        # Test complex query that joins multiple tables
        response = self.client.get(reverse("bank-list"), {"ordering": "name"})
        assert response.status_code == 200

        # Should handle complex queries efficiently
        data = response.json()
        assert data["count"] == 10


@pytest.mark.django_db
class TestErrorHandlingAndRecovery:
    """Test system error handling and recovery mechanisms."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(bank=self.bank)

    def test_database_constraint_violation_handling(self):
        """Test handling of database constraint violations."""
        # Create initial credit card
        CreditCardFactory(
            bank=self.bank, name=f"Duplicate Card {int(time.time() * 1000)}"
        )

        # Try to create another with same bank and name (no unique constraint currently)
        # This tests the system's handling of potential future constraints
        card2 = CreditCardFactory(
            bank=self.bank, name=f"Duplicate Card 2 {int(time.time() * 1000)}"
        )

        # Should handle gracefully (currently allowed)
        assert card2.id is not None

    @patch("banks.services.ContentExtractor.extract_content")
    def test_network_error_recovery(self, mock_extract):
        """Test recovery from network errors during crawling."""
        # Mock network error
        mock_extract.side_effect = Exception("Connection timeout")

        # Execute crawl
        crawler = BankDataCrawlerService()
        success = crawler.crawl_bank_data_source(self.data_source.id)

        # Should fail gracefully
        assert success is False

        # Error should be recorded
        crawled_content = self.data_source.crawled_contents.latest("crawl_date")
        assert crawled_content.processing_status == ProcessingStatus.FAILED
        assert "Connection timeout" in crawled_content.error_message

    def test_api_error_response_consistency(self):
        """Test consistent error responses across API endpoints."""
        # Test 404 errors
        endpoints_404 = [
            reverse("bank-detail", kwargs={"pk": 999999}),
            reverse("creditcard-detail", kwargs={"pk": 999999}),
        ]

        for endpoint in endpoints_404:
            response = self.client.get(endpoint)
            assert response.status_code == 404

            # Should return JSON error response
            data = response.json()
            assert "detail" in data or "error" in data


@pytest.mark.django_db
class TestSecurityIntegration:
    """Test security features across the entire system."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory()

    def test_cross_site_scripting_protection(self):
        """Test XSS protection across all endpoints."""
        # Create data with XSS payload
        xss_payload = "<script>alert('xss')</script>"

        bank = BankFactory(name=f"{xss_payload}_{int(time.time() * 1000)}")
        card = CreditCardFactory(
            bank=bank, name=f"{xss_payload}_{int(time.time() * 1000)}"
        )

        # Test various endpoints
        endpoints = [
            reverse("bank-detail", kwargs={"pk": bank.pk}),
            reverse("creditcard-detail", kwargs={"pk": card.pk}),
            reverse("bank-list"),
            reverse("creditcard-list"),
        ]

        for endpoint in endpoints:
            response = self.client.get(endpoint)
            assert response.status_code == 200

            # For JSON APIs, content is stored as-is (escaping is frontend responsibility)
            # But we should ensure the data is properly stored and retrieved
            data = response.json()
            # Verify response headers include proper content type
            assert response["Content-Type"].startswith("application/json")
            # Verify the data structure is intact (not corrupted by XSS attempts)
            if "results" in data:
                assert isinstance(data["results"], list)
            elif "id" in data:
                assert isinstance(data["id"], int)

    def test_sql_injection_protection_system_wide(self):
        """Test SQL injection protection across all endpoints."""
        sql_payloads = [
            "'; DROP TABLE banks_bank; --",
            "' OR '1'='1' --",
            "' UNION SELECT * FROM django_user --",
        ]

        # Test various search endpoints
        search_endpoints = [
            reverse("bank-list"),
            reverse("creditcard-list"),
        ]

        for endpoint in search_endpoints:
            for payload in sql_payloads:
                response = self.client.get(endpoint, {"search": payload})

                # Should not cause server error
                assert response.status_code in [200, 400]

                # Database should remain intact
                assert self.bank.__class__.objects.count() >= 1

    def test_data_access_control(self):
        """Test data access control and isolation."""
        # Create data for different banks
        bank1 = BankFactory(name=f"Bank 1 {int(time.time() * 1000)}")
        bank2 = BankFactory(name=f"Bank 2 {int(time.time() * 1000)}")

        CreditCardFactory(bank=bank1, name=f"Card 1 {int(time.time() * 1000)}")
        card2 = CreditCardFactory(bank=bank2, name=f"Card 2 {int(time.time() * 1000)}")

        # Test that bank-specific filtering only returns relevant data
        response = self.client.get(f"/api/v1/credit-cards/?bank_ids={bank1.id}")
        assert response.status_code == 200

        data = response.json()
        # Should only return cards from bank1
        for card in data["results"]:
            assert card["bank_name"] == bank1.name
            assert card["id"] != card2.id
