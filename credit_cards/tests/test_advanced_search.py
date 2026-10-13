"""Tests for the advanced search endpoint.

Covers multi-category OR logic filtering, faceted counts, sorting,
query normalization, and DB fallback when Elasticsearch is unavailable.
"""

import pytest
from decimal import Decimal

from credit_cards.api.advanced_filters import (
    CATEGORY_SLUGS,
    CreditCardAdvancedFilter,
    compute_facets,
    normalize_query_params,
)
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard
from banks.factories import BankFactory

ADVANCED_SEARCH_URL = "/api/v1/credit-cards/advanced-search/"


@pytest.mark.django_db()
class TestAdvancedFilters:
    """Test the CreditCardAdvancedFilter class."""

    def test_categories_filter_travel(self, api_client):
        """Filter by travel category."""
        CreditCardFactory(
            name="Travel Card",
            reward_points_policy="2x travel rewards"
        )
        CreditCardFactory(name="Cashback Card", reward_points_policy="2% cashback")

        response = api_client.get(ADVANCED_SEARCH_URL, {"categories": "travel"})
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["results"][0]["name"] == "Travel Card"

    def test_categories_filter_multiple_or_logic(self, api_client):
        """Multiple categories should use OR logic."""
        CreditCardFactory(
            name="Travel Card",
            reward_points_policy="2x travel rewards"
        )
        CreditCardFactory(
            name="Cashback Card",
            reward_points_policy="2% cashback"
        )
        CreditCardFactory(name="Premium Card", annual_fee=3000)

        response = api_client.get(ADVANCED_SEARCH_URL, {"categories": "travel,cashback"})
        assert response.status_code == 200
        assert response.data["total"] == 2

    def test_categories_invalid_slug_returns_empty(self, api_client):
        """Invalid category slug should return empty results."""
        CreditCardFactory(name="Travel Card", reward_points_policy="2x travel")

        response = api_client.get(ADVANCED_SEARCH_URL, {"categories": "invalid-category"})
        assert response.status_code == 200
        assert response.data["total"] == 0

    def test_annual_fee_range_filter(self, api_client):
        """Filter by annual fee range."""
        CreditCardFactory(name="Free Card", annual_fee=0)
        CreditCardFactory(name="Low Fee", annual_fee=500)
        CreditCardFactory(name="High Fee", annual_fee=2000)

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "annual_fee_min": "100",
            "annual_fee_max": "1000"
        })
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["results"][0]["name"] == "Low Fee"

    def test_interest_rate_filter(self, api_client):
        """Filter by interest rate range."""
        CreditCardFactory(name="Low APR", interest_rate_apr=Decimal("15.00"))
        CreditCardFactory(name="High APR", interest_rate_apr=Decimal("30.00"))

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "interest_rate_max": "20"
        })
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["results"][0]["name"] == "Low APR"

    def test_no_annual_fee_filter(self, api_client):
        """Filter cards with no annual fee."""
        CreditCardFactory(name="Free Card", annual_fee=0)
        CreditCardFactory(name="Paid Card", annual_fee=1000)

        response = api_client.get(ADVANCED_SEARCH_URL, {"no_annual_fee": "true"})
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["results"][0]["name"] == "Free Card"

    def test_has_lounge_access_filter(self, api_client):
        """Filter cards with lounge access."""
        CreditCardFactory(
            name="Lounge Card",
            lounge_access_international="2 visits",
            lounge_access_domestic="1 visit"
        )
        CreditCardFactory(
            name="No Lounge Card",
            lounge_access_international="",
            lounge_access_domestic=""
        )

        response = api_client.get(ADVANCED_SEARCH_URL, {"has_lounge_access": "true"})
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["results"][0]["name"] == "Lounge Card"

    def test_search_query_full_text(self, api_client):
        """Full-text search across multiple fields."""
        CreditCardFactory(name="Visa Platinum", reward_points_policy="travel rewards")
        CreditCardFactory(name="Mastercard Gold", reward_points_policy="cashback")

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "visa"})
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["results"][0]["name"] == "Visa Platinum"


