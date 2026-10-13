"""Deterministic multi-source validation of credit-card observations.

Task 2.4 (Multi-Source Validation). Compares *observations* - one value for one
credit-card field read from one concrete source - that come from independent
places (the bank's website, a bank PDF / schedule of charges, user
submissions) for the **same card and field**, and decides whether they agree,
whether they conflict, and what the field's confidence becomes.

Design rules (all deterministic and unit-tested):

* **Never merge unrelated cards.** Observations are grouped by
  ``(bank_key, card_key)``; a missing card identity keeps an observation out of
  every group instead of merging it into a generic bucket.
* **Never turn missing data into zero.** Missing markers (``None``, ``""``,
  ``"N/A"``, ``"unknown"``, ...) and invalid values (malformed strings,
  foreign currency, non-annual periods, conditional waivers, out-of-range
  numbers) are **not evidence**: they neither agree nor conflict, and they are
  never normalised to ``0``. A genuine ``0`` is a real value and remains one.
* **Independence is decided per concrete source.** Two observations are
  *independent* when their ``source_key`` differ (e.g. two bank URLs, or a
  bank URL and a user submission). Duplicates of the same source never count
  twice and never produce a boost. A single source that internally reports two
  different values is flagged as an inconsistency and its evidence is not
  trusted.
* **Units/normalization are explicit.** Critical numeric fields
  (``annual_fee``, ``interest_rate_apr``) reuse the shared normalization rules
  in ``banks.validators.numeric_fields`` (BDT amounts, annual rates, explicit
  rejection reasons). Observations that declare a unit other than the
  field's expected unit are excluded as incompatible, never compared.
* **Confidence only rises from independent agreement.** With one independent
  source the validated confidence is the source's own confidence. With two or
  more independent sources that agree, the confidence is combined with the
  noisy-OR rule ``1 - product(1 - c_i)``, which is monotone in the number of
  agreeing sources, bounded in ``0.0 - 1.0`` and never lowers the best single
  source. On a conflict no value is accepted (``validated_confidence`` is
  ``None``) and the field is flagged for manual review.

The module is intentionally pure (no Django imports) so every rule can run and
be tested without a database. The Django-aware collectors that turn
``CrawledContent`` rows and user-submission payloads into observations live in
``banks.services.validation_collectors``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, List, Optional

from banks.enums import SourceType
from banks.services.quality_scoring import clamp_confidence
from banks.validators.numeric_fields import (
    CRITICAL_FIELDS,
    REASON_BOOLEAN,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_VALID,
    is_missing_marker,
    parse_numeric_value_detailed,
)

#: No usable, independent evidence exists for a field.
STATUS_NO_DATA = "no_data"
#: Exactly one independent source contributed a usable value.
STATUS_SINGLE_SOURCE = "single_source"
#: Two or more independent sources reported the same normalized value.
STATUS_AGREEMENT = "agreement"
#: Two or more independent sources reported different normalized values.
STATUS_CONFLICT = "conflict"

#: Observable fields collected from crawled content. Everything else in a card
#: dict (reward policy prose, waiver policy objects, ...) is left out of
#: cross-source comparison because free-text fields cannot be compared safely.
VALIDATED_FIELDS = CRITICAL_FIELDS + (
    "lounge_access_international",
    "lounge_access_domestic",
    "lounge_access_condition",
    "cash_advance_fee",
    "late_payment_fee",
)

#: Explicit expected unit for critical numeric fields. Units are metadata on an
#: observation; when a caller declares one that does not match, the
#: observation is excluded as incompatible instead of being compared as equal.
FIELD_UNITS = {
    "annual_fee": "bdt",
    "interest_rate_apr": "percent_per_year",
}

#: Documented default confidence used when an observation carries none. These
#: keep the service deterministic without pretending every source is equally
#: reliable: user submissions start lower than bank publications.
SOURCE_DEFAULT_CONFIDENCE = {
    SourceType.BANK_WEBSITE: 0.6,
    SourceType.BANK_PDF: 0.6,
    SourceType.BANK_CSV: 0.6,
    SourceType.BANK_IMAGE: 0.5,
    SourceType.USER_SUBMISSION: 0.4,
}
DEFAULT_SOURCE_CONFIDENCE = 0.4

#: Machine-readable rejection reason for a unit that does not match the field.
REASON_UNIT_MISMATCH = "unit_mismatch"


@dataclass(frozen=True)
class Observation:
    """One value for one credit-card field read from one concrete source.

    Attributes
    ----------
    field : str
        Credit-card field name (``annual_fee``, ``interest_rate_apr``, ...).
    value : any
        Raw value exactly as read from the source.
    source_type : str
        Broad origin class (``banks.enums.SourceType`` value).
    source_key : str
        Stable identity of the concrete source (e.g. the data source URL, or a
        submission id). Independence is decided on this key.
    card_key : str
        Normalized identity of the credit card (bank + card name) the
        observation belongs to. Observations without one are not grouped.
    bank_key : str, optional
        Normalized bank identity, used with ``card_key`` for strict grouping.
    confidence : float, optional
        Reliability of this observation in ``0.0 - 1.0``. When omitted the
        per-``source_type`` default applies.
    unit : str, optional
        Optional explicit unit metadata (``"bdt"``, ``"usd"``,
        ``"percent_per_year"``, ...). Mismatches against the field's expected
        unit exclude the observation.
    """

    field: str
    value: Any
    source_type: str = SourceType.USER_SUBMISSION
    source_key: str = ""
    card_key: str = ""
    bank_key: str = ""
    confidence: Optional[float] = None
    unit: Optional[str] = None


@dataclass
class ObservationResult:
    """Normalized result of one observation inside a field comparison."""

    source_key: str
    source_type: str
    raw_value: Any
    normalized_value: Any
    status: str = STATUS_MISSING
    reason: Optional[str] = None
    confidence: float = 0.0


@dataclass
class FieldValidation:
    """Outcome of comparing all observations for one card/field."""

    card_key: str
    bank_key: str
    field: str
    status: str = STATUS_NO_DATA
    agreed_value: Any = None
    base_confidence: Optional[float] = None
    validated_confidence: Optional[float] = None
    confidence_boost: float = 0.0
    independent_source_count: int = 0
    source_type_counts: Dict[str, int] = dataclass_field(default_factory=dict)
    observations: List[ObservationResult] = dataclass_field(default_factory=list)
    conflicts: List[Dict[str, Any]] = dataclass_field(default_factory=list)
    inconsistent_sources: List[str] = dataclass_field(default_factory=list)
    reasons: List[str] = dataclass_field(default_factory=list)

    @property
    def needs_manual_review(self) -> bool:
        """True when a real conflict (or same-source inconsistency) exists."""
        return self.status == STATUS_CONFLICT or bool(self.inconsistent_sources)


@dataclass
class CardValidation:
    """All field comparisons for one credit card."""

    card_key: str
    bank_key: str
    fields: Dict[str, FieldValidation] = dataclass_field(default_factory=dict)

    @property
    def needs_manual_review(self) -> bool:
        """True when any field of the card needs manual review."""
        return any(result.needs_manual_review for result in self.fields.values())

    @property
    def conflict_fields(self) -> List[str]:
        """Field names whose independent sources disagreed."""
        return sorted(
            name
            for name, result in self.fields.items()
            if result.status == STATUS_CONFLICT
        )


@dataclass
class ValidationBatch:
    """All card validations produced from one set of observations."""

    cards: List[CardValidation] = dataclass_field(default_factory=list)
    ignored_observations: int = 0

    @property
    def needs_manual_review(self) -> bool:
        """True when any card shows a real conflict or inconsistency."""
        return any(card.needs_manual_review for card in self.cards)

    @property
    def conflict_field_count(self) -> int:
        """Number of fields across all cards with independent disagreements."""
        return sum(len(card.conflict_fields) for card in self.cards)

    @property
    def has_comparison(self) -> bool:
        """True when any field was actually cross-checked.

        A comparison exists when at least two independent sources agree on a
        value, or a conflict / same-source inconsistency was found. A batch of
        only single-source (or all-missing) fields carries no cross-source
        information, so callers may skip persisting an empty report for it.
        """
        return any(
            result.independent_source_count >= 2
            or bool(result.conflicts)
            or bool(result.inconsistent_sources)
            for card in self.cards
            for result in card.fields.values()
        )


def default_confidence(source_type) -> float:
    """Return the documented default confidence for a source type."""
    return SOURCE_DEFAULT_CONFIDENCE.get(source_type, DEFAULT_SOURCE_CONFIDENCE)


def normalize_observation(field, value, unit=None):
    """Normalize one raw value for a field into ``(value, status, reason)``.

    Critical numeric fields reuse ``parse_numeric_value_detailed`` so unit,
    period and waiver safety rules stay in one place. Other fields are
    compared as canonical text. An explicitly declared unit that differs from
    the field's expected unit excludes the value (``unit_mismatch``).
    """
    expected_unit = FIELD_UNITS.get(field)
    if expected_unit is not None and unit is not None:
        if str(unit).strip().lower() != expected_unit:
            return None, STATUS_INVALID, REASON_UNIT_MISMATCH
    if field in CRITICAL_FIELDS:
        number, status, reason = parse_numeric_value_detailed(value, field)
        return number, status, reason
    return _normalize_text_value(value)


def _normalize_text_value(value):
    """Normalize a non-critical value to canonical text for comparison."""
    if isinstance(value, bool):
        return None, STATUS_INVALID, REASON_BOOLEAN
    if is_missing_marker(value) or value is None:
        return None, STATUS_MISSING, None
    text = " ".join(str(value).strip().lower().split())
    if not text:
        return None, STATUS_MISSING, None
    return text, STATUS_VALID, None


def _normalize_key(value) -> str:
    """Normalize a group key (bank/card identity) for exact matching."""
    if value is None:
        return ""
    return " ".join(str(value).lower().split())


def _observation_confidence(observation) -> float:
    """Return the bounded confidence of one observation (defaults included)."""
    if observation.confidence is None:
        return clamp_confidence(default_confidence(observation.source_type))
    return clamp_confidence(observation.confidence)


def _combine_agreeing_sources(confidences) -> float:
    """Combine independent agreeing source confidences with noisy-OR.

    ``1 - product(1 - c_i)`` is monotone in every ``c_i``, bounded in
    ``0.0 - 1.0`` and never smaller than the largest input, so agreement can
    only raise confidence and the boost is always explainable.
    """
    remaining = 1.0
    for value in confidences:
        remaining *= 1.0 - clamp_confidence(value)
    return clamp_confidence(1.0 - remaining)


class MultiSourceValidator:
    """Deterministic validation of credit-card observations."""

    def validate(self, observations) -> ValidationBatch:
        """Validate a mixed list of observations, grouped by card identity.

        Grouping is strict on ``(bank_key, card_key)`` - two different cards
        are never compared against each other - and observations without a
        usable card identity are counted as ignored instead of merged.

        Parameters
        ----------
        observations : list of Observation
            Observations to validate.

        Returns
        -------
        ValidationBatch
            One :class:`CardValidation` per distinct card, plus the count of
            ignored (unattributable) observations.
        """
        groups: Dict[tuple, List[Observation]] = {}
        ignored = 0
        for observation in observations if observations else []:
            bank_key = _normalize_key(getattr(observation, "bank_key", ""))
            card_key = _normalize_key(getattr(observation, "card_key", ""))
            if not card_key:
                # Never merge unattributable observations into a card group.
                ignored += 1
                continue
            groups.setdefault((bank_key, card_key), []).append(observation)

        cards = []
        for (bank_key, card_key), group in sorted(groups.items()):
            cards.append(self._validate_card(card_key, bank_key, group))
        return ValidationBatch(cards=cards, ignored_observations=ignored)

    def validate_card(self, observations) -> CardValidation:
        """Validate observations that all belong to one credit card.

        The card identity is taken from the first observation; callers that
        need strict grouping should use :meth:`validate` instead.
        """
        if not observations:
            return CardValidation(card_key="", bank_key="")
        first = observations[0]
        bank_key = _normalize_key(getattr(first, "bank_key", ""))
        card_key = _normalize_key(getattr(first, "card_key", ""))
        return self._validate_card(card_key, bank_key, observations)

    def _validate_card(self, card_key, bank_key, observations) -> CardValidation:
        by_field: Dict[str, List[Observation]] = {}
        for observation in observations:
            by_field.setdefault(observation.field, []).append(observation)
        fields = {}
        for field in sorted(by_field):
            fields[field] = self.validate_field(card_key, bank_key, by_field[field])
        return CardValidation(card_key=card_key, bank_key=bank_key, fields=fields)

    def validate_field(self, card_key, bank_key, observations) -> FieldValidation:
        """Validate every observation for one card/field.

        Rules (see module docstring): duplicate/same-source observations are
        collapsed per concrete source; a single source reporting two different
        values is an inconsistency and its evidence is not trusted; missing and
        invalid values are never evidence; independent agreeing sources boost
        confidence; independent disagreeing sources flag manual review.
        """
        result = FieldValidation(
            card_key=card_key,
            bank_key=bank_key,
            field=observations[0].field if observations else "",
        )
        if not observations:
            result.reasons.append("no_observations")
            return result

        normalized = self._normalize_all(result, observations)

        representatives, inconsistent = self._source_representatives(normalized)

        result.inconsistent_sources = sorted(inconsistent)
        if result.inconsistent_sources:
            result.reasons.append(
                "source_inconsistency: " + ", ".join(result.inconsistent_sources)
            )

        result.independent_source_count = len(representatives)
        result.source_type_counts = self._count_source_types(
            representatives, observations
        )

        if not representatives:
            result.status = STATUS_NO_DATA
            result.reasons.append("no_valid_evidence")
            return result

        base = max(item["confidence"] for item in representatives)
        result.base_confidence = base

        distinct_values = sorted(
            {item["value"] for item in representatives}, key=repr
        )
        if len(distinct_values) == 1:
            if len(representatives) == 1:
                result.status = STATUS_SINGLE_SOURCE
                result.reasons.append("single_independent_source")
            else:
                result.status = STATUS_AGREEMENT
                result.reasons.append("independent_agreement")
            result.agreed_value = distinct_values[0]
            if result.status == STATUS_AGREEMENT:
                combined = _combine_agreeing_sources(
                    [item["confidence"] for item in representatives]
                )
                result.validated_confidence = combined
                result.confidence_boost = round(combined - base, 4)
            else:
                result.validated_confidence = base
            return result

        result.status = STATUS_CONFLICT
        result.validated_confidence = None
        result.reasons.append("independent_conflict")
        self._build_conflicts(result, representatives)
        return result

    @staticmethod
    def _source_representatives(normalized) -> List[Dict[str, Any]]:
        """Collapse observations per concrete source.

        Returns ``(representatives, inconsistent_sources)``: one best valid
        value per source plus the list of sources that reported two distinct
        valid values (whose evidence is not trusted).
        """
        representatives: List[Dict[str, Any]] = []
        inconsistent: List[str] = []
        for source_key in sorted({obs.source_key for obs in normalized}):
            group = [obs for obs in normalized if obs.source_key == source_key]
            valid = [obs for obs in group if obs.status == STATUS_VALID]
            if not valid:
                continue
            distinct = sorted({obs.normalized_value for obs in valid})
            if len(distinct) > 1:
                inconsistent.append(source_key)
                continue
            best = max(valid, key=lambda obs: (obs.confidence, obs.source_key))
            representatives.append(
                {
                    "source_key": source_key,
                    "source_type": best.source_type,
                    "value": best.normalized_value,
                    "confidence": best.confidence,
                }
            )
        return representatives, inconsistent

    def _normalize_all(self, result, observations) -> List[ObservationResult]:
        """Normalize every observation and record provenance on the result."""
        normalized = []
        for observation in sorted(
            observations,
            key=lambda obs: (obs.source_key, _observation_confidence(obs)),
        ):
            value, status, reason = normalize_observation(
                observation.field,
                observation.value,
                getattr(observation, "unit", None),
            )
            record = ObservationResult(
                source_key=observation.source_key,
                source_type=observation.source_type,
                raw_value=observation.value,
                normalized_value=value,
                status=status,
                reason=reason,
                confidence=_observation_confidence(observation),
            )
            normalized.append(record)
            result.observations.append(record)
        return normalized

    @staticmethod
    def _count_source_types(representatives, observations) -> Dict[str, int]:
        """Count independent **valid** evidence by broad source type.

        Only representatives (sources with usable evidence) count, so the
        mapping sums to ``independent_source_count``.
        """
        counts: Dict[str, int] = {}
        for item in representatives:
            counts[item["source_type"]] = counts.get(item["source_type"], 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _build_conflicts(result, representatives):
        """Fill ``conflicts`` with the distinct disagreeing values."""
        by_value: Dict[Any, List[Dict[str, Any]]] = {}
        for item in representatives:
            by_value.setdefault(item["value"], []).append(
                {
                    "source_key": item["source_key"],
                    "source_type": item["source_type"],
                    "confidence": item["confidence"],
                }
            )
        result.conflicts = [
            {
                "value": value,
                "sources": sorted(
                    sources, key=lambda source: (source["source_key"],)
                ),
            }
            for value, sources in sorted(by_value.items(), key=lambda item: repr(item[0]))
        ]


# ---------------------------------------------------------------------------
# JSON-safe serialization helpers (used by the crawler and the collectors)
# ---------------------------------------------------------------------------


def field_validation_to_dict(result: FieldValidation) -> Dict[str, Any]:
    """Serialize one field validation to a JSON-safe dictionary."""
    return {
        "field": result.field,
        "status": result.status,
        "agreed_value": result.agreed_value,
        "base_confidence": result.base_confidence,
        "validated_confidence": result.validated_confidence,
        "confidence_boost": result.confidence_boost,
        "independent_source_count": result.independent_source_count,
        "source_types": dict(result.source_type_counts),
        "needs_manual_review": result.needs_manual_review,
        "inconsistent_sources": list(result.inconsistent_sources),
        "conflicts": [
            {
                "value": conflict["value"],
                "sources": list(conflict["sources"]),
            }
            for conflict in result.conflicts
        ],
        "reasons": list(result.reasons),
        "observations": [
            {
                "source_key": observation.source_key,
                "source_type": observation.source_type,
                "raw_value": _json_safe(observation.raw_value),
                "normalized_value": _json_safe(observation.normalized_value),
                "status": observation.status,
                "reason": observation.reason,
                "confidence": observation.confidence,
            }
            for observation in result.observations
        ],
    }


def card_validation_to_dict(result: CardValidation) -> Dict[str, Any]:
    """Serialize one card validation to a JSON-safe dictionary."""
    return {
        "card_key": result.card_key,
        "bank_key": result.bank_key,
        "needs_manual_review": result.needs_manual_review,
        "conflict_fields": result.conflict_fields,
        "fields": {
            name: field_validation_to_dict(field)
            for name, field in sorted(result.fields.items())
        },
    }


def batch_summary(batch: ValidationBatch) -> Dict[str, Any]:
    """Serialize a whole validation batch into the stored summary shape."""
    return {
        "needs_manual_review": batch.needs_manual_review,
        "conflict_field_count": batch.conflict_field_count,
        "ignored_observations": batch.ignored_observations,
        "cards": [card_validation_to_dict(card) for card in batch.cards],
    }


def _json_safe(value):
    """Coerce unknown values (e.g. Decimals, booleans) into JSON-safe ones."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        import decimal

        if isinstance(value, decimal.Decimal):
            return float(value)
    except ImportError:  # pragma: no cover - decimal is part of the stdlib
        pass
    return repr(value)


__all__ = [
    "DEFAULT_SOURCE_CONFIDENCE",
    "FIELD_UNITS",
    "REASON_UNIT_MISMATCH",
    "SOURCE_DEFAULT_CONFIDENCE",
    "STATUS_AGREEMENT",
    "STATUS_CONFLICT",
    "STATUS_NO_DATA",
    "STATUS_SINGLE_SOURCE",
    "VALIDATED_FIELDS",
    "CardValidation",
    "FieldValidation",
    "MultiSourceValidator",
    "Observation",
    "ObservationResult",
    "ValidationBatch",
    "batch_summary",
    "card_validation_to_dict",
    "default_confidence",
    "field_validation_to_dict",
    "normalize_observation",
]
