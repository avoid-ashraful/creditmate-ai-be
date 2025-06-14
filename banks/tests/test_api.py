from urllib.parse import urlencode

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.urls import reverse

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory


def reverse_with_qp(url_name, kwargs=None, query_params=None):
    """Utility function to reverse URL with query parameters."""
    url = reverse(url_name, kwargs=kwargs)
    if query_params:
        url += "?" + urlencode(query_params)
    return url


@pytest.mark.django_db
class TestBankAPI:
    """Test Bank API endpoints."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = APIClient()
        # Use unique names per test by including test method id
        import time

        unique_id = str(int(time.time() * 1000000))[-6:]  # Last 6 digits of microseconds
        self.bank1 = BankFactory(name=f"Alpha Bank {unique_id}", is_active=True)
        self.bank2 = BankFactory(name=f"Beta Bank {unique_id}", is_active=True)
        self.inactive_bank = BankFactory(
            name=f"Inactive Bank {unique_id}", is_active=False
        )

        # Set up URLs using reverse
        self.bank_list_url = reverse("bank-list")
        self.bank_detail_url = reverse("bank-detail", kwargs={"pk": self.bank1.id})
        self.bank_not_found_url = reverse("bank-detail", kwargs={"pk": 99999})
        self.bank_credit_cards_url = reverse(
            "bank-credit-cards", kwargs={"pk": self.bank1.id}
        )

    def test_bank_list(self):
        """Test listing all active banks."""
        response = self.client.get(self.bank_list_url)

        assert response.status_code == status.HTTP_200_OK

        # Get the banks we created for this test
        bank_names = [bank["name"] for bank in response.data["results"]]

        # Verify our test banks are in the response
        assert self.bank1.name in bank_names
        assert self.bank2.name in bank_names

        # Verify inactive bank is not in the response
        assert self.inactive_bank.name not in bank_names

        # Verify at least our 2 active banks are returned
        active_count = sum(
            1
            for bank in response.data["results"]
            if bank["name"] in [self.bank1.name, self.bank2.name]
        )
        assert active_count == 2

    def test_bank_detail(self):
        """Test retrieving a specific bank."""
        response = self.client.get(self.bank_detail_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == self.bank1.name
        assert response.data["is_active"] is True
        assert "credit_card_count" in response.data

    def test_bank_not_found(self):
        """Test retrieving a non-existent bank."""
        response = self.client.get(self.bank_not_found_url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_bank_search(self):
        """Test searching banks by name."""
        url = reverse_with_qp("bank-list", query_params={"search": self.bank1.name})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

        # Check that our searched bank is in the results
        bank_names = [bank["name"] for bank in response.data["results"]]
        assert self.bank1.name in bank_names

    def test_bank_search_case_insensitive(self):
        """Test that search is case insensitive."""
        search_term = self.bank1.name.lower()
        url = reverse_with_qp("bank-list", query_params={"search": search_term})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        # Check that our searched bank is in the results (case insensitive)
        bank_names = [bank["name"] for bank in response.data["results"]]
        assert self.bank1.name in bank_names

    def test_bank_filter_by_name(self):
        """Test filtering banks by name."""
        url = reverse_with_qp("bank-list", query_params={"name": self.bank1.name})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        # Check that our specific bank is in the results
        bank_names = [bank["name"] for bank in response.data["results"]]
        assert self.bank1.name in bank_names

    def test_bank_filter_has_credit_cards(self):
        """Test filtering banks that have credit cards."""
        # Add credit cards to bank1
        CreditCardFactory.create_batch(2, bank=self.bank1)

        url = reverse_with_qp("bank-list", query_params={"has_credit_cards": "true"})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

        # Verify that bank1 (which has credit cards) is in the results
        bank_names = [bank["name"] for bank in response.data["results"]]
        assert any("Alpha Bank" in name for name in bank_names)

        # Verify all returned banks have credit cards
        for bank in response.data["results"]:
            assert bank["credit_card_count"] > 0

    def test_bank_filter_no_credit_cards(self):
        """Test filtering banks that have no credit cards."""
        # Add credit cards to bank1 only
        CreditCardFactory.create_batch(2, bank=self.bank1)

        url = reverse_with_qp("bank-list", query_params={"has_credit_cards": "false"})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

        # Verify that bank2 (which has no credit cards) is in the results
        bank_names = [bank["name"] for bank in response.data["results"]]
        assert any("Beta Bank" in name for name in bank_names)

        # Verify all returned banks have no credit cards
        for bank in response.data["results"]:
            assert bank["credit_card_count"] == 0

    def test_bank_ordering_by_name(self):
        """Test ordering banks by name."""
        url = reverse_with_qp("bank-list", query_params={"ordering": "name"})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Check that results are ordered by name (ascending)
        if len(results) >= 2:
            names = [bank["name"] for bank in results]
            assert names == sorted(names), "Banks should be ordered by name ascending"

    def test_bank_ordering_by_name_desc(self):
        """Test ordering banks by name descending."""
        url = reverse_with_qp("bank-list", query_params={"ordering": "-name"})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Check that results are ordered by name (descending)
        if len(results) >= 2:
            names = [bank["name"] for bank in results]
            assert names == sorted(
                names, reverse=True
            ), "Banks should be ordered by name descending"

    def test_bank_credit_cards_action(self):
        """Test the credit_cards action endpoint."""
        # Add credit cards to bank1
        CreditCardFactory(bank=self.bank1, name="Card 1")
        CreditCardFactory(bank=self.bank1, name="Card 2")
        CreditCardFactory(bank=self.bank1, name="Inactive Card", is_active=False)

        response = self.client.get(self.bank_credit_cards_url)

        assert response.status_code == status.HTTP_200_OK
        assert "bank" in response.data
        assert "credit_cards" in response.data
        assert "Alpha Bank" in response.data["bank"]["name"]
        assert len(response.data["credit_cards"]) == 2  # Only active cards

        card_names = [card["name"] for card in response.data["credit_cards"]]
        assert "Card 1" in card_names
        assert "Card 2" in card_names
        assert "Inactive Card" not in card_names

    def test_bank_serializer_fields(self):
        """Test that all expected fields are present in bank response."""
        response = self.client.get(self.bank_detail_url)

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
        response = self.client.get(self.bank_list_url)

        expected_fields = ["id", "name", "logo", "credit_card_count", "is_active"]

        for field in expected_fields:
            assert field in response.data["results"][0]

        # These fields should not be in list view
        assert "website" not in response.data["results"][0]
        assert "created" not in response.data["results"][0]
        assert "modified" not in response.data["results"][0]

    @pytest.mark.parametrize(
        "endpoint_name,kwargs",
        [
            ("bank-list", None),
            ("bank-detail", {"pk": 1}),
            ("bank-credit-cards", {"pk": 1}),
        ],
    )
    def test_bank_api_read_only(self, endpoint_name, kwargs):
        """Test that bank API is read-only."""
        endpoint = reverse(endpoint_name, kwargs=kwargs)
        for method in ["post", "put", "patch", "delete"]:
            response = getattr(self.client, method)(endpoint, {})
            assert response.status_code in [
                status.HTTP_405_METHOD_NOT_ALLOWED,
                status.HTTP_404_NOT_FOUND,  # For non-existent detail endpoints
            ]
