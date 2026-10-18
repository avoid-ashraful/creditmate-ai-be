"""Advanced search view for credit cards.

Provides a unified search endpoint with:
- Multi-category OR logic filtering
- Full-text search with relevance scoring
- Faceted counts for filter refinement
- Sort by relevance, fee, APR, lounge access
- Graceful fallback to DB when Elasticsearch is unavailable
- Query normalization for saved searches
- Caching consistent with existing cache layer
"""

import logging
from urllib.parse import urlencode

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.core.cache import cache
from django.db import models

from credit_cards.api.advanced_filters import (
    CANONICAL_CATEGORIES,
    CreditCardAdvancedFilter,
    compute_facets,
    get_sort_options,
    normalize_query_params,
)
from credit_cards.api.serializers import CreditCardListSerializer
from credit_cards.models import CreditCard
from credit_mate_ai.cache import ADVANCED_SEARCH_TTL, ADVANCED_SEARCH_VERSION_KEY
from credit_mate_ai.metrics import increment_search

logger = logging.getLogger(__name__)


# Search constants
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_PAGE_NUMBER = 10000


class ElasticsearchUnavailable(Exception):
    """Raised when Elasticsearch is unavailable and no fallback is configured."""

    pass


def _try_elasticsearch_search(query_params, request):
    """Attempt to execute search via Elasticsearch.

    Parameters
    ----------
    query_params : dict
        Normalized query parameters.
    request : HttpRequest
        The incoming request (for cache key building).

    Returns
    -------
    dict or None
        Search results if successful, None if Elasticsearch is unavailable.
    """
    try:
        from search.client import is_enabled, ping
        from search.queries import build_body
        from search.service import SearchService

        # Check if search is enabled and available
        if not is_enabled():
            return None

        # Quick ping to verify connectivity
        if not ping():
            return None

        service = SearchService()

        # Extract search parameters
        query = query_params.get("search", "").strip()
        page, page_size = _pagination_values(query_params)
        ordering = query_params.get("ordering")

        # Build filters from query params (excluding control params)
        reserved = {"search", "page", "page_size", "ordering", "facets", "categories"}
        filters = {
            key: value for key, value in query_params.items() if key not in reserved
        }

        # Handle categories filter - convert to ES filters
        if "categories" in query_params:
            category_slugs = query_params["categories"].split(",")
            # Map categories to ES filterable fields
            # Use "category" filter which maps to proper ES queries matching DB logic
            filters["category"] = ",".join(category_slugs)

        # Build search body with aggregations for facets
        body = build_body(
            kind="cards",
            query=query if query else None,
            filters=filters,
            page=page,
            page_size=page_size,
            ordering=ordering,
        )

        # Execute search
        index_name = service.resolve_name("credit_cards")
        response = service.client.search(index=index_name, body=body)

        # Normalize response
        return _normalize_es_response(response, query, page, page_size)

    except Exception as exc:
        logger.warning("Elasticsearch search failed, falling back to DB: %s", exc)
        return None


