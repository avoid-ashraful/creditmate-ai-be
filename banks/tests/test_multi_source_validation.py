"""Unit tests for the deterministic multi-source validation service.

Covers agreement (with confidence boost), disagreement (manual-review
flagging), duplicate / same-source independence, missing fields, explicit
units/normalization, zero-versus-missing, strict card separation and the
JSON-safe serialization used by the crawler.
"""

import pytest

from banks.enums import SourceType
from banks.services.multi_source_validation import (
    STATUS_AGREEMENT,
    STATUS_CONFLICT,
    STATUS_NO_DATA,
    STATUS_SINGLE_SOURCE,
    MultiSourceValidator,
    Observation,
    batch_summary,
    field_validation_to_dict,
    normalize_observation,
)


def obs(
    field="annual_fee",
    value=None,
    source_type=SourceType.BANK_WEBSITE,
    source_key="https://bank.example/products",
    card_key="Gold",
    bank_key="Acme Bank",
    confidence=None,
    unit=None,
):
    """Build an observation with sensible defaults for tests."""
    return Observation(
        field=field,
        value=value,
        source_type=source_type,
        source_key=source_key,
        card_key=card_key,
        bank_key=bank_key,
        confidence=confidence,
        unit=unit,
    )


def card_field(batch, card_key="Gold", field="annual_fee"):
    """Pull one FieldValidation out of a ValidationBatch by normalized key."""
    normalized = " ".join(card_key.lower().split())
    card = next(card for card in batch.cards if card.card_key == normalized)
    return card.fields[field]


class TestAgreement:
    """Independent sources reporting the same value agree and boost confidence."""

    @pytest.mark.parametrize(
        "confidences",
        [
            [None, None, None],
            [0.6, 0.7, 0.4],
            [0.9, 0.9, 0.9],
        ],
    )
    def test_independent_agreement_boosts_confidence(self, confidences):
        sources = [
            (SourceType.BANK_WEBSITE, "https://bank.example/products"),
            (SourceType.BANK_PDF, "https://bank.example/schedule-of-charges.pdf"),
            (SourceType.USER_SUBMISSION, "submission-42"),
        ]
        observations = [
            obs(
                source_type=source_type,
                source_key=source_key,
                value=5000,
                confidence=confidence,
            )
            for (source_type, source_key), confidence in zip(sources, confidences)
        ]
        result = MultiSourceValidator().validate(observations)
        field = card_field(result)
        assert field.status == STATUS_AGREEMENT
        assert field.agreed_value == 5000
        assert field.independent_source_count == 3
        assert field.confidence_boost > 0
        assert field.validated_confidence > field.base_confidence
        assert field.needs_manual_review is False
        assert field.conflicts == []
        assert field.validated_confidence <= 1.0

    def test_boost_grows_with_more_independent_sources(self):
        validate = MultiSourceValidator().validate
        one = validate([obs(value=5000, confidence=0.5, source_key="a")])
        two = validate(
            [obs(value=5000, confidence=0.5, source_key="a"),
             obs(value=5000, confidence=0.5, source_key="b")]
        )
        three = validate(
            [obs(value=5000, confidence=0.5, source_key="a"),
             obs(value=5000, confidence=0.5, source_key="b"),
             obs(value=5000, confidence=0.5, source_key="c")]
        )
        assert card_field(three).validated_confidence > card_field(two).validated_confidence
        assert card_field(two).validated_confidence > card_field(one).validated_confidence

    def test_bank_website_and_pdf_agree(self):
        """The acceptance scenario: bank website + PDF + user submission."""
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_type=SourceType.BANK_WEBSITE, source_key="web-url"),
                obs(value=5000, source_type=SourceType.BANK_PDF, source_key="pdf-url"),
                obs(value=5000, source_type=SourceType.USER_SUBMISSION, source_key="sub-1"),
            ]
        )
        batch_field = card_field(batch)
        assert batch_field.status == STATUS_AGREEMENT
        assert batch_field.source_type_counts == {
            SourceType.BANK_WEBSITE: 1,
            SourceType.BANK_PDF: 1,
            SourceType.USER_SUBMISSION: 1,
        }
        assert batch.needs_manual_review is False


