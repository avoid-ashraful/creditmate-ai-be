from django.contrib import admin

from bank_accounts.models import (
    AccountFeeSchedule,
    AccountFieldHistory,
    AccountProduct,
)


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

    @admin.display(description="BB maintenance warnings")
    def maintenance_warning_count(self, obj):
        warnings = obj.maintenance_warnings()
        return f"⚠ {len(warnings)}" if warnings else "—"


@admin.register(AccountFieldHistory)
class AccountFieldHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "field_name", "created")
    list_filter = ("field_name",)


@admin.register(AccountFeeSchedule)
class AccountFeeScheduleAdmin(admin.ModelAdmin):
    list_display = ("key", "effective_from", "description")
