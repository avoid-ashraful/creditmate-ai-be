import django_filters

from django import forms
from django.db.models import Q

from credit_cards.constants import CardNetwork
from credit_cards.lounge import (
    card_lounge_access_q,
    filter_lounge_count_min,
    lounge_access_q,
)
from credit_cards.models import CreditCard


class IntegerInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    """Filter on a comma-separated list of integers (e.g. ``ids=1,2``).

    ``BaseInFilter`` alone treats every element as an untyped string, so a
    non-integer value such as ``ids=abc`` reaches ``id__in`` and raises
    ``ValueError`` (HTTP 500). Pairing it with an ``IntegerField`` turns
    malformed values into a validation error (HTTP 400) instead.
    """

    field_class = forms.IntegerField

    def filter(self, qs, value):
        # Ensure validation runs even when queryset is empty
        if value is not None and value != "":
            # This will trigger the IntegerField validation
            try:
                self.get_filter_predicate(value)
            except Exception:
                # Validation will be caught by filterset.is_valid()
                pass
        return super().filter(qs, value)


class CardDetailFilterSet(django_filters.FilterSet):
    """Card detail filters shared by the list and advanced-search endpoints."""

    card_network = django_filters.CharFilter(
        method="filter_card_network",
        help_text="Card network, or comma-separated networks (e.g. visa,mastercard)",
    )
    is_islamic = django_filters.BooleanFilter(
        help_text="Only Islamic (true) or only conventional (false) cards"
    )
    is_dual_currency = django_filters.BooleanFilter(
        help_text="Only dual-currency (true) or known single-currency (false) cards"
    )
    max_min_monthly_income = django_filters.NumberFilter(
        method="filter_max_min_monthly_income",
        help_text="Cards whose minimum monthly income (BDT) is at most this value",
    )
    include_unknown_income = django_filters.BooleanFilter(
        method="filter_include_unknown_income",
        help_text=(
            "With max_min_monthly_income, also include cards with no stated "
            "minimum income"
        ),
    )
    annual_fee = django_filters.NumberFilter(
        field_name="annual_fee",
        lookup_expr="exact",
        help_text="Exact annual fee in BDT (e.g. 0 for no-fee cards)",
    )

    def filter_card_network(self, queryset, name, value):
        """Filter by one or several comma-separated card networks."""
        networks = {item.strip().lower() for item in value.split(",") if item.strip()}
        valid = networks & set(CardNetwork.values)
        return queryset.filter(card_network__in=valid) if valid else queryset.none()

    def filter_max_min_monthly_income(self, queryset, name, value):
        """Filter cards whose minimum monthly income is at most ``value``.

        Cards with an unknown minimum income are kept only when
        ``include_unknown_income`` is true.
        """
        condition = Q(min_monthly_income__lte=value)
        if self.form.cleaned_data.get("include_unknown_income") is True:
            condition |= Q(min_monthly_income__isnull=True)
        return queryset.filter(condition)

    def filter_include_unknown_income(self, queryset, name, value):
        """No-op: consumed by ``filter_max_min_monthly_income``."""
        return queryset


class CreditCardFilter(CardDetailFilterSet):
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
    ids = IntegerInFilter(field_name="id", lookup_expr="in")

    # Bank IDs filter for filtering by multiple banks
    bank_ids = IntegerInFilter(field_name="bank", lookup_expr="in")

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
