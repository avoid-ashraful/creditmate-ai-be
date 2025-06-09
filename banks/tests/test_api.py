import pytest
from rest_framework import status
from rest_framework.test import APIClient

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory


@pytest.mark.django_db
class TestBankAPI:
    """Test Bank API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test data before each test method."""
        self.client = APIClient()
        self.bank1 = BankFactory(name="Alpha Bank", is_active=True)
        self.bank2 = BankFactory(name="Beta Bank", is_active=True)
        self.inactive_bank = BankFactory(name="Inactive Bank", is_active=False)

    def test_bank_list(self):
        """Test listing all active banks."""
        response = self.client.get("/api/v1/banks/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2  # Only active banks

        bank_names = [bank["name"] for bank in response.data["results"]]
        assert "Alpha Bank" in bank_names
        assert "Beta Bank" in bank_names
        assert "Inactive Bank" not in bank_names

    def test_bank_detail(self):
        """Test retrieving a specific bank."""
        response = self.client.get(f"/api/v1/banks/{self.bank1.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Alpha Bank"
        assert response.data["is_active"] is True
        assert "credit_card_count" in response.data

    def test_bank_not_found(self):
        """Test retrieving a non-existent bank."""
        response = self.client.get("/api/v1/banks/99999/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_bank_search(self):
        """Test searching banks by name."""
        response = self.client.get("/api/v1/banks/?search=Alpha Bank")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Bank"

    def test_bank_search_case_insensitive(self):
        """Test that search is case insensitive."""
        response = self.client.get("/api/v1/banks/?search=alpha bank")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Bank"

    def test_bank_filter_by_name(self):
        """Test filtering banks by name."""
        response = self.client.get("/api/v1/banks/?name=Alpha Bank")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Bank"

    def test_bank_filter_has_credit_cards(self):
        """Test filtering banks that have credit cards."""
        # Add credit cards to bank1
        CreditCardFactory.create_batch(2, bank=self.bank1)

        response = self.client.get("/api/v1/banks/?has_credit_cards=true")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Alpha Bank"

    def test_bank_filter_no_credit_cards(self):
        """Test filtering banks that have no credit cards."""
        # Add credit cards to bank1
        CreditCardFactory.create_batch(2, bank=self.bank1)

        response = self.client.get("/api/v1/banks/?has_credit_cards=false")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Beta Bank"

    def test_bank_ordering_by_name(self):
        """Test ordering banks by name."""
        response = self.client.get("/api/v1/banks/?ordering=name")

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert results[0]["name"] == "Alpha Bank"
        assert results[1]["name"] == "Beta Bank"

    def test_bank_ordering_by_name_desc(self):
        """Test ordering banks by name descending."""
        response = self.client.get("/api/v1/banks/?ordering=-name")

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert results[0]["name"] == "Beta Bank"
        assert results[1]["name"] == "Alpha Bank"

    def test_bank_credit_cards_action(self):
        """Test the credit_cards action endpoint."""
        # Add credit cards to bank1
        CreditCardFactory(bank=self.bank1, name="Card 1")
        CreditCardFactory(bank=self.bank1, name="Card 2")
        CreditCardFactory(bank=self.bank1, name="Inactive Card", is_active=False)

        response = self.client.get(f"/api/v1/banks/{self.bank1.id}/credit_cards/")

        assert response.status_code == status.HTTP_200_OK
        assert "bank" in response.data
        assert "credit_cards" in response.data
        assert response.data["bank"]["name"] == "Alpha Bank"
        assert len(response.data["credit_cards"]) == 2  # Only active cards

        card_names = [card["name"] for card in response.data["credit_cards"]]
        assert "Card 1" in card_names
        assert "Card 2" in card_names
        assert "Inactive Card" not in card_names

    def test_bank_serializer_fields(self):
        """Test that all expected fields are present in bank response."""
        response = self.client.get(f"/api/v1/banks/{self.bank1.id}/")

        expected_fields = [
            "id",
            "name",
            "logo",
            "website",
            "is_active",
            "credit_card_count",
            "created",
            "modified",
        ]

        for field in expected_fields:
            assert field in response.data

    def test_bank_list_serializer_fields(self):
        """Test that list view returns lighter serializer."""
        response = self.client.get("/api/v1/banks/")

        expected_fields = ["id", "name", "logo", "credit_card_count", "is_active"]

        for field in expected_fields:
            assert field in response.data["results"][0]

        # These fields should not be in list view
        assert "website" not in response.data["results"][0]
        assert "created" not in response.data["results"][0]
        assert "modified" not in response.data["results"][0]

    @pytest.mark.parametrize(
        "endpoint",
        ["/api/v1/banks/", "/api/v1/banks/1/", "/api/v1/banks/1/credit_cards/"],
    )
    def test_bank_api_read_only(self, endpoint):
        """Test that bank API is read-only."""
        for method in ["post", "put", "patch", "delete"]:
            response = getattr(self.client, method)(endpoint, {})
            assert response.status_code in [
                status.HTTP_405_METHOD_NOT_ALLOWED,
                status.HTTP_404_NOT_FOUND,  # For non-existent detail endpoints
            ]
