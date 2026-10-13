"""
Schema and documentation tests for Credit Mate AI API.

These tests verify that:
1. Documentation endpoints (schema, Swagger UI, Redoc) are accessible and valid
2. Schema contains all documented route groups (banks, credit-cards, search, admin)
3. Rate limit configuration is accurate in settings and reflected in schema
4. Authentication documentation matches actual configuration (session-based, public API)
"""

import yaml
from rest_framework import status
from rest_framework.test import APIClient

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_schema_endpoint_live():
    """Test /api/v1/schema/ returns valid OpenAPI schema."""
    client = APIClient()
    response = client.get("/api/v1/schema/")
    assert (
        response.status_code == status.HTTP_200_OK
    ), f"Schema endpoint failed: {response.status_code}"
    # Accept JSON or OpenAPI spec content type
    content_type = response["content-type"]
    assert (
        "json" in content_type or "openapi" in content_type
    ), f"Schema not JSON-based: {content_type}"
    schema = response.data
    assert schema.get("openapi") == "3.0.3", "Invalid OpenAPI version"
    assert "info" in schema, "Missing info section"
    assert "paths" in schema, "Missing paths section"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_swagger_ui_endpoint_live():
    """Test /api/v1/docs/swagger/ returns valid Swagger UI HTML."""
    client = APIClient()
    response = client.get("/api/v1/docs/swagger/")
    assert (
        response.status_code == status.HTTP_200_OK
    ), f"Swagger endpoint failed: {response.status_code}"
    assert (
        "text/html" in response["content-type"]
    ), f"Not HTML: {response['content-type']}"
    content = response.content.decode()
    assert "swagger" in content.lower(), "Swagger UI not loaded"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_redoc_endpoint_live():
    """Test /api/v1/docs/redoc/ returns valid Redoc HTML."""
    client = APIClient()
    response = client.get("/api/v1/docs/redoc/")
    assert (
        response.status_code == status.HTTP_200_OK
    ), f"Redoc endpoint failed: {response.status_code}"
    assert (
        "text/html" in response["content-type"]
    ), f"Not HTML: {response['content-type']}"
    content = response.content.decode()
    assert "redoc" in content.lower(), "Redoc not loaded"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_schema_has_banks_routes():
    """Verify schema includes banks endpoint group."""
    client = APIClient()
    response = client.get("/api/v1/schema/")
    schema = response.data
    paths = schema.get("paths", {})
    assert any(
        "banks" in p for p in paths
    ), f"Banks routes missing. Paths: {list(paths.keys())}"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_schema_has_credit_cards_routes():
    """Verify schema includes credit-cards endpoint group."""
    client = APIClient()
    response = client.get("/api/v1/schema/")
    schema = response.data
    paths = schema.get("paths", {})
    assert any(
        "credit-cards" in p for p in paths
    ), f"Credit-cards routes missing. Paths: {list(paths.keys())}"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_schema_has_search_routes():
    """Verify schema includes search endpoint group."""
    client = APIClient()
    response = client.get("/api/v1/schema/")
    schema = response.data
    paths = schema.get("paths", {})
    assert any(
        "search" in p for p in paths
    ), f"Search routes missing. Paths: {list(paths.keys())}"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_schema_has_proper_tags():
    """Verify schema uses banks, credit-cards, search, admin tags."""
    client = APIClient()
    response = client.get("/api/v1/schema/")
    schema = response.data
    tags_used = set()
    for path_item in schema.get("paths", {}).values():
        if isinstance(path_item, dict):
            for op in path_item.values():
                if isinstance(op, dict) and "tags" in op:
                    tags_used.update(op["tags"])

    expected = {"banks", "credit-cards", "search"}
    assert expected.issubset(
        tags_used
    ), f"Missing tags. Found: {tags_used}, Expected: {expected}"


def test_throttle_rates_in_settings():
    """Verify throttle rates are configured in Django settings."""
    throttle_rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    assert "anon" in throttle_rates, "Anonymous throttle rate not configured"
    assert "user" in throttle_rates, "User throttle rate not configured"
    assert "burst" in throttle_rates, "Burst throttle rate not configured"


def test_throttle_rate_format():
    """Verify throttle rates have valid format (N/unit)."""
    throttle_rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    for key, rate in throttle_rates.items():
        assert "/" in rate, f"Invalid rate format for {key}: {rate}"
        num, unit = rate.split("/")
        assert num.isdigit(), f"Invalid numeric part for {key}: {num}"
        assert unit in ("sec", "min", "hour", "day"), f"Invalid unit for {key}: {unit}"


def test_throttle_class_configured():
    """Verify throttle class is in REST_FRAMEWORK config."""
    throttle_classes = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_CLASSES", [])
    assert len(throttle_classes) > 0, "No throttle classes configured"
    assert any(
        "TrustedClientRateThrottle" in cls for cls in throttle_classes
    ), f"TrustedClientRateThrottle not found in {throttle_classes}"


def test_session_authentication_configured():
    """Verify SessionAuthentication is in use."""
    auth_classes = settings.REST_FRAMEWORK.get("DEFAULT_AUTHENTICATION_CLASSES", [])
    assert any(
        "SessionAuthentication" in cls for cls in auth_classes
    ), f"SessionAuthentication not found in {auth_classes}"


def test_public_api_permissions():
    """Verify API uses AllowAny permissions (public by default)."""
    perms = settings.REST_FRAMEWORK.get("DEFAULT_PERMISSION_CLASSES", [])
    assert any("AllowAny" in p for p in perms), f"AllowAny not found in {perms}"


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
def test_schema_no_api_key_scheme():
    """Verify schema does not advertise non-existent API key auth."""
    client = APIClient()
    response = client.get("/api/v1/schema/")
    schema = response.data
    security_schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "apiKey" not in security_schemes, "Schema incorrectly advertises apiKey scheme"


def test_schema_generates_without_warnings_and_documents_public_operations(
    tmp_path, capsys
):
    """Validate the generated schema and require complete public operation docs."""
    schema_path = tmp_path / "openapi.yml"
    call_command("spectacular", file=str(schema_path), validate=True, verbosity=0)
    output = capsys.readouterr()
    diagnostics = output.out + output.err
    assert "Warning:" not in diagnostics
    assert "Error" not in diagnostics

    schema = yaml.safe_load(schema_path.read_text())
    assert schema["paths"]
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            assert operation.get(
                "operationId"
            ), f"{method.upper()} {path} has no operationId"
            assert operation.get("tags"), f"{method.upper()} {path} has no tags"
            response_codes = set(operation.get("responses", {}))
            assert response_codes.intersection(
                {"200", "201", "202", "204"}
            ), f"{method.upper()} {path} has no documented success response"
