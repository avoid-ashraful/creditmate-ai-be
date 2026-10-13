# Generated migration for adding email field and case-insensitive unique constraint
from django.conf import settings
from django.db import migrations, models


def populate_email(apps, schema_editor):
    """Populate email field from related User, deduplicating case-insensitively."""
    UserProfile = apps.get_model("accounts", "UserProfile")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    # Get all profiles ordered by user pk for deterministic results
    profiles = list(UserProfile.objects.select_related("user").order_by("user_id"))

    # Track seen emails (lowercase) to deduplicate
    seen_emails = set()

    for profile in profiles:
        email = profile.user.email.lower().strip() if profile.user.email else ""
        if email in seen_emails:
            # Duplicate email (case-insensitive) - need to make it unique
            # Append user id to make it unique, but keep it valid-ish
            base_email = email.split("@")[0] if "@" in email else email
            domain = email.split("@")[1] if "@" in email else "example.com"
            email = f"{base_email}+{profile.user_id}@{domain}"
        seen_emails.add(email)
        profile.email = email
        profile.save(update_fields=["email"])


def reverse_populate_email(apps, schema_editor):
    """No-op reverse - email field will be removed."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="email",
            field=models.EmailField(default="", max_length=254),
            preserve_default=False,
        ),
        migrations.RunPython(populate_email, reverse_populate_email),
        migrations.AlterField(
            model_name="userprofile",
            name="email",
            field=models.EmailField(max_length=254, db_index=True),
        ),
        migrations.AddConstraint(
            model_name="userprofile",
            constraint=models.UniqueConstraint(
                models.functions.Lower("email"),
                name="accounts_userprofile_unique_email_ci",
                violation_error_message="A user with this email already exists (case-insensitive).",
            ),
        ),
    ]
