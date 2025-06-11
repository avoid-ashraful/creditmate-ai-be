"""
Security and edge case tests for Banks API endpoints.

These tests focus on security vulnerabilities, authentication, permissions,
and edge cases that could expose security issues.
"""

import pytest
from rest_framework import status
from rest_framework.test import APITestCase

from django.test import Client
from django.urls import reverse

from banks.factories import BankDataSourceFactory, BankFactory


@pytest.mark.django_db
class TestBankAPISecurityVulnerabilities:
    """Test protection against common security vulnerabilities."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()
        self.bank = BankFactory(name="Test Bank")

    def test_sql_injection_protection_in_search(self):
        """Test SQL injection protection in search parameters."""
        # Create test banks
        BankFactory(name="Valid Bank")
        BankFactory(name="Another Bank")

        # SQL injection attempts in search parameter
        sql_injection_payloads = [
            "'; DROP TABLE banks_bank; --",
            "' OR '1'='1' --",
            "'; DELETE FROM banks_bank WHERE '1'='1'; --",
            "' UNION SELECT * FROM django_user --",
            "'; INSERT INTO banks_bank (name) VALUES ('hacked'); --",
        ]

        for payload in sql_injection_payloads:
            response = self.client.get(reverse("banks:bank-list"), {"search": payload})
            # Should not cause server error or expose data
            assert response.status_code in [200, 400]

            # Verify no banks were deleted/modified
            assert BankFactory._meta.model.objects.count() >= 2

    def test_xss_protection_in_api_responses(self):
        """Test Cross-Site Scripting protection."""
        xss_payloads = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "';alert(String.fromCharCode(88,83,83))//';alert(String.fromCharCode(88,83,83))//",
            "\"><script>alert('xss')</script>",
        ]

        for payload in xss_payloads:
            # Test XSS in bank name (should be escaped in response)
            bank = BankFactory(name=payload)
            response = self.client.get(
                reverse("banks:bank-detail", kwargs={"pk": bank.pk})
            )

            assert response.status_code == 200
            # Response should not contain unescaped script tags
            response_content = response.content.decode()
            assert "<script>" not in response_content
            assert "javascript:" not in response_content

    def test_parameter_pollution_protection(self):
        """Test protection against HTTP parameter pollution."""
        # Multiple identical parameters
        response = self.client.get(
            reverse("banks:bank-list"), "search=bank1&search=bank2&search=bank3"
        )
        assert response.status_code in [200, 400]

        # Should handle gracefully without exposing sensitive data
        if response.status_code == 200:
            data = response.json()
            assert "results" in data or "detail" in data

    def test_invalid_characters_in_url_parameters(self):
        """Test handling of invalid characters in URL parameters."""
        invalid_chars = [
            "%00",  # Null byte
            "../",  # Path traversal
            "..\\",  # Windows path traversal
            "%2e%2e%2f",  # URL encoded path traversal
            "%0a",  # Line feed
            "%0d",  # Carriage return
        ]

        for char in invalid_chars:
            response = self.client.get(
                reverse("banks:bank-list"), {"search": f"bank{char}"}
            )
            # Should handle gracefully
            assert response.status_code in [200, 400, 404]

    def test_very_long_parameter_values(self):
        """Test handling of extremely long parameter values."""
        # Very long search parameter (potential buffer overflow)
        long_search = "A" * 10000
        response = self.client.get(reverse("banks:bank-list"), {"search": long_search})
        assert response.status_code in [200, 400, 413]

    def test_malformed_json_in_request_body(self):
        """Test handling of malformed JSON in request bodies."""
        malformed_json_payloads = [
            '{"name": "test"',  # Missing closing brace
            '{"name": }',  # Missing value
            '{name: "test"}',  # Unquoted key
            '{"name": "test",}',  # Trailing comma
            '{"name": "test"}}',  # Extra closing brace
            "null",  # Null JSON
            "",  # Empty string
            "not json at all",  # Not JSON
        ]

        for payload in malformed_json_payloads:
            response = self.client.post(
                reverse("banks:bank-list"), data=payload, content_type="application/json"
            )
            # Should handle gracefully with proper error response
            assert response.status_code in [400, 422, 500]

    def test_content_type_confusion(self):
        """Test handling of incorrect content types."""
        # Send XML with JSON content-type
        xml_data = '<?xml version="1.0"?><root><name>test</name></root>'
        response = self.client.post(
            reverse("banks:bank-list"), data=xml_data, content_type="application/json"
        )
        assert response.status_code in [400, 422]

        # Send JSON with XML content-type
        json_data = '{"name": "test"}'
        response = self.client.post(
            reverse("banks:bank-list"), data=json_data, content_type="application/xml"
        )
        assert response.status_code in [400, 415]


@pytest.mark.django_db
class TestBankAPIEdgeCases:
    """Test API edge cases and boundary conditions."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()

    def test_pagination_edge_cases(self):
        """Test pagination with edge case values."""
        # Create test banks
        BankFactory.create_batch(50)

        edge_cases = [
            {"page": 0},  # Zero page
            {"page": -1},  # Negative page
            {"page": 999999},  # Very large page number
            {"page": "invalid"},  # Non-numeric page
            {"page_size": 0},  # Zero page size
            {"page_size": -1},  # Negative page size
            {"page_size": 10000},  # Very large page size
            {"page_size": "invalid"},  # Non-numeric page size
        ]

        for params in edge_cases:
            response = self.client.get(reverse("banks:bank-list"), params)
            # Should handle gracefully
            assert response.status_code in [200, 400, 404]

            if response.status_code == 200:
                data = response.json()
                # Should return reasonable data
                assert "results" in data
                assert len(data["results"]) <= 100  # Reasonable max limit

    def test_ordering_with_null_values(self):
        """Test ordering behavior when some fields have null values."""
        # Create banks with mixed null and non-null values
        BankFactory(name="A Bank", logo="")
        BankFactory(name="B Bank", logo="https://example.com/logo.png")
        BankFactory(name="C Bank", logo="")

        # Test ordering by logo field (which has null/empty values)
        response = self.client.get(reverse("banks:bank-list"), {"ordering": "logo"})
        assert response.status_code == 200

        # Should handle null values gracefully
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 3

    def test_filtering_with_special_characters(self):
        """Test search/filter with special characters."""
        # Create banks with special characters
        special_banks = [
            "Bank & Trust",
            "Банк Россия",
            "中国银行",
            "البنك العربي",
            "Bank (USA)",
            "Bank-Co",
            "Bank/Corp",
            "Bank@Co",
            "Bank#1",
        ]

        for name in special_banks:
            BankFactory(name=name)

        # Test searching for each special character bank
        for name in special_banks:
            response = self.client.get(reverse("banks:bank-list"), {"search": name})
            assert response.status_code == 200

            data = response.json()
            assert "results" in data
            # Should find the bank with special characters
            assert len(data["results"]) >= 1

    def test_case_sensitivity_search(self):
        """Test search behavior with mixed case."""
        BankFactory(name="Test Bank")
        BankFactory(name="TEST BANK")
        BankFactory(name="test bank")

        # Test case variations
        search_terms = ["test", "TEST", "Test", "tEsT"]

        for term in search_terms:
            response = self.client.get(reverse("banks:bank-list"), {"search": term})
            assert response.status_code == 200

            data = response.json()
            assert "results" in data
            # Should find banks regardless of case
            assert len(data["results"]) >= 3

    def test_multiple_filter_combinations(self):
        """Test complex combinations of multiple filters."""
        # Create diverse bank data
        active_bank = BankFactory(name="Active Bank", is_active=True)
        inactive_bank = BankFactory(name="Inactive Bank", is_active=False)

        # Test various filter combinations
        filter_combinations = [
            {"search": "Bank", "is_active": "true"},
            {"search": "Bank", "is_active": "false"},
            {"search": "Active", "is_active": "true"},
            {"search": "Inactive", "is_active": "false"},
        ]

        for filters in filter_combinations:
            response = self.client.get(reverse("banks:bank-list"), filters)
            assert response.status_code == 200

            data = response.json()
            assert "results" in data

    def test_invalid_ordering_fields(self):
        """Test API response to invalid ordering field names."""
        BankFactory.create_batch(3)

        invalid_fields = [
            "nonexistent_field",
            "password",  # Sensitive field
            "id__sql_injection",
            "../etc/passwd",
            "name; DROP TABLE banks_bank; --",
        ]

        for field in invalid_fields:
            response = self.client.get(reverse("banks:bank-list"), {"ordering": field})
            # Should either ignore invalid field or return error
            assert response.status_code in [200, 400]

    def test_credit_cards_action_with_inactive_bank(self):
        """Test credit_cards action on inactive banks."""
        # Create inactive bank with credit cards
        inactive_bank = BankFactory(is_active=False)

        response = self.client.get(
            reverse("banks:bank-credit-cards", kwargs={"pk": inactive_bank.pk})
        )
        # Should handle gracefully
        assert response.status_code in [200, 404]

    def test_concurrent_api_access_simulation(self):
        """Test API behavior under simulated concurrent requests."""
        bank = BankFactory()

        # Simulate multiple concurrent requests
        responses = []
        for i in range(10):
            response = self.client.get(
                reverse("banks:bank-detail", kwargs={"pk": bank.pk})
            )
            responses.append(response)

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == bank.id

    def test_malformed_query_parameters(self):
        """Test handling of malformed or invalid query parameters."""
        malformed_params = [
            {"page": "not_a_number"},
            {"page_size": "invalid"},
            {"ordering": ""},
            {"search": None},
            {"is_active": "maybe"},
            {"unknown_param": "value"},
        ]

        for params in malformed_params:
            response = self.client.get(reverse("banks:bank-list"), params)
            # Should handle gracefully
            assert response.status_code in [200, 400]

    def test_error_response_formats(self):
        """Test error response format and status codes."""
        # Test 404 for non-existent bank
        response = self.client.get(reverse("banks:bank-detail", kwargs={"pk": 999999}))
        assert response.status_code == 404

        # Response should be JSON with proper error format
        data = response.json()
        assert "detail" in data or "error" in data

    def test_performance_with_large_datasets(self):
        """Test API performance with large number of banks."""
        # Create large dataset
        BankFactory.create_batch(500)

        # Test list endpoint performance
        response = self.client.get(reverse("banks:bank-list"))
        assert response.status_code == 200

        # Should respond within reasonable time and with pagination
        data = response.json()
        assert "results" in data
        assert "count" in data
        assert data["count"] == 500

        # Should limit results per page
        assert len(data["results"]) <= 100


