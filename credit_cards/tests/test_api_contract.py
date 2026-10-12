"""Response contract regression tests for the credit card list endpoint.

Covers the manager-requested integration correction: the list response must
include nested bank identity (bank, bank_id) alongside bank_name, plus reward
policy, additional features, waiver policy and detail fee fields that the real
frontend renders. Also covers the bounded page_size paginator (default 20,
hard max 100) needed for real FE paging.
"""

import pytest

from credit_cards.api.serializers import CreditCardListSerializer
from credit_cards.factories import CreditCardFactory
from credit_mate_ai.pagination import BoundedPageNumberPagination

LIST_URL = "/api/v1/credit-cards/"


@pytest.mark.django_db()
class TestListResponseContract:
    def test_list_item_contains_full_contract_fields(self, api_client):
        card = CreditCardFactory(
            reward_points_policy="2 points per 100 BDT",
            additional_features=["Travel insurance"],
            annual_fee_waiver_policy={"condition": "spend 200k"},
            cash_advance_fee="2.5% or 500 BDT",
            late_payment_fee="750 BDT",
        )

        response = api_client.get(LIST_URL)
        assert response.status_code == 200
        item = response.data["results"][0]

        # Bank identity: nested bank object and bank_id, bank_name preserved
        assert item["bank_id"] == card.bank_id
        assert item["bank"]["id"] == card.bank_id
        assert item["bank"]["name"] == card.bank.name
        assert item["bank_name"] == card.bank.name

        # Detail fields the FE renders
        assert item["reward_points_policy"] == "2 points per 100 BDT"
        assert item["additional_features"] == ["Travel insurance"]
        assert item["annual_fee_waiver_policy"] == {"condition": "spend 200k"}
        assert item["cash_advance_fee"] == "2.5% or 500 BDT"
        assert item["late_payment_fee"] == "750 BDT"
        assert "lounge_access_international" in item
        assert "lounge_access_domestic" in item

    def test_list_decimals_stay_truthful(self, api_client):
        card = CreditCardFactory(annual_fee=None, interest_rate_apr=None)
        item = CreditCardListSerializer(card).data
        assert item["annual_fee"] is None
        assert item["interest_rate_apr"] is None

        response = api_client.get(LIST_URL)
        assert response.status_code == 200
        response_item = next(
            result for result in response.data["results"] if result["id"] == card.id
        )
        assert response_item["annual_fee"] is None
        assert response_item["interest_rate_apr"] is None

    def test_legitimate_zero_fee_is_not_null(self, api_client):
        card = CreditCardFactory(annual_fee=0)
        item = CreditCardListSerializer(card).data
        assert item["annual_fee"] == "0.00"
        assert item["has_annual_fee"] is False

        response = api_client.get(LIST_URL)
        assert response.status_code == 200
        response_item = next(
            result for result in response.data["results"] if result["id"] == card.id
        )
        assert response_item["annual_fee"] == "0.00"
        assert response_item["has_annual_fee"] is False


@pytest.mark.django_db()
class TestBoundedPagination:
    def test_defaults(self):
        paginator = BoundedPageNumberPagination()
        assert paginator.page_size == 20
        assert paginator.max_page_size == 100

    def test_default_page_size_is_20(self, api_client):
        CreditCardFactory.create_batch(25)
        response = api_client.get(LIST_URL)
        assert response.status_code == 200
        assert len(response.data["results"]) == 20
        assert response.data["count"] == 25

    def test_custom_page_size_is_honored(self, api_client):
        CreditCardFactory.create_batch(10)
        response = api_client.get(LIST_URL, {"page_size": 4})
        assert len(response.data["results"]) == 4

    def test_page_size_clamped_to_max_100(self, api_client):
        CreditCardFactory.create_batch(120)
        response = api_client.get(LIST_URL, {"page_size": 1000})
        assert response.status_code == 200
        assert len(response.data["results"]) == 100
        assert response.data["count"] == 120
