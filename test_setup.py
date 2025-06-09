"""
Test file to verify pytest and Django setup is working correctly.
"""

import pytest

from django.contrib.auth.models import User
from django.test import TestCase


class TestDjangoSetup(TestCase):
    """Test Django setup and database connectivity."""

    def test_database_connection(self):
        """Test that we can connect to the database and create a user."""
        user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("testpass123"))

    def test_user_creation_count(self):
        """Test that we can count users in the database."""
        initial_count = User.objects.count()
        User.objects.create_user(
            username="testuser2", email="test2@example.com", password="testpass123"
        )
        self.assertEqual(User.objects.count(), initial_count + 1)


@pytest.mark.django_db
def test_pytest_django_integration():
    """Test that pytest-django integration is working."""
    user = User.objects.create_user(
        username="pytestuser", email="pytest@example.com", password="testpass123"
    )
    assert user.username == "pytestuser"
    assert user.email == "pytest@example.com"
    assert user.check_password("testpass123")


def test_basic_python():
    """Test basic Python functionality."""
    assert 1 + 1 == 2
    assert "hello" == "hello"
    assert [1, 2, 3] == [1, 2, 3]
