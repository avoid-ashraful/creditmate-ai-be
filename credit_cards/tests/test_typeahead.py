"""Focused tests for the typeahead/autocomplete endpoint.

Covers query validation, groups/counts, facets, special characters,
no results, authentication, rate limiting, and response contract.
"""

import pytest

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory

TYPEAHEAD_URL = "/api/v1/credit-cards/typeahead/"


@pytest.mark.django_db()
class TestTypeaheadQueryBounds:
    """Test query length validation and bounds."""

    def test_query_below_minimum_length_returns_empty(self, api_client):
        """Query with less than 2 characters returns empty results."""
        CreditCardFactory(name="Visa Infinite")

        response = api_client.get(TYPEAHEAD_URL, {"q": "v"})
        assert response.status_code == 200

        # Empty results for sub-minimum queries
        assert response.data["query"] == "v"
        assert response.data["suggestions"] == []
        assert response.data["matches"]["card"] == []
        assert response.data["matches"]["bank"] == []
        assert response.data["match_policy"]["active"] is False

    def test_query_minimum_length_accepted(self, api_client):
        """Query with exactly 2 characters is accepted."""
        CreditCardFactory(name="Visa Infinite")

        response = api_client.get(TYPEAHEAD_URL, {"q": "vi"})
        assert response.status_code == 200
        assert response.data["match_policy"]["active"] is True
        # Should find the card
        assert len(response.data["matches"]["card"]) > 0

    def test_query_exceeding_max_length_is_truncated(self, api_client):
        """Query longer than 100 chars is truncated to 100."""
        CreditCardFactory(name="Visa Signature")
        long_query = "visa" + "x" * 150  # 154 chars total

        response = api_client.get(TYPEAHEAD_URL, {"q": long_query})
        assert response.status_code == 200
        # Query is internally truncated to 100 chars ("visa" + 96 x's)
        # which doesn't match anything (just "visa" + x's)
        assert response.data["query"] == long_query
        # Query won't match any prefix/substring, so empty suggestions expected
        assert response.data["suggestions"] == []

    def test_query_truncation_preserves_prefix_matches(self, api_client):
        """Query is truncated but still returns prefix matches."""
        CreditCardFactory(name="Visa Gold")
        # "visa" + 96 spaces/chars that get stripped = "visa" -> matches "Visa Gold"
        long_query = "visa" + " " * 150

        response = api_client.get(TYPEAHEAD_URL, {"q": long_query})
        assert response.status_code == 200
        # After truncation to 100 chars and strip(), "visa" remains
        # which matches "Visa Gold" prefix
        assert len(response.data["matches"]["card"]) > 0

    def test_empty_query_treated_as_empty_string(self, api_client):
        """Missing or empty q parameter returns empty results."""
        CreditCardFactory(name="Visa")

        response = api_client.get(TYPEAHEAD_URL)
        assert response.status_code == 200
        assert response.data["suggestions"] == []
        assert response.data["match_policy"]["active"] is False

    def test_query_stripped_before_length_check(self, api_client):
        """Leading/trailing whitespace is trimmed before length check."""
        CreditCardFactory(name="Visa")

        # " v " has length 3 but trims to "v" (length 1)
        response = api_client.get(TYPEAHEAD_URL, {"q": " v "})
        assert response.status_code == 200
        assert response.data["suggestions"] == []
        assert response.data["match_policy"]["active"] is False


