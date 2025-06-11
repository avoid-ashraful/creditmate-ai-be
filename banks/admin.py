from django.contrib import admin
from django.utils.html import format_html

from .models import Bank, BankDataSource, CrawledContent


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

    fieldsets = (
        (None, {"fields": ("name", "logo", "website", "is_active")}),
        (
            "Metadata",
            {
                "fields": (
                    "credit_card_count",
                    "data_source_count",
                    "created",
                    "modified",
                ),
                "classes": ("collapse",),
            },
        ),
    )

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

    fieldsets = (
        (None, {"fields": ("bank", "url", "content_type", "description", "is_active")}),
        (
            "Crawling Status",
            {
                "fields": (
                    "failed_attempt_count",
                    "is_failing",
                    "last_crawled_at",
                    "last_successful_crawl_at",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created", "modified"),
                "classes": ("collapse",),
            },
        ),
    )

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
        "crawl_date",
        "content_preview",
    ]
    list_filter = [
        "processing_status",
        "crawl_date",
        "data_source__bank",
        "data_source__content_type",
    ]
    search_fields = [
        "data_source__bank__name",
        "credit_card__name",
        "extracted_content",
        "error_message",
    ]
    readonly_fields = ["created", "modified", "crawl_date", "content_preview"]
    ordering = ["-crawl_date"]

    fieldsets = (
        (None, {"fields": ("data_source", "credit_card", "processing_status")}),
        (
            "Content",
            {
                "fields": (
                    "content_preview",
                    "raw_content",
                    "extracted_content",
                    "parsed_json",
                )
            },
        ),
        (
            "Error Information",
            {
                "fields": ("error_message",),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("crawl_date", "created", "modified"),
                "classes": ("collapse",),
            },
        ),
    )

    def content_preview(self, obj):
        """Display preview of extracted content."""
        content = obj.extracted_content
        if len(content) > 100:
            return content[:97] + "..."
        return content

    content_preview.short_description = "Content Preview"

    def has_add_permission(self, request):
        """Prevent manual addition of crawled content."""
        return False
