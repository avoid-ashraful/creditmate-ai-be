"""Public read-only retrieval endpoint.

GET /api/v1/retrieval/search/?q=...&product_type=credit_card&bank=..
    &is_islamic=false&k=10&hybrid=true

Disabled unless settings.VECTOR_SEARCH_ENABLED is true.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from credit_mate_ai.throttling import TrustedClientRateThrottle
from retrieval.services import search


class RetrievalSearchView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [TrustedClientRateThrottle]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=True),
            OpenApiParameter("product_type", str, required=False),
            OpenApiParameter("bank", str, required=False),
            OpenApiParameter("is_islamic", bool, required=False),
            OpenApiParameter("k", int, required=False),
            OpenApiParameter("hybrid", bool, required=False),
        ],
        responses={200: None},
    )
    def get(self, request):
        if not getattr(settings, "VECTOR_SEARCH_ENABLED", False):
            return Response({"detail": "Vector search is not enabled."}, status=503)
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response({"detail": "Query parameter 'q' is required."}, status=400)
        try:
            k = int(request.query_params.get("k", 10))
        except (TypeError, ValueError):
            return Response({"detail": "Parameter 'k' must be an integer."}, status=400)
        filters = {
            "product_type": request.query_params.get("product_type"),
            "bank": request.query_params.get("bank"),
            "is_islamic": request.query_params.get("is_islamic"),
        }
        hybrid = (request.query_params.get("hybrid") or "").lower() in (
            "1",
            "true",
            "yes",
        )
        results = search(query, filters=filters, k=k, hybrid=hybrid)
        return Response({"query": query, "count": len(results), "results": results})
