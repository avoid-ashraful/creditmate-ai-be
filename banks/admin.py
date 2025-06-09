from django.contrib import admin

from .models import Bank


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    """Admin interface for Bank model."""

    list_display = ["name", "is_active", "credit_card_count", "created", "modified"]
    list_filter = ["is_active", "created", "modified"]
    search_fields = ["name"]
    readonly_fields = ["created", "modified", "credit_card_count"]
    ordering = ["name"]

    fieldsets = (
        (None, {"fields": ("name", "logo", "website", "is_active")}),
        (
            "Metadata",
            {
                "fields": ("credit_card_count", "created", "modified"),
                "classes": ("collapse",),
            },
        ),
    )
