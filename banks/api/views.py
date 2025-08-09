from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

from banks.api.filters import BankFilter
from banks.api.serializers import BankListSerializer, BankSerializer
from banks.models import Bank


class BankViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Banks.

    Provides read-only REST API operations for banks with comprehensive
    filtering, search, and ordering capabilities. Supports list and detail
    views with different serialization formats.
    """

    queryset = Bank.objects.filter(is_active=True)
    serializer_class = BankSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BankFilter
    search_fields = ["name"]
    ordering_fields = ["name", "created_at", "updated_at"]
    ordering = ["name"]

    def get_serializer_class(self):
        """Return appropriate serializer based on action.

        Parameters
        ----------
        None

        Returns
        -------
        class
            BankListSerializer for list actions, BankSerializer for detail actions
        """
        if self.action == "list":
            return BankListSerializer
        return BankSerializer
