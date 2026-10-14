"""Tests for ExtractionQualityValidator - the scoring stage used by the crawler."""

from types import SimpleNamespace

import pytest

from banks.factories import CrawledContentFactory
from banks.services.quality_validator import (
    MANUAL_REVIEW_CONFIDENCE_THRESHOLD,
    ExtractionQualityValidator,
)

QUALITY_CONTENT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | "
) * 30

FULL_CARDS = [
    {
        "name": "Gold Card",
        "annual_fee": 5000,
        "interest_rate_apr": 20.0,
    }
]


def stub_content(content=QUALITY_CONTENT, cards=None, method="pdf_text"):
    """Build a lightweight stand-in for CrawledContent (no database needed)."""
    return SimpleNamespace(
        parsed_json={"credit_cards": cards if cards is not None else FULL_CARDS},
        extracted_content=content,
        extraction_method=method,
        missing_critical_fields=[],
        needs_manual_review=False,
        extraction_passes=[],
        quality_scored_at=None,
        id=1,
    )


class TestValidateExtractionQuality:
    """Score without persisting anything."""

    def test_returns_bounded_confidence_and_issues(self):
        confidence, issues = ExtractionQualityValidator.validate_extraction_quality(
            stub_content()
        )
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.8
        assert issues == []

    @pytest.mark.parametrize(
        "content,cards,method",
        [
            ("", [], "pdf_text"),
            ("", FULL_CARDS, "ocr"),
            (QUALITY_CONTENT, [], "pdf_text"),
            (QUALITY_CONTENT, [{"name": "x"}], "webpage"),
            (QUALITY_CONTENT, [{"name": "x", "annual_fee": "abc"}], "pdf_text"),
        ],
        ids=[
            "empty-no-cards",
            "empty-full-cards",
            "good-no-cards",
            "good-partial-card",
            "good-invalid-fee",
        ],
    )
    def test_bounds_hold(self, content, cards, method):
        confidence, _ = ExtractionQualityValidator.validate_extraction_quality(
            stub_content(content=content, cards=cards, method=method)
        )
        assert 0.0 <= confidence <= 1.0

    def test_invalid_value_reported_as_issue(self):
        cards = [{"name": "x", "annual_fee": "bogus", "interest_rate_apr": None}]
        _, issues = ExtractionQualityValidator.validate_extraction_quality(
            stub_content(cards=cards)
        )
        assert "invalid_annual_fee" in issues
        assert "missing_interest_rate_apr" in issues

    def test_zero_fee_is_not_an_issue(self):
        cards = [{"name": "x", "annual_fee": 0, "interest_rate_apr": 20.0}]
        confidence, issues = ExtractionQualityValidator.validate_extraction_quality(
            stub_content(cards=cards)
        )
        assert issues == []
        assert confidence > 0.8


