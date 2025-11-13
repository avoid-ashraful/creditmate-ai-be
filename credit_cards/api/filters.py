import django_filters

from django.db import models

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
        field_name="lounge_access_international", lookup_expr="gte"
    )
    min_domestic_lounge = django_filters.NumberFilter(
        field_name="lounge_access_domestic", lookup_expr="gte"
    )

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

    # NEW: AI Classification filters
    waiver_difficulty = django_filters.MultipleChoiceFilter(
        field_name="annual_fee_waiver_difficulty",
        choices=[
            ("EASY", "Easy to Waive"),
            ("MODERATE", "Moderate Conditions"),
            ("DIFFICULT", "Difficult to Waive"),
            ("NOT_AVAILABLE", "No Waiver Available"),
            ("UNKNOWN", "Unknown"),
        ],
    )
    tier = django_filters.MultipleChoiceFilter(
        field_name="spending_tier",
        choices=[
            ("ENTRY", "Entry Level"),
            ("MID", "Mid-Range"),
            ("PREMIUM", "Premium"),
            ("ULTRA_PREMIUM", "Ultra Premium"),
        ],
    )
    best_for = django_filters.CharFilter(method="filter_best_for_tags")

    # NEW: Benefit category filters
    benefit_category = django_filters.CharFilter(method="filter_benefit_category")
    benefit_category_ids = django_filters.BaseInFilter(
        field_name="benefit_categories", lookup_expr="in"
    )
    has_benefits = django_filters.BooleanFilter(method="filter_has_benefits")

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
        """Filter cards that have any lounge access."""
        if value:
            return queryset.exclude(
                models.Q(lounge_access_international="")
                & models.Q(lounge_access_domestic="")
            )
        return queryset.filter(lounge_access_international="", lounge_access_domestic="")

    def filter_has_international_lounge(self, queryset, name, value):
        """Filter cards that have international lounge access."""
        if value:
            return queryset.exclude(lounge_access_international="")
        return queryset.filter(lounge_access_international="")

    def filter_has_domestic_lounge(self, queryset, name, value):
        """Filter cards that have domestic lounge access."""
        if value:
            return queryset.exclude(lounge_access_domestic="")
        return queryset.filter(lounge_access_domestic="")

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

    def filter_best_for_tags(self, queryset, name, value):
        """Filter cards by best_for_tags content."""
        if value:
            return queryset.filter(best_for_tags__icontains=value)
        return queryset

    def filter_benefit_category(self, queryset, name, value):
        """Filter cards by benefit category name."""
        if value:
            return queryset.filter(
                benefit_categories__name__icontains=value
            ).distinct()
        return queryset

    def filter_has_benefits(self, queryset, name, value):
        """Filter cards that have benefit categories assigned."""
        if value:
            return queryset.filter(benefit_categories__isnull=False).distinct()
        return queryset.filter(benefit_categories__isnull=True)
