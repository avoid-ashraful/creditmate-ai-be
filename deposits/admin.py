from django.contrib import admin

from deposits.models import (
    DepositChartSnapshot,
    DepositFieldHistory,
    DepositProduct,
    DepositRate,
    DepositTaxRule,
)


class DepositRateInline(admin.TabularInline):
    model = DepositRate
    extra = 0


@admin.register(DepositProduct)
class DepositProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "institution_display_name",
        "kind",
        "rate_type",
        "verification_status",
        "is_benchmark",
        "is_active",
    )
    list_filter = ("kind", "rate_type", "verification_status", "is_benchmark")
    search_fields = ("name", "institution_name", "bank__name")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [DepositRateInline]


@admin.register(DepositRate)
class DepositRateAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "tenure_months_min",
        "tenure_months_max",
        "rate_min",
        "rate_max",
        "is_derived",
    )
    list_filter = ("is_derived",)


@admin.register(DepositFieldHistory)
class DepositFieldHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "field_name", "created")
    list_filter = ("field_name",)


@admin.register(DepositChartSnapshot)
class DepositChartSnapshotAdmin(admin.ModelAdmin):
    list_display = ("source", "edition_label", "edition_month", "created")
    exclude = ("raw_html",)


@admin.register(DepositTaxRule)
class DepositTaxRuleAdmin(admin.ModelAdmin):
    list_display = ("key", "effective_from", "description")
