import pytest
from rest_framework.test import APIClient


@pytest.fixture(scope="session", autouse=True)
def django_db_setup(django_db_setup, django_db_blocker):
    """Load essential test data once per test session."""
    with django_db_blocker.unblock():
        # Add any initial data loading commands here if needed
        pass


@pytest.fixture(autouse=True)
def auto_setup_method(request):
    """
    Automatically call setup_method on test classes if it exists.
    This replaces the need to add @pytest.fixture(autouse=True) to every setup_method.
    """
    if request.instance and hasattr(request.instance, "setup_method"):
        # Make sure setup_method is a callable method, not a fixture
        setup_method = getattr(request.instance, "setup_method")
        if callable(setup_method) and not hasattr(setup_method, "_pytestfixturefunction"):
            setup_method()


@pytest.fixture()
def api_client():
    """Django REST Framework API test client."""
    return APIClient()


@pytest.fixture()
def authed_api_client(api_client):
    """Authenticated API client factory."""

    def _api_client_authenticator(user):
        api_client.force_authenticate(user=user)
        return api_client

    return _api_client_authenticator
