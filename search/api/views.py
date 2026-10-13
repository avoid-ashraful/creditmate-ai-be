"""Read-only search API exposed under ``/api/search/``."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from search import client as client_module
from search import queue as queue_module
from search.queries import filterable_fields, index_name
from search.service import SearchService


class SearchUnavailable(APIException):
    """Raised when the search engine cannot answer the request."""

    status_code = 503
    default_detail = "Search service is temporarily unavailable"
    default_code = "search_unavailable"


def _service():
    """Return a ready to use service instance.

    Returns
    -------
    SearchService
        Service with an active engine connection.

    Raises
    ------
    SearchUnavailable
        If the engine is disabled or unreachable.
    """
    service = SearchService()
    if not service.available or not client_module.ping():
        raise SearchUnavailable()
    return service


def _parse_page(request):
    """Return validated ``(page, page_size)``.

    Parameters
    ----------
    request : Request
        Incoming DRF request.

    Returns
    -------
    tuple of int
        Page number and page size.
    """
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.query_params.get("page_size", 20))
    except (TypeError, ValueError):
        page_size = 20
    return page, min(max(page_size, 1), 100)


class SearchView(APIView):
    """Full text search over banks and credit cards."""

    permission_classes = []

    @extend_schema(
        description="Full text search over banks and credit cards",
        tags=["search"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, *args, **kwargs):
        """Run a search.

        Parameters
        ----------
        request : Request
            Query params: ``q``, ``type`` (banks|cards|all), ``page``,
            ``page_size``, ``ordering`` plus any documented filter.

        Returns
        -------
        Response
            Search results with totals, hits and facet buckets.
        """
        service = _service()
        query = request.query_params.get("q", "").strip()
        kind = request.query_params.get("type", "cards").lower()
        page, page_size = _parse_page(request)
        ordering = request.query_params.get("ordering") or None

        # Everything except the query control params is treated as a filter.
        reserved = {"q", "type", "page", "page_size", "ordering"}
        filters = {
            key: value
            for key, value in request.query_params.items()
            if key not in reserved
        }

        targets = ["banks", "cards"] if kind == "all" else [kind]
        payload = {}
        for target in targets:
            if target not in ("banks", "cards"):
                raise NotFound(f"Unknown search type: {target}")
            payload[target] = service.search(
                target,
                query=query,
                filters=filters,
                page=page,
                page_size=page_size,
                ordering=ordering,
            )
        return Response(
            {
                "query": query,
                "type": kind,
                "page": page,
                "page_size": page_size,
                "results": payload,
            }
        )


class SuggestView(APIView):
    """Type ahead suggestions."""

    permission_classes = []

    @extend_schema(
        description="Get type-ahead suggestions for search queries",
        tags=["search"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, *args, **kwargs):
        """Return suggestions for a partial query.

        Parameters
        ----------
        request : Request
            Query params: ``q``, ``type`` and ``limit``.

        Returns
        -------
        Response
            Suggestion list.
        """
        service = _service()
        query = request.query_params.get("q", "").strip()
        kind = request.query_params.get("type", "cards").lower()
        if kind not in ("banks", "cards"):
            raise NotFound(f"Unknown search type: {kind}")
        if not query:
            return Response({"suggestions": []})
        try:
            limit = int(request.query_params.get("limit", 8))
        except (TypeError, ValueError):
            limit = 8
        return Response({"suggestions": service.suggest(kind, query, size=limit)})


class SearchStatusView(APIView):
    """Search infrastructure status (engine, indexes, queue)."""

    permission_classes = []

    @extend_schema(
        description="Get search service status including engine, indexes, and queue metrics",
        tags=["search"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, *args, **kwargs):
        """Return the search service status.

        Parameters
        ----------
        request : Request
            Unused.

        Returns
        -------
        Response
            Status payload.
        """
        service = SearchService()
        payload = service.status()
        payload["indexes_meta"] = {
            kind: {
                "index": index_name(kind),
                "filterable_fields": filterable_fields(kind),
            }
            for kind in ("banks", "cards")
        }
        payload["queue_depth"] = queue_module.queue_depth()
        payload["sync_mode"] = getattr(settings, "SEARCH_SYNC_MODE", "queue")
        return Response(payload)
