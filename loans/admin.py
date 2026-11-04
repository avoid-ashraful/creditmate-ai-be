from django.contrib import admin

from .caps import product_cap_flags
from .models import (
    LendingChartSnapshot,
    LoanChartBand,
    LoanFieldHistory,
    LoanProduct,
    RegulatoryCap,
)


@admin.register(LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "lender",
        "loan_type",
        "rate_min",
        "rate_max",
        "verification_status",
        "is_active",
        "cap_flag_count",
    )
    list_filter = ("loan_type", "lender_type", "is_islamic", "verification_status")
    search_fields = ("name", "institution_name", "bank__name")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("regulatory_cap_flags_display",)

    @admin.display(description="Lender")
    def lender(self, obj):
        return obj.lender_display_name

    @admin.display(description="Cap flags")
    def cap_flag_count(self, obj):
        return len(product_cap_flags(obj))

    @admin.display(description="Regulatory cap flags")
    def regulatory_cap_flags_display(self, obj):
        flags = product_cap_flags(obj)
        return " | ".join(flags) if flags else "—"


@admin.register(LoanFieldHistory)
class LoanFieldHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "field_name", "old_value", "new_value", "created")
    list_filter = ("field_name",)


@admin.register(LendingChartSnapshot)
class LendingChartSnapshotAdmin(admin.ModelAdmin):
    list_display = ("edition_label", "edition_month", "created")


@admin.register(LoanChartBand)
class LoanChartBandAdmin(admin.ModelAdmin):
    list_display = ("lender", "category", "rate_min", "rate_max", "edition_label")
    list_filter = ("category",)

    @admin.display(description="Lender")
    def lender(self, obj):
        return obj.lender_display_name


@admin.register(RegulatoryCap)
class RegulatoryCapAdmin(admin.ModelAdmin):
    list_display = ("key", "effective_from")
