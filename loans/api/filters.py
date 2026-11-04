import django_filters

from loans.models import LoanProduct


class LoanProductFilter(django_filters.FilterSet):
    """List filters for loan products.

    Feasibility filters follow the deposits convention: a bound only
    excludes a product when the product PUBLISHES that bound and the
    scenario violates it — unknown is never treated as ineligible here
    (the scenario endpoint reports per-product flags instead).
    """

    loan_type = django_filters.CharFilter(field_name="loan_type")
    bank = django_filters.NumberFilter(field_name="bank__id")
    lender_type = django_filters.CharFilter(field_name="lender_type")
    is_islamic = django_filters.BooleanFilter(field_name="is_islamic")
    segment = django_filters.CharFilter(method="filter_segment")
    purpose = django_filters.CharFilter(method="filter_purpose")
    amount = django_filters.NumberFilter(method="filter_amount")
    tenure_months = django_filters.NumberFilter(method="filter_tenure")

    class Meta:
        model = LoanProduct
        fields = ["loan_type", "bank", "lender_type", "is_islamic"]

    def filter_segment(self, queryset, name, value):
        return queryset.filter(segment_tags__contains=[value])

    def filter_purpose(self, queryset, name, value):
        return queryset.filter(purpose_tags__contains=[value])

    def filter_amount(self, queryset, name, value):
        from django.db.models import Q

        return queryset.filter(
            Q(amount_min_bdt__isnull=True) | Q(amount_min_bdt__lte=value),
            Q(amount_max_bdt__isnull=True) | Q(amount_max_bdt__gte=value),
        )

    def filter_tenure(self, queryset, name, value):
        from django.db.models import Q

        return queryset.filter(
            Q(tenure_min_months__isnull=True) | Q(tenure_min_months__lte=value),
            Q(tenure_max_months__isnull=True) | Q(tenure_max_months__gte=value),
        )
