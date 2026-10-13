"""
API contract tests for Task 9.3 - API Documentation.

These tests verify that all documented route groups are present in the
OpenAPI schema and that docs endpoints are available and functional.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from django.core.cache import cache
from django.test import override_settings


@override_settings(SECURE_SSL_REDIRECT=False)
class SchemaAPITests(APITestCase):
    """Tests for API schema and documentation endpoints."""

    def setUp(self):
        cache.clear()

    def test_schema_endpoint_available(self):
        """Verify the OpenAPI schema endpoint is accessible and valid."""
        response = self.client.get("/api/v1/schema/")
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         f"Schema endpoint failed: {response.status_code}")
        schema = response.data
        self.assertIn("info", schema, "Schema missing info section")
        info = schema["info"]
        self.assertIn("title", info, "Schema info missing title")
        self.assertIn("version", info, "Schema info missing version")
        self.assertIn("paths", schema, "Schema missing paths section")

    def test_swagger_ui_endpoint_available(self):
        """Verify the Swagger UI endpoint is accessible."""
        response = self.client.get("/api/v1/docs/swagger/")
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         f"Swagger endpoint failed: {response.status_code}")
        self.assertIn("text/html", response["content-type"],
                      f"Swagger not HTML: {response['content-type']}")

    def test_redoc_endpoint_available(self):
        """Verify the Redoc UI endpoint is accessible."""
        response = self.client.get("/api/v1/docs/redoc/")
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         f"Redoc endpoint failed: {response.status_code}")
        self.assertIn("text/html", response["content-type"],
                      f"Redoc not HTML: {response['content-type']}")

    def test_schema_has_banks_paths(self):
        """Verify the schema includes banks endpoint paths."""
        response = self.client.get("/api/v1/schema/")
        schema = response.data
        bank_paths = [p for p in schema.get("paths", {}).keys() if "banks" in p]
        self.assertTrue(len(bank_paths) > 0,
                        f"Banks routes missing. Paths: {list(schema.get('paths', {}).keys())}")

    def test_schema_has_credit_cards_paths(self):
        """Verify the schema includes credit cards endpoint paths."""
        response = self.client.get("/api/v1/schema/")
        schema = response.data
        cc_paths = [p for p in schema.get("paths", {}).keys() if "credit-cards" in p]
        self.assertTrue(len(cc_paths) > 0,
                        f"Credit-cards routes missing. Paths: {list(schema.get('paths', {}).keys())}")

    def test_schema_has_search_paths(self):
        """Verify the schema includes search endpoint paths."""
        response = self.client.get("/api/v1/schema/")
        schema = response.data
        search_paths = [p for p in schema.get("paths", {}).keys() if "search" in p]
        self.assertTrue(len(search_paths) > 0,
                        f"Search routes missing. Paths: {list(schema.get('paths', {}).keys())}")


@override_settings(SECURE_SSL_REDIRECT=False)
class RouteGroupTests(APITestCase):
    """Tests verifying all route groups are present and functional."""

    def setUp(self):
        cache.clear()

    def test_banks_list_endpoint(self):
        """Test the banks list endpoint is functional."""
        from banks.factories import BankFactory

        BankFactory(name="Test Bank")
        response = self.client.get("/api/v1/banks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)

    def test_credit_cards_list_endpoint(self):
        """Test the credit cards list endpoint is functional."""
        from credit_cards.factories import CreditCardFactory

        CreditCardFactory()
        response = self.client.get("/api/v1/credit-cards/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)

    def test_credit_cards_search_suggestions(self):
        """Test the credit cards search suggestions endpoint."""
        from banks.factories import BankFactory
        from credit_cards.factories import CreditCardFactory

        bank = BankFactory(name="Suggestion Bank")
        CreditCardFactory(bank=bank)
        response = self.client.get("/api/v1/credit-cards/search-suggestions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("annual_fee_ranges", response.data)
        self.assertIn("benefits", response.data)
        self.assertIn("popular_banks", response.data)

    def test_schema_documents_search_routes(self):
        """Verify schema documents search endpoint routes via resolution."""
        response = self.client.get("/api/v1/schema/")
        schema = response.data
        search_paths = [p for p in schema.get("paths", {}).keys() if "search" in p]
        self.assertTrue(len(search_paths) > 0,
                        "Schema should document search routes")
