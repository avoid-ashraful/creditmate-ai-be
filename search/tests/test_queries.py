"""Unit tests for search query construction (filters, facets, queries)."""

import pytest

from search.queries import (
    BANK_AGGREGATIONS,
    BANK_FILTERS,
    CARD_AGGREGATIONS,
    CARD_FILTERS,
    build_body,
    build_filters,
    build_ordering,
    build_query,
    build_suggest_body,
    filterable_fields,
    index_body,
    index_name,
)


class TestIndexNames:
    def test_index_names_follow_settings(self, settings):
        settings.SEARCH_INDEX_PREFIX = "dev6_"
        assert index_name("banks") == "dev6_banks"
        assert index_name("cards") == "dev6_credit_cards"
        assert index_name("credit_cards") == "dev6_credit_cards"

    def test_default_index_names(self, settings):
        settings.SEARCH_INDEX_PREFIX = ""
        assert index_name("banks") == "banks"
        assert index_name("credit_cards") == "credit_cards"

    @pytest.mark.parametrize("kind", ["banks", "cards"])
    def test_index_body_has_both_sections(self, kind):
        body = index_body(kind)
        assert set(body) == {"settings", "mappings"}


class TestFilters:
    def test_bank_id_and_active_filters(self):
        clauses = build_filters("cards", {"bank_id": 7, "is_active": "true"})
        assert {"term": {"bank_id": 7}} in clauses
        assert {"term": {"is_active": True}} in clauses

    def test_boolean_false_is_preserved(self):
        clauses = build_filters("cards", {"is_active": False})
        assert {"term": {"is_active": False}} in clauses

    def test_range_filters(self):
        clauses = build_filters(
            "cards",
            {"annual_fee_min": "0", "annual_fee_max": 1500, "interest_rate_min": 20},
        )
        assert {"range": {"annual_fee": {"gte": 0.0}}} in clauses
        assert {"range": {"annual_fee": {"lte": 1500.0}}} in clauses
        assert {"range": {"interest_rate_apr": {"gte": 20.0}}} in clauses

    def test_unknown_annual_fee_is_excluded_from_zero_fee_filter(self):
        no_fee = build_filters("cards", {"no_annual_fee": True})
        assert {"term": {"annual_fee": 0}} in no_fee
        # The zero-fee filter must never touch the "known" flag: an unknown
        # fee has no ``annual_fee`` value at all, so a term on 0 excludes it.
        assert not any("annual_fee_known" in str(clause) for clause in no_fee)

    def test_unknown_annual_fee_filter_targets_known_flag(self):
        unknown = build_filters("cards", {"annual_fee_unknown": True})
        assert unknown == [{"term": {"annual_fee_known": False}}]

    def test_disabled_toggle_filters_are_dropped(self):
        assert build_filters("cards", {"no_annual_fee": False}) == []
        assert build_filters("cards", {"annual_fee_unknown": "false"}) == []

    def test_has_annual_fee_false_matches_only_known_zero_fee_cards(self):
        clauses = build_filters("cards", {"has_annual_fee": "false"})
        # `has_annual_fee` is indexed as null for unknown fees, so a term on
        # false only matches cards that really have no fee.
        assert clauses == [{"term": {"has_annual_fee": False}}]

    def test_bank_ids_terms_filter(self):
        clauses = build_filters("cards", {"bank_ids": ["1", "2", "x"]})
        assert {"terms": {"bank_id": [1, 2]}} in clauses

    def test_feature_search_uses_text_subfield(self):
        clauses = build_filters("cards", {"feature_search": "lounge"})
        assert {"match": {"additional_features.text": {"query": "lounge"}}} in clauses

    def test_lounge_presence_uses_classified_boolean(self):
        clauses = build_filters("cards", {"has_lounge_access_international": True})
        assert {"term": {"has_international_lounge": True}} in clauses

    def test_lounge_presence_false_selects_known_none_only(self):
        clauses = build_filters("cards", {"has_lounge_access_domestic": False})
        assert {"term": {"has_domestic_lounge": False}} in clauses

    def test_unknown_keys_are_ignored(self):
        assert build_filters("cards", {"unrelated": "x"}) == []
        assert build_filters("banks", {"bank_id": 3}) == []

    def test_sample_value_for_each_declared_card_filter(self):
        """Every card filter definition must produce a usable clause."""
        samples = {
            "bank_id": 1,
            "is_active": True,
            "has_annual_fee": True,
            "has_lounge_access": True,
            "has_lounge_access_international": True,
            "has_lounge_access_domestic": True,
            "has_fee_waiver": True,
            "no_annual_fee": True,
            "annual_fee_unknown": True,
            "annual_fee_min": 0,
            "annual_fee_max": 1000,
            "annual_fee_exact": 0,
            "interest_rate_min": 20,
            "interest_rate_max": 30,
            "min_lounge_visits_international": 2,
            "min_lounge_visits_domestic": 1,
        }
        # Note: "category" filter is handled specially in _build_multi_value_filters
        expected = set(CARD_FILTERS.keys()) - {"category"}
        assert set(samples) == expected, "filter definitions changed"
        for name, value in samples.items():
            assert build_filters("cards", {name: value}), f"no clause for {name}"

    def test_every_filter_field_exists_in_declared_filterable_fields(self):
        declared = set(filterable_fields("cards"))
        # Skip "category" filter which is handled specially and doesn't have a field reference
        referenced = {
            definition[1] for definition in CARD_FILTERS.values() if len(definition) > 1
        }
        missing = referenced - declared
        assert not missing, f"filters reference non-declared fields: {missing}"

    def test_every_bank_filter_field_exists(self):
        declared = set(filterable_fields("banks"))
        referenced = {definition[1] for definition in BANK_FILTERS.values()}
        assert not (referenced - declared)

    @pytest.mark.parametrize("kind", ["banks", "cards"])
    def test_aggregations_reference_declared_fields(self, kind):
        aggregations = BANK_AGGREGATIONS if kind == "banks" else CARD_AGGREGATIONS
        declared = set(filterable_fields(kind))
        for name, agg in aggregations.items():
            if "terms" in agg:
                assert agg["terms"]["field"] in declared, f"{name} -> {agg}"
            else:
                assert agg["range"]["field"] in declared, f"{name} -> {agg}"