@pytest.mark.django_db()
class TestAdvancedSearchFacets:
    """Test facet computation in advanced search."""

    def test_facets_included_by_default(self, api_client):
        """Facets should be included in response by default."""
        CreditCardFactory(name="Test Card", annual_fee=0)

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "test"})
        assert response.status_code == 200
        assert "facets" in response.data
        assert isinstance(response.data["facets"], dict)

    def test_category_facets(self, api_client):
        """Category facets should show counts per category."""
        CreditCardFactory(name="Travel Card", reward_points_policy="travel rewards")
        CreditCardFactory(name="Cashback Card", reward_points_policy="cashback")
        CreditCardFactory(name="Free Card", annual_fee=0)

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "card"})
        assert response.status_code == 200
        facets = response.data["facets"]
        assert "category" in facets
        category_buckets = facets["category"]["buckets"]
        category_keys = [b["key"] for b in category_buckets]
        assert "travel" in category_keys
        assert "cashback" in category_keys
        assert "no-annual-fee" in category_keys

    def test_annual_fee_range_facets(self, api_client):
        """Annual fee range facets should show counts per range."""
        CreditCardFactory(name="Free Card", annual_fee=0)
        CreditCardFactory(name="Low Card", annual_fee=500)
        CreditCardFactory(name="High Card", annual_fee=3000)

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "card"})
        assert response.status_code == 200
        facets = response.data["facets"]
        assert "annual_fee_range" in facets
        buckets = facets["annual_fee_range"]["buckets"]
        free_bucket = next(b for b in buckets if b["key"] == "free")
        assert free_bucket["count"] == 1

    def test_bank_facets(self, api_client):
        """Bank facets should show counts per bank."""
        bank = BankFactory(name="Test Bank")
        CreditCardFactory.create_batch(3, bank=bank)

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "card"})
        assert response.status_code == 200
        facets = response.data["facets"]
        assert "bank" in facets
        bank_bucket = next(b for b in facets["bank"]["buckets"] if b["key"] == "Test Bank")
        assert bank_bucket["count"] == 3

    def test_selected_facets_only(self, api_client):
        """Request specific facets only."""
        CreditCardFactory(name="Test Card")

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "search": "test",
            "facets": "category,annual_fee_range"
        })
        assert response.status_code == 200
        facets = response.data["facets"]
        assert "category" in facets
        assert "annual_fee_range" in facets
        assert "bank" not in facets


