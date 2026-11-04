from django.contrib import admin

from bank_accounts.constants import (
    SCHEDULE_CURRENT_MAINTENANCE_CAP,
    SCHEDULE_SAVINGS_MAINTENANCE,
)
from bank_accounts.models import (
    AccountFeeSchedule,
    AccountFieldHistory,
    AccountProduct,
)
from bank_accounts.netvalue import fee_schedule_params

SCHEDULE_KEYS = (SCHEDULE_SAVINGS_MAINTENANCE, SCHEDULE_CURRENT_MAINTENANCE_CAP)


@admin.register(AccountProduct)
class AccountProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "bank",
        "account_type",
        "segment",
        "rate_type",
        "verification_status",
        "fee_data_complete",
        "maintenance_warning_count",
        "is_active",
    )
    list_filter = (
        "account_type",
        "segment",
        "rate_type",
        "verification_status",
        "fee_data_complete",
    )
    search_fields = ("name", "bank__name")
    prepopulated_fields = {"slug": ("name",)}

    def get_changelist(self, request, **kwargs):
        # Resolve the dated BB fee-schedule params once per changelist
        # request; maintenance_warning_count passes them to each row's
        # validation instead of re-querying per product (N+1).
        self._schedule_params = {
            key: fee_schedule_params(key) for key in SCHEDULE_KEYS
        }
        return super().get_changelist(request, **kwargs)

    @admin.display(description="BB maintenance warnings")
    def maintenance_warning_count(self, obj):
        params_by_key = getattr(self, "_schedule_params", None)
        warnings = obj.maintenance_warnings(params_by_key=params_by_key)
        return f"⚠ {len(warnings)}" if warnings else "—"


@admin.register(AccountFieldHistory)
class AccountFieldHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "field_name", "created")
    list_filter = ("field_name",)


@admin.register(AccountFeeSchedule)
class AccountFeeScheduleAdmin(admin.ModelAdmin):
    list_display = ("key", "effective_from", "description")
