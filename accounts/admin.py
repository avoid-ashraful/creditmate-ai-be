"""Admin configuration for the accounts application."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

from accounts.models import UserProfile

User = get_user_model()


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin for UserProfile."""

    list_display = ["user", "email_verified", "email_opt_in", "created"]
    list_filter = ["email_verified", "email_opt_in", "created"]
    search_fields = ["user__username", "user__email", "user__first_name", "user__last_name"]
    readonly_fields = ["created", "modified"]
    raw_id_fields = ["user"]


class UserProfileInline(admin.StackedInline):
    """Inline for UserProfile in User admin."""

    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ["email_verified", "email_opt_in", "preferences"]


class UserAdmin(BaseUserAdmin):
    """Extended User admin with profile inline."""

    inlines = [UserProfileInline]
    list_display = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]
    list_filter = ["is_staff", "is_superuser", "is_active", "groups"]
    search_fields = ["username", "email", "first_name", "last_name"]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
