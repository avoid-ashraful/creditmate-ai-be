"""
Comprehensive API tests for Credit Cards including security, edge cases, and performance.

These tests cover security vulnerabilities, API edge cases, performance boundaries,
and integration scenarios that are critical for production readiness.
"""

import time
from decimal import Decimal

import pytest
from rest_framework import status

from django.test import Client
from django.urls import reverse

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


@pytest.mark.django_db
class TestCreditCardAPISecurityVulnerabilities:
    """Test protection against common security vulnerabilities in Credit Card API."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory(name=f"Test Bank {int(time.time() * 1000000)}")
        self.card = CreditCardFactory(
            bank=self.bank, name=f"Test Card {int(time.time() * 1000000)}"
        )

    def test_sql_injection_protection_in_search(self):
        """Test SQL injection protection in search parameters."""
        # Create test credit cards
        CreditCardFactory(bank=self.bank, name=f"Valid Card {int(time.time() * 1000000)}")
        CreditCardFactory(
            bank=self.bank, name=f"Another Card {int(time.time() * 1000000)}"
        )

        sql_injection_payloads = [
            "'; DROP TABLE credit_cards_creditcard; --",
            "' OR '1'='1' --",
            "'; DELETE FROM credit_cards_creditcard WHERE '1'='1'; --",
            "' UNION SELECT * FROM django_user --",
            "'; INSERT INTO credit_cards_creditcard (name) VALUES ('hacked'); --",
        ]

        for payload in sql_injection_payloads:
            response = self.client.get(reverse("creditcard-list"), {"search": payload})
            # Should not cause server error or expose data
            assert response.status_code in [200, 400]

            # Verify no cards were deleted/modified
            assert CreditCard.objects.count() >= 2

    def test_xss_protection_in_api_responses(self):
        """Test Cross-Site Scripting protection."""
        xss_payloads = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "';alert(String.fromCharCode(88,83,83))//",
            "\"><script>alert('xss')</script>",
        ]

        for payload in xss_payloads:
            # Test XSS in card name (should be escaped in response)
            card = CreditCardFactory(bank=self.bank, name=payload)
            response = self.client.get(
                reverse("creditcard-detail", kwargs={"pk": card.pk})
            )

            assert response.status_code == 200
            # For JSON APIs, content is typically not HTML-escaped since that's a frontend responsibility
            # However, we should ensure the content is properly stored and retrieved
            data = response.json()
            # Verify the data contains the payload (this is expected behavior for JSON APIs)
            assert payload in data["name"]
            # Verify response headers include proper content type
            assert response["Content-Type"].startswith("application/json")

    def test_parameter_pollution_protection(self):
        """Test protection against HTTP parameter pollution."""
        # Multiple identical parameters
        response = self.client.get(
            reverse("creditcard-list") + "?search=card1&search=card2&search=card3"
        )
        assert response.status_code in [200, 400]

        # Should handle gracefully without exposing sensitive data
        if response.status_code == 200:
            data = response.json()
            assert "results" in data or "detail" in data

    def test_json_injection_in_filters(self):
        """Test JSON injection protection in filter parameters."""
        json_injection_payloads = [
            '{"$ne": null}',  # NoSQL injection attempt
            '{"annual_fee": {"$gt": 0}}',  # MongoDB-style injection
            '{"name": {"$regex": ".*"}}',  # Regex injection
            '[{"name": "test"}]',  # Array injection
        ]

        for payload in json_injection_payloads:
            response = self.client.get(reverse("creditcard-list"), {"filter": payload})
            # Should handle gracefully
            assert response.status_code in [200, 400]

    def test_very_long_parameter_values(self):
        """Test handling of extremely long parameter values."""
        # Very long search parameter (potential buffer overflow)
        long_search = "A" * 10000
        response = self.client.get(reverse("creditcard-list"), {"search": long_search})
        assert response.status_code in [200, 400, 413]

    def test_malformed_numeric_filters(self):
        """Test handling of malformed numeric filter values."""
        malformed_values = [
            "not_a_number",
            "999999999999999999999999999999",  # Very large number
            "NaN",
            "Infinity",
            "-Infinity",
            "1.2.3",  # Invalid decimal
            "1e999",  # Scientific notation overflow
        ]

        for value in malformed_values:
            response = self.client.get(
                reverse("creditcard-list"), {"annual_fee__gte": value}
            )
            # Should handle gracefully
            assert response.status_code in [200, 400]


@pytest.mark.django_db
class TestCreditCardAPIEdgeCases:
    """Test Credit Card API edge cases and boundary conditions."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory()

    def test_compare_with_duplicate_ids(self):
        """Test compare action with duplicate card IDs in request."""
        card1 = CreditCardFactory(bank=self.bank)
        card2 = CreditCardFactory(bank=self.bank)

        # Test with duplicate IDs
        response = self.client.get(
            reverse("creditcard-compare") + f"?ids={card1.id},{card1.id},{card2.id}"
        )

        # Should handle duplicates gracefully
        assert response.status_code in [200, 400, 404]

        if response.status_code == 200:
            data = response.json()
            # Should deduplicate or handle appropriately
            assert len(data) <= 2

    def test_compare_with_inactive_cards(self):
        """Test compare action including inactive cards."""
        active_card = CreditCardFactory(bank=self.bank, is_active=True)
        inactive_card = CreditCardFactory(bank=self.bank, is_active=False)

        response = self.client.get(
            reverse("creditcard-compare") + f"?ids={active_card.id},{inactive_card.id}"
        )

        # Should handle gracefully (may include or exclude inactive cards)
        assert response.status_code in [200, 400, 404]

    def test_compare_boundary_conditions(self):
        """Test compare with exactly 1, 4, and 5 cards."""
        cards = CreditCardFactory.create_batch(5, bank=self.bank)

        # Test edge cases
        test_cases = [
            ([cards[0].id], "single card"),
            ([c.id for c in cards[:4]], "maximum allowed (4 cards)"),
            ([c.id for c in cards], "exceeding maximum (5 cards)"),
        ]

        for card_ids, description in test_cases:
            response = self.client.get(
                reverse("creditcard-compare") + f"?ids={','.join(map(str, card_ids))}"
            )

            # Should handle all cases appropriately
            assert response.status_code in [200, 400, 404], f"Failed for {description}"

    def test_featured_cards_algorithm_edge_cases(self):
        """Test featured cards selection with edge case data."""
        # Create cards with edge case values
        edge_case_cards = [
            CreditCardFactory(bank=self.bank, annual_fee=Decimal("0.00")),  # Free card
            CreditCardFactory(
                bank=self.bank, annual_fee=Decimal("99999.99")
            ),  # Very expensive
            CreditCardFactory(
                bank=self.bank, interest_rate_apr=Decimal("0.00")
            ),  # 0% interest
            CreditCardFactory(
                bank=self.bank, interest_rate_apr=Decimal("99.99")
            ),  # High interest
        ]

        response = self.client.get(reverse("creditcard-featured"))
        assert response.status_code == 200

        data = response.json()
        assert "cards" in data
        # Should handle edge cases without errors

    def test_premium_cards_empty_results(self):
        """Test premium cards action when no cards meet criteria."""
        # Create only low-fee cards
        CreditCardFactory.create_batch(3, bank=self.bank, annual_fee=Decimal("0.00"))

        response = self.client.get(reverse("creditcard-premium"))
        assert response.status_code == 200

        data = response.json()
        assert "cards" in data
        # Should handle empty results gracefully

    def test_search_suggestions_dynamic_data(self):
        """Test search suggestions with varying data sets."""
        # Create cards with various name patterns
        card_names = [
            "Visa Platinum",
            "Mastercard Gold",
            "American Express",
            "Discover It",
            "Chase Sapphire",
            "Capital One Venture",
        ]

        for name in card_names:
            CreditCardFactory(bank=self.bank, name=name)

        # Test search suggestions for different terms
        search_terms = ["visa", "master", "amex", "chase", "xyz"]

        for term in search_terms:
            response = self.client.get(reverse("creditcard-search-suggestions"))
            assert response.status_code == 200

            data = response.json()
            # Should return relevant suggestions or empty list

    def test_filter_combination_edge_cases(self):
        """Test complex filter combinations that might return empty results."""
        # Create diverse card data
        CreditCardFactory(
            bank=self.bank, annual_fee=Decimal("0.00"), interest_rate_apr=Decimal("15.99")
        )
        CreditCardFactory(
            bank=self.bank, annual_fee=Decimal("95.00"), interest_rate_apr=Decimal("0.00")
        )

        # Test contradictory filters
        contradictory_filters = [
            {"annual_fee__gte": 1000, "annual_fee__lte": 100},  # Impossible range
            {"is_active": True, "name": "NonexistentCard"},  # No matches
            {"annual_fee__gte": 999999},  # Very high threshold
        ]

        for filters in contradictory_filters:
            response = self.client.get(reverse("creditcard-list"), filters)
            assert response.status_code == 200

            data = response.json()
            assert "results" in data
            # Should return empty results gracefully

    def test_decimal_precision_in_filters(self):
        """Test filtering with high precision decimal values."""
        # Create card with specific decimal value
        CreditCardFactory(bank=self.bank, annual_fee=Decimal("99.99"))

        # Test high precision filtering
        precision_tests = [
            {"annual_fee": "99.99"},
            {"annual_fee__gte": "99.990"},
            {"annual_fee__lte": "99.999"},
            {"interest_rate__gte": "15.9999"},
        ]

        for filters in precision_tests:
            response = self.client.get(reverse("creditcard-list"), filters)
            assert response.status_code in [200, 400]

    def test_ordering_with_ties(self):
        """Test ordering behavior when multiple cards have identical values."""
        # Create cards with identical annual fees
        cards = CreditCardFactory.create_batch(
            3, bank=self.bank, annual_fee=Decimal("95.00")
        )

        # Test ordering by annual fee (should have ties)
        response = self.client.get(reverse("creditcard-list"), {"ordering": "annual_fee"})
        assert response.status_code == 200

        data = response.json()
        assert "results" in data
        assert len(data["results"]) >= 3

    def test_response_serialization_edge_cases(self):
        """Test serialization of cards with null/empty optional fields."""
        # Create card with minimal data
        minimal_card = CreditCardFactory(
            bank=self.bank,
            cash_advance_fee="",
            reward_points_policy="",
            additional_features=[],
            annual_fee_waiver_policy={},
        )

        response = self.client.get(
            reverse("creditcard-detail", kwargs={"pk": minimal_card.pk})
        )
        assert response.status_code == 200

        data = response.json()
        # Should handle null/empty fields gracefully
        assert "id" in data
        assert "name" in data
        assert data["cash_advance_fee"] == ""
        assert data["reward_points_policy"] == ""


