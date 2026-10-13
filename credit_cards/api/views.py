from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.core.cache import cache

from credit_cards.api.filters import CreditCardFilter
from credit_cards.api.serializers import CreditCardListSerializer, CreditCardSerializer
from banks.models import Bank
from credit_cards.models import CreditCard
from django.db import models
from credit_mate_ai.cache import (
    CARD_LIST_TTL,
    CARD_LIST_VERSION_KEY,
    FILTER_RESULTS_TTL,
    FILTER_RESULTS_VERSION_KEY,
    SEARCH_SUGGESTIONS_TTL,
    SEARCH_SUGGESTIONS_VERSION_KEY,
    build_query_cache_key,
)


AUTOCOMPLETE_MIN_QUERY_LENGTH = 2
AUTOCOMPLETE_MAX_RESULTS = 8
AUTOCOMPLETE_TYPO_THRESHOLD = 0.8
AUTOCOMPLETE_QUERY_MAX_LENGTH = 100


def _autocomplete_match_ratio(query, value):
    """Return a safe similarity ratio without a database extension.

    The local ratio is computed on a bounded copy of both strings. It is
    intentionally used only as a fallback ranking/typo signal; normal
    prefix and substring matches remain database-backed.

    Parameters
    ----------
    query : str
        The normalized user query.
    value : str
        The normalized candidate text.

    Returns
    -------
    float
        Similarity in the inclusive range 0.0 to 1.0.
    """
    from difflib import SequenceMatcher

    bounded_value = value[:AUTOCOMPLETE_QUERY_MAX_LENGTH]
    if not query or not bounded_value:
        return 0.0
    return SequenceMatcher(None, query, bounded_value).ratio()


def _build_autocomplete_response(query, cards, banks, facets, did_you_mean):
    """Build the canonical, frontend-facing autocomplete envelope.

    Parameters
    ----------
    query : str
        The user query, returned exactly as received.
    cards : list of CreditCard
        Bounded, ordered card matches.
    banks : list of Bank
        Bounded, ordered bank matches.
    facets : dict
        Bounded active-card facet counts by key.
    did_you_mean : str or None
        Safe close-match suggestion, or ``None`` when unavailable.

    Returns
    -------
    dict
        The canonical typeahead response contract.
    """
    card_matches = [card.name for card in cards]
    bank_matches = [bank.name for bank in banks]
    card_suggestions = []
    for card in cards[:AUTOCOMPLETE_MAX_RESULTS]:
        card_suggestions.append(
            {
                "type": "card",
                "id": card.id,
                "label": card.name,
                "detail": card.bank.name,
                "query": card.name,
            }
        )
    for bank in banks[:AUTOCOMPLETE_MAX_RESULTS - len(card_suggestions)]:
        card_suggestions.append(
            {
                "type": "bank",
                "id": bank.id,
                "label": bank.name,
                "detail": f"{bank.active_card_count} cards",
                "query": bank.name,
            }
        )

    return {
        "query": query,
        "matches": {
            "card": card_matches[:AUTOCOMPLETE_MAX_RESULTS],
            "bank": bank_matches[:AUTOCOMPLETE_MAX_RESULTS],
            "category": [],
            "source": "database",
        },
        "suggestions": card_suggestions[:AUTOCOMPLETE_MAX_RESULTS],
        "facets": facets,
        "did_you_mean": did_you_mean,
        "highlight": {
            "terms": [query],
            "scope": "card_name_and_bank_name",
            "strategy": "case_insensitive_substring",
        },
    }


class CreditCardViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Credit Cards.

    Provides read-only REST API operations for credit cards with comprehensive
    filtering, search capabilities, comparison functionality, and search suggestions.
    Optimized with select_related for efficient database queries.
    """

    queryset = CreditCard.objects.select_related("bank").filter(is_active=True)
    serializer_class = CreditCardSerializer
    permission_classes = [AllowAny]
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

    @action(detail=False, methods=["get"], url_path="autocomplete")
    def autocomplete(self, request):
        """Return bounded, anonymous-safe card and bank typeahead results.

        Parameters
        ----------
        request : HttpRequest
            The incoming request. ``q`` must contain at least two characters;
            a long query is accepted but only its first 100 characters are
            used for matching.

        Returns
        -------
        Response
            The canonical autocomplete response. Category suggestions are an
            explicit empty fallback because no reliable category model exists.
        """
        raw_query = request.query_params.get("q", "")
        query = raw_query[:AUTOCOMPLETE_QUERY_MAX_LENGTH].strip()
        if len(query) < AUTOCOMPLETE_MIN_QUERY_LENGTH:
            response = _build_autocomplete_response(raw_query, [], [], {}, None)
            response["highlight"] = {"terms": [], "scope": None, "strategy": None}
            response["match_policy"] = {
                "minimum_characters": AUTOCOMPLETE_MIN_QUERY_LENGTH,
                "result_limit": AUTOCOMPLETE_MAX_RESULTS,
                "active": False,
            }
            return Response(response)

        card_queryset = self.get_queryset()
        prefix_cards = list(
            card_queryset.filter(name__istartswith=query).order_by("name")[
                :AUTOCOMPLETE_MAX_RESULTS
            ]
        )
        if len(prefix_cards) < AUTOCOMPLETE_MAX_RESULTS:
            contains_cards = list(
                card_queryset.filter(name__icontains=query)
                .exclude(id__in=[card.id for card in prefix_cards])
                .order_by("name")[:AUTOCOMPLETE_MAX_RESULTS]
            )
            prefix_cards.extend(contains_cards)
        prefix_banks = list(
            Bank.objects.filter(is_active=True, name__istartswith=query)
            .annotate(active_card_count=Count("credit_cards", filter=models.Q(
                credit_cards__is_active=True
            )))
            .order_by("name")[:AUTOCOMPLETE_MAX_RESULTS]
        )
        if len(prefix_banks) < AUTOCOMPLETE_MAX_RESULTS:
            prefix_ids = [bank.id for bank in prefix_banks]
            contains_banks = list(
                Bank.objects.filter(is_active=True, name__icontains=query)
                .exclude(id__in=prefix_ids)
                .annotate(active_card_count=Count("credit_cards", filter=models.Q(
                    credit_cards__is_active=True
                )))
                .order_by("name")[:AUTOCOMPLETE_MAX_RESULTS]
            )
            prefix_banks.extend(contains_banks)

        normalized_query = query.casefold()
        card_candidates = prefix_cards
        bank_candidates = prefix_banks
        if not card_candidates and not bank_candidates:
            fallback_cards = list(
                card_queryset.order_by("name")[:AUTOCOMPLETE_MAX_RESULTS * 2]
            )
            fallback_banks = list(
                Bank.objects.filter(is_active=True)
                .annotate(active_card_count=Count("credit_cards", filter=models.Q(
                    credit_cards__is_active=True
                )))
                .order_by("name")[:AUTOCOMPLETE_MAX_RESULTS * 2]
            )
            card_candidates = fallback_cards
            bank_candidates = fallback_banks

        card_matches = sorted(
            card_candidates,
            key=lambda card: _autocomplete_match_ratio(normalized_query, card.name),
            reverse=True,
        )[:AUTOCOMPLETE_MAX_RESULTS]
        bank_matches = sorted(
            bank_candidates,
            key=lambda bank: _autocomplete_match_ratio(normalized_query, bank.name),
            reverse=True,
        )[:AUTOCOMPLETE_MAX_RESULTS]

        facet_counts = card_queryset.aggregate(
            no_fee=Count("id", filter=models.Q(annual_fee=0)),
            travel=Count(
                "id",
                filter=models.Q(
                    models.Q(reward_points_policy__icontains="travel")
                    | models.Q(additional_features__icontains="travel")
                ),
            ),
            cashback=Count(
                "id",
                filter=models.Q(reward_points_policy__icontains="cashback")
            ),
            lounge=Count(
                "id",
                filter=~models.Q(
                    lounge_access_international="", lounge_access_domestic=""
                ),
            ),
        )
        facets = {
            key: {
                "label": label,
                "count": count,
                "filter": filter_value,
            }
            for key, (label, count, filter_value) in {
                "no_fee": ("No Fee", facet_counts["no_fee"], "no_annual_fee=true"),
                "travel": ("Travel", facet_counts["travel"], "feature_search=travel"),
                "cashback": (
                    "Cashback",
                    facet_counts["cashback"],
                    "feature_search=cashback",
                ),
                "lounge": (
                    "Lounge",
                    facet_counts["lounge"],
                    "has_lounge_access=true",
                ),
            }.items()
        }

        did_you_mean = None
        if not card_matches and not bank_matches:
            close_values = [
                (ratio, value)
                for value in (
                    [card.name for card in fallback_cards]
                    + [bank.name for bank in fallback_banks]
                )
                if (ratio := _autocomplete_match_ratio(normalized_query, value))
                >= AUTOCOMPLETE_TYPO_THRESHOLD
            ]
            if close_values:
                did_you_mean = max(close_values, key=lambda item: (item[0], item[1]))[1]

        response_data = _build_autocomplete_response(
            raw_query,
            card_matches,
            bank_matches,
            facets,
            did_you_mean,
        )
        response_data["match_policy"] = {
            "minimum_characters": AUTOCOMPLETE_MIN_QUERY_LENGTH,
            "result_limit": AUTOCOMPLETE_MAX_RESULTS,
            "active": True,
        }
        return Response(response_data)
