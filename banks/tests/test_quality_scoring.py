"""Tests for the bounded, documented extraction confidence scoring (Phases 2+3).

Every score must live in the inclusive range 0.0-1.0, critical-field credit is
only given for *valid* normalized numbers, and missing versus invalid values
must be reported with distinct issue codes while a genuine 0 is never penalised.
"""

import math

import pytest

from banks.services.quality_scoring import (
    CRITICAL_FIELDS,
    ExtractionQuality,
    card_completeness,
    cards_completeness,
    clamp_confidence,
    coalesce_cards,
    coverage_factor,
    invalid_critical_fields,
    is_missing,
    keyword_factor,
    length_factor,
    method_factor,
    missing_critical_fields,
    normalize_missing,
    present_critical_fields,
    score_content,
    score_extraction,
    structure_factor,
)

QUALITY_CONTENT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | "
) * 30


class TestClampConfidence:
    """clamp_confidence is the single guard keeping scores bounded."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (-1.0, 0.0),
            (-0.0001, 0.0),
            (0.0, 0.0),
            (0.5, 0.5),
            (1.0, 1.0),
            (1.5, 1.0),
            (99, 1.0),
            (None, 0.0),
            ("not a number", 0.0),
            (math.nan, 0.0),
        ],
    )
    def test_bounds(self, value, expected):
        assert clamp_confidence(value) == expected

    def test_result_is_always_bounded(self):
        quality = ExtractionQuality(confidence=12.5)
        assert quality.confidence == 1.0
        quality = ExtractionQuality(confidence=-3)
        assert quality.confidence == 0.0


class TestContentScore:
    """score_content combines length, keywords, structure and method."""

    def test_empty_content_is_zero(self):
        assert score_content("", "pdf_text") == 0.0

    @pytest.mark.parametrize("method", ["pdf_text", "ocr", "webpage", "unknown", ""])
    def test_bounds_hold_for_every_method(self, method):
        for content in ("", "short", QUALITY_CONTENT, "x" * 5000):
            score = score_content(content, method)
            assert 0.0 <= score <= 1.0

    def test_long_financial_content_scores_higher_than_noise(self):
        financial = score_content(QUALITY_CONTENT, "pdf_text")
        noise = score_content("lorem ipsum dolor sit amet " * 40, "pdf_text")
        assert financial > noise

    def test_ocr_is_discounted_versus_native_pdf_text(self):
        native = score_content(QUALITY_CONTENT, "pdf_text")
        ocr = score_content(QUALITY_CONTENT, "ocr")
        assert ocr < native

    @pytest.mark.parametrize(
        "content,expected",
        [("", 0.0), ("tiny", 0.4), ("x" * 150, 0.7), ("x" * 700, 0.9), ("x" * 3000, 1.0)],
    )
    def test_length_factor(self, content, expected):
        assert length_factor(content) == expected

    def test_keyword_factor_range(self):
        assert keyword_factor("") == 0.0
        assert keyword_factor(QUALITY_CONTENT) == 1.0
        assert 0.0 <= keyword_factor("annual fee only") <= 1.0

    def test_structure_factor_range(self):
        assert structure_factor("") == 0.0
        assert 0.0 <= structure_factor("table | tk. 5%") <= 1.0

    @pytest.mark.parametrize(
        "method,expected",
        [
            ("pdf_text", 1.0),
            ("webpage", 1.0),
            ("csv", 1.0),
            ("ocr", 0.85),
            ("image_ocr", 0.85),
            ("unknown", 0.9),
            ("something-new", 0.9),
        ],
    )
    def test_method_factor_is_bounded(self, method, expected):
        assert method_factor(method) == expected
        assert 0.0 <= expected <= 1.0

    def test_ocr_method_multiplier_is_lower(self):
        assert method_factor("ocr") < method_factor("pdf_text")


class TestCardCompleteness:
    """Completeness only counts valid normalized numbers."""

    def test_complete_card_scores_one(self):
        card = {"name": "Gold", "annual_fee": 0, "interest_rate_apr": 20.0}
        assert card_completeness(card) == 1.0
        assert present_critical_fields(card) == list(CRITICAL_FIELDS)
        assert missing_critical_fields(card) == []

    def test_missing_card_scores_zero(self):
        card = {"name": "Gold"}
        assert card_completeness(card) == 0.0
        assert missing_critical_fields(card) == list(CRITICAL_FIELDS)

    @pytest.mark.parametrize(
        "annual_fee,apr,expected",
        [
            (None, 20.0, 0.5),
            ("N/A", 20.0, 0.5),
            ("unknown", None, 0.0),
            ("abc", 20.0, 0.5),  # invalid, not missing-but-fine
            (True, 20.0, 0.5),  # boolean is invalid
            (float("nan"), 20.0, 0.5),
            (-5, 20.0, 0.5),
            (0, 0, 1.0),  # genuine zeros count as extracted
            ("Free", 18.0, 1.0),
        ],
    )
    def test_validity_based_completeness(self, annual_fee, apr, expected):
        card = {"name": "X", "annual_fee": annual_fee, "interest_rate_apr": apr}
        assert card_completeness(card) == expected

    def test_invalid_fields_are_reported_separately(self):
        card = {"name": "X", "annual_fee": "abc", "interest_rate_apr": None}
        assert invalid_critical_fields(card) == ["annual_fee"]
        assert sorted(missing_critical_fields(card)) == [
            "annual_fee",
            "interest_rate_apr",
        ]

    def test_cards_completeness_average(self):
        complete = {"annual_fee": 1, "interest_rate_apr": 1}
        half = {"annual_fee": 1, "interest_rate_apr": None}
        assert cards_completeness([complete, half]) == 0.75

    def test_cards_completeness_with_no_cards(self):
        assert cards_completeness([]) == 0.0
        assert cards_completeness(None) == 0.0
        assert cards_completeness(["junk"]) == 0.0


class TestCoverageFactor:
    def test_no_cards_is_zero(self):
        assert coverage_factor([]) == 0.0

    def test_single_card_is_slightly_penalised(self):
        assert coverage_factor([{"name": "a"}]) == 0.9

    def test_multiple_cards_full_coverage(self):
        assert coverage_factor([{"name": "a"}, {"name": "b"}]) == 1.0


class TestScoreExtraction:
    """The final score is the documented product of bounded factors."""

    def test_high_quality_extraction(self):
        cards = [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
        quality = score_extraction(QUALITY_CONTENT, cards, "pdf_text")
        assert 0.8 <= quality.confidence <= 1.0
        assert quality.missing_critical_fields == []
        assert quality.details["content_score"] <= 1.0
        assert quality.details["cards_completeness"] == 1.0

    @pytest.mark.parametrize(
        "content,cards,method",
        [
            ("", [], "pdf_text"),
            ("", [{"name": "x"}], "unknown"),
            (QUALITY_CONTENT, [], "pdf_text"),
            (QUALITY_CONTENT, [{}], "ocr"),
            (QUALITY_CONTENT, [{"name": "x", "annual_fee": "abc"}], "pdf_text"),
            ("short", [{"name": "x", "annual_fee": None}], "ocr"),
        ],
        ids=[
            "empty-no-cards",
            "empty-partial-card",
            "good-no-cards",
            "good-empty-card",
            "good-invalid-fee",
            "short-missing-fee",
        ],
    )
    def test_bounds_hold(self, content, cards, method):
        quality = score_extraction(content, cards, method)
        assert 0.0 <= quality.confidence <= 1.0

    def test_missing_values_are_reported(self):
        cards = [{"name": "Gold", "annual_fee": None, "interest_rate_apr": 20.0}]
        quality = score_extraction(QUALITY_CONTENT, cards, "pdf_text")
        assert quality.missing_critical_fields == ["annual_fee"]
        assert "missing_annual_fee" in quality.issues

    def test_invalid_values_get_their_own_issue_code(self):
        cards = [{"name": "Gold", "annual_fee": "abc", "interest_rate_apr": 20.0}]
        quality = score_extraction(QUALITY_CONTENT, cards, "pdf_text")
        assert "invalid_annual_fee" in quality.issues
        assert "missing_annual_fee" not in quality.issues
        assert quality.missing_critical_fields == ["annual_fee"]

    def test_zero_fee_does_not_create_issues(self):
        cards = [{"name": "Gold", "annual_fee": 0, "interest_rate_apr": 0}]
        quality = score_extraction(QUALITY_CONTENT, cards, "pdf_text")
        assert quality.issues == []
        assert quality.missing_critical_fields == []

    def test_no_content_issue(self):
        quality = score_extraction("", [{"name": "x"}], "pdf_text")
        assert "no_extracted_content" in quality.issues

    def test_no_cards_issue(self):
        quality = score_extraction(QUALITY_CONTENT, [], "pdf_text")
        assert "no_cards_extracted" in quality.issues

    def test_invalid_card_drops_score_below_complete_card(self):
        complete = score_extraction(
            QUALITY_CONTENT,
            [{"name": "a", "annual_fee": 1, "interest_rate_apr": 1}],
            "pdf_text",
        )
        invalid = score_extraction(
            QUALITY_CONTENT,
            [{"name": "a", "annual_fee": "nonsense", "interest_rate_apr": 1}],
            "pdf_text",
        )
        assert invalid.confidence < complete.confidence


class TestManualReviewRules:
    def test_low_confidence_needs_review(self):
        quality = ExtractionQuality(confidence=0.4)
        assert quality.needs_manual_review is True

    def test_high_confidence_single_issue_ok(self):
        quality = ExtractionQuality(confidence=0.9, issues=["missing_annual_fee"])
        assert quality.needs_manual_review is False

    def test_multiple_issues_need_review(self):
        quality = ExtractionQuality(
            confidence=0.9, issues=["missing_annual_fee", "missing_interest_rate_apr"]
        )
        assert quality.needs_manual_review is True


class TestMissingHelpers:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, True),
            ("", True),
            ("N/A", True),
            ("unknown", True),
            ("not mentioned", True),
            (0, False),  # genuine zero is a value
            (0.0, False),
            ("Free", False),
            ("5000", False),
            (False, False),  # present-but-invalid is not "missing"
        ],
    )
    def test_is_missing(self, value, expected):
        assert is_missing(value) is expected

    def test_normalize_missing_keeps_zero(self):
        assert normalize_missing(0) == 0
        assert normalize_missing("unknown") is None


class TestCoalesceCards:
    @pytest.mark.parametrize(
        "payload,expected_count",
        [
            ([{"name": "a"}], 1),
            ({"credit_cards": [{"name": "a"}, {"name": "b"}]}, 2),
            ({"cards": [{"name": "a"}]}, 1),
            ({"data": [{"name": "a"}]}, 1),
            ({"name": "single"}, 1),
            ({"credit_cards": ["junk", {"name": "a"}]}, 1),
            (None, 0),
            ("string", 0),
            (42, 0),
        ],
    )
    def test_variants(self, payload, expected_count):
        assert len(coalesce_cards(payload)) == expected_count
