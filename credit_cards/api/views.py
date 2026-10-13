from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.core.cache import cache

from credit_cards.api.filters import CreditCardFilter
from credit_cards.api.serializers import CreditCardListSerializer, CreditCardSerializer
from credit_cards.models import CreditCard
from credit_mate_ai.cache import (
    CARD_LIST_TTL,
    CARD_LIST_VERSION_KEY,
    FILTER_RESULTS_TTL,
    FILTER_RESULTS_VERSION_KEY,
    SEARCH_SUGGESTIONS_TTL,
    SEARCH_SUGGESTIONS_VERSION_KEY,
    build_query_cache_key,
)


@extend_schema_view(
    list=extend_schema(
        description="List all active credit cards with filtering and search",
        tags=["credit-cards"],
    ),
    retrieve=extend_schema(
        description="Retrieve a specific credit card by ID",
        tags=["credit-cards"],
    ),
    search_suggestions=extend_schema(
        description="Get search suggestions for annual fee ranges, benefits, and popular banks",
        tags=["credit-cards"],
    ),
)
class CreditCardViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Credit Cards.

    Provides read-only REST API operations for credit cards with comprehensive
    filtering, search capabilities, comparison functionality, and search suggestions.
    Optimized with select_related for efficient database queries.
    """

    queryset = CreditCard.objects.select_related("bank").filter(is_active=True)
    serializer_class = CreditCardSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CreditCardFilter
    search_fields = [
        "name",
        "bank__name",
        "reward_points_policy",
        "cash_advance_fee",
        "late_payment_fee",
    ]
    ordering_fields = [
        "name",
        "annual_fee",
        "interest_rate_apr",
        "lounge_access_international",
        "lounge_access_domestic",
        "created_at",
        "updated_at",
    ]
    ordering = ["bank__name", "name"]

    def get_serializer_class(self):
        """Return appropriate serializer based on action.

        Parameters
        ----------
        None

        Returns
        -------
        class
            CreditCardListSerializer for list actions,
            CreditCardSerializer for detail actions
        """
        if self.action == "list":
            return CreditCardListSerializer
        return CreditCardSerializer

    def list(self, request, *args, **kwargs):
        """List credit cards with query-aware caching.

        Filtered or searched queries (CreditCardFilter params or DRF
        SearchFilter ``search``) use the filter-results TTL (2 min); plain
        list requests use the card list TTL (5 min). Keys are specific to the
        normalized query parameters and request origin/path.
        """
        filter_param_keys = set(self.filterset_class.get_filters().keys())
        has_filters = (
            any(key in request.query_params for key in filter_param_keys)
            or "search" in request.query_params
        )

        cache_key = (
            build_query_cache_key(
                "credit_cards:filter", FILTER_RESULTS_VERSION_KEY, request
            )
            if has_filters
            else build_query_cache_key(
                "credit_cards:list", CARD_LIST_VERSION_KEY, request
            )
        )
        ttl = FILTER_RESULTS_TTL if has_filters else CARD_LIST_TTL

        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            cache.set(cache_key, response.data, ttl)
        return response

    @action(detail=False, methods=["get"], url_path="search-suggestions")
    def search_suggestions(self, request):
        """Get search suggestions based on popular filters.

        Parameters
        ----------
        request : HttpRequest
            Django HTTP request object

        Returns
        -------
        Response
            DRF Response containing structured suggestions for:
            - Annual fee ranges with filter parameters
            - Common benefits with filter parameters
            - Popular bank names for filtering
        """
        cache_key = build_query_cache_key(
            "credit_cards:search_suggestions",
            SEARCH_SUGGESTIONS_VERSION_KEY,
            request,
        )
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        response = Response(
            {
                "annual_fee_ranges": [
                    {"label": "Free", "filter": "annual_fee=0"},
                    {
                        "label": "Low (1-1000)",
                        "filter": "annual_fee_min=1&annual_fee_max=1000",
                    },
                    {
                        "label": "Medium (1001-3000)",
                        "filter": "annual_fee_min=1001&annual_fee_max=3000",
                    },
                    {"label": "Premium (3000+)", "filter": "annual_fee_min=3000"},
                ],
                "benefits": [
                    {
                        "label": "International Lounge Access",
                        "filter": "has_international_lounge=true",
                    },
                    {
                        "label": "Domestic Lounge Access",
                        "filter": "has_domestic_lounge=true",
                    },
                    {"label": "No Annual Fee", "filter": "no_annual_fee=true"},
                    {"label": "Fee Waiver Available", "filter": "has_fee_waiver=true"},
                ],
                "popular_banks": list(
                    self.get_queryset()
                    .values_list("bank__name", flat=True)
                    .distinct()[:10]
                ),
            }
        )
        cache.set(cache_key, response.data, SEARCH_SUGGESTIONS_TTL)
        return response
