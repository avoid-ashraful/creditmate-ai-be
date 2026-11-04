"""Filters for the deposit product list endpoint."""

import django_filters

from deposits.models import DepositProduct


class DepositProductFilter(django_filters.FilterSet):
    bank = django_filters.NumberFilter(field_name="bank__id")
    min_amount_lte = django_filters.NumberFilter(
        field_name="min_amount", lookup_expr="lte"
    )

    class Meta:
        model = DepositProduct
        fields = [
            "kind",
            "bank",
            "institution_type",
            "rate_type",
            "is_islamic",
            "is_benchmark",
            "is_generic",
            "payout_style",
            "segment",
        ]
