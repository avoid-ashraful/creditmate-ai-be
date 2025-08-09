from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from credit_cards.api.filters import CreditCardFilter
from credit_cards.api.serializers import CreditCardListSerializer, CreditCardSerializer
from credit_cards.models import CreditCard


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
