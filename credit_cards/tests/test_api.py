from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory, PremiumCreditCardFactory


@pytest.mark.django_db
class TestCreditCardAPI:
    """Test Credit Card API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test data before each test method."""
        self.client = APIClient()
        self.bank1 = BankFactory(name="Alpha Bank")
        self.bank2 = BankFactory(name="Beta Bank")

        self.card1 = CreditCardFactory(
            bank=self.bank1,
            name="Alpha Card",
            annual_fee=Decimal("1000"),
            interest_rate_apr=Decimal("25.5"),
            lounge_access_international=5,
            lounge_access_domestic=10,
        )
        self.card2 = CreditCardFactory(
            bank=self.bank2,
            name="Beta Card",
            annual_fee=Decimal("0"),
            interest_rate_apr=Decimal("30.0"),
            lounge_access_international=0,
            lounge_access_domestic=0,
        )
        self.inactive_card = CreditCardFactory(
            bank=self.bank1, name="Inactive Card", is_active=False
        )

    def test_credit_card_list(self):
        """Test listing all active credit cards."""
        response = self.client.get("/api/v1/credit-cards/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2  # Only active cards

        card_names = [card["name"] for card in response.data["results"]]
        assert "Alpha Card" in card_names
        assert "Beta Card" in card_names
        assert "Inactive Card" not in card_names

    def test_credit_card_detail(self):
        """Test retrieving a specific credit card."""
        response = self.client.get(f"/api/v1/credit-cards/{self.card1.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Alpha Card"
        assert response.data["bank"]["name"] == "Alpha Bank"
        assert response.data["has_lounge_access"] is True
        assert response.data["has_annual_fee"] is True

    def test_credit_card_search(self):
        """Test searching credit cards by name."""
        response = self.client.get("/api/v1/credit-cards/?search=Alpha Card")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Card"

    def test_credit_card_search_by_bank(self):
        """Test searching credit cards by bank name."""
        response = self.client.get("/api/v1/credit-cards/?search=Alpha Bank")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["bank_name"] == "Alpha Bank"

    def test_credit_card_filter_by_bank(self):
        """Test filtering credit cards by bank."""
        response = self.client.get(f"/api/v1/credit-cards/?bank={self.bank1.id}")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["bank_name"] == "Alpha Bank"

    def test_credit_card_filter_by_annual_fee_range(self):
        """Test filtering credit cards by annual fee range."""
        response = self.client.get(
            "/api/v1/credit-cards/?annual_fee_min=500&annual_fee_max=1500"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Card"

    def test_credit_card_filter_no_annual_fee(self):
        """Test filtering credit cards with no annual fee."""
        response = self.client.get("/api/v1/credit-cards/?no_annual_fee=true")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Beta Card"
        assert response.data["results"][0]["annual_fee"] == "0.00"

    def test_credit_card_filter_has_lounge_access(self):
        """Test filtering credit cards with lounge access."""
        response = self.client.get("/api/v1/credit-cards/?has_lounge_access=true")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Card"

    def test_credit_card_filter_international_lounge(self):
        """Test filtering credit cards with international lounge access."""
        response = self.client.get("/api/v1/credit-cards/?has_international_lounge=true")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["lounge_access_international"] > 0

    def test_credit_card_ordering(self):
        """Test ordering credit cards by annual fee."""
        response = self.client.get("/api/v1/credit-cards/?ordering=annual_fee")

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert float(results[0]["annual_fee"]) <= float(results[1]["annual_fee"])

    def test_credit_card_compare_action(self):
        """Test the compare action endpoint."""
        response = self.client.get(
            f"/api/v1/credit-cards/compare/?ids={self.card1.id}, {self.card2.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["comparison_count"] == 2
        assert len(response.data["cards"]) == 2

        card_names = [card["name"] for card in response.data["cards"]]
        assert "Alpha Card" in card_names
        assert "Beta Card" in card_names

    def test_credit_card_compare_action_too_many_cards(self):
        """Test compare action with too many cards."""
        cards = CreditCardFactory.create_batch(5)
        card_ids = ",".join(str(card.id) for card in cards)

        response = self.client.get(f"/api/v1/credit-cards/compare/?ids={card_ids}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum 4 credit cards" in response.data["error"]

    def test_credit_card_compare_action_invalid_ids(self):
        """Test compare action with invalid IDs."""
        response = self.client.get("/api/v1/credit-cards/compare/?ids=invalid,ids")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid ID format" in response.data["error"]

    def test_credit_card_compare_action_no_ids(self):
        """Test compare action without IDs."""
        response = self.client.get("/api/v1/credit-cards/compare/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Please provide credit card IDs" in response.data["error"]

    def test_credit_card_featured_action(self):
        """Test the featured action endpoint."""
        # Create some featured cards
        PremiumCreditCardFactory.create_batch(2, annual_fee=Decimal("1500"))

        response = self.client.get("/api/v1/credit-cards/featured/")

        assert response.status_code == status.HTTP_200_OK
        assert "cards" in response.data
        assert len(response.data["cards"]) > 0

    def test_credit_card_no_annual_fee_action(self):
        """Test the no_annual_fee action endpoint."""
        response = self.client.get("/api/v1/credit-cards/no_annual_fee/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["cards"][0]["name"] == "Beta Card"

    def test_credit_card_premium_action(self):
        """Test the premium action endpoint."""
        # Create premium cards
        PremiumCreditCardFactory.create_batch(2)

        response = self.client.get("/api/v1/credit-cards/premium/")

        assert response.status_code == status.HTTP_200_OK
        assert "cards" in response.data
        assert response.data["count"] >= 0

    def test_credit_card_search_suggestions_action(self):
        """Test the search_suggestions action endpoint."""
        response = self.client.get("/api/v1/credit-cards/search_suggestions/")

        assert response.status_code == status.HTTP_200_OK
        assert "annual_fee_ranges" in response.data
        assert "benefits" in response.data
        assert "popular_banks" in response.data

    def test_credit_card_serializer_fields(self):
        """Test that all expected fields are present in credit card response."""
        response = self.client.get(f"/api/v1/credit-cards/{self.card1.id}/")

        expected_fields = [
            "id",
            "bank",
            "name",
            "annual_fee",
            "interest_rate_apr",
            "lounge_access_international",
            "lounge_access_domestic",
            "cash_advance_fee",
            "late_payment_fee",
            "annual_fee_waiver_policy",
            "reward_points_policy",
            "additional_features",
            "source_url",
            "is_active",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
            "created_at",
            "updated_at",
        ]

        for field in expected_fields:
            assert field in response.data

    def test_credit_card_list_serializer_fields(self):
        """Test that list view returns lighter serializer."""
        response = self.client.get("/api/v1/credit-cards/")

        expected_fields = [
            "id",
            "bank_name",
            "name",
            "annual_fee",
            "interest_rate_apr",
            "lounge_access_international",
            "lounge_access_domestic",
            "has_lounge_access",
            "has_annual_fee",
            "is_active",
        ]

        for field in expected_fields:
            assert field in response.data["results"][0]

    @pytest.mark.parametrize(
        "filter_param,expected_count",
        [
            ("has_lounge_access=true", 1),
            ("has_lounge_access=false", 1),
            ("has_annual_fee=true", 1),
            ("has_annual_fee=false", 1),
            ("annual_fee_min=1000", 1),
            ("annual_fee_max=500", 1),
            ("interest_rate_min=30", 1),
            ("interest_rate_max=26", 1),
        ],
    )
    def test_credit_card_filters(self, filter_param, expected_count):
        """Test various credit card filters."""
        response = self.client.get(f"/api/v1/credit-cards/?{filter_param}")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == expected_count

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/v1/credit-cards/",
            "/api/v1/credit-cards/1/",
            "/api/v1/credit-cards/compare/",
            "/api/v1/credit-cards/featured/",
            "/api/v1/credit-cards/no_annual_fee/",
            "/api/v1/credit-cards/premium/",
            "/api/v1/credit-cards/search_suggestions/",
        ],
    )
    def test_credit_card_api_read_only(self, endpoint):
        """Test that credit card API is read-only."""
        for method in ["post", "put", "patch", "delete"]:
            response = getattr(self.client, method)(endpoint, {})
            assert response.status_code in [
                status.HTTP_405_METHOD_NOT_ALLOWED,
                status.HTTP_404_NOT_FOUND,  # For non-existent detail endpoints
            ]

    def test_credit_card_filter_combinations(self):
        """Test combining multiple filters."""
        response = self.client.get(
            "/api/v1/credit-cards/?has_lounge_access=true&annual_fee_min=500"
        )

        assert response.status_code == status.HTTP_200_OK
        # Should return cards with lounge access and annual fee >= 500
        for card in response.data["results"]:
            assert card["has_lounge_access"] is True
            assert float(card["annual_fee"]) >= 500
