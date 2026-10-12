from urllib.parse import urlsplit

import pytest
from rest_framework.test import APIClient

from django.core.cache import cache


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


def assert_dedicated_redis_database(cache_config):
    if not cache_config["BACKEND"].endswith("RedisCache"):
        return
    database_path = urlsplit(cache_config["LOCATION"]).path
    assert database_path == "/14", (
        "Tests may only clear the dedicated Redis cache database 14; "
        f"got {database_path or 'database 0'}"
    )


@pytest.fixture(autouse=True)
def isolated_cache(settings, socket_enabled, request):
    """Give each test module a private, safely clearable cache namespace."""
    cache_configs = {
        alias: cache_config.copy() for alias, cache_config in settings.CACHES.items()
    }
    module_name = request.module.__name__.rsplit(".", 1)[-1]
    default_cache_config = cache_configs["default"]
    existing_prefix = default_cache_config.get("KEY_PREFIX", "")
    default_cache_config["KEY_PREFIX"] = f"{existing_prefix}:{module_name}"
    settings.CACHES = cache_configs
    assert_dedicated_redis_database(default_cache_config)
    cache.clear()
    yield
    assert_dedicated_redis_database(default_cache_config)
    cache.clear()


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
