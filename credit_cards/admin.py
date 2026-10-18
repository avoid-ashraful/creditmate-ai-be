from django.contrib import admin
from django.utils import timezone

from credit_cards.constants import VerificationStatus
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
        "verification_status",
        "card_network",
        "modified",
    ]
    list_filter = [
        "verification_status",
        "card_network",
        "is_islamic",
        "bank",
        "is_active",
        "created",
        "modified",
    ]
    search_fields = ["name", "bank__name", "reward_points_policy"]
    readonly_fields = ["verified_at", "verified_by", "created", "modified"]
    ordering = ["bank__name", "name"]
    actions = ["mark_verified", "mark_needs_review"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("bank", "name", "annual_fee", "interest_rate_apr", "is_active")},
        ),
        (
            "Verification",
            {"fields": ("verification_status", "verified_at", "verified_by")},
        ),
        (
            "Card Details",
            {
                "fields": (
                    "source_url",
                    "apply_url",
                    "card_network",
                    "is_islamic",
                    "is_dual_currency",
                    "min_monthly_income",
                    "supplementary_card_fee",
                    "foreign_transaction_fee",
                ),
            },
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

    @admin.action(description="Mark selected cards verified (publishes active cards)")
    def mark_verified(self, request, queryset):
        """Mark cards verified, recording who verified them and when."""
        for card in queryset:
            card.verification_status = VerificationStatus.VERIFIED
            card.verified_at = timezone.now()
            card.verified_by = request.user
            card.save(
                update_fields=[
                    "verification_status",
                    "verified_at",
                    "verified_by",
                    "modified",
                ]
            )
        self.message_user(request, f"Marked {queryset.count()} card(s) verified.")

    @admin.action(description="Mark selected cards as needs review (unpublishes)")
    def mark_needs_review(self, request, queryset):
        """Take cards out of public view until staff re-verify them."""
        for card in queryset:
            card.verification_status = VerificationStatus.NEEDS_REVIEW
            card.save(update_fields=["verification_status", "modified"])
        self.message_user(request, f"Marked {queryset.count()} card(s) as needs review.")