class TestQueries:
    def test_empty_query_uses_match_all_with_filters(self):
        body = build_query("cards", query=None, filters={"is_active": True})
        assert body == {"bool": {"filter": [{"term": {"is_active": True}}]}}

    def test_query_adds_language_clauses(self):
        body = build_query("cards", query="visa card")
        should = body["bool"]["should"]
        assert body["bool"]["minimum_should_match"] == 1
        assert any(
            clause["multi_match"]["fields"][0].startswith("name") for clause in should
        )

    def test_bengali_query_targets_bengali_subfields(self):
        body = build_query("cards", query="ক্রেডিট কার্ড")
        should = body["bool"]["should"]
        bengali = [
            clause
            for clause in should
            if any(".bengali" in field for field in clause["multi_match"]["fields"])
        ]
        assert bengali, "expected a Bengali clause for a Bengali query"
        assert all(clause["multi_match"]["operator"] == "and" for clause in bengali)

    def test_english_query_has_no_bengali_clause(self):
        body = build_query("cards", query="cashback card")
        fields = [
            field
            for clause in body["bool"]["should"]
            for field in clause["multi_match"]["fields"]
        ]
        assert not any(".bengali" in field for field in fields)


class TestOrdering:
    @pytest.mark.parametrize(
        "ordering",
        ["credit_card_count", "-credit_card_count", "created", "-name.keyword"],
    )
    def test_allowed_bank_ordering(self, ordering):
        assert build_ordering("banks", ordering) != []

    @pytest.mark.parametrize(
        "ordering",
        ["annual_fee", "-annual_fee", "interest_rate_apr", "created", "-name.keyword"],
    )
    def test_allowed_card_ordering(self, ordering):
        assert build_ordering("cards", ordering) != []

    def test_relevance_ordering_by_default(self):
        assert build_ordering("cards", None) == []

    def test_unknown_ordering_falls_back_to_relevance(self):
        assert build_ordering("cards", "secret_field") == []

    def test_unknown_kind_field_rejected(self):
        assert build_ordering("cards", "credit_card_count") == []


class TestSearchBody:
    def test_pagination_is_clamped(self):
        body = build_body("cards", query="visa", page=0, page_size=1000)
        assert body["from"] == 0
        assert body["size"] == 100

    def test_aggregations_present(self):
        body = build_body("cards", query="visa")
        assert set(body["aggs"]) == set(CARD_AGGREGATIONS)

    def test_track_total_hits(self):
        body = build_body("banks")
        assert body["track_total_hits"] is True


class TestSuggest:
    def test_bool_prefix_suggest_body(self):
        body = build_suggest_body("cards", "ske", size=5)
        assert body["query"]["multi_match"]["type"] == "bool_prefix"
        assert body["size"] == 5

    def test_empty_query_returns_none(self):
        assert build_suggest_body("cards", "   ") is None
