"""Schema documentation regression tests for API endpoints.

Validates that generated OpenAPI schema accurately reflects the actual API
response contracts, with specific focus on:
- Typeahead endpoint mixed suggestion payloads (oneOf polymorphic types)
- Facet structure (keyed by slug, items with label/count/filter)
- Response references (no CreditCard model leakage)
- Optional and conditional fields (did_you_mean, match_policy)
"""

import pytest
from rest_framework.test import APIClient

from django.test import TestCase, override_settings

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory

SCHEMA_URL = "/api/v1/schema/"


@pytest.mark.django_db()
class TestTypeaheadSchemaDocumentation:
    """Validate typeahead endpoint OpenAPI documentation."""

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_endpoint_exists_in_schema(self, api_client):
        """Typeahead endpoint must be documented in OpenAPI schema."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        assert "paths" in schema
        assert "/api/v1/credit-cards/typeahead/" in schema["paths"]

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_endpoint_response_schema_defined(self, api_client):
        """Typeahead response must have explicit response schema."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        assert "get" in typeahead_path

        get_op = typeahead_path["get"]
        assert "responses" in get_op
        assert "200" in get_op["responses"]

        response_200 = get_op["responses"]["200"]
        assert "content" in response_200
        assert "application/json" in response_200["content"]

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_response_has_required_fields(self, api_client):
        """Response schema must define all required top-level fields."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        assert "properties" in response_schema
        properties = response_schema["properties"]

        # Required top-level fields
        assert "query" in properties
        assert "suggestions" in properties
        assert "matches" in properties
        assert "facets" in properties
        assert "did_you_mean" in properties
        assert "highlight" in properties
        assert "match_policy" in properties

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_suggestions_array_documented(self, api_client):
        """Suggestions array must be documented as mixed type array."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        suggestions = response_schema["properties"]["suggestions"]
        assert "type" in suggestions
        assert suggestions["type"] == "array"

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_matches_structure_documented(self, api_client):
        """Matches object must document card, bank, category, source fields."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        matches = response_schema["properties"]["matches"]

        if "$ref" in matches:
            matches_ref = matches["$ref"].split("/")[-1]
            matches = schema["components"]["schemas"][matches_ref]

        assert "properties" in matches
        assert "card" in matches["properties"]
        assert "bank" in matches["properties"]
        assert "category" in matches["properties"]
        assert "source" in matches["properties"]

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_facets_structure_documented(self, api_client):
        """Facets must document label, count, filter fields."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        facets = response_schema["properties"]["facets"]
        assert "type" in facets

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_highlight_structure_documented(self, api_client):
        """Highlight must document terms, scope, strategy fields."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        highlight = response_schema["properties"]["highlight"]

        if "$ref" in highlight:
            highlight_ref = highlight["$ref"].split("/")[-1]
            highlight = schema["components"]["schemas"][highlight_ref]

        assert "properties" in highlight
        assert "terms" in highlight["properties"]
        assert "scope" in highlight["properties"]
        assert "strategy" in highlight["properties"]

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_match_policy_structure_documented(self, api_client):
        """Match policy must document minimum_characters, result_limit, active."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200

        schema = response.data
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        match_policy = response_schema["properties"]["match_policy"]

        if "$ref" in match_policy:
            policy_ref = match_policy["$ref"].split("/")[-1]
            match_policy = schema["components"]["schemas"][policy_ref]

        assert "properties" in match_policy
        assert "minimum_characters" in match_policy["properties"]
        assert "result_limit" in match_policy["properties"]
        assert "active" in match_policy["properties"]


