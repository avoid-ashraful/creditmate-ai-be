"""Tests for the quality fields added to CrawledContent (Phase 2.4).

Covers field definitions/defaults, bounded confidence clamping, the manual
review flag and the persisted provenance (method, passes, scoring timestamp).
"""

import pytest

from banks.factories import CrawledContentFactory


QUALITY_FIELDS = (
    "extraction_confidence",
    "missing_critical_fields",
    "extraction_method",
    "needs_manual_review",
    "extraction_passes",
    "quality_scored_at",
)


@pytest.mark.django_db
class TestQualityFieldDefinitions:
    """The new columns must exist with the documented types and defaults."""

    @pytest.mark.parametrize("field_name", QUALITY_FIELDS)
    def test_field_exists(self, field_name):
        from banks.models import CrawledContent

        field = CrawledContent._meta.get_field(field_name)
        assert field is not None

    def test_confidence_is_nullable_float(self):
        from banks.models import CrawledContent

        field = CrawledContent._meta.get_field("extraction_confidence")
        assert field.null is True
        assert field.get_internal_type() == "FloatField"

    def test_json_fields_have_list_defaults(self):
        from banks.models import CrawledContent

        for name in ("missing_critical_fields", "extraction_passes"):
            field = CrawledContent._meta.get_field(name)
            assert field.default is list

    def test_review_flag_defaults_false(self):
        from banks.models import CrawledContent

        assert CrawledContent._meta.get_field("needs_manual_review").default is False

    def test_new_record_starts_unscored(self):
        content = CrawledContentFactory()
        assert content.extraction_confidence is None
        assert content.is_scored is False
        assert content.is_low_confidence is False
        assert content.missing_critical_fields == []
        assert content.extraction_passes == []
        assert content.quality_scored_at is None
        assert content.needs_manual_review is False
        assert content.extraction_method == ""

    def test_fields_persist_to_database(self):
        content = CrawledContentFactory(extraction_method="pdf_text")
        content.apply_quality_score(
            confidence=0.72,
            missing_critical_fields=["annual_fee"],
            extraction_passes=[{"pass": "standard", "confidence": 0.7}],
        )
        content.save()
        content.refresh_from_db()

        assert content.extraction_confidence == 0.72
        assert content.missing_critical_fields == ["annual_fee"]
        assert content.extraction_passes[0]["pass"] == "standard"
        assert content.quality_scored_at is not None
        assert content.is_scored is True


@pytest.mark.django_db
class TestApplyQualityScore:
    """apply_quality_score stores bounded values and stamps the scoring time."""

    @pytest.mark.parametrize(
        "raw,expected",
        [(-5.0, 0.0), (0.0, 0.0), (0.42, 0.42), (1.0, 1.0), (3.7, 1.0)],
    )
    def test_confidence_is_clamped(self, raw, expected):
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=raw)
        content.save()
        content.refresh_from_db()
        assert content.extraction_confidence == expected

    def test_none_confidence_keeps_record_unscored(self):
        """None means "not scored yet" and must stay NULL, unlike 0.0."""
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=None)
        assert content.extraction_confidence is None
        assert content.is_scored is False

    @pytest.mark.parametrize(
        "confidence,expected_review",
        [(0.2, True), (0.49, True), (0.5, False), (0.95, False)],
    )
    def test_review_flag_derived_from_confidence(self, confidence, expected_review):
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=confidence)
        assert content.needs_manual_review is expected_review

    def test_explicit_review_flag_wins(self):
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=0.99, needs_manual_review=True)
        assert content.needs_manual_review is True

    def test_passes_are_replaced_not_appended(self):
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=0.8, extraction_passes=[{"pass": "a"}])
        content.apply_quality_score(confidence=0.8, extraction_passes=[{"pass": "b"}])
        assert len(content.extraction_passes) == 1
        assert content.extraction_passes[0]["pass"] == "b"

    def test_scoring_timestamp_is_set(self):
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=0.5)
        assert content.quality_scored_at is not None

    def test_is_low_confidence_flag(self):
        content = CrawledContentFactory()
        content.apply_quality_score(confidence=0.3)
        assert content.is_low_confidence is True
        content.apply_quality_score(confidence=0.9)
        assert content.is_low_confidence is False