def _normalize_es_response(response, query, page, page_size):
    """Normalize Elasticsearch response to match our API contract.

    Parameters
    ----------
    response : dict
        Raw Elasticsearch response.
    query : str
        Original search query.
    page : int
        Page number.
    page_size : int
        Page size.

    Returns
    -------
    dict
        Normalized response with hits, facets, pagination.
    """
    hits = response.get("hits", {})
    total = hits.get("total", {})
    total_value = total.get("value", 0) if isinstance(total, dict) else total

    documents = []
    for hit in hits.get("hits", []):
        source = dict(hit.get("_source", {}))
        source["_score"] = hit.get("_score")
        documents.append(source)

    aggregations = response.get("aggregations", {})

    # Convert ES aggregations to our facet format
    facets = {}
    if "bank_name" in aggregations:
        facets["bank"] = {
            "label": "Bank",
            "type": "terms",
            "buckets": [
                {"key": bucket["key"], "count": bucket["doc_count"]}
                for bucket in aggregations["bank_name"]["buckets"]
            ],
        }

    if "additional_features" in aggregations:
        facets["features"] = {
            "label": "Features",
            "type": "terms",
            "buckets": [
                {"key": bucket["key"], "count": bucket["doc_count"]}
                for bucket in aggregations["additional_features"]["buckets"]
            ],
        }

    if "annual_fee_ranges" in aggregations:
        facets["annual_fee_range"] = {
            "label": "Annual Fee Range",
            "type": "range",
            "buckets": [
                {
                    "key": bucket["key"],
                    "label": bucket["key"].replace("_", " ").title(),
                    "from": bucket.get("from"),
                    "to": bucket.get("to"),
                    "count": bucket["doc_count"],
                }
                for bucket in aggregations["annual_fee_ranges"]["buckets"]
            ],
        }

    if "interest_rate_apr_ranges" in aggregations:
        facets["interest_rate_range"] = {
            "label": "APR Range",
            "type": "range",
            "buckets": [
                {
                    "key": bucket["key"],
                    "label": bucket["key"].replace("_", " ").title(),
                    "from": bucket.get("from"),
                    "to": bucket.get("to"),
                    "count": bucket["doc_count"],
                }
                for bucket in aggregations["interest_rate_apr_ranges"]["buckets"]
            ],
        }

    if "has_lounge_access" in aggregations:
        facets["lounge_access"] = {
            "label": "Lounge Access",
            "type": "boolean",
            "buckets": [
                {
                    "key": bucket["key"],
                    "label": "Yes" if bucket["key"] else "No",
                    "count": bucket["doc_count"],
                }
                for bucket in aggregations["has_lounge_access"]["buckets"]
            ],
        }

    if "has_annual_fee" in aggregations:
        facets["has_annual_fee"] = {
            "label": "Has Annual Fee",
            "type": "boolean",
            "buckets": [
                {
                    "key": bucket["key"],
                    "label": "Yes" if bucket["key"] else "No",
                    "count": bucket["doc_count"],
                }
                for bucket in aggregations["has_annual_fee"]["buckets"]
            ],
        }

    return {
        "query": query,
        "total": total_value,
        "page": page,
        "page_size": page_size,
        "results": documents,
        "facets": facets,
        "took": response.get("took", 0),
        "source": "elasticsearch",
    }


def _execute_db_search(query_params):
    """Execute search using Django ORM as fallback.

    Parameters
    ----------
    query_params : dict
        Normalized query parameters.

    Returns
    -------
    dict
        Search results with hits, facets, pagination.
    """
    queryset = CreditCard.objects.select_related("bank").public()

    # Apply search query
    search_query = query_params.get("search", "").strip()
    if search_query:
        queryset = queryset.filter(
            models.Q(name__icontains=search_query)
            | models.Q(bank__name__icontains=search_query)
            | models.Q(reward_points_policy__icontains=search_query)
            | models.Q(additional_features__icontains=search_query)
            | models.Q(cash_advance_fee__icontains=search_query)
            | models.Q(late_payment_fee__icontains=search_query)
        )

    # Apply filters using the advanced filter set
    filter_set = CreditCardAdvancedFilter(query_params, queryset=queryset)
    queryset = filter_set.qs

    # Apply ordering
    ordering = query_params.get("ordering")
    if ordering:
        allowed_ordering = {
            "name",
            "-name",
            "annual_fee",
            "-annual_fee",
            "interest_rate_apr",
            "-interest_rate_apr",
            "lounge_access_international",
            "-lounge_access_international",
            "lounge_access_domestic",
            "-lounge_access_domestic",
            "created",
            "-created",
            "modified",
            "-modified",
        }
        if ordering.lstrip("-") in allowed_ordering:
            queryset = queryset.order_by(ordering)
    elif search_query:
        # Default to relevance-like ordering when search query present
        queryset = queryset.order_by("bank__name", "name")

    # Pagination
    page, page_size = _pagination_values(query_params)

    total = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size

    results = list(queryset[start:end])

    # Serialize results
    serializer = CreditCardListSerializer(results, many=True)

    # Compute facets
    facet_names = query_params.get("facets")
    if facet_names:
        facet_list = [f.strip() for f in facet_names.split(",") if f.strip()]
    else:
        facet_list = None

    facets = compute_facets(queryset, facet_names=facet_list)

    return {
        "query": search_query,
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": serializer.data,
        "facets": facets,
        "took": 0,  # DB doesn't provide timing easily
        "source": "database",
    }


