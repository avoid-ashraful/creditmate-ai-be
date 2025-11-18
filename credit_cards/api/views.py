from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count
from rest_framework import filters, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from credit_cards.api.filters import CreditCardFilter
from credit_cards.api.serializers import (
    BenefitCategorySerializer,
    CreditCardListSerializer,
    CreditCardRatingCreateSerializer,
    CreditCardRatingSerializer,
    CreditCardReviewCreateSerializer,
    CreditCardReviewListSerializer,
    CreditCardReviewSerializer,
    CreditCardSerializer,
)
from credit_cards.models import (
    BenefitCategory,
    CreditCard,
    CreditCardRating,
    CreditCardReview,
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
    """ViewSet for Benefit Categories with card counts."""

    queryset = BenefitCategory.objects.filter(is_active=True)
    serializer_class = BenefitCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["display_order", "name", "card_count"]
    ordering = ["display_order", "name"]

    def get_queryset(self):
        """Annotate queryset with card count."""
        return super().get_queryset().annotate(card_count=Count("credit_cards", distinct=True))

    @action(detail=True, methods=["get"])
    def cards(self, request, pk=None):
        """Get all credit cards in this benefit category."""
        category = self.get_object()
        cards = CreditCard.objects.filter(benefit_categories=category, is_active=True).select_related("bank")

        return Response(
            {
                "category": BenefitCategorySerializer(category).data,
                "card_count": cards.count(),
                "cards": CreditCardListSerializer(cards, many=True).data,
            }
        )


class CreditCardRatingViewSet(viewsets.ModelViewSet):
    """ViewSet for Credit Card Ratings."""

    queryset = CreditCardRating.objects.all()
    serializer_class = CreditCardRatingSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["credit_card", "rating"]
    ordering_fields = ["created", "rating"]
    ordering = ["-created"]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "create":
            return CreditCardRatingCreateSerializer
        return CreditCardRatingSerializer

    def list(self, request, *args, **kwargs):
        """List ratings - only show if credit_card filter is provided."""
        if "credit_card" not in request.query_params:
            return Response(
                {"error": "Please provide credit_card query parameter to list ratings."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().list(request, *args, **kwargs)


class CreditCardReviewViewSet(viewsets.ModelViewSet):
    """ViewSet for Credit Card Reviews."""

    queryset = CreditCardReview.objects.filter(is_approved=True)
    serializer_class = CreditCardReviewSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["credit_card", "rating", "is_verified_user"]
    ordering_fields = ["created", "helpful_count", "rating"]
    ordering = ["-helpful_count", "-created"]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "create":
            return CreditCardReviewCreateSerializer
        elif self.action == "list":
            return CreditCardReviewListSerializer
        return CreditCardReviewSerializer

    def list(self, request, *args, **kwargs):
        """List reviews - only show if credit_card filter is provided."""
        if "credit_card" not in request.query_params:
            return Response(
                {"error": "Please provide credit_card query parameter to list reviews."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Create a new review - defaults to not approved."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {
                "message": "Review submitted successfully. It will be visible after admin approval.",
                "review": serializer.data,
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    @action(detail=True, methods=["post"])
    def mark_helpful(self, request, pk=None):
        """Increment helpful count for a review."""
        review = self.get_object()
        review.helpful_count += 1
        review.save()
        return Response(
            {"message": "Review marked as helpful", "helpful_count": review.helpful_count},
            status=status.HTTP_200_OK,
        )
