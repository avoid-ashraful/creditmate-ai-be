"""Tests for the card network / Islamic / dual currency / income filters."""

import pytest

from credit_cards.api.advanced_filters import compute_facets, normalize_query_params
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard

LIST_URL = "/api/v1/credit-cards/"
ADVANCED_URL = "/api/v1/credit-cards/advanced-search/"


@pytest.fixture()
def cards(db):
    """Four cards covering every filter dimension."""
    return {
        "visa": CreditCardFactory(
            name="Visa Card",
            card_network="visa",
            is_islamic=False,
            is_dual_currency=True,
            min_monthly_income=30000,
        ),
        "master": CreditCardFactory(
            name="Master Card",
            card_network="mastercard",
            is_islamic=True,
            is_dual_currency=False,
            min_monthly_income=60000,
        ),
        "amex": CreditCardFactory(
            name="Amex Card",
            card_network="amex",
            is_islamic=False,
            is_dual_currency=None,
            min_monthly_income=None,
        ),
        "plain": CreditCardFactory(name="Plain Card", card_network=""),
    }


def names(response):
    return {card["name"] for card in response.data["results"]}


@pytest.mark.parametrize("url", [LIST_URL, ADVANCED_URL])
class TestCardDetailFilters:
    def test_card_network_single_and_csv(self, api_client, cards, url):
        assert names(api_client.get(url, {"card_network": "visa"})) == {"Visa Card"}
        response = api_client.get(url, {"card_network": "Visa,MASTERCARD"})
        assert names(response) == {"Visa Card", "Master Card"}

    def test_unknown_network_matches_nothing(self, api_client, cards, url):
        assert names(api_client.get(url, {"card_network": "nonsense"})) == set()

    def test_is_islamic(self, api_client, cards, url):
        assert names(api_client.get(url, {"is_islamic": "true"})) == {"Master Card"}
        assert "Master Card" not in names(api_client.get(url, {"is_islamic": "false"}))

    def test_is_dual_currency_excludes_unknown(self, api_client, cards, url):
        assert names(api_client.get(url, {"is_dual_currency": "true"})) == {"Visa Card"}
        assert names(api_client.get(url, {"is_dual_currency": "false"})) == {
            "Master Card"
        }

    def test_income_cap_excludes_unknown_by_default(self, api_client, cards, url):
        assert names(api_client.get(url, {"max_min_monthly_income": 30000})) == {
            "Visa Card"
        }
        assert names(api_client.get(url, {"max_min_monthly_income": 60000})) == {
            "Visa Card",
            "Master Card",
        }

    def test_income_cap_includes_unknown_when_explicit(self, api_client, cards, url):
        params = {"max_min_monthly_income": 30000, "include_unknown_income": "true"}
        assert names(api_client.get(url, params)) == {
            "Visa Card",
            "Amex Card",
            "Plain Card",
        }

    def test_include_unknown_income_alone_is_a_noop(self, api_client, cards, url):
        assert len(names(api_client.get(url, {"include_unknown_income": "true"}))) == 4


@pytest.mark.django_db()
class TestAdvancedDetailSupport:
    def test_explicit_false_survives_normalization(self):
        normalized = normalize_query_params(
            {"is_islamic": "false", "max_min_monthly_income": "40000"}
        )
        assert normalized == {"is_islamic": "false", "max_min_monthly_income": "40000"}

    def test_facets_count_new_fields(self, cards):
        facets = compute_facets(
            CreditCard.objects.all(),
            ["card_network", "is_islamic", "is_dual_currency"],
        )
        networks = {b["key"]: b["count"] for b in facets["card_network"]["buckets"]}
        assert networks["visa"] == 1 and networks["Unknown"] == 1
        islamic = {b["key"]: b["count"] for b in facets["is_islamic"]["buckets"]}
        assert islamic["true"] == 1
        dual = {b["key"]: b["count"] for b in facets["is_dual_currency"]["buckets"]}
        assert dual == {"true": 1, "false": 1}


def test_es_response_normalizes_new_facets():
    from credit_cards.api.advanced_views import _normalize_es_response

    response = {
        "hits": {"total": {"value": 0}, "hits": []},
        "aggregations": {
            "card_network": {"buckets": [{"key": "visa", "doc_count": 3}]},
            "is_islamic": {"buckets": [{"key": True, "doc_count": 1}]},
        },
    }
    facets = _normalize_es_response(response, "", 1, 20)["facets"]
    assert facets["card_network"]["buckets"] == [{"key": "visa", "count": 3}]
    assert facets["is_islamic"]["buckets"][0] == {"key": True, "label": "Yes", "count": 1}
    assert "is_dual_currency" not in facets