@pytest.mark.django_db()
class TestAdvancedSearchSorting:
    """Test sorting options in advanced search."""

    def test_sort_by_annual_fee_asc(self, api_client):
        """Sort by annual fee ascending."""
        CreditCardFactory(name="High Fee Card", annual_fee=2000)
        CreditCardFactory(name="Low Fee Card", annual_fee=500)
        CreditCardFactory(name="Free Card", annual_fee=0)

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "search": "card",
            "ordering": "annual_fee"
        })
        assert response.status_code == 200
        fees = [r["annual_fee"] for r in response.data["results"]]
        assert fees == ["0.00", "500.00", "2000.00"]

    def test_sort_by_annual_fee_desc(self, api_client):
        """Sort by annual fee descending."""
        CreditCardFactory(name="High Fee Card", annual_fee=2000)
        CreditCardFactory(name="Low Fee Card", annual_fee=500)
        CreditCardFactory(name="Free Card", annual_fee=0)

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "search": "card",
            "ordering": "-annual_fee"
        })
        assert response.status_code == 200
        fees = [r["annual_fee"] for r in response.data["results"]]
        assert fees == ["2000.00", "500.00", "0.00"]

    def test_sort_by_apr_asc(self, api_client):
        """Sort by APR ascending."""
        CreditCardFactory(name="High APR Card", interest_rate_apr=Decimal("30.00"))
        CreditCardFactory(name="Low APR Card", interest_rate_apr=Decimal("15.00"))

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "search": "card",
            "ordering": "interest_rate_apr"
        })
        assert response.status_code == 200
        aprs = [r["interest_rate_apr"] for r in response.data["results"]]
        assert aprs == ["15.00", "30.00"]

    def test_sort_by_lounge_access_desc(self, api_client):
        """Sort by lounge access descending."""
        CreditCardFactory(name="Lounge Card", lounge_access_international="5 visits", lounge_access_domestic="1 visit")
        CreditCardFactory(name="No Lounge Card", lounge_access_international="", lounge_access_domestic="")

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "search": "card",
            "ordering": "-lounge_access_international"
        })
        assert response.status_code == 200
        assert response.data["results"][0]["name"] == "Lounge Card"

    def test_sort_by_name(self, api_client):
        """Sort by card name."""
        CreditCardFactory(name="Zebra Card")
        CreditCardFactory(name="Alpha Card")

        response = api_client.get(ADVANCED_SEARCH_URL, {
            "search": "card",
            "ordering": "name"
        })
        assert response.status_code == 200
        names = [r["name"] for r in response.data["results"]]
        assert names == ["Alpha Card", "Zebra Card"]

    def test_default_sort_with_search(self, api_client):
        """Default sort should be by relevance when search query present."""
        CreditCardFactory(name="Visa Card")
        CreditCardFactory(name="Mastercard")

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "visa"})
        assert response.status_code == 200
        assert response.data["results"][0]["name"] == "Visa Card"


@pytest.mark.django_db()
class TestAdvancedSearchPagination:
    """Test pagination in advanced search."""

    def test_default_page_size(self, api_client):
        """Default page size should be 20."""
        CreditCardFactory.create_batch(25)
        response = api_client.get(ADVANCED_SEARCH_URL)
        assert response.status_code == 200
        assert len(response.data["results"]) == 20
        assert response.data["page"] == 1
        assert response.data["page_size"] == 20

    def test_custom_page_size(self, api_client):
        """Custom page size should be respected."""
        CreditCardFactory.create_batch(10)
        response = api_client.get(ADVANCED_SEARCH_URL, {"page_size": 5})
        assert response.status_code == 200
        assert len(response.data["results"]) == 5
        assert response.data["page_size"] == 5

    def test_page_size_max_100(self, api_client):
        """Page size should be capped at 100."""
        CreditCardFactory.create_batch(120)
        response = api_client.get(ADVANCED_SEARCH_URL, {"page_size": 1000})
        assert response.status_code == 200
        assert len(response.data["results"]) == 100
        assert response.data["page_size"] == 100

    def test_invalid_pagination_is_rejected(self, api_client):
        for params in ({"page": "not-an-int"}, {"page": 10001}, {"page_size": "x"}):
            response = api_client.get(ADVANCED_SEARCH_URL, params)
            assert response.status_code == 400

    def test_pagination_second_page(self, api_client):
        """Second page should return correct results."""
        CreditCardFactory.create_batch(25, name="Card")
        response = api_client.get(ADVANCED_SEARCH_URL, {"page": 2, "page_size": 10})
        assert response.status_code == 200
        assert len(response.data["results"]) == 10
        assert response.data["page"] == 2


