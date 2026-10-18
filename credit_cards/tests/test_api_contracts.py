from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from django.core.cache import cache

from banks.api.serializers import BankListSerializer
from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard

CARD_LIST_FIELDS = {
    "id",
    "bank",
    "bank_id",
    "bank_name",
    "name",
    "annual_fee",
    "interest_rate_apr",
    "lounge_access_international",
    "lounge_access_domestic",
    "cash_advance_fee",
    "late_payment_fee",
    "annual_fee_waiver_policy",
    "reward_points_policy",
    "reward_program_name",
    "reward_earn_rules",
    "cashback_rules",
    "reward_point_value_bdt",
    "points_expiry_text",
    "reward_source_url",
    "additional_features",
    "has_lounge_access",
    "has_annual_fee",
    "is_active",
    "source_url",
    "apply_url",
    "verification_status",
    "verified_at",
    "card_network",
    "is_islamic",
    "is_dual_currency",
    "min_monthly_income",
    "supplementary_card_fee",
    "foreign_transaction_fee",
    "created",
    "modified",
}

CARD_DETAIL_FIELDS = CARD_LIST_FIELDS - {"bank_id", "bank_name"}

BANK_FIELDS = {"id", "name", "logo", "credit_card_count", "is_active"}


class CreditCardAPIContractTests(APITestCase):
    """Local consumer-facing contract checks for the Task 5.4 API."""

    client_class = APIClient

    def setUp(self):
        cache.clear()

    def test_list_uses_paginated_envelope_and_card_schema(self):
        card = CreditCardFactory(
            annual_fee=0,
            lounge_access_international="",
            lounge_access_domestic="",
        )
        paid_card = CreditCardFactory(bank=card.bank, annual_fee=250)

        response = self.client.get("/api/v1/credit-cards/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data.keys()), {"count", "next", "previous", "results"}
        )
        self.assertEqual(response.data["count"], 2)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertIsInstance(response.data["results"], list)

        result = next(item for item in response.data["results"] if item["id"] == card.id)
        paid_result = next(
            item for item in response.data["results"] if item["id"] == paid_card.id
        )
        self.assertEqual(set(result.keys()), CARD_LIST_FIELDS)
        self.assertEqual(result["id"], card.id)
        self.assertIsInstance(result["bank"], dict)
        self.assertEqual(set(result["bank"].keys()), BANK_FIELDS)
        self.assertEqual(result["bank"], BankListSerializer(card.bank).data)
        self.assertEqual(result["bank_id"], card.bank.id)
        self.assertEqual(result["bank_name"], card.bank.name)
        self.assertIsInstance(result["annual_fee"], str)
        self.assertEqual(result["annual_fee"], "0.00")
        self.assertIsNotNone(result["annual_fee"])
        self.assertEqual(paid_result["annual_fee"], "250.00")
        self.assertIs(paid_result["has_annual_fee"], True)
        self.assertIsInstance(result["interest_rate_apr"], str)
        self.assertIsInstance(result["lounge_access_international"], str)
        self.assertIsInstance(result["lounge_access_domestic"], str)
        self.assertIsInstance(result["cash_advance_fee"], str)
        self.assertIsInstance(result["late_payment_fee"], str)
        self.assertIsInstance(result["annual_fee_waiver_policy"], dict)
        self.assertIsInstance(result["reward_points_policy"], str)
        self.assertIsInstance(result["additional_features"], list)
        self.assertIsNone(result["has_lounge_access"])
        self.assertIs(result["has_annual_fee"], False)
        self.assertIs(result["is_active"], True)
        self.assertIsInstance(result["created"], str)
        self.assertIsInstance(result["modified"], str)

    def test_detail_schema_has_lounge_total_but_not_denormalized_bank(self):
        """Assert the detail serializer's actual contract.

        Detail responses intentionally use the same nested bank shape as the
        list response, while omitting the list-only denormalized bank fields.
        """
        card = CreditCardFactory(
            lounge_access_international=2,
            lounge_access_domestic=3,
        )

        response = self.client.get(f"/api/v1/credit-cards/{card.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data.keys()), CARD_DETAIL_FIELDS)
        self.assertNotIn("bank_id", response.data)
        self.assertNotIn("bank_name", response.data)
        self.assertEqual(set(response.data["bank"].keys()), BANK_FIELDS)
        self.assertEqual(response.data["bank"], BankListSerializer(card.bank).data)
        self.assertIs(response.data["has_lounge_access"], True)

    def test_pagination_contract_preserves_count_and_cursors(self):
        """Assert page semantics rather than cursor URL equality."""
        CreditCardFactory.create_batch(3)

        first_page = self.client.get("/api/v1/credit-cards/", {"page_size": 2})
        second_page = self.client.get(first_page.data["next"])

        self.assertEqual(first_page.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(first_page.data.keys()), {"count", "next", "previous", "results"}
        )
        self.assertEqual(first_page.data["count"], 3)
        self.assertEqual(len(first_page.data["results"]), 2)
        self.assertTrue(
            str(first_page.data["next"]).startswith(
                "http://testserver/api/v1/credit-cards/"
            )
        )
        self.assertIsNone(first_page.data["previous"])
        self.assertEqual(second_page.status_code, status.HTTP_200_OK)
        self.assertEqual(second_page.data["count"], 3)
        self.assertEqual(len(second_page.data["results"]), 1)
        self.assertIsNone(second_page.data["next"])
        self.assertEqual(set(second_page.data["results"][0].keys()), CARD_LIST_FIELDS)
        self.assertNotEqual(first_page.data["results"], second_page.data["results"])
        self.assertEqual(
            {item["id"] for item in first_page.data["results"]}
            | {item["id"] for item in second_page.data["results"]},
            set(CreditCard.objects.values_list("id", flat=True)),
        )

    def test_search_suggestions_contract(self):
        bank = BankFactory(name="Contract Bank")
        CreditCardFactory(bank=bank, is_active=True)

        response = self.client.get("/api/v1/credit-cards/search-suggestions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data.keys()),
            {"annual_fee_ranges", "benefits", "popular_banks"},
        )
        self.assertEqual(len(response.data["annual_fee_ranges"]), 4)
        self.assertEqual(len(response.data["benefits"]), 4)
        self.assertEqual(response.data["popular_banks"], ["Contract Bank"])
        for suggestion in response.data["annual_fee_ranges"]:
            self.assertEqual(set(suggestion.keys()), {"label", "filter"})
            self.assertIsInstance(suggestion["label"], str)
            self.assertIsInstance(suggestion["filter"], str)
        for benefit in response.data["benefits"]:
            self.assertEqual(set(benefit.keys()), {"label", "filter"})
            self.assertIsInstance(benefit["label"], str)
            self.assertIsInstance(benefit["filter"], str)
        for bank_name in response.data["popular_banks"]:
            self.assertIsInstance(bank_name, str)

    def test_invalid_filter_returns_stable_error_envelope(self):
        CreditCardFactory()

        response = self.client.get(
            "/api/v1/credit-cards/", {"annual_fee_min": "not-a-number"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data.keys()), {"annual_fee_min"})
        self.assertIsInstance(response.data["annual_fee_min"], list)
        self.assertIn("Enter a number.", response.data["annual_fee_min"][0])

    def test_unknown_detail_returns_error_shape(self):
        CreditCardFactory()
        unavailable_id = CreditCard.objects.latest("id").id + 1

        response = self.client.get(f"/api/v1/credit-cards/{unavailable_id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            str(response.data["detail"]), "No CreditCard matches the given query."
        )
        self.assertEqual(response.data["detail"].code, "not_found")