class TestDisagreement:
    """Independent sources reporting different values conflict and flag review."""

    def test_conflict_flags_manual_review(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="web-url"),
                obs(value=6000, source_key="pdf-url"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_CONFLICT
        assert field.validated_confidence is None
        assert field.confidence_boost == 0
        assert field.needs_manual_review is True
        assert batch.needs_manual_review is True
        assert batch.conflict_field_count == 1
        values = {conflict["value"] for conflict in field.conflicts}
        assert values == {5000, 6000}

    def test_majority_does_not_silently_win(self):
        """Two sources agreeing must not outvote a third disagreeing one."""
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="a"),
                obs(value=5000, source_key="b"),
                obs(value=7000, source_key="c"),
            ]
        )
        assert card_field(batch).status == STATUS_CONFLICT
        assert batch.needs_manual_review is True

    def test_conflict_only_between_valid_values(self):
        """Missing/invalid values on one side are not evidence and never
        manufacture a conflict against a valid value."""
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="web-url", confidence=0.8),
                obs(value=None, source_key="pdf-url"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_SINGLE_SOURCE
        assert field.needs_manual_review is False
        assert field.agreed_value == 5000


class TestSameSourceIndependence:
    """Duplicates of one concrete source never count as multiple sources."""

    def test_duplicate_observations_are_a_single_source(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="web-url", confidence=0.5),
                obs(value=5000, source_key="web-url", confidence=0.9),
                obs(value=5000, source_key="web-url", confidence=0.7),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_SINGLE_SOURCE
        assert field.independent_source_count == 1
        assert field.base_confidence == 0.9
        assert field.validated_confidence == 0.9  # best single source, no boost
        assert field.confidence_boost == 0

    def test_same_source_different_values_is_an_inconsistency(self):
        """One source reporting two different values is unreliable and flags
        manual review; it does not produce an agreement boost with itself."""
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="web-url", confidence=0.8),
                obs(value=6000, source_key="web-url", confidence=0.8),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_NO_DATA
        assert field.inconsistent_sources == ["web-url"]
        assert field.needs_manual_review is True
        assert field.validated_confidence is None

    def test_inconsistent_source_is_not_trusted_for_agreement(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="web-url", confidence=0.8),
                obs(value=6000, source_key="web-url", confidence=0.8),
                obs(value=5000, source_key="pdf-url", confidence=0.8),
            ]
        )
        field = card_field(batch)
        assert field.independent_source_count == 1  # only the PDF is trusted
        assert field.status == STATUS_SINGLE_SOURCE
        assert field.needs_manual_review is True  # inconsistency still flags


class TestMissingFields:
    """Missing data never becomes zero and never creates conflicts."""

    def test_all_missing_is_no_data(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=None, source_key="a"),
                obs(value="N/A", source_key="b"),
                obs(value="", source_key="c"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_NO_DATA
        assert field.validated_confidence is None
        assert field.agreed_value is None
        assert field.needs_manual_review is False

    def test_zero_is_a_real_value_not_missing(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=0, source_key="a"),
                obs(value="Free", source_key="b"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_AGREEMENT
        assert field.agreed_value == 0
        assert field.validated_confidence is not None


class TestNormalization:
    """Values that mean the same thing normalize to the same token."""

    def test_currency_string_and_number_agree(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value="TK 5,000", source_key="web-url"),
                obs(value=5000.0, source_key="pdf-url"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_AGREEMENT
        assert field.agreed_value == 5000.0

    def test_apr_percentage_and_number_agree(self):
        batch = MultiSourceValidator().validate(
            [
                obs(field="interest_rate_apr", value="18.99% p.a.", source_key="web-url"),
                obs(field="interest_rate_apr", value=18.99, source_key="pdf-url"),
            ]
        )
        field = card_field(batch, field="interest_rate_apr")
        assert field.status == STATUS_AGREEMENT
        assert field.agreed_value == 18.99

    def test_foreign_currency_is_invalid_not_a_conflict(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value="USD 95", source_key="web-url"),
                obs(value=95, source_key="pdf-url"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_SINGLE_SOURCE
        assert field.agreed_value == 95
        assert field.needs_manual_review is False
        web_record = next(
            record
            for record in field.observations
            if record.source_key == "web-url"
        )
        assert web_record.status == "invalid"
        assert web_record.reason == "foreign_currency"

    def test_explicit_unit_mismatch_excludes_observation(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=95, source_key="web-url", unit="usd"),
                obs(value=95, source_key="pdf-url"),
            ]
        )
        field = card_field(batch)
        assert field.status == STATUS_SINGLE_SOURCE
        usd_record = next(
            record
            for record in field.observations
            if record.source_key == "web-url"
        )
        assert usd_record.reason == "unit_mismatch"

    def test_non_critical_text_field_compares_canonical_text(self):
        batch = MultiSourceValidator().validate(
            [
                obs(field="lounge_access_international", value=" 2 visits ", source_key="a"),
                obs(field="lounge_access_international", value="2 VISITS", source_key="b"),
            ]
        )
        field = card_field(batch, field="lounge_access_international")
        assert field.status == STATUS_AGREEMENT
        assert field.agreed_value == "2 visits"


class TestCardSeparation:
    """Observations for different cards are never merged or cross-checked."""

    def test_unrelated_cards_validate_separately(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="a", card_key="Gold"),
                obs(value=6000, source_key="b", card_key="Gold"),
                obs(value=1000, source_key="a", card_key="Platinum"),
                obs(value=1000, source_key="b", card_key="Platinum"),
            ]
        )
        assert {card.card_key for card in batch.cards} == {"gold", "platinum"}
        assert card_field(batch, "Gold").status == STATUS_CONFLICT
        assert card_field(batch, "Platinum").status == STATUS_AGREEMENT

    def test_different_banks_never_merge(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="a", bank_key="Acme Bank", card_key="Gold"),
                obs(value=6000, source_key="b", bank_key="Other Bank", card_key="Gold"),
            ]
        )
        assert len(batch.cards) == 2
        assert batch.needs_manual_review is False

    def test_unattributable_observation_is_ignored(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="a", card_key="Gold"),
                obs(value=6000, source_key="b", card_key=""),
            ]
        )
        assert batch.ignored_observations == 1
        assert card_field(batch).status == STATUS_SINGLE_SOURCE