@pytest.mark.django_db()
class TestQueryNormalization:
    """Test query parameter normalization for saved searches."""

    def test_normalize_basic_params(self):
        """Normalize basic scalar parameters."""
        from django.http import QueryDict
        query = QueryDict("search=visa&annual_fee_min=100&annual_fee_max=1000")
        normalized = normalize_query_params(query)
        assert normalized["search"] == "visa"
        assert normalized["annual_fee_min"] == "100"
        assert normalized["annual_fee_max"] == "1000"

    def test_normalize_boolean_params(self):
        """Normalize boolean parameters (only include when true)."""
        from django.http import QueryDict
        query = QueryDict("no_annual_fee=true&has_lounge_access=false")
        normalized = normalize_query_params(query)
        assert normalized["no_annual_fee"] == "true"
        assert "has_lounge_access" not in normalized

    def test_normalize_multi_value_params(self):
        """Normalize multi-value parameters (sorted for consistency)."""
        from django.http import QueryDict
        query = QueryDict("categories=travel,cashback&bank_ids=3,1,2")
        normalized = normalize_query_params(query)
        assert normalized["categories"] == "cashback,travel"
        assert normalized["bank_ids"] == "1,2,3"

    def test_normalize_ordering(self):
        """Normalize ordering parameter."""
        from django.http import QueryDict
        query = QueryDict("ordering=-annual_fee")
        normalized = normalize_query_params(query)
        assert normalized["ordering"] == "-annual_fee"

    def test_normalize_excludes_empty(self):
        """Empty parameters should be excluded."""
        from django.http import QueryDict
        query = QueryDict("search=&annual_fee_min=")
        normalized = normalize_query_params(query)
        assert "search" not in normalized
        assert "annual_fee_min" not in normalized


@pytest.mark.django_db()
class TestNormalizeEndpoint:
    """Test the /normalize endpoint."""

    def test_normalize_endpoint_returns_hash(self, api_client):
        """Normalize endpoint should return normalized query and hash."""
        response = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"search": "visa", "categories": "travel,cashback", "ordering": "-annual_fee"}
        )
        assert response.status_code == 200
        assert "normalized_query" in response.data
        assert "query_hash" in response.data
        assert "canonical_string" in response.data
        assert response.data["normalized_query"]["search"] == "visa"
        assert response.data["normalized_query"]["categories"] == "cashback,travel"

    def test_normalize_endpoint_deterministic_hash(self, api_client):
        """Same query should produce same hash regardless of parameter order."""
        response1 = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"search": "visa", "categories": "travel,cashback"}
        )
        response2 = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"categories": "cashback,travel", "search": "visa"}
        )
        assert response1.data["query_hash"] == response2.data["query_hash"]


@pytest.mark.django_db()
class TestSortOptionsEndpoint:
    """Test the /sort-options endpoint."""

    def test_sort_options_endpoint(self, api_client):
        """Sort options endpoint should return all available sort options."""
        response = api_client.get("/api/v1/credit-cards/advanced-search/sort-options/")
        assert response.status_code == 200
        options = response.data["sort_options"]
        assert len(options) > 0
        keys = [opt["key"] for opt in options]
        assert "relevance" in keys
        assert "annual_fee" in keys
        assert "-annual_fee" in keys
        assert "interest_rate_apr" in keys
        assert "-interest_rate_apr" in keys


@pytest.mark.django_db()
class TestCategoriesEndpoint:
    """Test the /categories endpoint."""

    def test_categories_endpoint(self, api_client):
        """Categories endpoint should return canonical taxonomy."""
        response = api_client.get("/api/v1/credit-cards/advanced-search/categories/")
        assert response.status_code == 200
        categories = response.data["categories"]
        assert len(categories) == 6
        slugs = [c["slug"] for c in categories]
        assert slugs == CATEGORY_SLUGS
        for cat in categories:
            assert "slug" in cat
            assert "name" in cat


@pytest.mark.django_db()
class TestAdvancedFilterClass:
    """Test the CreditCardAdvancedFilter class directly."""

    def test_categories_filter_method(self):
        """Test the filter_categories method directly."""
        queryset = CreditCard.objects.filter(is_active=True)
        CreditCardFactory(name="Travel Card", reward_points_policy="travel rewards")
        CreditCardFactory(name="Cashback Card", reward_points_policy="cashback")
        CreditCardFactory(name="Free Card", annual_fee=0)

        filter_set = CreditCardAdvancedFilter({"categories": "travel,cashback"}, queryset=queryset)
        results = list(filter_set.qs)
        assert len(results) == 2

    def test_search_filter_method(self):
        """Test the filter_search method directly."""
        queryset = CreditCard.objects.filter(is_active=True)
        CreditCardFactory(name="Visa Platinum", reward_points_policy="travel")
        CreditCardFactory(name="Mastercard Gold", reward_points_policy="cashback")

        filter_set = CreditCardAdvancedFilter({"search": "visa"}, queryset=queryset)
        results = list(filter_set.qs)
        assert len(results) == 1
        assert results[0].name == "Visa Platinum"


