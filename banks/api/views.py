from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Bank
from .filters import BankFilter
from .serializers import BankListSerializer, BankSerializer


class BankViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Banks.

    Provides read-only operations for banks with filtering and search capabilities.
    """

    queryset = Bank.objects.filter(is_active=True)
    serializer_class = BankSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BankFilter
    search_fields = ["name"]
    ordering_fields = ["name", "created_at", "updated_at"]
    ordering = ["name"]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "list":
            return BankListSerializer
        return BankSerializer

    @action(detail=True, methods=["get"])
    def credit_cards(self, request, pk=None):
        """Get all credit cards for a specific bank."""
        bank = self.get_object()
        credit_cards = bank.credit_cards.filter(is_active=True)

        # Import here to avoid circular imports
        from credit_cards.api.serializers import CreditCardListSerializer

        serializer = CreditCardListSerializer(credit_cards, many=True)

        return Response(
            {"bank": BankSerializer(bank).data, "credit_cards": serializer.data}
        )
