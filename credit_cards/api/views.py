from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db.models import Q

from ..models import CreditCard
from .filters import CreditCardFilter
from .serializers import (
    CreditCardComparisonSerializer,
    CreditCardListSerializer,
    CreditCardSerializer,
)


class CreditCardViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Credit Cards.

    Provides read-only operations for credit cards with comprehensive filtering,
    search capabilities, and comparison functionality.
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
        """Return appropriate serializer based on action."""
        if self.action == "list":
            return CreditCardListSerializer
        elif self.action == "compare":
            return CreditCardComparisonSerializer
        return CreditCardSerializer

    @action(detail=False, methods=["get"])
    def compare(self, request):
        """
        Compare up to 4 credit cards side by side.

        Query parameters:
        - ids: Comma-separated list of credit card IDs (max 4)

        Example: /api/v1/credit-cards/compare/?ids=1,2,3,4
        """
        ids_param = request.query_params.get("ids", "")

        if not ids_param:
            return Response(
                {"error": "Please provide credit card IDs to compare using ?ids=1,2,3,4"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            card_ids = [int(id.strip()) for id in ids_param.split(",")]
        except ValueError:
            return Response(
                {
                    "error": "Invalid ID format. Please provide numeric IDs separated by commas."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(card_ids) > 4:
            return Response(
                {"error": "Maximum 4 credit cards can be compared at once."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cards = self.get_queryset().filter(id__in=card_ids)

        if cards.count() != len(card_ids):
            return Response(
                {"error": "One or more credit card IDs not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(cards, many=True)

        return Response({"comparison_count": len(card_ids), "cards": serializer.data})

    @action(detail=False, methods=["get"])
    def featured(self, request):
        """Get featured credit cards (cards with good benefits and reasonable fees)."""
        featured_cards = (
            self.get_queryset()
            .filter(
                Q(annual_fee__lte=2000)
                & (  # Reasonable annual fee
                    Q(lounge_access_international__gt=0) | Q(lounge_access_domestic__gt=0)
                )  # Has lounge access
            )
            .order_by("annual_fee")[:10]
        )

        serializer = CreditCardListSerializer(featured_cards, many=True)

        return Response(
            {
                "message": "Featured credit cards with good value propositions",
                "cards": serializer.data,
            }
        )

    @action(detail=False, methods=["get"])
    def no_annual_fee(self, request):
        """Get credit cards with no annual fee."""
        no_fee_cards = (
            self.get_queryset().filter(annual_fee=0).order_by("interest_rate_apr")
        )

        serializer = CreditCardListSerializer(no_fee_cards, many=True)

        return Response(
            {
                "message": "Credit cards with no annual fee",
                "count": no_fee_cards.count(),
                "cards": serializer.data,
            }
        )

    @action(detail=False, methods=["get"])
    def premium(self, request):
        """Get premium credit cards (high annual fee but premium benefits)."""
        premium_cards = (
            self.get_queryset()
            .filter(annual_fee__gte=5000, lounge_access_international__gte=5)
            .order_by("-lounge_access_international", "-lounge_access_domestic")
        )

        serializer = CreditCardListSerializer(premium_cards, many=True)

        return Response(
            {
                "message": "Premium credit cards with exclusive benefits",
                "count": premium_cards.count(),
                "cards": serializer.data,
            }
        )

    @action(detail=False, methods=["get"])
    def search_suggestions(self, request):
        """Get search suggestions based on popular filters."""
        return Response(
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