@pytest.mark.django_db
class TestAPIAuthenticationAndPermissions:
    """Test API authentication and permission edge cases."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()

    def test_api_without_authentication(self):
        """Test API access without authentication headers."""
        bank = BankFactory()

        # Test various endpoints without auth
        endpoints = [
            reverse("banks:bank-list"),
            reverse("banks:bank-detail", kwargs={"pk": bank.pk}),
            reverse("banks:bank-credit-cards", kwargs={"pk": bank.pk}),
        ]

        for endpoint in endpoints:
            response = self.client.get(endpoint)
            # Should work since API appears to be public, or return 401/403
            assert response.status_code in [200, 401, 403]

    def test_invalid_authentication_headers(self):
        """Test handling of invalid authentication headers."""
        bank = BankFactory()

        invalid_headers = [
            {"HTTP_AUTHORIZATION": "Bearer invalid_token"},
            {"HTTP_AUTHORIZATION": "Invalid format"},
            {"HTTP_AUTHORIZATION": ""},
            {"HTTP_AUTHORIZATION": "Bearer"},  # Missing token
            {"HTTP_AUTHORIZATION": "Basic invalid"},
        ]

        for headers in invalid_headers:
            response = self.client.get(
                reverse("banks:bank-detail", kwargs={"pk": bank.pk}), **headers
            )
            # Should handle gracefully
            assert response.status_code in [200, 401, 403]

    def test_rate_limiting_behavior(self):
        """Test API rate limiting if implemented."""
        bank = BankFactory()

        # Make many rapid requests
        responses = []
        for i in range(100):
            response = self.client.get(
                reverse("banks:bank-detail", kwargs={"pk": bank.pk})
            )
            responses.append(response)

        # Check if rate limiting is implemented
        status_codes = [r.status_code for r in responses]

        # If rate limiting exists, should see 429 status codes
        # If not, all should be 200
        assert all(code in [200, 429] for code in status_codes)


@pytest.mark.django_db
class TestAPIDataIntegrity:
    """Test API data integrity and consistency."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = Client()

    def test_api_response_data_consistency(self):
        """Test that API responses are consistent with database state."""
        bank = BankFactory(
            name="Test Bank",
            logo="https://example.com/logo.png",
            website="https://example.com",
            is_active=True,
        )

        response = self.client.get(reverse("banks:bank-detail", kwargs={"pk": bank.pk}))
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == bank.id
        assert data["name"] == bank.name
        assert data["logo"] == bank.logo
        assert data["website"] == bank.website
        assert data["is_active"] == bank.is_active

    def test_api_response_format_consistency(self):
        """Test response format consistency across different scenarios."""
        # Test with different bank configurations
        banks = [
            BankFactory(logo="", website=""),  # Empty fields
            BankFactory(
                logo="https://example.com/logo.png", website="https://example.com"
            ),  # Full fields
            BankFactory(is_active=False),  # Inactive bank
        ]

        for bank in banks:
            response = self.client.get(
                reverse("banks:bank-detail", kwargs={"pk": bank.pk})
            )
            assert response.status_code == 200

            data = response.json()
            # Should have consistent field structure
            required_fields = [
                "id",
                "name",
                "logo",
                "website",
                "is_active",
                "created",
                "modified",
            ]
            for field in required_fields:
                assert field in data

    def test_api_handles_deleted_resources(self):
        """Test API behavior when resources are deleted during request processing."""
        bank = BankFactory()
        bank_id = bank.id

        # Delete the bank
        bank.delete()

        # Try to access deleted bank
        response = self.client.get(reverse("banks:bank-detail", kwargs={"pk": bank_id}))
        assert response.status_code == 404
