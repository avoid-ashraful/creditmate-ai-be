from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from credit_cards.api.filters import CreditCardFilter
from credit_cards.api.serializers import (
    BenefitCategorySerializer,
    CreditCardListSerializer,
    CreditCardSerializer,
)
from credit_cards.models import BenefitCategory, CreditCard


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

    @action(detail=False, methods=["get"])
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


class BenefitCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Benefit Categories.

    Provides read-only REST API operations for benefit categories with:
    - List all categories with card counts
    - Search categories by name
    - Filter by category type
    - Order by display order or card count
    """

    queryset = BenefitCategory.objects.filter(is_active=True)
    serializer_class = BenefitCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["display_order", "name", "card_count"]
    ordering = ["display_order", "name"]

    def get_queryset(self):
        """Annotate queryset with credit card counts.

        Parameters
        ----------
        None

        Returns
        -------
        QuerySet
            BenefitCategory queryset annotated with card_count field
        """
        return (
            super()
            .get_queryset()
            .annotate(card_count=Count("credit_cards", distinct=True))
        )

    def list(self, request, *args, **kwargs):
        """List benefit categories with enhanced response.

        Parameters
        ----------
        request : HttpRequest
            Django HTTP request object
        args : tuple
            Positional arguments
        kwargs : dict
            Keyword arguments

        Returns
        -------
        Response
            DRF Response with categories and their card counts
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            # Add card_count to serialized data
            data = serializer.data
            for i, category in enumerate(page):
                data[i]["card_count"] = category.card_count
            return self.get_paginated_response(data)

        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        for i, category in enumerate(queryset):
            data[i]["card_count"] = category.card_count

        return Response(data)

    @action(detail=True, methods=["get"])
    def cards(self, request, pk=None):
        """Get all credit cards in this benefit category.

        Parameters
        ----------
        request : HttpRequest
            Django HTTP request object
        pk : int
            Primary key of the benefit category

        Returns
        -------
        Response
            DRF Response containing list of credit cards in this category
        """
        category = self.get_object()
        cards = CreditCard.objects.filter(
            benefit_categories=category, is_active=True
        ).select_related("bank")

        # Apply same filtering as CreditCardViewSet
        serializer = CreditCardListSerializer(cards, many=True)
        return Response(
            {
                "category": BenefitCategorySerializer(category).data,
                "card_count": cards.count(),
                "cards": serializer.data,
            }
        )
