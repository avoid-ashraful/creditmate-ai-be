import json

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from banks.models import Bank, BankDataSource, CrawledContent, ReviewQueue
from banks.services import ReviewQueueService


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    """Admin interface for Bank model."""

    list_display = [
        "name",
        "is_active",
        "credit_card_count",
        "data_source_count",
        "created",
        "modified",
    ]
    list_filter = ["is_active", "created", "modified"]
    search_fields = ["name"]
    readonly_fields = ["created", "modified", "credit_card_count", "data_source_count"]
    ordering = ["name"]

    def data_source_count(self, obj):
        """Return the number of data sources for this bank."""
        return obj.data_sources.count()

    data_source_count.short_description = "Data Sources"


@admin.register(BankDataSource)
class BankDataSourceAdmin(admin.ModelAdmin):
    """Admin interface for BankDataSource model."""

    list_display = [
        "bank",
        "url_display",
        "content_type",
        "is_active",
        "failed_attempt_count",
        "last_crawled_at",
        "last_successful_crawl_at",
    ]
    list_filter = [
        "content_type",
        "is_active",
        "bank",
        "last_crawled_at",
        "failed_attempt_count",
    ]
    search_fields = ["bank__name", "url", "description"]
    readonly_fields = ["created", "modified", "is_failing"]
    ordering = ["bank__name", "url"]

    def url_display(self, obj):
        """Display truncated URL with link."""
        url = obj.url
        if len(url) > 50:
            display_url = url[:47] + "..."
        else:
            display_url = url
        return format_html('<a href="{}" target="_blank">{}</a>', url, display_url)

    url_display.short_description = "URL"

    actions = ["reset_failed_attempts", "activate_sources", "deactivate_sources"]

    def reset_failed_attempts(self, request, queryset):
        """Reset failed attempts for selected data sources."""
        count = 0
        for source in queryset:
            source.reset_failed_attempts()
            count += 1
        self.message_user(request, f"Reset failed attempts for {count} data sources.")

    reset_failed_attempts.short_description = "Reset failed attempts"

    def activate_sources(self, request, queryset):
        """Activate selected data sources."""
        count = queryset.update(is_active=True)
        self.message_user(request, f"Activated {count} data sources.")

    activate_sources.short_description = "Activate data sources"

    def deactivate_sources(self, request, queryset):
        """Deactivate selected data sources."""
        count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {count} data sources.")

    deactivate_sources.short_description = "Deactivate data sources"


@admin.register(CrawledContent)
class CrawledContentAdmin(admin.ModelAdmin):
    """Admin interface for CrawledContent model."""

    list_display = [
        "data_source",
        "credit_card",
        "processing_status",
        "crawled_at",
        "content_preview",
    ]
    list_filter = [
        "processing_status",
        "crawled_at",
        "data_source__bank",
        "data_source__content_type",
    ]
    search_fields = [
        "data_source__bank__name",
        "credit_card__name",
        "extracted_content",
        "error_message",
    ]
    readonly_fields = ["created", "modified", "crawled_at", "content_preview"]
    ordering = ["-crawled_at"]

    def content_preview(self, obj):
        """Display preview of extracted content."""
        content = obj.extracted_content
        if len(content) > 100:
            return content[:97] + "..."
        return content

    content_preview.short_description = "Content Preview"


@admin.register(ReviewQueue)
class ReviewQueueAdmin(admin.ModelAdmin):
    """Admin interface for the focused manual review queue."""

    list_display = [
        "bank",
        "crawled_content",
        "priority",
        "status",
        "extracted_summary",
        "reviewed_by",
        "reviewed_at",
        "created",
    ]
    list_filter = ["bank", "priority", "status", "created", "reviewed_at"]
    search_fields = [
        "bank__name",
        "crawled_content__credit_card__name",
        "crawled_content__data_source__url",
        "reviewer_notes",
    ]
    readonly_fields = [
        "created",
        "modified",
        "bank",
        "priority",
        "status",
        "reviewed_by",
        "reviewed_at",
        "extracted_values",
        "trusted_values",
        "crawled_content",
    ]
    fields = [
        "crawled_content",
        "bank",
        "priority",
        "status",
        "extracted_values",
        "trusted_values",
        "reviewer_notes",
        "reviewed_by",
        "reviewed_at",
        "created",
        "modified",
    ]
    actions = ["approve_items", "reject_items"]

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("banks.view_reviewqueue") and request.user.has_perm(
            "banks.change_reviewqueue"
        )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "bank",
                "reviewed_by",
                "crawled_content__data_source",
                "crawled_content__credit_card",
            )
        )

    def extracted_summary(self, obj):
        """Return a compact extraction summary for the changelist."""
        card_data = obj.crawled_content.review_card_data or {}
        return f"{card_data.get('name', 'No card')} / fee {card_data.get('annual_fee', 'unknown')}"

    extracted_summary.short_description = "Extraction"

    def extracted_values(self, obj):
        """Show extracted values beside trusted values for manual comparison."""
        return json.dumps(obj.crawled_content.review_card_data, indent=2, sort_keys=True)

    extracted_values.short_description = "Extracted values"

    def trusted_values(self, obj):
        """Show the currently trusted card record for manual comparison."""
        card = obj.crawled_content.credit_card
        if card is None:
            return "No linked credit card"
        return json.dumps(
            {
                "name": card.name,
                "annual_fee": str(card.annual_fee),
                "interest_rate_apr": str(card.interest_rate_apr),
                "lounge_access_international": card.lounge_access_international,
                "lounge_access_domestic": card.lounge_access_domestic,
                "cash_advance_fee": card.cash_advance_fee,
                "late_payment_fee": card.late_payment_fee,
            },
            indent=2,
            sort_keys=True,
        )

    trusted_values.short_description = "Trusted values"

    def approve_items(self, request, queryset):
        """Approve selected pending items without changing trusted card data."""
        service = ReviewQueueService()
        approved = 0
        for item in queryset:
            try:
                service.approve(item, reviewer=request.user)
            except ValidationError:
                self.message_user(
                    request,
                    f"{item} could not be approved because it is not pending.",
                    messages.ERROR,
                )
            else:
                approved += 1
        if approved:
            self.message_user(request, f"Approved {approved} review item(s).")

    approve_items.short_description = "Approve selected review items"

    def reject_items(self, request, queryset):
        """Reject selected pending items without changing trusted card data."""
        service = ReviewQueueService()
        rejected = 0
        for item in queryset:
            try:
                service.reject(item, reviewer=request.user)
            except ValidationError:
                self.message_user(
                    request,
                    f"{item} could not be rejected because it is not pending.",
                    messages.ERROR,
                )
            else:
                rejected += 1
        if rejected:
            self.message_user(request, f"Rejected {rejected} review item(s).")

    reject_items.short_description = "Reject selected review items"