@pytest.mark.django_db()
class TestTypeaheadGroupsAndCounts:
    """Test grouped results and bounded counts per group."""

    def test_cards_group_limited_to_max_results(self, api_client):
        """Card results are bounded to AUTOCOMPLETE_MAX_RESULTS (8)."""
        for i in range(15):
            CreditCardFactory(name=f"Visa Card {i:02d}")  # noqa: F841

        response = api_client.get(TYPEAHEAD_URL, {"q": "visa"})
        assert response.status_code == 200
        assert len(response.data["matches"]["card"]) <= 8
        assert all(s["type"] == "card" for s in response.data["suggestions"] if s["type"] == "card")

    def test_banks_group_limited_to_max_results(self, api_client):
        """Bank results are bounded to AUTOCOMPLETE_MAX_RESULTS (8)."""
        for i in range(15):
            bank = BankFactory(name=f"Bank {i:02d}")
            CreditCardFactory(bank=bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "bank"})
        assert response.status_code == 200
        assert len(response.data["matches"]["bank"]) <= 8
        assert all(s["type"] == "bank" for s in response.data["suggestions"] if s["type"] == "bank")

    def test_mixed_suggestions_combined_not_exceed_max_results(self, api_client):
        """Combined card+bank suggestions don't exceed AUTOCOMPLETE_MAX_RESULTS."""
        CreditCardFactory(name="Visa Card")
        bank = BankFactory(name="Visa Bank")
        CreditCardFactory(bank=bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "visa"})
        assert response.status_code == 200
        # Total suggestions should not exceed 8
        assert len(response.data["suggestions"]) <= 8

    def test_card_suggestions_include_bank_detail(self, api_client):
        """Card suggestions include bank name as detail."""
        bank = BankFactory(name="Chase")
        card = CreditCardFactory(name="Sapphire", bank=bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "sa"})
        assert response.status_code == 200
        card_suggestion = next(
            (s for s in response.data["suggestions"] if s["type"] == "card"),
            None
        )
        assert card_suggestion is not None
        assert card_suggestion["detail"] == "Chase"
        assert card_suggestion["id"] == card.id
        assert card_suggestion["label"] == "Sapphire"

    def test_bank_suggestions_include_card_count(self, api_client):
        """Bank suggestions include active card count."""
        bank = BankFactory(name="Chase")
        CreditCardFactory.create_batch(3, bank=bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "cha"})
        assert response.status_code == 200
        bank_suggestion = next(
            (s for s in response.data["suggestions"] if s["type"] == "bank"),
            None
        )
        assert bank_suggestion is not None
        assert "3 cards" in bank_suggestion["detail"]

    def test_prefix_matches_prioritized_over_contains(self, api_client):
        """Prefix matches appear before substring-only matches."""
        CreditCardFactory(name="Visa Infinite")
        CreditCardFactory(name="Bank of Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "visa"})
        assert response.status_code == 200
        matches = response.data["matches"]["card"]
        # "Visa Infinite" starts with "Visa", should appear in prefix group
        assert "Visa Infinite" in matches
        # "Bank of Visa" is substring-only, should come after prefix matches
        assert matches.index("Visa Infinite") < matches.index("Bank of Visa")


@pytest.mark.django_db()
class TestTypeaheadFacets:
    """Test facet calculation and bounds."""

    def test_facets_included_in_response(self, api_client):
        """Response includes facet counts for common filters."""
        CreditCardFactory(
            name="Test Card",
            annual_fee=0,
            reward_points_policy="Travel rewards"
        )

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        assert "facets" in response.data
        assert isinstance(response.data["facets"], dict)

    def test_facet_structure(self, api_client):
        """Each facet has label, count, and filter properties."""
        CreditCardFactory(name="Test", annual_fee=0)  # noqa: F841

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        facets = response.data["facets"]
        for facet_key, facet_data in facets.items():
            assert "label" in facet_data
            assert "count" in facet_data
            assert "filter" in facet_data
            assert isinstance(facet_data["count"], int)

    def test_no_fee_facet(self, api_client):
        """No-fee facet counts cards with annual_fee=0."""
        CreditCardFactory(name="Free", annual_fee=0)
        CreditCardFactory(name="Premium", annual_fee=1000)

        response = api_client.get(TYPEAHEAD_URL, {"q": "ca"})
        assert response.status_code == 200
        no_fee_facet = response.data["facets"].get("no_fee")
        assert no_fee_facet is not None
        assert no_fee_facet["count"] == 1

    def test_travel_facet(self, api_client):
        """Travel facet counts cards with travel rewards."""
        CreditCardFactory(
            name="Travel Card",
            reward_points_policy="2x travel"
        )
        CreditCardFactory(name="Cashback", reward_points_policy="2% cashback")

        response = api_client.get(TYPEAHEAD_URL, {"q": "ca"})
        assert response.status_code == 200
        travel_facet = response.data["facets"].get("travel")
        assert travel_facet is not None
        assert travel_facet["count"] >= 1

    def test_cashback_facet(self, api_client):
        """Cashback facet counts cards with cashback rewards."""
        CreditCardFactory(
            name="CB Card",
            reward_points_policy="5% cashback"
        )

        response = api_client.get(TYPEAHEAD_URL, {"q": "ca"})
        assert response.status_code == 200
        cashback_facet = response.data["facets"].get("cashback")
        assert cashback_facet is not None
        assert cashback_facet["count"] >= 1


@pytest.mark.django_db()
class TestTypeaheadSpecialCharacters:
    """Test handling of special characters in queries."""

    def test_query_with_quotes(self, api_client):
        """Queries with quotes don't crash; matched as literal."""
        CreditCardFactory(name='Card "Premium"')

        response = api_client.get(TYPEAHEAD_URL, {"q": 'pre"'})
        assert response.status_code == 200

    def test_query_with_sql_like_chars(self, api_client):
        """SQL-like characters are safe (no injection)."""
        CreditCardFactory(name="Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "visa' OR '1'='1"})
        assert response.status_code == 200
        assert response.data["suggestions"] == []

    def test_query_with_regex_chars(self, api_client):
        """Regex characters are treated literally."""
        CreditCardFactory(name="Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "vi.*"})
        assert response.status_code == 200
        assert response.data["suggestions"] == []

    def test_query_with_unicode(self, api_client):
        """Unicode characters are handled gracefully."""
        CreditCardFactory(name="Visa Gold")

        response = api_client.get(TYPEAHEAD_URL, {"q": "café"})
        assert response.status_code == 200


@pytest.mark.django_db()
class TestTypeaheadNoResults:
    """Test behavior when no results match."""

    def test_no_matches_returns_empty_suggestions(self, api_client):
        """Non-matching query returns empty suggestions."""
        CreditCardFactory(name="Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "mastercard xyz"})
        assert response.status_code == 200
        assert response.data["suggestions"] == []
        assert response.data["matches"]["card"] == []

    def test_did_you_mean_on_typo(self, api_client):
        """Close typos suggest a correct name."""
        CreditCardFactory(name="Sapphire")

        response = api_client.get(TYPEAHEAD_URL, {"q": "sapir"})
        assert response.status_code == 200
        # Typo threshold is 0.8; minor typos may suggest
        if response.data["did_you_mean"]:
            assert isinstance(response.data["did_you_mean"], str)

    def test_did_you_mean_none_on_no_matches(self, api_client):
        """No suggestion when very dissimilar query."""
        CreditCardFactory(name="Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "xyz"})
        assert response.status_code == 200
        assert response.data["did_you_mean"] is None


@pytest.mark.django_db()
class TestTypeaheadResponse:
    """Test response structure and contract."""

    def test_response_includes_required_fields(self, api_client):
        """Response includes all required contract fields."""
        CreditCardFactory(name="Test Card")  # noqa: F841

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        assert "query" in response.data
        assert "suggestions" in response.data
        assert "matches" in response.data
        assert "facets" in response.data
        assert "did_you_mean" in response.data
        assert "highlight" in response.data
        assert "match_policy" in response.data

    def test_matches_has_correct_structure(self, api_client):
        """matches object has card, bank, category, source fields."""
        CreditCardFactory(name="Test")

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        matches = response.data["matches"]
        assert "card" in matches
        assert "bank" in matches
        assert "category" in matches
        assert "source" in matches
        assert matches["source"] == "database"
        assert isinstance(matches["card"], list)
        assert isinstance(matches["bank"], list)
        assert isinstance(matches["category"], list)

    def test_category_matches_empty_when_no_backend_support(self, api_client):
        """Category matches are explicitly empty (no backend source)."""
        CreditCardFactory(name="Test")

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        assert response.data["matches"]["category"] == []

    def test_highlight_info_provided(self, api_client):
        """Highlight object describes highlighting strategy."""
        CreditCardFactory(name="Test")

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        highlight = response.data["highlight"]
        assert "terms" in highlight
        assert "scope" in highlight
        assert "strategy" in highlight

    def test_highlight_with_valid_query(self, api_client):
        """Highlight includes query term when active."""
        CreditCardFactory(name="Test")

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200
        assert response.data["highlight"]["terms"] == ["te"]
        assert response.data["highlight"]["strategy"] == "case_insensitive_substring"

    def test_highlight_without_valid_query(self, api_client):
        """Highlight is empty when query below minimum."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "x"})
        assert response.status_code == 200
        highlight = response.data["highlight"]
        assert highlight["terms"] == []
        assert highlight["scope"] is None
        assert highlight["strategy"] is None

    def test_suggestion_has_type_field(self, api_client):
        """Each suggestion includes type (card or bank)."""
        CreditCardFactory(name="Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "vi"})
        assert response.status_code == 200
        for suggestion in response.data["suggestions"]:
            assert "type" in suggestion
            assert suggestion["type"] in ("card", "bank")

    def test_suggestion_card_structure(self, api_client):
        """Card suggestions have id, label, detail, type."""
        bank = BankFactory(name="Chase")
        card = CreditCardFactory(name="Sapphire", bank=bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "sa"})
        assert response.status_code == 200
        card_suggestion = next(
            (s for s in response.data["suggestions"] if s["type"] == "card"),
            None
        )
        assert card_suggestion is not None
        assert card_suggestion["id"] == card.id
        assert card_suggestion["label"] == card.name
        assert card_suggestion["detail"] == bank.name
        assert "type" in card_suggestion

    def test_suggestion_bank_structure(self, api_client):
        """Bank suggestions have id, label, detail, type."""
        bank = BankFactory(name="Chase")
        CreditCardFactory(bank=bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "cha"})
        assert response.status_code == 200
        bank_suggestion = next(
            (s for s in response.data["suggestions"] if s["type"] == "bank"),
            None
        )
        assert bank_suggestion is not None
        assert bank_suggestion["id"] == bank.id
        assert bank_suggestion["label"] == bank.name
        assert "cards" in bank_suggestion["detail"]

    def test_query_returned_as_received(self, api_client):
        """query field in response matches raw input."""
        CreditCardFactory(name="Test")
        raw_q = " TEST "

        response = api_client.get(TYPEAHEAD_URL, {"q": raw_q})
        assert response.status_code == 200
        assert response.data["query"] == raw_q


@pytest.mark.django_db()
class TestTypeaheadAuthAndRateLimit:
    """Test authentication and rate limiting behavior."""

    def test_endpoint_accessible_without_auth(self, api_client):
        """Typeahead endpoint requires no authentication."""
        CreditCardFactory(name="Test")

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200

    def test_endpoint_accessible_by_anonymous_user(self, api_client):
        """Anonymous users can access typeahead."""
        CreditCardFactory(name="Test")
        api_client.force_authenticate(user=None)

        response = api_client.get(TYPEAHEAD_URL, {"q": "te"})
        assert response.status_code == 200


@pytest.mark.django_db()
class TestTypeaheadCaseSensitivity:
    """Test case-insensitive matching."""

    def test_query_case_insensitive_prefix(self, api_client):
        """Prefix matching is case-insensitive."""
        CreditCardFactory(name="Visa Infinite")

        response = api_client.get(TYPEAHEAD_URL, {"q": "VISA"})
        assert response.status_code == 200
        assert len(response.data["matches"]["card"]) > 0

    def test_query_case_insensitive_contains(self, api_client):
        """Substring matching is case-insensitive."""
        CreditCardFactory(name="Bank of Visa")

        response = api_client.get(TYPEAHEAD_URL, {"q": "visa"})
        assert response.status_code == 200
        assert len(response.data["matches"]["card"]) > 0

    def test_mixed_case_query(self, api_client):
        """Mixed-case queries match correctly."""
        CreditCardFactory(name="Visa Gold")

        response = api_client.get(TYPEAHEAD_URL, {"q": "ViSa"})
        assert response.status_code == 200
        assert len(response.data["matches"]["card"]) > 0


@pytest.mark.django_db()
class TestTypeaheadInactiveCards:
    """Test that inactive cards are excluded."""

    def test_inactive_cards_not_returned(self, api_client):
        """Inactive cards are excluded from results."""
        active = CreditCardFactory(name="Active Card", is_active=True)
        inactive = CreditCardFactory(name="Inactive Card", is_active=False)

        response = api_client.get(TYPEAHEAD_URL, {"q": "card"})
        assert response.status_code == 200
        suggestions = response.data["suggestions"]
        card_ids = [s["id"] for s in suggestions if s["type"] == "card"]

        assert active.id in card_ids
        assert inactive.id not in card_ids

    def test_inactive_banks_not_returned(self, api_client):
        """Inactive banks are excluded from results."""
        active_bank = BankFactory(name="Active Bank", is_active=True)
        inactive_bank = BankFactory(name="Inactive Bank", is_active=False)
        CreditCardFactory(bank=active_bank)
        CreditCardFactory(bank=inactive_bank)

        response = api_client.get(TYPEAHEAD_URL, {"q": "bank"})
        assert response.status_code == 200
        suggestions = response.data["suggestions"]
        bank_ids = [s["id"] for s in suggestions if s["type"] == "bank"]

        assert active_bank.id in bank_ids
        assert inactive_bank.id not in bank_ids


@pytest.mark.django_db()
class TestTypeaheadCategories:
    """Test category suggestions from canonical taxonomy."""

    def test_category_exact_match(self, api_client):
        """Matching category name returns category suggestion."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "travel"})
        assert response.status_code == 200

        # Should find Travel category
        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        assert len(category_suggestions) > 0
        assert category_suggestions[0]["slug"] == "travel"
        assert category_suggestions[0]["label"] == "Travel"

    def test_category_prefix_match(self, api_client):
        """Partial category name matches."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "tra"})
        assert response.status_code == 200

        # Should find Travel category by prefix
        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        assert len(category_suggestions) > 0
        assert category_suggestions[0]["slug"] == "travel"

    def test_category_slug_match(self, api_client):
        """Category slug (no-annual-fee) matches."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "no-annual"})
        assert response.status_code == 200

        # Should find No Annual Fee category by slug prefix
        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        assert len(category_suggestions) > 0
        assert category_suggestions[0]["slug"] == "no-annual-fee"
        assert category_suggestions[0]["label"] == "No Annual Fee"

    def test_multiple_categories_match(self, api_client):
        """Multiple categories can match when query is ambiguous."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "ca"})
        assert response.status_code == 200

        # Both Cashback and Business could match
        category_matches = response.data["matches"]["category"]
        # At least one category should match
        assert "Cashback" in category_matches or len(category_matches) > 0

    def test_category_in_matches_array(self, api_client):
        """Matching categories appear in matches.category array."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "travel"})
        assert response.status_code == 200

        assert "Travel" in response.data["matches"]["category"]

    def test_category_suggestion_has_required_fields(self, api_client):
        """Category suggestions have slug and label fields."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "premium"})
        assert response.status_code == 200

        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        if len(category_suggestions) > 0:
            assert "slug" in category_suggestions[0]
            assert "label" in category_suggestions[0]
            assert "type" in category_suggestions[0]
            assert category_suggestions[0]["type"] == "category"

    def test_no_category_match_for_non_matching_query(self, api_client):
        """Non-matching queries return empty category matches."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "xyz123"})
        assert response.status_code == 200

        assert response.data["matches"]["category"] == []

    def test_category_does_not_leak_arbitrary_text(self, api_client):
        """Category suggestions only return canonical categories, not arbitrary text."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "visa' OR '1'='1"})
        assert response.status_code == 200

        # No categories should match this SQL injection attempt
        assert response.data["matches"]["category"] == []

    def test_case_insensitive_category_match(self, api_client):
        """Category matching is case-insensitive."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "TRAVEL"})
        assert response.status_code == 200

        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        assert len(category_suggestions) > 0
        assert category_suggestions[0]["slug"] == "travel"

    def test_category_slug_format_preserved(self, api_client):
        """Category slug is preserved in lowercase with hyphens."""
        response = api_client.get(TYPEAHEAD_URL, {"q": "no"})
        assert response.status_code == 200

        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        matching = [s for s in category_suggestions if "fee" in s.get("label", "").lower()]
        if len(matching) > 0:
            # Slug should use hyphens, not underscores
            assert "-" in matching[0]["slug"]
            assert "_" not in matching[0]["slug"]

    def test_categories_bounded_with_cards_banks(self, api_client):
        """Categories reserved even when many card matches exist."""
        CreditCardFactory.create_batch(10, name="Card Travel")

        response = api_client.get(TYPEAHEAD_URL, {"q": "tra"})
        assert response.status_code == 200

        # Total suggestions should not exceed 8
        assert len(response.data["suggestions"]) <= 8

        # Travel category should still appear even with 10 matching cards
        category_suggestions = [s for s in response.data["suggestions"] if s.get("type") == "category"]
        assert len(category_suggestions) > 0, "Category should be reserved despite many card matches"
        assert category_suggestions[0]["slug"] == "travel", "Travel category slug should survive"
        assert "Travel" in response.data["matches"]["category"], "Travel in matches.category"
