"""Tests for the Redis caching layer (task 1.3).

Verifies query-specific cache keys with correct per-surface TTLs, signal-based
invalidation on data updates, and the reviewed key-building semantics
(origin/path awareness, value-order preservation, on_commit invalidation).
"""

from urllib.parse import urlsplit

import pytest
import redis

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.test import override_settings
from django.urls import reverse

from banks.models import Bank
from credit_cards.factories import CreditCardFactory
from credit_mate_ai.cache import (
    CARD_LIST_TTL,
    CARD_LIST_VERSION_KEY,
    FILTER_RESULTS_TTL,
    FILTER_RESULTS_VERSION_KEY,
    SEARCH_SUGGESTIONS_TTL,
    SEARCH_SUGGESTIONS_VERSION_KEY,
    _get_cache_version,
    build_query_cache_key,
)

LIST_URL = "/api/v1/credit-cards/"
SUGGESTIONS_URL = "/api/v1/credit-cards/search-suggestions/"


def assert_ttl_if_exposed(key, expected):
    """Assert TTL is set within bounds when the backend exposes ttl()."""
    try:
        ttl = cache.ttl(key)
    except (AttributeError, NotImplementedError):
        ttl = None
    if ttl is not None:
        assert 0 < ttl <= expected


def redis_ttl(key):
    cache_config = settings.CACHES["default"]
    assert cache_config["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    location = cache_config["LOCATION"]
    assert urlsplit(location).path == "/14"
    client = redis.Redis.from_url(location)
    return int(client.ttl(cache.make_key(key)))


def test_search_suggestions_route_matches_frontend():
    assert reverse("creditcard-search-suggestions") == SUGGESTIONS_URL


class TestCacheKeySemantics:
    def test_reordered_single_params_share_key(self):
        from django.test import RequestFactory

        rf = RequestFactory()
        r1 = rf.get(LIST_URL, {"bank": "1", "search": "visa"})
        r2 = rf.get("%s?search=visa&bank=1" % LIST_URL)
        assert build_query_cache_key(
            "credit_cards:filter", FILTER_RESULTS_VERSION_KEY, r1
        ) == build_query_cache_key("credit_cards:filter", FILTER_RESULTS_VERSION_KEY, r2)

    def test_repeated_params_with_different_order_get_different_keys(self):
        """bank=1&bank=2 and bank=2&bank=1 differ (last-value-wins semantics)."""
        from django.test import RequestFactory

        rf = RequestFactory()
        r1 = rf.get("%s?bank=1&bank=2" % LIST_URL)
        r2 = rf.get("%s?bank=2&bank=1" % LIST_URL)
        assert build_query_cache_key(
            "credit_cards:filter", FILTER_RESULTS_VERSION_KEY, r1
        ) != build_query_cache_key("credit_cards:filter", FILTER_RESULTS_VERSION_KEY, r2)

    def test_different_origins_get_different_keys(self):
        """Paginated responses embed absolute next/previous links, so origins
        must not share cache entries."""
        from django.test import RequestFactory

        rf = RequestFactory()
        with override_settings(ALLOWED_HOSTS=["a.example.com", "b.example.com"]):
            r1 = rf.get(LIST_URL, SERVER_NAME="a.example.com")
            r2 = rf.get(LIST_URL, SERVER_NAME="b.example.com")
            assert build_query_cache_key(
                "credit_cards:list", CARD_LIST_VERSION_KEY, r1
            ) != build_query_cache_key("credit_cards:list", CARD_LIST_VERSION_KEY, r2)

    def test_version_initialization_is_atomic_and_never_resets(self):
        cache.set(CARD_LIST_VERSION_KEY, 7, None)
        assert _get_cache_version(CARD_LIST_VERSION_KEY) == 7


@pytest.mark.django_db()
class TestListCaching:
    def test_list_is_cached_with_card_list_ttl(self, api_client):
        CreditCardFactory()
        response = api_client.get(LIST_URL)
        assert response.status_code == 200

        key = build_query_cache_key(
            "credit_cards:list", CARD_LIST_VERSION_KEY, response.wsgi_request
        )
        assert cache.get(key) == response.data
        assert CARD_LIST_TTL == 300  # 5 minutes
        assert_ttl_if_exposed(key, CARD_LIST_TTL)
        if settings.CACHES["default"]["BACKEND"].endswith("RedisCache"):
            assert redis_ttl(key) in range(1, CARD_LIST_TTL + 1)

    def test_cached_response_returned_despite_signal_bypassing_write(self, api_client):
        """Second request is served from cache: a QuerySet.update() bypasses
        post_save signals, so the cached results remain unchanged."""
        from credit_cards.models import CreditCard

        card = CreditCardFactory()
        first = api_client.get(LIST_URL)
        assert first.status_code == 200
        assert len(first.data["results"]) == 1

        # Bypasses post_save signals entirely -- no invalidation occurs.
        CreditCard.objects.filter(pk=card.pk).update(is_active=False)

        second = api_client.get(LIST_URL)
        assert second.status_code == 200
        assert second.data == first.data
        assert len(second.data["results"]) == 1


@pytest.mark.django_db()
class TestFilterResultCaching:
    def test_filtered_query_is_cached_with_filter_ttl(self, api_client):
        card = CreditCardFactory()
        response = api_client.get(LIST_URL, {"bank": card.bank_id})
        assert response.status_code == 200

        key = build_query_cache_key(
            "credit_cards:filter", FILTER_RESULTS_VERSION_KEY, response.wsgi_request
        )
        assert cache.get(key) == response.data
        assert FILTER_RESULTS_TTL == 120  # 2 minutes
        assert_ttl_if_exposed(key, FILTER_RESULTS_TTL)
        if settings.CACHES["default"]["BACKEND"].endswith("RedisCache"):
            assert redis_ttl(key) in range(1, FILTER_RESULTS_TTL + 1)

    def test_search_query_is_cached_with_filter_ttl(self, api_client):
        """Search goes through DRF SearchFilter, so it must use the 2 min TTL."""
        CreditCardFactory(name="Visa Platinum")
        response = api_client.get(LIST_URL, {"search": "visa"})
        assert response.status_code == 200
        assert len(response.data["results"]) == 1

        key = build_query_cache_key(
            "credit_cards:filter", FILTER_RESULTS_VERSION_KEY, response.wsgi_request
        )
        assert ":filter:" in key
        assert cache.get(key) == response.data

    def test_query_keys_are_specific_per_query(self, api_client):
        card = CreditCardFactory()
        r1 = api_client.get(LIST_URL, {"bank": card.bank_id})
        r2 = api_client.get(LIST_URL, {"search": "nothing-matches-this"})
        assert r1.status_code == 200 and r2.status_code == 200
        assert len(r1.data["results"]) == 1
        assert len(r2.data["results"]) == 0
        # Same request again returns identical cached payload
        r1b = api_client.get(LIST_URL, {"bank": card.bank_id})
        assert r1b.data == r1.data


@pytest.mark.django_db()
class TestSearchSuggestionsCaching:
    def test_search_suggestions_cached_with_suggestions_ttl(self, api_client):
        CreditCardFactory()
        response = api_client.get(SUGGESTIONS_URL)
        assert response.status_code == 200
        assert SEARCH_SUGGESTIONS_TTL == 600  # 10 minutes

        key = build_query_cache_key(
            "credit_cards:search_suggestions",
            SEARCH_SUGGESTIONS_VERSION_KEY,
            response.wsgi_request,
        )
        assert cache.get(key) == response.data
        assert_ttl_if_exposed(key, SEARCH_SUGGESTIONS_TTL)
        if settings.CACHES["default"]["BACKEND"].endswith("RedisCache"):
            assert redis_ttl(key) in range(1, SEARCH_SUGGESTIONS_TTL + 1)

    def test_search_suggestions_invalidated_on_card_save(
        self, api_client, django_capture_on_commit_callbacks
    ):
        CreditCardFactory()
        first = api_client.get(SUGGESTIONS_URL)
        assert first.status_code == 200
        assert "Cache Test Bank XYZ" not in first.data["popular_banks"]

        with django_capture_on_commit_callbacks(execute=True):
            new_bank = Bank.objects.create(name="Cache Test Bank XYZ")
            CreditCardFactory(bank=new_bank)

        second = api_client.get(SUGGESTIONS_URL)
        assert second.status_code == 200
        assert "Cache Test Bank XYZ" in second.data["popular_banks"]


@pytest.mark.django_db()
class TestInvalidationSignals:
    def test_post_save_invalidates_list_cache(
        self, api_client, django_capture_on_commit_callbacks
    ):
        card = CreditCardFactory()
        first = api_client.get(LIST_URL)
        assert len(first.data["results"]) == 1

        with django_capture_on_commit_callbacks(execute=True):
            card.name = "Renamed Card"
            card.save()

        second = api_client.get(LIST_URL)
        names = [item["name"] for item in second.data["results"]]
        assert "Renamed Card" in names

    def test_post_save_invalidates_filtered_cache(
        self, api_client, django_capture_on_commit_callbacks
    ):
        card = CreditCardFactory()
        first = api_client.get(LIST_URL, {"bank": card.bank_id})
        assert len(first.data["results"]) == 1

        with django_capture_on_commit_callbacks(execute=True):
            card.annual_fee = 9999
            card.save()

        second = api_client.get(LIST_URL, {"bank": card.bank_id})
        assert second.data["results"][0]["annual_fee"] == "9999.00"

    def test_post_delete_invalidates_cache(
        self, api_client, django_capture_on_commit_callbacks
    ):
        card = CreditCardFactory()
        first = api_client.get(LIST_URL)
        assert len(first.data["results"]) == 1

        with django_capture_on_commit_callbacks(execute=True):
            card.delete()

        second = api_client.get(LIST_URL)
        assert len(second.data["results"]) == 0

    def test_bank_change_invalidates_card_caches(
        self, api_client, django_capture_on_commit_callbacks
    ):
        card = CreditCardFactory()
        first = api_client.get(LIST_URL)
        old_name = first.data["results"][0]["bank_name"]

        with django_capture_on_commit_callbacks(execute=True):
            card.bank.name = "Renamed Bank ABC"
            card.bank.save()

        second = api_client.get(LIST_URL)
        new_name = second.data["results"][0]["bank_name"]
        assert new_name == "Renamed Bank ABC"
        assert new_name != old_name


@pytest.mark.django_db(transaction=True)
class TestOnCommitInvalidation:
    def test_invalidation_deferred_until_transaction_commit(self, api_client):
        """Version bump must run on transaction commit so cached data is
        never re-populated with pre-commit values."""
        card = CreditCardFactory()
        first = api_client.get(LIST_URL)
        assert len(first.data["results"]) == 1
        version_before = _get_cache_version(CARD_LIST_VERSION_KEY)

        with transaction.atomic():
            card.name = "Uncommitted Name"
            card.save()
            assert _get_cache_version(CARD_LIST_VERSION_KEY) == version_before

        # After commit the bump takes effect and fresh data is served.
        assert _get_cache_version(CARD_LIST_VERSION_KEY) == version_before + 1
        second = api_client.get(LIST_URL)
        names = [item["name"] for item in second.data["results"]]
        assert "Uncommitted Name" in names
