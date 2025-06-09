import pytest
from rest_framework.test import APITestCase

from django.contrib.auth.models import User


@pytest.mark.django_db
class TestBasicSetup:
    """Basic tests to verify pytest setup is working."""

    def test_simple_math(self):
        """Test that basic Python operations work."""
        assert 2 + 2 == 4

    def test_pytest_assertion_works(self):
        """Test that pytest assertions work properly."""
        assert 1 + 1 == 2

    def test_database_access(self):
        """Test that database access is working."""
        user_count_before = User.objects.count()
        User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        user_count_after = User.objects.count()
        assert user_count_after == user_count_before + 1


@pytest.mark.django_db
class TestPytestSetup:
    """Basic tests to verify pytest setup is working."""

    def test_pytest_marker_works(self):
        """Test that pytest django_db marker works."""
        user = User.objects.create_user(
            username="pytestuser", email="pytest@example.com", password="testpass123"
        )
        assert user.username == "pytestuser"
        assert User.objects.filter(username="pytestuser").exists()

    def test_fixtures_work(self, api_client):
        """Test that custom fixtures from conftest.py work."""
        assert api_client is not None
        response = api_client.get("/")
        # This might return 404 since we don't have a root URL defined yet,
        # but it proves the client is working
        assert response.status_code in [404, 200, 301]


class TestAPISetup(APITestCase):
    """Test API setup using Django REST Framework."""

    def test_api_test_case_works(self):
        """Test that APITestCase is working."""
        response = self.client.get("/")
        # Expecting 404 since no root URL is defined
        self.assertIn(response.status_code, [404, 200, 301])

    def test_api_client_authentication(self):
        """Test that API client authentication works."""
        user = User.objects.create_user(
            username="apiuser", email="api@example.com", password="testpass123"
        )
        self.client.force_authenticate(user=user)
        # Just test that authentication doesn't raise an error
        response = self.client.get("/")
        self.assertIn(response.status_code, [404, 200, 301])


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (1, 2, 3),
        (5, 5, 10),
        (-1, 1, 0),
    ],
)
def test_parametrized_test(a, b, expected):
    """Test that parametrized tests work."""
    assert a + b == expected
