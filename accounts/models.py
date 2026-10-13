"""Models for the accounts application."""

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Extended user profile stored as a OneToOne with Django's built-in User.

    This model stores authentication-related extras without replacing
    Django's stock auth.User model.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    email_verified = models.BooleanField(default=False)
    email_opt_in = models.BooleanField(default=False)
    preferences = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_userprofile"

    def __str__(self):
        return f"Profile for {self.user.username}"
