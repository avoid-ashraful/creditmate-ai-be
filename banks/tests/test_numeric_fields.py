"""Unit tests for the shared critical numeric field normalization rules.

Covers the zero-versus-missing-versus-invalid contract that confidence scoring
and database storage both rely on.
"""

import math

import pytest

from banks.validators.numeric_fields import (
    CRITICAL_FIELDS,
    FIELD_BOUNDS,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_VALID,
    critical_field_status,
    is_valid_critical_value,
    normalize_critical_fields,
    normalize_cards,
    parse_numeric_value,
)


class TestParseNumericValue:
    """parse_numeric_value must return a bounded float or None plus a status."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (0, 0.0),  # genuine zero fee (free card) is valid
            (0.0, 0.0),
            (95, 95.0),
            (18.99, 18.99),
            (5000, 5000.0),
        ],
    )
    def test_valid_numbers_including_zero(self, value, expected):
        normalized, status = parse_numeric_value(value, "annual_fee")
        assert status == STATUS_VALID
        assert normalized == expected

    @pytest.mark.parametrize(
        "value",
        ["Free", "free of charge", "Nil", "NIL", "No annual fee", "Waived", "Exempted"],
    )
    def test_free_wording_is_genuine_zero_for_fee(self, value):
        normalized, status = parse_numeric_value(value, "annual_fee")
        assert status == STATUS_VALID
        assert normalized == 0.0

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", "N/A", "na", "unknown", "-", "not mentioned", "Not specified"],
    )
    def test_missing_markers(self, value):
        normalized, status = parse_numeric_value(value, "annual_fee")
        assert status == STATUS_MISSING
        assert normalized is None

    @pytest.mark.parametrize(
        "value",
        [
            "abc",
            "12abc",
            "ask your RM",
            "12 months free",
            True,
            False,
            float("nan"),
            float("inf"),
            -float("inf"),
            "NaN",
            "Infinity",
            -50,
            "-50",
            120000,  # above documented annual fee bound
            [5000],
            {"amount": 5000},
        ],
    )
    def test_invalid_values(self, value):
        normalized, status = parse_numeric_value(value, "annual_fee")
        assert status == STATUS_INVALID
        assert normalized is None

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("20%", 20.0),
            ("18.99%", 18.99),
            ("20% p.a.", 20.0),
            ("20 percent per annum", 20.0),
            ("TK 5,000", 5000.0),
            ("Tk. 1,500", 1500.0),
            ("BDT 500", 500.0),
            ("$95.00", 95.0),
            ("taka 2,500", 2500.0),
        ],
    )
    def test_currency_and_percentage_strings(self, value, expected):
        normalized, status = parse_numeric_value(value, "annual_fee")
        assert status == STATUS_VALID
        assert normalized == expected

    @pytest.mark.parametrize(
        "value,status",
        [
            (150, STATUS_INVALID),  # APR above 100% is not plausible
            (-1, STATUS_INVALID),
            ("Free", STATUS_INVALID),  # "free" wording must not become 0% APR
            (None, STATUS_MISSING),
            ("N/A", STATUS_MISSING),
            (18.99, STATUS_VALID),
        ],
    )
    def test_apr_specific_rules(self, value, status):
        normalized, parsed_status = parse_numeric_value(value, "interest_rate_apr")
        assert parsed_status == status
        assert normalized is None or status == STATUS_VALID

    def test_bounds_are_documented(self):
        assert FIELD_BOUNDS["annual_fee"][0] == 0.0
        assert FIELD_BOUNDS["interest_rate_apr"] == (0.0, 100.0)

    def test_is_valid_critical_value(self):
        assert is_valid_critical_value(0, "annual_fee") is True
        assert is_valid_critical_value(None, "annual_fee") is False
        assert is_valid_critical_value("abc", "annual_fee") is False


class TestCardLevelHelpers:
    """Statuses and normalization for whole card dictionaries."""

    def test_critical_field_status_distinguishes_zero_from_missing(self):
        card = {"name": "Free Card", "annual_fee": 0, "interest_rate_apr": None}
        assert critical_field_status(card, "annual_fee") == STATUS_VALID
        assert critical_field_status(card, "interest_rate_apr") == STATUS_MISSING

    def test_field_absent_is_missing(self):
        assert critical_field_status({"name": "X"}, "annual_fee") == STATUS_MISSING

    def test_invalid_value_status(self):
        card = {"name": "X", "annual_fee": "abc"}
        assert critical_field_status(card, "annual_fee") == STATUS_INVALID

    def test_normalize_critical_fields_keeps_other_keys(self):
        card = {
            "name": "Gold Card",
            "annual_fee": "TK 5,000",
            "interest_rate_apr": "bogus",
            "CIB Fee": "BDT 100",
        }
        normalized, statuses = normalize_critical_fields(card)
        assert normalized["annual_fee"] == 5000.0
        assert normalized["interest_rate_apr"] is None
        assert statuses["interest_rate_apr"] == STATUS_INVALID
        assert normalized["name"] == "Gold Card"
        assert normalized["CIB Fee"] == "BDT 100"  # provenance preserved

    def test_normalize_cards_skips_non_dicts(self):
        cards, statuses = normalize_cards([{"annual_fee": 1}, "junk", None])
        assert len(cards) == 1
        assert len(statuses) == 1

    def test_all_fields_declared(self):
        assert CRITICAL_FIELDS == ("annual_fee", "interest_rate_apr")

    def test_nan_never_survives_normalization(self):
        normalized, _ = normalize_critical_fields(
            {"annual_fee": math.nan, "interest_rate_apr": math.inf}
        )
        assert normalized["annual_fee"] is None
        assert normalized["interest_rate_apr"] is None
