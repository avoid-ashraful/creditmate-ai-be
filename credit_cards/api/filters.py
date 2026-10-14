import django_filters

from credit_cards.lounge import (
    card_lounge_access_q,
    filter_lounge_count_min,
    lounge_access_q,
)
from credit_cards.models import CreditCard


class CreditCardFilter(django_filters.FilterSet):
    """Filter class for CreditCard model."""

    # Basic filters
    name = django_filters.CharFilter(lookup_expr="icontains")
    bank_name = django_filters.CharFilter(
        field_name="bank__name", lookup_expr="icontains"
    )

    # Price range filters
    annual_fee_min = django_filters.NumberFilter(
        field_name="annual_fee", lookup_expr="gte"
    )
    annual_fee_max = django_filters.NumberFilter(
        field_name="annual_fee", lookup_expr="lte"
    )
    annual_fee_range = django_filters.RangeFilter(field_name="annual_fee")

    # Interest rate filters
    interest_rate_min = django_filters.NumberFilter(
        field_name="interest_rate_apr", lookup_expr="gte"
    )
    interest_rate_max = django_filters.NumberFilter(
        field_name="interest_rate_apr", lookup_expr="lte"
    )
    interest_rate_range = django_filters.RangeFilter(field_name="interest_rate_apr")

    # Lounge access filters
    has_lounge_access = django_filters.BooleanFilter(method="filter_has_lounge_access")
    has_international_lounge = django_filters.BooleanFilter(
        method="filter_has_international_lounge"
    )
    has_domestic_lounge = django_filters.BooleanFilter(
        method="filter_has_domestic_lounge"
    )
    min_international_lounge = django_filters.NumberFilter(
        method="filter_min_international_lounge"
    )
    min_domestic_lounge = django_filters.NumberFilter(method="filter_min_domestic_lounge")

    # Fee filters
    has_annual_fee = django_filters.BooleanFilter(method="filter_has_annual_fee")
    no_annual_fee = django_filters.BooleanFilter(method="filter_no_annual_fee")

    # Feature filters
    has_additional_features = django_filters.BooleanFilter(
        method="filter_has_additional_features"
    )
    feature_search = django_filters.CharFilter(method="filter_feature_search")

    # Waiver policy filters
    has_fee_waiver = django_filters.BooleanFilter(method="filter_has_fee_waiver")

    # IDs filter for filtering multiple credit cards
    ids = django_filters.BaseInFilter(field_name="id", lookup_expr="in")

    # Bank IDs filter for filtering by multiple banks
    bank_ids = django_filters.BaseInFilter(field_name="bank", lookup_expr="in")

    class Meta:
        model = CreditCard
        fields = {
            "bank": ["exact"],
            "is_active": ["exact"],
            "created": ["gte", "lte"],
            "modified": ["gte", "lte"],
        }

    def filter_has_lounge_access(self, queryset, name, value):
        """Filter by card-level lounge access (True: any access, False: known none)."""
        return queryset.filter(card_lounge_access_q(value))

    def filter_has_international_lounge(self, queryset, name, value):
        """Filter by international lounge access (True: access, False: known none)."""
        return queryset.filter(lounge_access_q("lounge_access_international", value))

    def filter_has_domestic_lounge(self, queryset, name, value):
        """Filter by domestic lounge access (True: access, False: known none)."""
        return queryset.filter(lounge_access_q("lounge_access_domestic", value))

    def filter_min_international_lounge(self, queryset, name, value):
        """Filter cards whose stated international visit count is at least value."""
        return filter_lounge_count_min(queryset, "lounge_access_international", value)

    def filter_min_domestic_lounge(self, queryset, name, value):
        """Filter cards whose stated domestic visit count is at least value."""
        return filter_lounge_count_min(queryset, "lounge_access_domestic", value)

    def filter_has_annual_fee(self, queryset, name, value):
        """Filter cards that have annual fee."""
        if value:
            return queryset.filter(annual_fee__gt=0)
        return queryset.filter(annual_fee=0)

    def filter_no_annual_fee(self, queryset, name, value):
        """Filter cards that have no annual fee."""
        if value:
            return queryset.filter(annual_fee=0)
        return queryset.filter(annual_fee__gt=0)

    def filter_has_additional_features(self, queryset, name, value):
        """Filter cards that have additional features."""
        if value:
            return queryset.exclude(additional_features=[])
        return queryset.filter(additional_features=[])

    def filter_feature_search(self, queryset, name, value):
        """Search in additional features."""
        if value:
            return queryset.filter(additional_features__icontains=value)
        return queryset

    def filter_has_fee_waiver(self, queryset, name, value):
        """Filter cards that have fee waiver policy."""
        if value:
            return queryset.filter(annual_fee_waiver_policy__isnull=False)
        return queryset.filter(annual_fee_waiver_policy__isnull=True)
