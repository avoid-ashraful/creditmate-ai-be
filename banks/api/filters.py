import django_filters

from banks.models import Bank


class BankFilter(django_filters.FilterSet):
    """Filter class for Bank model."""

    name = django_filters.CharFilter(lookup_expr="icontains")
    has_credit_cards = django_filters.BooleanFilter(method="filter_has_credit_cards")

    class Meta:
        model = Bank
        fields = {
            "is_active": ["exact"],
            "created": ["gte", "lte"],
            "modified": ["gte", "lte"],
        }

    def filter_has_credit_cards(self, queryset, name, value):
        """Filter banks that have credit cards."""
        if value:
            return queryset.filter(credit_cards__isnull=False).distinct()
        return queryset.filter(credit_cards__isnull=True).distinct()
