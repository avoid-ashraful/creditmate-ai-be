"""Admin registration for the search outbox queue."""

from django.contrib import admin

from search.models import SearchIndexUpdate


@admin.register(SearchIndexUpdate)
class SearchIndexUpdateAdmin(admin.ModelAdmin):
    """Read-mostly admin view of the search outbox rows."""

    list_display = (
        "index_name",
        "object_id",
        "action",
        "status",
        "attempts",
        "available_at",
        "modified",
    )
    list_filter = ("index_name", "action", "status")
    search_fields = ("index_name", "last_error")
    ordering = ("-created",)
    readonly_fields = ("created", "modified")
