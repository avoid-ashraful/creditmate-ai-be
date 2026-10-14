import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.test import override_settings


@pytest.fixture()
def schema(db):
    """Fetch the live OpenAPI document once per test."""
    with override_settings(SECURE_SSL_REDIRECT=False):
        response = APIClient().get("/api/v1/schema/")
    assert response.status_code == status.HTTP_200_OK
    return response.data


@pytest.mark.django_db
class TestOpenApiDocumentation:
    """Saved endpoints appear in the generated OpenAPI document."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/saved/comparisons/",
            "/api/v1/saved/comparisons/{id}/",
            "/api/v1/saved/comparisons/{id}/duplicate/",
            "/api/v1/saved/collections/",
            "/api/v1/saved/collections/{id}/",
            "/api/v1/saved/collections/{id}/cards/",
            "/api/v1/saved/collections/{id}/cards/{card_id}/",
            "/api/v1/saved/shared/{token}/",
            "/api/v1/saved/shared/collections/{slug}/",
        ],
    )
    def test_saved_path_is_documented(self, schema, path):
        assert path in schema["paths"]

    def test_saved_operations_are_tagged(self, schema):
        operation = schema["paths"]["/api/v1/saved/comparisons/"]["get"]

        assert operation["tags"] == ["saved"]

    def test_comparison_schema_nests_card_list_serializer(self, schema):
        components = schema["components"]["schemas"]

        assert "SavedComparison" in components
        assert "CreditCardList" in components
        assert "PublicSavedComparison" in components

    def test_public_share_operation_allows_anonymous_callers(self, schema):
        operation = schema["paths"]["/api/v1/saved/shared/{token}/"]["get"]

        # An empty requirement object is OpenAPI's way of saying "no auth needed".
        assert operation["security"] == [{}]
