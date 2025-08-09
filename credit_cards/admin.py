from django.contrib import admin

from credit_cards.models import CreditCard


@admin.register(CreditCard)
class CreditCardAdmin(admin.ModelAdmin):
    """Admin interface for CreditCard model."""

    list_display = [
        "name",
        "bank",
        "annual_fee",
        "interest_rate_apr",
        "has_lounge_access",
        "has_annual_fee",
        "is_active",
        "modified",
    ]
    list_filter = ["bank", "is_active", "created", "modified"]
    search_fields = ["name", "bank__name", "reward_points_policy"]
    readonly_fields = ["created", "modified"]
    ordering = ["bank__name", "name"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("bank", "name", "annual_fee", "interest_rate_apr", "is_active")},
        ),
        (
            "Lounge Access",
            {
                "fields": ("lounge_access_international", "lounge_access_domestic"),
                "classes": ("collapse",),
            },
        ),
        (
            "Fees & Policies",
            {
                "fields": (
                    "cash_advance_fee",
                    "late_payment_fee",
                    "annual_fee_waiver_policy",
                    "reward_points_policy",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Additional Information",
            {"fields": ("additional_features",), "classes": ("collapse",)},
        ),
        ("Computed Fields", {"fields": (), "classes": ("collapse",)}),
        ("Metadata", {"fields": ("created", "modified"), "classes": ("collapse",)}),
    )

    def has_lounge_access(self, obj):
        """Display lounge access status."""
        return obj.has_lounge_access

    has_lounge_access.boolean = True
    has_lounge_access.short_description = "Has Lounge Access"

    def has_annual_fee(self, obj):
        """Display annual fee status."""
        return obj.has_annual_fee

    has_annual_fee.boolean = True
    has_annual_fee.short_description = "Has Annual Fee"
