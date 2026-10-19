"""Pin public API query budgets with populated, mixed-visibility card data."""

import pytest

from django.core.cache import cache

from banks.factories import BankFactory
from credit_cards.api.advanced_filters import compute_facets
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


@pytest.fixture
def catalog(db):
    """Create banks with public, draft, and inactive cards."""
    cards = []
    for index in range(8):
        bank = BankFactory(name=f"Performance Bank {index}")
        cards.append(CreditCardFactory(bank=bank, name=f"Visa {index}", annual_fee=100))
        CreditCardFactory(bank=bank, verification_status="draft")
        CreditCardFactory(bank=bank, is_active=False)
    CreditCardFactory(bank=cards[0].bank, annual_fee=10000)
    return cards


@pytest.mark.django_db
@pytest.mark.parametrize("page_size", [1, 8])
def test_card_list_and_compare_queries(
    catalog, api_client, django_assert_num_queries, page_size
):
    """Both list and comparison avoid one bank count query per result."""
    for params in (
        {"annual_fee_max": 5000, "page_size": page_size},
        {"ids": ",".join(str(card.pk) for card in catalog[:page_size])},
    ):
        cache.clear()
        with django_assert_num_queries(3):
            response = api_client.get("/api/v1/credit-cards/", params)
        assert response.status_code == 200
        assert len(response.data["results"]) == page_size
        for row in response.data["results"]:
            expected = 2 if row["bank"]["id"] == catalog[0].bank_id else 1
            assert row["bank"]["credit_card_count"] == expected
        with django_assert_num_queries(0):
            cached = api_client.get("/api/v1/credit-cards/", params)
        assert cached.data == response.data


@pytest.mark.django_db
@pytest.mark.parametrize("page_size", [1, 8])
def test_bank_list_queries(catalog, api_client, django_assert_num_queries, page_size):
    """Public bank counts are computed together for any page size."""
    with django_assert_num_queries(2):
        response = api_client.get("/api/v1/banks/", {"page_size": page_size})
    assert response.status_code == 200
    assert len(response.data["results"]) == page_size
    assert response.data["results"][0]["credit_card_count"] == 2


@pytest.mark.django_db
def test_card_detail_queries(catalog, api_client, django_assert_num_queries):
    """Detail eagerly loads the public bank count without traversing other relations."""
    with django_assert_num_queries(2):
        response = api_client.get(f"/api/v1/credit-cards/{catalog[0].pk}/")
    assert response.status_code == 200
    assert response.data["bank"]["credit_card_count"] == 2


@pytest.mark.django_db
def test_advanced_search_queries(catalog, api_client, django_assert_num_queries):
    """All facets plus populated cards use a fixed query budget, then hit cache."""
    url = "/api/v1/credit-cards/advanced-search/?annual_fee_max=5000"
    cache.clear()
    with django_assert_num_queries(6):
        response = api_client.get(url)
    assert response.status_code == 200
    assert len(response.data["results"]) == 8
    assert response.data["results"][0]["bank"]["credit_card_count"] == 2
    with django_assert_num_queries(0):
        response = api_client.get(url)
    assert response.data["cached"] is True


@pytest.mark.django_db
def test_facets_count_queries(catalog, django_assert_num_queries):
    """Range, boolean and category buckets share one conditional aggregate."""
    with django_assert_num_queries(3):
        facets = compute_facets(CreditCard.objects.public().filter(annual_fee__lte=5000))
    assert sum(bucket["count"] for bucket in facets["bank"]["buckets"]) == 8
    fee_counts = {
        bucket["key"]: bucket["count"] for bucket in facets["has_annual_fee"]["buckets"]
    }
    assert fee_counts == {"true": 8, "false": 0}
    assert all(bucket["count"] > 0 for bucket in facets["category"]["buckets"])


@pytest.mark.django_db
def test_typeahead_queries_and_invalidation(
    catalog, api_client, django_assert_num_queries, django_capture_on_commit_callbacks
):
    """Repeated typeahead hits cache; committed card changes invalidate it."""
    url = "/api/v1/credit-cards/typeahead/?q=Visa"
    cache.clear()
    with django_assert_num_queries(4):
        first = api_client.get(url)
    assert first.status_code == 200
    assert len(first.data["matches"]["card"]) == 8
    with django_assert_num_queries(0):
        cached = api_client.get(url)
    assert cached.data == first.data
    with django_capture_on_commit_callbacks(execute=True):
        catalog[0].name = "Renamed card"
        catalog[0].save()
    # Seven matches now require both prefix and contains queries.
    with django_assert_num_queries(5):
        updated = api_client.get(url)
    assert len(updated.data["matches"]["card"]) == 7
    with django_assert_num_queries(0):
        api_client.get(url)
