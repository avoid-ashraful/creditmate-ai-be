"""Filters for the account product list endpoint."""

import django_filters

from bank_accounts.models import AccountProduct


class AccountProductFilter(django_filters.FilterSet):
    bank = django_filters.NumberFilter(field_name="bank__id")

    class Meta:
        model = AccountProduct
        fields = [
            "account_type",
            "bank",
            "segment",
            "is_islamic",
            "contract_type",
            "rate_type",
            "fee_data_complete",
        ]