@pytest.mark.django_db()
class TestComputeFacets:
    """Test the compute_facets utility function."""

    def test_compute_category_facets(self):
        """Test category facet computation."""
        CreditCardFactory(name="Travel", reward_points_policy="travel")
        CreditCardFactory(name="Cashback", reward_points_policy="cashback")

        queryset = CreditCard.objects.filter(is_active=True)
        facets = compute_facets(queryset, facet_names=["category"])
        assert "category" in facets
        category_buckets = facets["category"]["buckets"]
        assert len(category_buckets) >= 2

    def test_compute_annual_fee_range_facets(self):
        """Test annual fee range facet computation."""
        free_card = CreditCardFactory(name="Free Card Facet", annual_fee=0)
        low_card = CreditCardFactory(name="Low Card Facet", annual_fee=500)

        queryset = CreditCard.objects.filter(id__in=[free_card.id, low_card.id])
        facets = compute_facets(queryset, facet_names=["annual_fee_range"])
        assert "annual_fee_range" in facets
        buckets = facets["annual_fee_range"]["buckets"]
        # "free" range (to=0.01) only matches annual_fee=0
        assert any(b["key"] == "free" and b["count"] == 1 for b in buckets)
        # "low" range (0-1000) matches both free (0) and low (500)
        assert any(b["key"] == "low" and b["count"] == 2 for b in buckets)


@pytest.mark.django_db()
class TestDBFallback:
    """Test that search falls back to DB when Elasticsearch is unavailable."""

    def test_search_works_without_elasticsearch(self, api_client, monkeypatch):
        """Search should work even when Elasticsearch is unavailable."""
        # Disable Elasticsearch
        import search.client as client_module
        monkeypatch.setattr(client_module, "is_enabled", lambda: False)

        CreditCardFactory(name="Test Card", annual_fee=0)

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "test"})
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["source"] == "database"

    def test_facets_work_in_db_fallback(self, api_client, monkeypatch):
        """Facets should work in DB fallback mode."""
        import search.client as client_module
        monkeypatch.setattr(client_module, "is_enabled", lambda: False)

        CreditCardFactory(name="Travel Card", reward_points_policy="travel")
        CreditCardFactory(name="Free Card", annual_fee=0)

        response = api_client.get(ADVANCED_SEARCH_URL, {"search": "card"})
        assert response.status_code == 200
        assert response.data["source"] == "database"
        facets = response.data["facets"]
        assert "category" in facets


@pytest.mark.django_db()
class TestSavedSearchCompatibility:
    """Test that normalized queries work for saved searches."""

    def test_same_query_different_order_same_hash(self, api_client):
        """Same query with different param order should produce same hash."""
        response1 = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"search": "visa", "annual_fee_min": "100", "categories": "travel"}
        )
        response2 = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"categories": "travel", "search": "visa", "annual_fee_min": "100"}
        )
        assert response1.data["query_hash"] == response2.data["query_hash"]

    def test_different_query_different_hash(self, api_client):
        """Different queries should produce different hashes."""
        response1 = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"search": "visa"}
        )
        response2 = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"search": "mastercard"}
        )
        assert response1.data["query_hash"] != response2.data["query_hash"]

    def test_boolean_true_only_in_normalized(self, api_client):
        """Only true boolean params should appear in normalized query."""
        response = api_client.get(
            "/api/v1/credit-cards/advanced-search/normalize/",
            {"no_annual_fee": "true", "has_lounge_access": "false"}
        )
        assert "no_annual_fee" in response.data["normalized_query"]
        assert "has_lounge_access" not in response.data["normalized_query"]
