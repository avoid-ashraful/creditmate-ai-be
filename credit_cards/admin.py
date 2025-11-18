from django.contrib import admin

from credit_cards.models import (
    BenefitCategory,
    CreditCard,
    CreditCardBenefit,
    CreditCardRating,
    CreditCardReview,
)


@admin.register(CreditCard)
class CreditCardAdmin(admin.ModelAdmin):
    """Admin interface for CreditCard model."""

    list_display = [
        "name",
        "bank",
        "annual_fee",
        "interest_rate_apr",
        "annual_fee_waiver_difficulty",
        "spending_tier",
        "has_lounge_access",
        "has_annual_fee",
        "is_active",
        "modified",
    ]
    list_filter = [
        "bank",
        "is_active",
        "annual_fee_waiver_difficulty",
        "spending_tier",
        "benefit_categories",
        "created",
        "modified",
    ]
    search_fields = ["name", "bank__name", "reward_points_policy", "best_for_tags"]
    readonly_fields = ["created", "modified"]
    ordering = ["bank__name", "name"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("bank", "name", "annual_fee", "interest_rate_apr", "is_active")},
        ),
        (
            "Application & Monetization",
            {
                "fields": (
                    "apply_url",
                    "affiliate_code",
                    "commission_rate",
                    "commission_amount",
                ),
                "description": "Application URL and affiliate tracking for monetization",
            },
        ),
        (
            "AI Classification",
            {
                "fields": (
                    "annual_fee_waiver_difficulty",
                    "spending_tier",
                    "best_for_tags",
                ),
                "description": "AI-generated classifications for enhanced filtering",
            },
        ),
        (
            "Lounge Access",
            {
                "fields": (
                    "lounge_access_international",
                    "lounge_access_domestic",
                    "lounge_access_condition",
                ),
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


@admin.register(BenefitCategory)
class BenefitCategoryAdmin(admin.ModelAdmin):
    """Admin interface for BenefitCategory model."""

    list_display = [
        "name",
        "category_type",
        "display_order",
        "is_active",
        "icon",
        "credit_card_count",
    ]
    list_filter = ["category_type", "is_active"]
    search_fields = ["name", "description"]
    ordering = ["display_order", "name"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "category_type", "description", "icon")},
        ),
        (
            "MCC Alignment",
            {
                "fields": ("mcc_codes",),
                "description": "ISO 18245 Merchant Category Codes aligned with this category",
            },
        ),
        (
            "Display Settings",
            {"fields": ("display_order", "is_active")},
        ),
    )

    def credit_card_count(self, obj):
        """Display number of credit cards in this category."""
        return obj.credit_cards.count()

    credit_card_count.short_description = "Credit Cards"


class CreditCardBenefitInline(admin.TabularInline):
    """Inline admin for CreditCardBenefit."""

    model = CreditCardBenefit
    extra = 1
    fields = [
        "benefit_category",
        "reward_rate",
        "reward_description",
        "conditions",
        "confidence_score",
        "is_primary",
    ]


@admin.register(CreditCardBenefit)
class CreditCardBenefitAdmin(admin.ModelAdmin):
    """Admin interface for CreditCardBenefit model."""

    list_display = [
        "credit_card",
        "benefit_category",
        "reward_rate",
        "is_primary",
        "confidence_score",
    ]
    list_filter = ["benefit_category", "is_primary", "confidence_score"]
    search_fields = [
        "credit_card__name",
        "benefit_category__name",
        "reward_description",
    ]
    ordering = ["credit_card", "-is_primary", "-reward_rate"]

    fieldsets = (
        (
            "Relationship",
            {"fields": ("credit_card", "benefit_category")},
        ),
        (
            "Reward Details",
            {"fields": ("reward_rate", "reward_description", "conditions")},
        ),
        (
            "Metadata",
            {"fields": ("confidence_score", "is_primary")},
        ),
    )


@admin.register(CreditCardRating)
class CreditCardRatingAdmin(admin.ModelAdmin):
    """Admin interface for CreditCardRating model."""

    list_display = [
        "user_name",
        "credit_card",
        "rating",
        "is_verified_user",
        "created",
    ]
    list_filter = ["rating", "is_verified_user", "created"]
    search_fields = ["user_name", "user_email", "credit_card__name"]
    readonly_fields = ["created", "modified"]
    ordering = ["-created"]

    fieldsets = (
        (
            "Rating Information",
            {"fields": ("credit_card", "user_name", "user_email", "rating")},
        ),
        (
            "Verification",
            {"fields": ("is_verified_user",)},
        ),
        (
            "Timestamps",
            {"fields": ("created", "modified"), "classes": ("collapse",)},
        ),
    )


@admin.register(CreditCardReview)
class CreditCardReviewAdmin(admin.ModelAdmin):
    """Admin interface for CreditCardReview model."""

    list_display = [
        "title",
        "user_name",
        "credit_card",
        "rating",
        "helpful_count",
        "is_verified_user",
        "is_approved",
        "created",
    ]
    list_filter = ["rating", "is_verified_user", "is_approved", "created"]
    search_fields = ["user_name", "user_email", "title", "review_text", "credit_card__name"]
    readonly_fields = ["helpful_count", "created", "modified"]
    ordering = ["-created"]
    actions = ["approve_reviews", "unapprove_reviews"]

    fieldsets = (
        (
            "Review Information",
            {"fields": ("credit_card", "user_name", "user_email", "title", "review_text")},
        ),
        (
            "Rating & Details",
            {"fields": ("rating", "pros", "cons", "usage_duration_months")},
        ),
        (
            "Moderation",
            {"fields": ("is_approved", "is_verified_user", "helpful_count")},
        ),
        (
            "Timestamps",
            {"fields": ("created", "modified"), "classes": ("collapse",)},
        ),
    )

    def approve_reviews(self, request, queryset):
        """Bulk approve selected reviews."""
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"{updated} review(s) approved.")

    approve_reviews.short_description = "Approve selected reviews"

    def unapprove_reviews(self, request, queryset):
        """Bulk unapprove selected reviews."""
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"{updated} review(s) unapproved.")

    unapprove_reviews.short_description = "Unapprove selected reviews"
