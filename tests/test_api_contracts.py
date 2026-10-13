"""
API contract tests for Task 9.3 - API Documentation.

These tests verify that all documented route groups are present in the
OpenAPI schema and that docs endpoints are available.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from django.core.cache import cache


class SchemaAPITests(APITestCase):
    """Tests for API schema and documentation endpoints."""

    def setUp(self):
        cache.clear()

    def test_schema_endpoint_available(self):
        """Verify the OpenAPI schema endpoint is accessible."""
        response = self.client.get("/api/v1/schema/")
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_301_MOVED_PERMANENTLY])
        if response.status_code == status.HTTP_200_OK:
            self.assertIn("title", response.data)
            self.assertIn("version", response.data)
            self.assertIn("paths", response.data)

    def test_swagger_ui_endpoint_available(self):
        """Verify the Swagger UI endpoint is accessible."""
        response = self.client.get("/api/v1/docs/swagger/")
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_301_MOVED_PERMANENTLY])

    def test_redoc_endpoint_available(self):
        """Verify the Redoc UI endpoint is accessible."""
        response = self.client.get("/api/v1/docs/redoc/")
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_301_MOVED_PERMANENTLY])

    def test_schema_has_banks_tag(self):
        """Verify the schema includes banks endpoint paths."""
        from drf_spectacular.generators import SchemaGenerator
        from django.conf import settings

        settings.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        bank_paths = [
            path for path in schema.get("paths", {}).keys()
            if "banks" in path
        ]
        self.assertTrue(len(bank_paths) > 0, "Schema should have bank paths")

    def test_schema_has_credit_cards_tag(self):
        """Verify the schema includes credit cards endpoint paths."""
        from drf_spectacular.generators import SchemaGenerator
        from django.conf import settings

        settings.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        cc_paths = [
            path for path in schema.get("paths", {}).keys()
            if "credit-cards" in path
        ]
        self.assertTrue(len(cc_paths) > 0, "Schema should have credit card paths")

    def test_schema_has_search_tag(self):
        """Verify the schema includes search endpoint paths."""
        from drf_spectacular.generators import SchemaGenerator
        from django.conf import settings

        settings.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        search_paths = [
            path for path in schema.get("paths", {}).keys()
            if "search" in path
        ]
        self.assertTrue(len(search_paths) > 0, "Schema should have search paths")

    def test_schema_has_required_info(self):
        """Verify the schema has required OpenAPI info fields."""
        from drf_spectacular.generators import SchemaGenerator
        from django.conf import settings

        settings.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        info = schema.get("info", {})
        self.assertIn("title", info)
        self.assertIn("version", info)


class RouteGroupTests(APITestCase):
    """Tests verifying all route groups are present and functional."""

    def setUp(self):
        cache.clear()

    def test_banks_list_endpoint(self):
        """Test the banks list endpoint is functional."""
        from banks.tests.factories import BankFactory

        BankFactory(name="Test Bank")
        response = self.client.get("/api/v1/banks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)

    def test_credit_cards_list_endpoint(self):
        """Test the credit cards list endpoint is functional."""
        from credit_cards.tests.factories import CreditCardFactory

        CreditCardFactory()
        response = self.client.get("/api/v1/credit-cards/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)

    def test_credit_cards_search_suggestions(self):
        """Test the credit cards search suggestions endpoint."""
        from credit_cards.tests.factories import CreditCardFactory, BankFactory

        bank = BankFactory(name="Suggestion Bank")
        CreditCardFactory(bank=bank)
        response = self.client.get("/api/v1/credit-cards/search-suggestions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("annual_fee_ranges", response.data)
        self.assertIn("benefits", response.data)
        self.assertIn("popular_banks", response.data)

    def test_search_endpoint(self):
        """Test the search endpoint is functional."""
        from search.tests.factories import BankFactory

        BankFactory(name="Search Bank")
        response = self.client.get("/api/search/", {"q": "test"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_search_suggest_endpoint(self):
        """Test the search suggest endpoint is functional."""
        from search.tests.factories import BankFactory

        BankFactory(name="Suggest Bank")
        response = self.client.get("/api/search/suggest/", {"q": "test"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("suggestions", response.data)

    def test_search_status_endpoint(self):
        """Test the search status endpoint is functional."""
        from search.tests.factories import BankFactory

        BankFactory(name="Status Bank")
        response = self.client.get("/api/search/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("status", response.data)
