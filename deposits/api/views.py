"""ViewSet for deposit products: list/detail, field history, scenario ranking.

The scenario endpoint is the heart of the vertical: given an amount (FDR)
or monthly instalment (DPS) and a horizon, every public product with a
published rate covering that scenario is evaluated server-side with
:mod:`deposits.maturity` and ranked by **net-of-tax maturity value at the
lower bound of its rate range**. Sanchayapatra benchmarks are evaluated
too but returned in their own list — never ranked among banks.
"""

from decimal import Decimal

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.db.models import Q

from credit_cards.constants import VerificationStatus  # noqa: F401  (re-export parity)
from deposits import maturity
from deposits.api.filters import DepositProductFilter
from deposits.api.serializers import (
    DepositFieldHistorySerializer,
    DepositProductListSerializer,
    DepositProductSerializer,
    DepositScenarioInputSerializer,
)
from deposits.constants import DepositKind
from deposits.models import DepositProduct


class DepositProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only API for deposit products."""

    queryset = (
        DepositProduct.objects.select_related("bank").prefetch_related("rates").public()
    )
    serializer_class = DepositProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = DepositProductFilter
    search_fields = ["name", "bank__name", "institution_name"]
    ordering_fields = ["name", "created"]
    ordering = ["bank__name", "institution_name", "name"]

    def get_serializer_class(self):
        if self.action == "list":
            return DepositProductListSerializer
        return DepositProductSerializer

    @extend_schema(responses=DepositFieldHistorySerializer(many=True))
    @action(detail=True, methods=["get"], url_path="field-history")
    def field_history(self, request, *args, **kwargs):
        """Return a bounded, newest-first history for a deposit product.

        Mirrors the credit-card endpoint: public (redesign decision D1).
        """
        product = self.get_object()
        history = product.field_history.all()
        page = self.paginate_queryset(history)
        serializer = DepositFieldHistorySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(request=DepositScenarioInputSerializer)
    @action(detail=False, methods=["post"], url_path="scenario")
    def scenario(self, request):
        """Rank products for an amount/instalment + horizon scenario."""
        serializer = DepositScenarioInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        kind = data["kind"]
        months = data["months"]
        amount = data.get("amount")
        instalment = data.get("monthly_instalment")
        scenario_amount = instalment if kind == DepositKind.DPS else amount

        products = self.get_queryset()
        if kind == DepositKind.DPS:
            # Benchmarks are kind="scheme", not "dps" — include them
            # explicitly or the benchmark handling below never sees them
            # in a DPS scenario.
            products = products.filter(Q(kind=DepositKind.DPS) | Q(is_benchmark=True))
        else:
            products = products.filter(
                kind__in=[
                    DepositKind.FDR,
                    DepositKind.MONTHLY_BENEFIT,
                    DepositKind.SCHEME,
                ]
            )
        if data.get("islamic_only"):
            products = products.filter(is_islamic=True)
        if data.get("bank"):
            products = products.filter(bank_id=data["bank"])

        # Resolve the dated tax rules once for the whole scenario instead
        # of one query per product.
        tax_params = maturity.resolve_tax_params()
        results, benchmarks, excluded = [], [], 0
        for product in products:
            pick_amount = scenario_amount
            if product.is_benchmark and kind == DepositKind.DPS:
                pick_amount = instalment * months
            row = maturity.pick_rate_row(product, months=months, amount=pick_amount)
            if row is None:
                excluded += 1
                continue
            eval_amount = amount
            if product.is_benchmark and kind == DepositKind.DPS:
                # Benchmarks are lump-sum certificates: for a DPS scenario
                # they are evaluated on the total contributions, as a
                # reference line only (stated in the response notes).
                eval_amount = instalment * months
            evaluation = maturity.evaluate_product(
                product,
                row,
                months=months,
                amount=eval_amount,
                instalment=instalment,
                has_tin=data["has_tin"],
                tax_params=tax_params,
            )
            entry = {
                "product": DepositProductListSerializer(product).data,
                **{
                    key: (str(value) if hasattr(value, "quantize") else value)
                    for key, value in evaluation.items()
                },
            }
            if product.is_benchmark:
                benchmarks.append(entry)
            else:
                results.append(entry)

        results.sort(key=lambda e: Decimal(e["net_maturity"]), reverse=True)
        benchmarks.sort(key=lambda e: Decimal(e["net_maturity"]), reverse=True)
        return Response(
            {
                "kind": kind,
                "months": months,
                "amount": str(amount) if amount is not None else None,
                "monthly_instalment": (
                    str(instalment) if instalment is not None else None
                ),
                "has_tin": data["has_tin"],
                "count": len(results),
                "excluded_without_rate": excluded,
                "results": results,
                "benchmarks": benchmarks,
                "notes": [
                    "Ranked by net-of-tax maturity value at the lower bound "
                    "of each product's published rate range.",
                    "Source tax is deducted from the interest/profit only, "
                    "at the dated rates in DepositTaxRule (bank deposits: "
                    "10% with TIN, 15% without; Sanchayapatra: 5% up to "
                    "BDT 5 lakh total holding, else 10%). Excise duty and "
                    "final income tax are not included.",
                    "FDR maturity uses each product's published compounding; "
                    "where unpublished (BB chart), annual compounding is "
                    "assumed. Sanchayapatra figures in a DPS scenario treat "
                    "the total contributions as a lump sum for reference.",
                ],
            }
        )
