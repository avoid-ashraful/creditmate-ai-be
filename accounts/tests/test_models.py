"""Tests for accounts models."""

import pytest

from django.contrib.auth import get_user_model
from django.db import IntegrityError

from accounts.models import UserProfile

User = get_user_model()


@pytest.mark.django_db
class TestUserProfileModel:
    """Tests for UserProfile model."""

    def test_user_profile_created_on_user_creation(self):
        """Test that UserProfile is automatically created when User is created."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        assert hasattr(user, "profile")
        assert isinstance(user.profile, UserProfile)
        assert user.profile.email_verified is False
        assert user.profile.email_opt_in is False
        assert user.profile.preferences == {}

    def test_user_profile_str_representation(self):
        """Test UserProfile string representation."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        assert str(user.profile) == "Profile for test@example.com"

    def test_user_profile_email_opt_in(self):
        """Test email_opt_in field."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        user.profile.email_opt_in = True
        user.profile.save()
        user.refresh_from_db()
        assert user.profile.email_opt_in is True

    def test_user_profile_preferences(self):
        """Test preferences JSON field."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        user.profile.preferences = {"theme": "dark", "notifications": True}
        user.profile.save()
        user.refresh_from_db()
        assert user.profile.preferences == {"theme": "dark", "notifications": True}

    def test_user_profile_cascade_delete(self):
        """Test that UserProfile is deleted when User is deleted."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        profile_id = user.profile.id
        user.delete()
        assert not UserProfile.objects.filter(id=profile_id).exists()

    def test_user_profile_unique_constraint(self):
        """Test that only one profile can exist per user."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        # Creating another profile for the same user should fail
        with pytest.raises(IntegrityError):
            UserProfile.objects.create(user=user)

    def test_user_profile_timestamps(self):
        """Test created and modified timestamps."""
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            password="testpass123",
        )
        assert user.profile.created is not None
        assert user.profile.modified is not None
        original_modified = user.profile.modified

        user.profile.email_opt_in = True
        user.profile.save()
        user.refresh_from_db()
        assert user.profile.modified > original_modified