class TestScoreCrawledContent:
    """Score and persist the quality fields on a real record."""

    @pytest.mark.django_db
    def test_persists_confidence_and_fields(self):
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            extraction_method="pdf_text",
            parsed_json={"credit_cards": FULL_CARDS},
        )
        quality = ExtractionQualityValidator.score_crawled_content(content)
        content.refresh_from_db()

        assert 0.0 <= quality.confidence <= 1.0
        assert content.extraction_confidence == quality.confidence
        assert content.quality_scored_at is not None
        assert content.is_scored is True

    @pytest.mark.django_db
    def test_missing_critical_fields_are_stored(self):
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            parsed_json={
                "credit_cards": [
                    {"name": "Gold", "annual_fee": None, "interest_rate_apr": 20.0}
                ]
            },
        )
        ExtractionQualityValidator.score_crawled_content(content)
        content.refresh_from_db()

        assert content.missing_critical_fields == ["annual_fee"]
        assert content.needs_manual_review is True

    @pytest.mark.django_db
    def test_invalid_value_marks_field_missing_and_flags_review(self):
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            parsed_json={
                "credit_cards": [
                    {"name": "Gold", "annual_fee": "abc", "interest_rate_apr": 20.0}
                ]
            },
        )
        quality = ExtractionQualityValidator.score_crawled_content(content)
        content.refresh_from_db()

        assert "annual_fee" in content.missing_critical_fields
        assert "invalid_annual_fee" in quality.issues
        assert content.needs_manual_review is True

    @pytest.mark.django_db
    def test_zero_fee_is_not_flagged_missing(self):
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            parsed_json={
                "credit_cards": [
                    {"name": "Free Card", "annual_fee": 0, "interest_rate_apr": 0}
                ]
            },
        )
        ExtractionQualityValidator.score_crawled_content(content)
        content.refresh_from_db()

        assert content.missing_critical_fields == []
        assert content.needs_manual_review is False
        assert content.extraction_confidence > 0.8

    @pytest.mark.django_db
    def test_extraction_passes_are_stored_as_provenance(self):
        passes = [
            {"pass": "standard", "provider": "fake", "cards_found": 1, "confidence": 0.7},
            {"pass": "validation", "provider": None, "cards_found": 1, "confidence": 0.8},
        ]
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            parsed_json={"credit_cards": FULL_CARDS},
        )
        quality = ExtractionQualityValidator.score_crawled_content(
            content, extraction_passes=passes
        )
        content.refresh_from_db()

        assert len(content.extraction_passes) == 2
        assert quality.passes == passes

    @pytest.mark.django_db
    def test_cards_can_be_passed_explicitly(self):
        """The crawler scores the validated cards, not the raw payload."""
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            parsed_json={"credit_cards": [{"name": "raw", "annual_fee": "TK 5,000"}]},
        )
        quality = ExtractionQualityValidator.score_crawled_content(
            content,
            cards=[{"name": "v", "annual_fee": 5000.0, "interest_rate_apr": 20.0}],
        )
        assert quality.missing_critical_fields == []

    @pytest.mark.django_db
    def test_unparsed_record_scores_zero(self):
        content = CrawledContentFactory(
            extracted_content="", parsed_json={}, extraction_method="pdf_text"
        )
        quality = ExtractionQualityValidator.score_crawled_content(content)
        assert quality.confidence == 0.0
        content.refresh_from_db()
        assert content.needs_manual_review is True

    @pytest.mark.django_db
    def test_ocr_content_scores_lower_than_pdf_text(self):
        pdf_content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            extraction_method="pdf_text",
            parsed_json={"credit_cards": FULL_CARDS},
        )
        ocr_content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            extraction_method="ocr",
            parsed_json={"credit_cards": FULL_CARDS},
        )
        pdf_quality = ExtractionQualityValidator.score_crawled_content(pdf_content)
        ocr_quality = ExtractionQualityValidator.score_crawled_content(ocr_content)
        assert ocr_quality.confidence < pdf_quality.confidence


class TestManualReviewDecision:
    @pytest.mark.parametrize(
        "confidence,issues,expected",
        [
            (0.0, [], True),
            (MANUAL_REVIEW_CONFIDENCE_THRESHOLD - 0.01, [], True),
            (MANUAL_REVIEW_CONFIDENCE_THRESHOLD, [], False),
            (0.9, [], False),
            (0.9, ["a"], False),
            (0.9, ["a", "b"], True),
        ],
    )
    def test_rules(self, confidence, issues, expected):
        assert (
            ExtractionQualityValidator.needs_manual_review(confidence, issues) is expected
        )

    def test_none_issues_treated_as_empty(self):
        assert ExtractionQualityValidator.needs_manual_review(0.9, None) is False


@pytest.mark.django_db
class TestQualitySummary:
    def test_summary_keys_and_bounds(self):
        content = CrawledContentFactory(
            extracted_content=QUALITY_CONTENT,
            extraction_method="pdf_text",
            parsed_json={"credit_cards": FULL_CARDS},
        )
        ExtractionQualityValidator.score_crawled_content(content)
        summary = ExtractionQualityValidator.quality_summary(content)

        assert set(summary) == {
            "extraction_confidence",
            "missing_critical_fields",
            "extraction_method",
            "needs_manual_review",
            "extraction_passes",
            "invalid_reasons",
            "quality_scored_at",
        }
        assert 0.0 <= summary["extraction_confidence"] <= 1.0
        assert summary["extraction_method"] == "pdf_text"
        assert summary["quality_scored_at"] is not None
