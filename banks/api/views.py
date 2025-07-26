from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

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