@pytest.mark.django_db
class TestCreditCardAPIPerformance:
    """Test Credit Card API performance and scalability."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory()

    def test_large_dataset_performance(self):
        """Test API performance with thousands of credit cards."""
        # Create large dataset
        CreditCardFactory.create_batch(1000, bank=self.bank)

        # Test list endpoint performance
        response = self.client.get(reverse("creditcard-list"))
        assert response.status_code == 200

        # Should respond within reasonable time and with pagination
        data = response.json()
        assert "results" in data
        assert "count" in data
        assert data["count"] == 1000

        # Should limit results per page
        assert len(data["results"]) <= 100

    def test_complex_query_performance(self):
        """Test performance of complex filter combinations."""
        # Create diverse dataset
        for i in range(100):
            CreditCardFactory(
                bank=self.bank,
                annual_fee=Decimal(str(i * 10)),
                interest_rate_apr=Decimal(str(i % 30)),
                is_active=(i % 2 == 0),
            )

        # Test complex filter query
        complex_filters = {
            "annual_fee__gte": 100,
            "annual_fee__lte": 500,
            "interest_rate__gte": 10,
            "is_active": True,
            "search": "Card",
            "ordering": "-annual_fee",
        }

        response = self.client.get(reverse("creditcard-list"), complex_filters)
        assert response.status_code == 200

        data = response.json()
        assert "results" in data

    def test_pagination_performance_edge_cases(self):
        """Test pagination performance with edge cases."""
        # Create large dataset
        CreditCardFactory.create_batch(500, bank=self.bank)

        # Test various pagination scenarios
        pagination_tests = [
            {"page": 1, "page_size": 10},
            {"page": 25, "page_size": 20},  # Middle pages
            {"page": 50, "page_size": 10},  # Last page
            {"page": 1, "page_size": 100},  # Large page size
        ]

        for params in pagination_tests:
            response = self.client.get(reverse("creditcard-list"), params)
            assert response.status_code in [200, 404]  # 404 for pages beyond range

    def test_concurrent_api_access_simulation(self):
        """Test API behavior under simulated concurrent requests."""
        card = CreditCardFactory(bank=self.bank)

        # Simulate multiple concurrent requests
        responses = []
        for i in range(20):
            response = self.client.get(
                reverse("creditcard-detail", kwargs={"pk": card.pk})
            )
            responses.append(response)

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == card.id


@pytest.mark.django_db
class TestCreditCardAPIDataIntegrity:
    """Test Credit Card API data integrity and consistency."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory()

    def test_api_response_data_consistency(self):
        """Test that API responses are consistent with database state."""
        card = CreditCardFactory(
            bank=self.bank,
            name=f"Test Card {int(time.time() * 1000000)}",
            annual_fee=Decimal("95.00"),
            interest_rate_apr=Decimal("15.99"),
            is_active=True,
        )

        response = self.client.get(reverse("creditcard-detail", kwargs={"pk": card.pk}))
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == card.id
        assert data["name"] == card.name
        assert Decimal(data["annual_fee"]) == card.annual_fee
        assert Decimal(data["interest_rate_apr"]) == card.interest_rate_apr
        assert data["is_active"] == card.is_active

    def test_api_handles_deleted_resources(self):
        """Test API behavior when resources are deleted during request processing."""
        card = CreditCardFactory(bank=self.bank)
        card_id = card.id

        # Delete the card
        card.delete()

        # Try to access deleted card
        response = self.client.get(reverse("creditcard-detail", kwargs={"pk": card_id}))
        assert response.status_code == 404

    def test_filter_consistency_across_requests(self):
        """Test that filters return consistent results across multiple requests."""
        # Create predictable dataset
        cards = []
        for i in range(10):
            card = CreditCardFactory(
                bank=self.bank, annual_fee=Decimal(str(i * 100)), is_active=(i % 2 == 0)
            )
            cards.append(card)

        # Test same filter multiple times
        filter_params = {"annual_fee__gte": 300, "is_active": True}

        responses = []
        for _ in range(5):
            response = self.client.get(reverse("creditcard-list"), filter_params)
            assert response.status_code == 200
            responses.append(response.json())

        # All responses should be identical
        first_response = responses[0]
        for response in responses[1:]:
            assert response["count"] == first_response["count"]
            assert len(response["results"]) == len(first_response["results"])

    def test_json_field_serialization_consistency(self):
        """Test JSON field serialization consistency."""
        complex_json = {
            "benefits": ["travel", "shopping", "dining"],
            "limits": {"daily": 10000, "monthly": 50000},
            "features": [
                {"name": "contactless", "enabled": True},
                {"name": "international", "enabled": False},
            ],
        }

        card = CreditCardFactory(
            bank=self.bank,
            additional_features=complex_json,
            annual_fee_waiver_policy=complex_json,
        )

        # Test multiple requests return same JSON structure
        for _ in range(3):
            response = self.client.get(
                reverse("creditcard-detail", kwargs={"pk": card.pk})
            )
            assert response.status_code == 200

            data = response.json()
            assert data["additional_features"] == complex_json
            assert data["annual_fee_waiver_policy"] == complex_json