def _pagination_values(query_params):
    """Parse bounded pagination values shared by the DB and ES paths."""
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        raise ValueError("page and page_size must be integers") from None
    if page < 1 or page > MAX_PAGE_NUMBER:
        raise ValueError(f"page must be between 1 and {MAX_PAGE_NUMBER}")
    return page, min(max(page_size, 1), MAX_PAGE_SIZE)


def _build_cache_key(prefix, query_params, request):
    """Build a cache key for search results."""
    # Create a deterministic string from query params
    param_string = urlencode(sorted(query_params.items()))
    # Include request origin for absolute URL consistency
    origin = request.build_absolute_uri("/").rstrip("/")
    fingerprint = f"{origin}{request.path}:{param_string}"
    import hashlib

    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:32]

    # Get cache version
    from credit_mate_ai.cache import _get_cache_version

    version = _get_cache_version(ADVANCED_SEARCH_VERSION_KEY)

    return f"{prefix}:v{version}:{digest}"


class AdvancedSearchViewSet(viewsets.ViewSet):
    """Advanced search endpoint for credit cards.

    Provides comprehensive search capabilities including:
    - Full-text search with relevance scoring
    - Multi-category filtering (OR logic)
    - Faceted navigation with counts
    - Flexible sorting (relevance, fee, APR, lounge)
    - Query normalization for saved searches
    - Graceful DB fallback when Elasticsearch is unavailable
    """

    permission_classes = [AllowAny]

    @extend_schema(
        description="Advanced search for credit cards with filtering, faceting, and sorting",
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Full-text search query across card name, bank, rewards, features",
            ),
            OpenApiParameter(
                name="categories",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Comma-separated category slugs for OR filtering (travel,cashback,premium,student,business,no-annual-fee)",
            ),
            OpenApiParameter(
                name="annual_fee_min",
                type=OpenApiTypes.NUMBER,
                location=OpenApiParameter.QUERY,
                description="Minimum annual fee",
            ),
            OpenApiParameter(
                name="annual_fee_max",
                type=OpenApiTypes.NUMBER,
                location=OpenApiParameter.QUERY,
                description="Maximum annual fee",
            ),
            OpenApiParameter(
                name="interest_rate_min",
                type=OpenApiTypes.NUMBER,
                location=OpenApiParameter.QUERY,
                description="Minimum APR",
            ),
            OpenApiParameter(
                name="interest_rate_max",
                type=OpenApiTypes.NUMBER,
                location=OpenApiParameter.QUERY,
                description="Maximum APR",
            ),
            OpenApiParameter(
                name="has_lounge_access",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter cards with any lounge access",
            ),
            OpenApiParameter(
                name="has_international_lounge",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter cards with international lounge access",
            ),
            OpenApiParameter(
                name="has_domestic_lounge",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter cards with domestic lounge access",
            ),
            OpenApiParameter(
                name="no_annual_fee",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter cards with no annual fee",
            ),
            OpenApiParameter(
                name="has_fee_waiver",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter cards with fee waiver policy",
            ),
            OpenApiParameter(
                name="feature_search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Search within additional features",
            ),
            OpenApiParameter(
                name="bank_ids",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Comma-separated bank IDs to filter",
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Sort field (relevance, annual_fee, -annual_fee, interest_rate_apr, -interest_rate_apr, -lounge_access_international, -lounge_access_domestic, name, -name, -created, created)",
                enum=[
                    "relevance",
                    "annual_fee",
                    "-annual_fee",
                    "interest_rate_apr",
                    "-interest_rate_apr",
                    "-lounge_access_international",
                    "-lounge_access_domestic",
                    "name",
                    "-name",
                    "-created",
                    "created",
                ],
            ),
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Page number (1-based)",
            ),
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description=f"Results per page (1-{MAX_PAGE_SIZE}, default {DEFAULT_PAGE_SIZE})",
            ),
            OpenApiParameter(
                name="facets",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Comma-separated facet names to include (bank,category,annual_fee_range,interest_rate_range,lounge_access,fee_waiver,has_annual_fee)",
            ),
        ],
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
        },
        tags=["credit-cards"],
    )
    def list(self, request):
        """Execute advanced search with faceting and sorting.

        Returns paginated results with facet counts for filter refinement.
        Automatically falls back to database search when Elasticsearch is unavailable.
        """
        increment_search("advanced")
        # Normalize query parameters
        normalized_params = normalize_query_params(request.query_params)
        try:
            _pagination_values(normalized_params)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        # Check cache
        cache_key = _build_cache_key(
            "credit_cards:advanced_search", normalized_params, request
        )
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            cached_response["cached"] = True
            return Response(cached_response)

        # Try Elasticsearch first
        es_results = _try_elasticsearch_search(normalized_params, request)

        if es_results is not None:
            results = es_results
        else:
            # Fall back to database search
            logger.info("Using database fallback for advanced search")
            results = _execute_db_search(normalized_params)

        # Add metadata
        results["cached"] = False
        results["sort_options"] = get_sort_options()
        results["categories"] = CANONICAL_CATEGORIES
        results["normalized_query"] = normalized_params

        # Cache the response
        cache.set(cache_key, results, ADVANCED_SEARCH_TTL)

        return Response(results)

    @extend_schema(
        description="Get available sort options for advanced search",
        responses={200: OpenApiTypes.OBJECT},
        tags=["credit-cards"],
    )
    @action(detail=False, methods=["get"], url_path="sort-options")
    def sort_options(self, request):
        """Return available sort options with descriptions."""
        return Response({"sort_options": get_sort_options()})

    @extend_schema(
        description="Get available categories for multi-category filtering",
        responses={200: OpenApiTypes.OBJECT},
        tags=["credit-cards"],
    )
    @action(detail=False, methods=["get"], url_path="categories")
    def categories(self, request):
        """Return canonical category taxonomy."""
        return Response({"categories": CANONICAL_CATEGORIES})

    @extend_schema(
        description="Normalize query parameters for saved search compatibility",
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Full-text search query",
            ),
            OpenApiParameter(
                name="categories",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Comma-separated category slugs",
            ),
            OpenApiParameter(
                name="annual_fee_min",
                type=OpenApiTypes.NUMBER,
                location=OpenApiParameter.QUERY,
                description="Minimum annual fee",
            ),
            OpenApiParameter(
                name="annual_fee_max",
                type=OpenApiTypes.NUMBER,
                location=OpenApiParameter.QUERY,
                description="Maximum annual fee",
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Sort field",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        tags=["credit-cards"],
    )
    @action(detail=False, methods=["get"], url_path="normalize")
    def normalize(self, request):
        """Normalize query parameters for saved search storage.

        Returns a canonical representation of the query parameters that can be
        stored and compared for saved search deduplication.
        """
        normalized = normalize_query_params(request.query_params)
        # Generate a stable hash for the normalized query
        import hashlib

        param_string = urlencode(sorted(normalized.items()))
        query_hash = hashlib.sha256(param_string.encode("utf-8")).hexdigest()[:16]

        return Response(
            {
                "normalized_query": normalized,
                "query_hash": query_hash,
                "canonical_string": param_string,
            }
        )