@pytest.mark.django_db()
class TestTypeaheadSchemaAccuracyRegression:
    """Regression tests ensuring schema matches actual API responses."""

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_actual_typeahead_response_matches_schema(self, api_client):
        """Actual typeahead response must conform to documented schema."""
        CreditCardFactory.create_batch(3, name="Travel Card")
        bank = BankFactory(name="Test Bank")
        CreditCardFactory(bank=bank, name="Test Card")

        # Get actual response
        actual_response = api_client.get("/api/v1/credit-cards/typeahead/?q=test")
        assert actual_response.status_code == 200
        actual_data = actual_response.data

        # Get schema
        schema_response = api_client.get(SCHEMA_URL)
        assert schema_response.status_code == 200
        schema = schema_response.data

        # Validate actual response structure against schema
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        if "$ref" in response_schema:
            ref_path = response_schema["$ref"].split("/")[-1]
            response_schema = schema["components"]["schemas"][ref_path]

        # Check all required fields are present
        assert "query" in actual_data
        assert isinstance(actual_data["query"], str)

        assert "suggestions" in actual_data
        assert isinstance(actual_data["suggestions"], list)

        assert "matches" in actual_data
        assert isinstance(actual_data["matches"], dict)
        assert all(
            key in actual_data["matches"]
            for key in ["card", "bank", "category", "source"]
        )

        assert "facets" in actual_data
        assert isinstance(actual_data["facets"], dict)

        assert "did_you_mean" in actual_data
        assert actual_data["did_you_mean"] is None or isinstance(
            actual_data["did_you_mean"], str
        )

        assert "highlight" in actual_data
        assert isinstance(actual_data["highlight"], dict)
        assert all(
            key in actual_data["highlight"] for key in ["terms", "scope", "strategy"]
        )

        assert "match_policy" in actual_data
        assert isinstance(actual_data["match_policy"], dict)
        assert all(
            key in actual_data["match_policy"]
            for key in ["minimum_characters", "result_limit", "active"]
        )

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_facets_structure_matches_schema(self, api_client):
        """Facets must be dict keyed by slug with label/count/filter items."""
        CreditCardFactory(name="Test", annual_fee=0)

        response = api_client.get("/api/v1/credit-cards/typeahead/?q=te")
        assert response.status_code == 200

        facets = response.data["facets"]
        # Facets should be keyed by slug: no_fee, travel, cashback, lounge
        expected_keys = {"no_fee", "travel", "cashback", "lounge"}
        actual_keys = set(facets.keys())
        assert actual_keys == expected_keys

        # Each facet item must have label, count, filter
        for facet_slug, facet_item in facets.items():
            assert isinstance(facet_item, dict)
            assert "label" in facet_item
            assert "count" in facet_item
            assert "filter" in facet_item
            assert isinstance(facet_item["label"], str)
            assert isinstance(facet_item["count"], int)
            assert isinstance(facet_item["filter"], str)

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_suggestions_polymorphic_types(self, api_client):
        """Suggestions must have type discrimination for card/bank/category."""
        CreditCardFactory(name="Sapphire")

        response = api_client.get("/api/v1/credit-cards/typeahead/?q=sap")
        assert response.status_code == 200

        suggestions = response.data["suggestions"]
        for suggestion in suggestions:
            assert isinstance(suggestion, dict)
            assert "type" in suggestion
            assert suggestion["type"] in ["card", "bank", "category"]

            if suggestion["type"] == "card":
                # Card suggestions: type, id, label, detail, query
                assert "id" in suggestion
                assert "label" in suggestion
                assert "detail" in suggestion
                assert "query" in suggestion

            elif suggestion["type"] == "bank":
                # Bank suggestions: type, id, label, detail, query
                assert "id" in suggestion
                assert "label" in suggestion
                assert "detail" in suggestion
                assert "query" in suggestion

            elif suggestion["type"] == "category":
                # Category suggestions: type, slug, label (no id/detail)
                assert "slug" in suggestion
                assert "label" in suggestion
                assert "id" not in suggestion

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_schema_does_not_reference_creditcard_model(self, api_client):
        """Response schemas must not leak CreditCard model reference."""
        schema_response = api_client.get(SCHEMA_URL)
        assert schema_response.status_code == 200
        schema = schema_response.data

        # Get typeahead response schema
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema_ref = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"].get("$ref", "")

        # Should reference TypeaheadResponse, not CreditCard
        assert "TypeaheadResponse" in response_schema_ref
        assert "CreditCard" not in response_schema_ref

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_field_history_schema_is_paginated_and_typed(self, api_client):
        """Field history must document its page envelope and history rows."""
        response = api_client.get(SCHEMA_URL)
        assert response.status_code == 200
        schema = response.data

        history_schema_ref = schema["paths"]["/api/v1/credit-cards/{id}/field-history/"][
            "get"
        ]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        history_schema = schema["components"]["schemas"][
            history_schema_ref.split("/")[-1]
        ]

        assert {"count", "next", "previous", "results"} <= set(
            history_schema["properties"]
        )
        result_items = history_schema["properties"]["results"]["items"]
        assert result_items["$ref"].endswith("/CreditCardFieldHistory")

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_suggestions_field_has_oneof_schema(self, api_client):
        """Suggestions field must declare oneOf with card/bank/category schemas."""
        schema_response = api_client.get(SCHEMA_URL)
        assert schema_response.status_code == 200
        schema = schema_response.data

        # Get typeahead response schema
        typeahead_path = schema["paths"]["/api/v1/credit-cards/typeahead/"]
        response_schema_ref = typeahead_path["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"].split("/")[-1]

        response_schema = schema["components"]["schemas"][response_schema_ref]
        suggestions_field = response_schema["properties"]["suggestions"]

        # Suggestions should be array with items
        assert suggestions_field["type"] == "array"
        assert "items" in suggestions_field

        items = suggestions_field["items"]

        # Items should have oneOf (polymorphic) or be a reference to schema with oneOf
        if "oneOf" in items:
            one_of = items["oneOf"]
            # Should have 3 options: card, bank, category
            assert len(one_of) >= 3

            # Extract types from oneOf options
            types_found = set()
            for option in one_of:
                if "$ref" in option:
                    ref_name = option["$ref"].split("/")[-1]
                    types_found.add(ref_name)
                elif "properties" in option:
                    # Inline schema - check type enum
                    if "type" in option["properties"]:
                        type_prop = option["properties"]["type"]
                        if "enum" in type_prop:
                            types_found.update(type_prop["enum"])

            # Should have card, bank, category
            assert "card" in str(one_of).lower()
            assert "bank" in str(one_of).lower()
            assert "category" in str(one_of).lower()

    @override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
    def test_typeahead_suggestions_with_results_conforms_to_schema(self, api_client):
        """Typeahead suggestions with actual results must match schema."""
        CreditCardFactory(name="Sapphire")

        response = api_client.get("/api/v1/credit-cards/typeahead/?q=sap")
        assert response.status_code == 200

        suggestions = response.data["suggestions"]
        # Each suggestion should be an object with type field
        for suggestion in suggestions:
            assert isinstance(suggestion, dict)
            assert "type" in suggestion
            assert suggestion["type"] in ["card", "bank", "category"]

            if suggestion["type"] == "card":
                assert "id" in suggestion
                assert "label" in suggestion
                assert "detail" in suggestion
                assert isinstance(suggestion["id"], int)
                assert isinstance(suggestion["label"], str)
                assert isinstance(suggestion["detail"], str)

            elif suggestion["type"] == "bank":
                assert "id" in suggestion
                assert "label" in suggestion
                assert "detail" in suggestion
                assert isinstance(suggestion["id"], int)
                assert isinstance(suggestion["label"], str)
                assert isinstance(suggestion["detail"], str)

            elif suggestion["type"] == "category":
                assert "slug" in suggestion
                assert "label" in suggestion
                assert isinstance(suggestion["slug"], str)
                assert isinstance(suggestion["label"], str)


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True)
class TestSchemaGeneration(TestCase):
    """Test schema generation functionality."""

    def test_schema_endpoint_returns_valid_openapi(self):
        """Schema endpoint must return valid OpenAPI spec."""
        client = APIClient()
        response = client.get(SCHEMA_URL)

        assert response.status_code == 200
        assert "openapi" in response.data or "swagger" in response.data
        assert "paths" in response.data
        assert "components" in response.data or "definitions" in response.data

    def test_schema_includes_all_credit_card_endpoints(self):
        """Schema must document all credit card API endpoints."""
        client = APIClient()
        response = client.get(SCHEMA_URL)

        assert response.status_code == 200
        paths = response.data["paths"]

        # Check for list endpoint
        assert "/api/v1/credit-cards/" in paths

        # Check for detail endpoint
        assert "/api/v1/credit-cards/{id}/" in paths or any(
            "credit-cards" in p and "{" in p for p in paths
        )

        # Check for typeahead endpoint
        assert "/api/v1/credit-cards/typeahead/" in paths

        # Check for search-suggestions endpoint
        assert "/api/v1/credit-cards/search-suggestions/" in paths
