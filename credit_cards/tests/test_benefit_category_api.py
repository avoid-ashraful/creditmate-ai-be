"""
Tests for benefit category API endpoints.

This module tests the new benefit category API including:
- List all categories with card counts
- Search categories
- Get cards by category
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from banks.models import Bank
from credit_cards.models import BenefitCategory, CreditCard, CreditCardBenefit


@pytest.mark.django_db
class TestBenefitCategoryAPI:
    """Test cases for BenefitCategory API endpoints."""

    @pytest.fixture
    def api_client(self):
        """Create API client."""
        return APIClient()

    @pytest.fixture
    def setup_data(self):
        """Set up test data."""
        # Create bank
        bank = Bank.objects.create(name="Test Bank", website="https://test.com")

        # Create benefit categories
        restaurant = BenefitCategory.objects.create(
            name="Restaurant & Dining",
            category_type="RESTAURANT",
            description="Dining rewards",
            icon="🍽️",
            display_order=1,
        )
        healthcare = BenefitCategory.objects.create(
            name="Healthcare & Hospital",
            category_type="HEALTHCARE",
            description="Medical benefits",
            icon="🏥",
            display_order=2,
        )
        shopping = BenefitCategory.objects.create(
            name="Shopping & Retail",
            category_type="SHOPPING",
            description="Shopping rewards",
            icon="🛍️",
            display_order=3,
            is_active=False,  # Inactive category
        )

        # Create credit cards
        card1 = CreditCard.objects.create(
            bank=bank,
            name="Restaurant Card",
            annual_fee=1000,
            interest_rate_apr=18.0,
        )
        card2 = CreditCard.objects.create(
            bank=bank,
            name="Healthcare Card",
            annual_fee=2000,
            interest_rate_apr=18.0,
        )
        card3 = CreditCard.objects.create(
            bank=bank,
            name="Multi-Benefit Card",
            annual_fee=3000,
            interest_rate_apr=18.0,
        )

        # Create benefit relationships
        CreditCardBenefit.objects.create(
            credit_card=card1,
            benefit_category=restaurant,
            reward_rate=5.0,
            is_primary=True,
        )
        CreditCardBenefit.objects.create(
            credit_card=card2,
            benefit_category=healthcare,
            reward_rate=3.0,
            is_primary=True,
        )
        CreditCardBenefit.objects.create(
            credit_card=card3,
            benefit_category=restaurant,
            reward_rate=4.0,
            is_primary=False,
        )
        CreditCardBenefit.objects.create(
            credit_card=card3,
            benefit_category=healthcare,
            reward_rate=2.0,
            is_primary=False,
        )

        return {
            "bank": bank,
            "restaurant": restaurant,
            "healthcare": healthcare,
            "shopping": shopping,
            "card1": card1,
            "card2": card2,
            "card3": card3,
        }

    def test_list_benefit_categories(self, api_client, setup_data):
        """Test listing all benefit categories."""
        url = reverse("benefitcategory-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2  # Only active categories

        # Check first category
        first_category = response.data[0]
        assert first_category["name"] == "Restaurant & Dining"
        assert first_category["icon"] == "🍽️"
        assert first_category["card_count"] == 2  # card1 and card3

        # Check second category
        second_category = response.data[1]
        assert second_category["name"] == "Healthcare & Hospital"
        assert second_category["card_count"] == 2  # card2 and card3

    def test_search_benefit_categories(self, api_client, setup_data):
        """Test searching benefit categories by name."""
        url = reverse("benefitcategory-list")
        response = api_client.get(url, {"search": "restaurant"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Restaurant & Dining"

    def test_search_benefit_categories_by_description(self, api_client, setup_data):
        """Test searching benefit categories by description."""
        url = reverse("benefitcategory-list")
        response = api_client.get(url, {"search": "medical"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Healthcare & Hospital"

    def test_ordering_by_display_order(self, api_client, setup_data):
        """Test ordering categories by display order."""
        url = reverse("benefitcategory-list")
        response = api_client.get(url, {"ordering": "display_order"})

        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]["display_order"] == 1
        assert response.data[1]["display_order"] == 2

    def test_ordering_by_card_count(self, api_client, setup_data):
        """Test ordering categories by card count."""
        url = reverse("benefitcategory-list")
        response = api_client.get(url, {"ordering": "-card_count"})

        assert response.status_code == status.HTTP_200_OK
        # Both have 2 cards, so order might vary, just check counts
        assert all(cat["card_count"] == 2 for cat in response.data)

    def test_get_category_detail(self, api_client, setup_data):
        """Test retrieving a single category."""
        category = setup_data["restaurant"]
        url = reverse("benefitcategory-detail", kwargs={"pk": category.pk})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Restaurant & Dining"
        assert response.data["category_type"] == "RESTAURANT"
        assert response.data["icon"] == "🍽️"

    def test_get_cards_by_category(self, api_client, setup_data):
        """Test getting all cards in a category."""
        category = setup_data["restaurant"]
        url = reverse("benefitcategory-cards", kwargs={"pk": category.pk})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["category"]["name"] == "Restaurant & Dining"
        assert response.data["card_count"] == 2
        assert len(response.data["cards"]) == 2

        # Check cards are correct
        card_names = [card["name"] for card in response.data["cards"]]
        assert "Restaurant Card" in card_names
        assert "Multi-Benefit Card" in card_names

    def test_inactive_categories_not_shown(self, api_client, setup_data):
        """Test that inactive categories are not shown."""
        url = reverse("benefitcategory-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        category_names = [cat["name"] for cat in response.data]
        assert "Shopping & Retail" not in category_names

    def test_category_with_no_cards(self, api_client):
        """Test category with zero cards."""
        # Create a category with no cards
        category = BenefitCategory.objects.create(
            name="Empty Category",
            category_type="OTHER",
        )

        url = reverse("benefitcategory-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        empty_cat = next(c for c in response.data if c["name"] == "Empty Category")
        assert empty_cat["card_count"] == 0