class TestDeterminism:
    """Same observations in any order produce identical results."""

    def test_input_order_does_not_change_outcome(self):
        observations = [
            obs(value=5000, source_key="a", confidence=0.6),
            obs(value=5000, source_key="b", confidence=0.7),
            obs(value=5000, source_key="c", confidence=0.4),
        ]
        forward = MultiSourceValidator().validate(observations)
        backward = MultiSourceValidator().validate(list(reversed(observations)))
        assert field_validation_to_dict(card_field(forward)) == field_validation_to_dict(
            card_field(backward)
        )


class TestSerialization:
    """The stored summary is JSON-safe and carries full provenance."""

    def test_batch_summary_is_json_safe(self):
        import json

        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="a"),
                obs(value=5000, source_key="b"),
            ]
        )
        summary = batch_summary(batch)
        json.dumps(summary)  # must not raise
        assert summary["needs_manual_review"] is False
        assert summary["conflict_field_count"] == 0
        fields = summary["cards"][0]["fields"]
        assert fields["annual_fee"]["status"] == STATUS_AGREEMENT
        assert fields["annual_fee"]["confidence_boost"] > 0

    def test_conflict_summary_lists_offending_values(self):
        batch = MultiSourceValidator().validate(
            [
                obs(value=5000, source_key="a"),
                obs(value=6000, source_key="b"),
                obs(value=5000, source_key="c", card_key="Platinum"),
            ]
        )
        summary = batch_summary(batch)
        assert summary["needs_manual_review"] is True
        assert summary["conflict_field_count"] == 1


class TestNormalizationHelper:
    """normalize_observation keeps units and zero-versus-missing explicit."""

    def test_missing_marker_stays_missing(self):
        value, status, _ = normalize_observation("annual_fee", "N/A")
        assert value is None
        assert status == "missing"

    def test_zero_stays_zero(self):
        value, status, _ = normalize_observation("annual_fee", 0)
        assert value == 0.0
        assert status == "valid"

    def test_free_wording_is_genuine_zero(self):
        value, status, _ = normalize_observation("annual_fee", "Free")
        assert value == 0.0
        assert status == "valid"

    def test_foreign_currency_rejected(self):
        value, status, _ = normalize_observation("annual_fee", "$95")
        assert value is None
        assert status == "invalid"

    def test_monthly_period_rejected(self):
        value, status, _ = normalize_observation("interest_rate_apr", "2% per month")
        assert value is None
        assert status == "invalid"

    def test_matching_unit_accepted(self):
        value, status, _ = normalize_observation("annual_fee", 95, unit="bdt")
        assert value == 95.0
        assert status == "valid"
