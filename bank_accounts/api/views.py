"""ViewSet for account products: list/detail, field history, scenario.

The scenario endpoint is the heart of the vertical: given an average
balance, every public product with a published rate covering that
balance is evaluated server-side with :mod:`bank_accounts.netvalue`
and ranked by **net annual value** — interest/profit earned at the
user's slab minus the annualised fees at that balance.

Salary/payroll products are priced per employer agreement, so they are
evaluated but returned separately (``segment_excluded``), never ranked
against walk-in products. Products whose bank publishes no fee lines at
all are returned in ``unranked_without_fees`` rather than being ranked
on interest alone.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.db.models import Prefetch

from bank_accounts import netvalue
from bank_accounts.api.filters import AccountProductFilter
from bank_accounts.api.serializers import (
    AccountFieldHistorySerializer,
    AccountProductListSerializer,
    AccountProductSerializer,
    AccountScenarioInputSerializer,
)
from bank_accounts.constants import AccountSegment
from bank_accounts.models import AccountProduct


class AccountProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only API for bank account products."""

    queryset = (
        AccountProduct.objects.select_related("bank", "variant_of")
        .prefetch_related(
            Prefetch(
                "variants",
                queryset=AccountProduct.objects.public(),
                to_attr="_prefetched_variants",
            )
        )
        .public()
    )
    serializer_class = AccountProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = AccountProductFilter
    search_fields = ["name", "bank__name"]
    ordering_fields = ["name", "created"]
    ordering = ["bank__name", "account_type", "name"]

    def get_serializer_class(self):
        if self.action == "list":
            return AccountProductListSerializer
        return AccountProductSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            # Variants are grouped under their base product by default.
            include_variants = self.request.query_params.get("include_variants")
            if include_variants not in ("true", "1"):
                queryset = queryset.filter(variant_of__isnull=True)
        return queryset

    @extend_schema(responses=AccountFieldHistorySerializer(many=True))
    @action(detail=True, methods=["get"], url_path="field-history")
    def field_history(self, request, *args, **kwargs):
        """Return a bounded, newest-first history for an account product.

        Mirrors the credit-card/deposit endpoints: requires authentication.
        """
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required to view field history."},
                status=status.HTTP_403_FORBIDDEN,
            )
        product = self.get_object()
        history = product.field_history.all()
        page = self.paginate_queryset(history)
        serializer = AccountFieldHistorySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(request=AccountScenarioInputSerializer)
    @action(detail=False, methods=["post"], url_path="scenario")
    def scenario(self, request):
        """Rank products by net annual value at an average balance."""
        serializer = AccountScenarioInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        balance = data["average_balance"]

        products = self.queryset
        products = products.filter(account_type=data["account_type"])
        if data.get("segments"):
            products = products.filter(segment__in=data["segments"])
        if data.get("bank"):
            products = products.filter(bank_id=data["bank"])
        if data.get("islamic_only"):
            products = products.filter(is_islamic=True)
        if not data.get("include_variants", True):
            products = products.filter(variant_of__isnull=True)

        results, segment_excluded, unranked, excluded_no_rate = [], [], [], 0
        evaluated = []
        for product in products:
            evaluation = netvalue.evaluate_product(product, balance)
            if evaluation is None:
                excluded_no_rate += 1
                continue
            evaluated.append((product, evaluation))

        for product, evaluation in evaluated:
            entry = {
                "product": AccountProductListSerializer(product).data,
                **{
                    key: (str(value) if hasattr(value, "quantize") else value)
                    for key, value in evaluation.items()
                },
            }
            if product.segment == AccountSegment.SALARY:
                segment_excluded.append((evaluation, entry))
            elif evaluation["total_fees"] is None:
                unranked.append(entry)
            else:
                results.append((evaluation, entry))

        results.sort(key=lambda pair: pair[0]["net_annual_value"], reverse=True)
        segment_excluded.sort(
            key=lambda pair: pair[0]["net_annual_value"] or 0, reverse=True
        )
        return Response(
            {
                "average_balance": str(balance),
                "account_type": data["account_type"],
                "count": len(results),
                "excluded_without_rate": excluded_no_rate,
                "results": [entry for _, entry in results],
                "segment_excluded": [entry for _, entry in segment_excluded],
                "unranked_without_fees": unranked,
                "notes": [
                    "Ranked by net annual value at your average balance: "
                    "interest/profit earned at your balance slab for one "
                    "year, minus annualised fees at that balance.",
                    "Savings account maintenance fees are fixed by "
                    "Bangladesh Bank on one slab for every bank "
                    "(half-yearly BDT 0/100/200/250/300 by average "
                    "balance; current accounts capped at BDT 300 "
                    "half-yearly) — they do not differentiate banks. "
                    "Among the recurring charges counted in this net "
                    "value, what differs is debit-card, SMS and "
                    "online-banking fees, waivers, and the interest "
                    "actually earned at your slab.",
                    "Net value excludes cheque-book, closure and other "
                    "one-off fees; those are shown per product.",
                    "Fees exclude 15% VAT and government excise duty on "
                    "balances, which apply equally at all banks. Figures "
                    "are steady-state (year-2) values: a first-year card "
                    "fee waiver does not reduce the card line.",
                    "A fee shown as null is not published by the bank in "
                    "the sources we hold; the product's net value is then "
                    "computed from its published fee lines only and is "
                    "flagged fees_complete=false.",
                    "Salary/payroll accounts are priced under employer "
                    "agreements; they are evaluated separately and never "
                    "ranked against walk-in accounts.",
                ],
            }
        )
