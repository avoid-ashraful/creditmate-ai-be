from django.contrib import admin

from advisor.models import AdvisorMessage, AdvisorSession


@admin.register(AdvisorSession)
class AdvisorSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "last_active", "created")
    readonly_fields = ("id", "created", "modified", "last_active")


@admin.register(AdvisorMessage)
class AdvisorMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "is_fallback", "created")
    readonly_fields = (
        "session",
        "user_text",
        "answer_markdown",
        "citations",
        "tool_trace",
        "is_fallback",
        "created",
        "modified",
    )
