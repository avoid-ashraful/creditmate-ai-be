"""Unit tests for TypeaheadResponseSerializer structure (no Django required).

Validates serializer field definitions and types.
"""


class TestTypeaheadResponseSerializerStructure:
    """Validate TypeaheadResponseSerializer matches actual response structure."""

    def test_serializer_has_all_required_fields(self):
        """TypeaheadResponseSerializer must define all response fields."""
        from credit_cards.api.serializers import TypeaheadResponseSerializer

        serializer = TypeaheadResponseSerializer()
        fields = serializer.fields

        # Check all required fields exist
        assert "query" in fields
        assert "suggestions" in fields
        assert "matches" in fields
        assert "facets" in fields
        assert "did_you_mean" in fields
        assert "highlight" in fields
        assert "match_policy" in fields

    def test_facets_uses_typed_dict_field(self):
        """Facets must be DictField with TypeaheadFacetSerializer child."""
        from rest_framework.fields import DictField

        from credit_cards.api.serializers import (
            TypeaheadFacetSerializer,
            TypeaheadResponseSerializer,
        )

        serializer = TypeaheadResponseSerializer()
        facets_field = serializer.fields["facets"]

        # Must be a DictField
        assert isinstance(facets_field, DictField)

        # Child should be TypeaheadFacetSerializer
        assert isinstance(facets_field.child, TypeaheadFacetSerializer)

    def test_suggestions_uses_polymorphic_field(self):
        """Suggestions must use TypeaheadSuggestionField for polymorphism."""
        from credit_cards.api.serializers import (
            TypeaheadResponseSerializer,
            TypeaheadSuggestionField,
        )

        serializer = TypeaheadResponseSerializer()
        suggestions_field = serializer.fields["suggestions"]

        # Child should be TypeaheadSuggestionField
        assert isinstance(suggestions_field.child, TypeaheadSuggestionField)

    def test_did_you_mean_nullable_and_optional(self):
        """did_you_mean must be nullable and optional."""
        from credit_cards.api.serializers import TypeaheadResponseSerializer

        serializer = TypeaheadResponseSerializer()
        did_you_mean_field = serializer.fields["did_you_mean"]

        # Should allow null
        assert did_you_mean_field.allow_null is True

        # Should be optional (not required)
        assert did_you_mean_field.required is False

    def test_match_policy_always_present(self):
        """match_policy must be required field (always present)."""
        from credit_cards.api.serializers import TypeaheadResponseSerializer

        serializer = TypeaheadResponseSerializer()
        match_policy_field = serializer.fields["match_policy"]

        # Should be required
        assert match_policy_field.required is True

    def test_facet_serializer_structure(self):
        """TypeaheadFacetSerializer must have label, count, filter fields."""
        from credit_cards.api.serializers import TypeaheadFacetSerializer

        serializer = TypeaheadFacetSerializer()
        fields = serializer.fields

        assert "label" in fields
        assert "count" in fields
        assert "filter" in fields

    def test_matches_serializer_structure(self):
        """TypeaheadMatchesSerializer must have card/bank/category/source."""
        from credit_cards.api.serializers import TypeaheadMatchesSerializer

        serializer = TypeaheadMatchesSerializer()
        fields = serializer.fields

        assert "card" in fields
        assert "bank" in fields
        assert "category" in fields
        assert "source" in fields

    def test_highlight_serializer_structure(self):
        """TypeaheadHighlightSerializer must have terms/scope/strategy."""
        from credit_cards.api.serializers import TypeaheadHighlightSerializer

        serializer = TypeaheadHighlightSerializer()
        fields = serializer.fields

        assert "terms" in fields
        assert "scope" in fields
        assert "strategy" in fields

    def test_match_policy_serializer_structure(self):
        """TypeaheadMatchPolicySerializer must have required policy fields."""
        from credit_cards.api.serializers import TypeaheadMatchPolicySerializer

        serializer = TypeaheadMatchPolicySerializer()
        fields = serializer.fields

        assert "minimum_characters" in fields
        assert "result_limit" in fields
        assert "active" in fields
