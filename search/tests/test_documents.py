"""Unit tests for index settings, analyzers, synonyms and mappings."""

import pytest

from credit_cards.lounge import card_has_lounge_access
from search.documents import (
    ANALYZER_BENGALI,
    ANALYZER_MULTILANG,
    ANALYZER_SUGGEST,
    BANK_FILTERABLE_FIELDS,
    BANK_INDEX_BODY,
    BANK_MAPPING,
    CREDIT_CARD_FILTERABLE_FIELDS,
    CREDIT_CARD_INDEX_BODY,
    CREDIT_CARD_MAPPING,
    FILTER_SYNONYMS,
    INDEX_SETTINGS,
    REQUIRED_SYNONYM_GROUPS,
    SYNONYMS,
    credit_card_to_document,
    filterable_paths,
)
from search.queries import mapped_filterable_fields


class TestSynonyms:
    """The mandated synonym groups must be declared in index settings."""

    @pytest.mark.parametrize(("term_a", "term_b"), REQUIRED_SYNONYM_GROUPS)
    def test_required_synonym_groups_declared(self, term_a, term_b):
        groups = [
            set(part.strip().lower() for part in group.split(",")) for group in SYNONYMS
        ]
        matched = any({term_a, term_b}.issubset(group) for group in groups)
        assert matched, f"missing synonym group linking {term_a!r} and {term_b!r}"

    def test_synonym_filter_is_registered(self):
        filters = INDEX_SETTINGS["analysis"]["filter"]
        assert FILTER_SYNONYMS in filters
        assert filters[FILTER_SYNONYMS]["type"] == "synonym_graph"
        assert filters[FILTER_SYNONYMS]["expand"] is True
        assert filters[FILTER_SYNONYMS]["synonyms"] == SYNONYMS

    def test_synonym_filter_used_by_every_analyzer(self):
        analyzers = INDEX_SETTINGS["analysis"]["analyzer"]
        for name in ("creditmate_multilang", "creditmate_english"):
            assert FILTER_SYNONYMS in analyzers[name]["filter"], name

    def test_suggest_analyzer_is_synonym_free(self):
        """``search_as_you_type`` fields must not use the synonym filter.

        Elasticsearch 8.19 refuses to index a document when a multi word
        synonym source (``credit card``) is analysed into a
        ``search_as_you_type`` sub field::

            first position increment must be > 0 (got 0) for field 'name._3gram'

        so the prefix suggest fields run on a synonym free chain instead.
        """
        analyzers = INDEX_SETTINGS["analysis"]["analyzer"]
        assert ANALYZER_SUGGEST in analyzers
        assert FILTER_SYNONYMS not in analyzers[ANALYZER_SUGGEST]["filter"]
        assert "bengali_normalization" in analyzers[ANALYZER_SUGGEST]["filter"]

    @pytest.mark.parametrize(
        "mapping", [BANK_MAPPING, CREDIT_CARD_MAPPING], ids=["banks", "cards"]
    )
    def test_suggest_fields_use_the_synonym_free_analyzer(self, mapping):
        for field in ("name_suggest", "bank_name_suggest"):
            spec = mapping["properties"].get(field)
            if spec is None:
                continue
            assert spec["type"] == "search_as_you_type"
            assert spec["analyzer"] == ANALYZER_SUGGEST

    def test_required_pairs_are_wired_into_index_body(self):
        synonyms = BANK_INDEX_BODY["settings"]["analysis"]["filter"][FILTER_SYNONYMS][
            "synonyms"
        ]
        joined = " | ".join(synonyms).lower()
        assert "visa, credit card" in joined
        assert "apr, interest rate" in joined
        # Both indexes share the same settings payload.
        assert CREDIT_CARD_INDEX_BODY["settings"] == BANK_INDEX_BODY["settings"]


class TestBengaliAnalyzer:
    """Bengali analysis must be available for local language search."""

    def test_bengali_language_analyzer_declared(self):
        analyzers = INDEX_SETTINGS["analysis"]["analyzer"]
        assert analyzers[ANALYZER_BENGALI] == {"type": "bengali"}

    def test_multilang_analyzer_normalises_bengali(self):
        filters = INDEX_SETTINGS["analysis"]["analyzer"][ANALYZER_MULTILANG]["filter"]
        assert "bengali_normalization" in filters
        assert "creditmate_bengali_stemmer" in filters
        assert INDEX_SETTINGS["analysis"]["filter"]["creditmate_bengali_stemmer"] == {
            "type": "stemmer",
            "language": "bengali",
        }

    @pytest.mark.parametrize("kind", ["banks", "cards"])
    def test_bengali_subfield_exposed_on_text_fields(self, kind):
        mapping = BANK_MAPPING if kind == "banks" else CREDIT_CARD_MAPPING
        properties = mapping["properties"]
        name_field = properties["name"]
        assert name_field["fields"]["bengali"]["analyzer"] == ANALYZER_BENGALI
        assert name_field["analyzer"] == ANALYZER_MULTILANG


class TestMappings:
    """Both indexes must exist with their settings and full mappings."""

    @pytest.mark.parametrize(
        "body", [BANK_INDEX_BODY, CREDIT_CARD_INDEX_BODY], ids=["banks", "credit_cards"]
    )
    def test_index_body_shape(self, body):
        assert set(body) == {"settings", "mappings"}
        assert body["settings"]["number_of_shards"] == 1
        assert body["settings"]["number_of_replicas"] == 0

    @pytest.mark.parametrize(
        ("kind", "declared", "mapping"),
        [
            ("banks", BANK_FILTERABLE_FIELDS, BANK_MAPPING),
            ("cards", CREDIT_CARD_FILTERABLE_FIELDS, CREDIT_CARD_MAPPING),
        ],
    )
    def test_filterable_fields_match_mapping(self, kind, declared, mapping):
        computed = filterable_paths(mapping["properties"])
        assert (
            sorted(declared) == computed
        ), f"{kind}: declared filterable fields diverge from the mapping"
        assert sorted(mapped_filterable_fields(kind)) == computed

    @pytest.mark.parametrize(
        ("declared", "mapping"),
        [
            (BANK_FILTERABLE_FIELDS, BANK_MAPPING),
            (CREDIT_CARD_FILTERABLE_FIELDS, CREDIT_CARD_MAPPING),
        ],
    )
    def test_declared_fields_resolve_in_mapping(self, declared, mapping):
        for path in declared:
            parts = path.split(".")
            node = mapping["properties"]
            for index, part in enumerate(parts):
                assert part in node, f"{path}: missing {part}"
                node = node[part]
                if index < len(parts) - 1:
                    node = node.get("fields", {})
            assert node.get("type") in (
                "keyword",
                "boolean",
                "long",
                "integer",
                "float",
                "double",
                "date",
                "flattened",
            ), f"{path}: {node.get('type')} is not filterable"


class TestDocumentSerialization:
    """Document payloads must keep unknown values distinguishable."""

    @pytest.mark.parametrize(
        ("fee", "expected_has_fee", "expected_known"),
        [
            (None, None, False),
            (0, False, True),
            (1200, True, True),
        ],
    )
    def test_annual_fee_tristate(self, fee, expected_has_fee, expected_known):
        card = _card(annual_fee=fee)
        document = credit_card_to_document(card)
        assert document["has_annual_fee"] is expected_has_fee
        assert document["annual_fee_known"] is expected_known
        assert document["annual_fee"] == (None if fee is None else float(fee))

    def test_lounge_visits_parsed(self):
        card = _card(
            lounge_access_international="5 visits per year",
            lounge_access_domestic="Unlimited",
        )
        document = credit_card_to_document(card)
        assert document["lounge_visits_international"] == 5.0
        assert document["lounge_visits_domestic"] is None
        assert document["has_lounge_access"] is True

    def test_lounge_none_values_are_not_access(self):
        card = _card(lounge_access_international="N/A", lounge_access_domestic="0")
        document = credit_card_to_document(card)
        assert document["lounge_visits_international"] == 0
        assert document["lounge_visits_domestic"] == 0
        assert document["has_international_lounge"] is False
        assert document["has_domestic_lounge"] is False
        assert document["has_lounge_access"] is False

    def test_lounge_unknown_values_leave_flags_unset(self):
        card = _card(lounge_access_international="", lounge_access_domestic="")
        document = credit_card_to_document(card)
        assert document["lounge_visits_international"] is None
        assert document["has_international_lounge"] is None
        assert document["has_lounge_access"] is None


class _StubBank:
    def __init__(self, name="Dutch-Bangla Bank", pk=1, credit_card_count=2):
        self.pk = pk
        self.name = name
        self.logo = "https://example.com/logo.png"
        self.website = "https://example.com"
        self.schedule_charge_url = "https://example.com/soc.pdf"
        self.is_active = True
        self.credit_card_count = credit_card_count
        self.created = "2026-01-01T00:00:00Z"
        self.modified = "2026-01-02T00:00:00Z"


class _StubCard:
    def __init__(self, **overrides):
        self.pk = 10
        self.bank_id = 1
        self.bank = _StubBank()
        self.name = "SkyBlue Visa"
        self.annual_fee = None
        self.interest_rate_apr = None
        self.lounge_access_international = ""
        self.lounge_access_domestic = ""
        self.lounge_access_condition = ""
        self.cash_advance_fee = "1.5%"
        self.late_payment_fee = "BDT 500"
        self.reward_points_policy = "1 point per BDT 100"
        self.additional_features = ["cashback"]
        self.annual_fee_waiver_policy = {"minimum_spend": 100000}
        self.is_active = True
        self.source_url = ""
        self.apply_url = ""
        self.card_network = ""
        self.is_islamic = False
        self.is_dual_currency = None
        self.min_monthly_income = None
        self.supplementary_card_fee = ""
        self.foreign_transaction_fee = ""
        self.created = "2026-01-01T00:00:00Z"
        self.modified = "2026-01-02T00:00:00Z"
        for key, value in overrides.items():
            setattr(self, key, value)

    @property
    def has_lounge_access(self):
        return card_has_lounge_access(
            self.lounge_access_international, self.lounge_access_domestic
        )


def _card(**overrides):
    return _StubCard(**overrides)
