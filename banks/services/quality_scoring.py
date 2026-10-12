"""Bounded, documented scoring helpers for extraction quality.

All scores produced here are floats in the inclusive range ``0.0 - 1.0`` and are
derived from explicit, documented rules so that a score can always be explained
(and unit-tested). Higher is better.

Two families of scores exist:

``content score`` (Phase 3, content extraction reliability)
    How trustworthy the extracted text itself is, based on length, presence of
    financial keywords, document structure markers and the extraction method
    (OCR is less reliable than native PDF text).

``card completeness score`` (Phase 2, LLM extraction quality)
    How much of the critical data (``annual_fee``, ``interest_rate_apr``) the LLM
    actually found for the cards in a document.

The final ``extraction_confidence`` is the product of both, which keeps the
result bounded and makes a failure in either dimension visible.

Validity rule (zero vs missing vs invalid)
------------------------------------------
Critical numeric fields are judged with the shared normalization rules in
:mod:`banks.validators.numeric_fields`, i.e. a field only counts as extracted
when it holds a **valid normalized number**:

* ``0`` (or the wording "Free"/"NIL" for a fee) is a genuine value and counts as
  extracted - a free card is never penalised;
* ``None``, ``""``, ``"N/A"``, ``"unknown"`` ... are *missing*;
* malformed strings (``"abc"``), booleans, ``NaN``/``Infinity``, negative and
  out-of-range numbers are *invalid* and score 0 for that field (they are never
  stored as ``0``).

Missing and invalid are reported separately (``missing_annual_fee`` vs
``invalid_annual_fee``) so operators can tell "document did not state it" from
"model returned garbage".
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from banks.validators.numeric_fields import (
    CRITICAL_FIELDS,
    FIELD_BOUNDS,
    MISSING_SENTINELS,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_VALID,
    critical_field_status,
    is_missing_marker,
    normalize_cards,
    parse_numeric_value,
)

# Keywords that indicate the document really is a fee/rate schedule.
FINANCIAL_KEYWORDS = (
    "annual fee",
    "interest rate",
    "credit card",
    "charges",
    "apr",
    "cash advance",
)

# Method multipliers applied to the raw content score.
METHOD_MULTIPLIERS = {
    "pdf_text": 1.0,
    "webpage": 1.0,
    "csv": 1.0,
    "ocr": 0.85,
    "image_ocr": 0.85,
    "unknown": 0.9,
}

MINIMUM_CONTENT_LENGTH = 100


def is_missing(value: Any) -> bool:
    """Return True when a value means "not extracted".

    Only explicit "unknown" markers count; a genuine ``0`` is not missing.
    Use :func:`critical_field_status` when the *validity* of a critical number
    matters.

    Parameters
    ----------
    value : Any
        Candidate value from a parsed card.

    Returns
    -------
    bool
        True when the value is absent or an explicit unknown marker.
    """
    return is_missing_marker(value)


def normalize_missing(value: Any) -> Any:
    """Convert explicit "unknown" markers to ``None`` while keeping real values.

    Parameters
    ----------
    value : Any
        Candidate value from a parsed card.

    Returns
    -------
    Any
        ``None`` for missing markers, otherwise the original value (including a
        genuine ``0``).
    """
    return None if is_missing_marker(value) else value


def critical_field_states(card: Dict[str, Any]) -> Dict[str, str]:
    """Get the extraction status of every critical field on a card.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.

    Returns
    -------
    dict
        Mapping of critical field name to ``"valid"``, ``"missing"`` or
        ``"invalid"``.
    """
    if not isinstance(card, dict):
        return {name: STATUS_MISSING for name in CRITICAL_FIELDS}
    return {name: critical_field_status(card, name) for name in CRITICAL_FIELDS}


def missing_critical_fields(card: Dict[str, Any]) -> List[str]:
    """List critical fields that were **not** successfully extracted.

    Both "the document never mentioned it" (missing) and "the value is
    unusable" (invalid, e.g. ``"abc"``, ``True``, ``NaN``, ``-50``) count as not
    extracted, so a bad value can never raise the confidence score.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.

    Returns
    -------
    list of str
        Field names, in :data:`CRITICAL_FIELDS` order.
    """
    states = critical_field_states(card)
    return [name for name in CRITICAL_FIELDS if states[name] != STATUS_VALID]


def invalid_critical_fields(card: Dict[str, Any]) -> List[str]:
    """List critical fields whose value cannot be trusted.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.

    Returns
    -------
    list of str
        Field names holding malformed / out-of-range values.
    """
    states = critical_field_states(card)
    return [name for name in CRITICAL_FIELDS if states[name] == STATUS_INVALID]


def present_critical_fields(card: Dict[str, Any]) -> List[str]:
    """List critical fields holding a valid, bounded number.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.

    Returns
    -------
    list of str
        Field names with a valid value (a genuine ``0`` counts as valid).
    """
    states = critical_field_states(card)
    return [name for name in CRITICAL_FIELDS if states[name] == STATUS_VALID]


def card_completeness(card: Dict[str, Any]) -> float:
    """Score how complete one card is (0.0-1.0).

    Only *valid normalized numbers* count: malformed strings, booleans,
    NaN/infinity and out-of-range values score 0 for that field, while a
    genuine ``0`` fee scores 1.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.

    Returns
    -------
    float
        Fraction of the critical fields holding a valid number.
    """
    if not isinstance(card, dict):
        return 0.0
    present = len(present_critical_fields(card))
    return present / len(CRITICAL_FIELDS)


def cards_completeness(cards) -> float:
    """Score critical-field completeness across all cards (0.0-1.0).

    Parameters
    ----------
    cards : list of dict
        Parsed credit card dictionaries.

    Returns
    -------
    float
        Mean per-card completeness. Zero cards score 0.0.
    """
    cards = [card for card in (cards or []) if isinstance(card, dict)]
    if not cards:
        return 0.0
    scores = [card_completeness(card) for card in cards]
    return sum(scores) / len(scores)


def coverage_factor(cards) -> float:
    """Penalize extractions that returned fewer cards than expected.

    A single-card document is slightly penalised (0.9) because a schedule of
    charges almost always lists several tiers, and a document with no cards at
    all scores 0.0.

    Parameters
    ----------
    cards : list of dict
        Parsed credit card dictionaries.

    Returns
    -------
    float
        Multiplier in the range 0.0-1.0.
    """
    card_count = len([card for card in (cards or []) if isinstance(card, dict)])
    if card_count == 0:
        return 0.0
    if card_count == 1:
        return 0.9
    return 1.0


@dataclass
class ExtractionQuality:
    """Outcome of scoring an extraction.

    Attributes
    ----------
    confidence : float
        Bounded confidence in the inclusive range 0.0-1.0.
    missing_critical_fields : list of str
        Union of not-extracted critical fields across all cards.
    issues : list of str
        Machine-readable issue codes explaining score reductions.
    details : dict
        Intermediate scores for auditing.
    passes : list of dict
        Multi-pass provenance records (populated by the extractor).
    """

    confidence: float
    missing_critical_fields: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    details: Dict[str, float] = field(default_factory=dict)
    passes: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """Clamp the confidence into the documented 0.0-1.0 range."""
        self.confidence = clamp_confidence(self.confidence)

    @property
    def needs_manual_review(self):
        """Return True when the extraction should be reviewed by a human."""
        return self.confidence < 0.5 or len(self.issues) > 1


def clamp_confidence(value) -> float:
    """Clamp any number into the bounded 0.0-1.0 confidence range.

    Parameters
    ----------
    value : float or None
        Raw score.

    Returns
    -------
    float
        Value clamped to 0.0-1.0 and rounded to four decimals.
    """
    if value is None:
        return 0.0
    try:
        return round(min(1.0, max(0.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def length_factor(content: str) -> float:
    """Score extracted text by length (short text usually means failed OCR).

    Parameters
    ----------
    content : str
        Extracted text.

    Returns
    -------
    float
        Multiplier in the range 0.0-1.0.
    """
    length = len(content or "")
    if length == 0:
        return 0.0
    if length < MINIMUM_CONTENT_LENGTH:
        return 0.4
    if length < 500:
        return 0.7
    if length < 2000:
        return 0.9
    return 1.0


def keyword_factor(content: str) -> float:
    """Score financial keyword coverage (0.0-1.0).

    Parameters
    ----------
    content : str
        Extracted text.

    Returns
    -------
    float
        Ratio of financial keywords found, saturating at all keywords found.
    """
    if not content:
        return 0.0
    content_lower = content.lower()
    hits = sum(1 for keyword in FINANCIAL_KEYWORDS if keyword in content_lower)
    return min(1.0, hits / len(FINANCIAL_KEYWORDS))


def structure_factor(content: str) -> float:
    """Score structural markers that indicate a real fee table was extracted.

    Parameters
    ----------
    content : str
        Extracted text.

    Returns
    -------
    float
        Multiplier in the range 0.0-1.0.
    """
    if not content:
        return 0.0
    content_lower = content.lower()
    markers = ("table", "|", "tk.", "bd t", "%", "per annum", "p.a.")
    hits = sum(1 for marker in markers if marker in content_lower)
    return min(1.0, 0.5 + 0.1 * hits)


def method_factor(method: str) -> float:
    """Return the reliability multiplier for an extraction method.

    Parameters
    ----------
    method : str
        Extraction method name (``pdf_text``, ``ocr``, ``webpage``, ...).

    Returns
    -------
    float
        Multiplier in the range 0.0-1.0 (OCR is discounted).
    """
    return METHOD_MULTIPLIERS.get((method or "unknown").lower(), 0.9)


def score_content(content: str, method: str = "unknown") -> float:
    """Score the reliability of extracted text (0.0-1.0).

    Rules (all bounded, documented):

    ==============  =======================================================
    factor          effect
    ==============  =======================================================
    length          ``>=2000`` chars x1.0, ``>=500`` x0.9, ``>=100`` x0.7,
                    ``<100`` x0.4, empty x0.0
    keywords        ratio of financial keywords found (0.0-1.0)
    structure       0.5 plus 0.1 per structural marker, capped at 1.0
    method          OCR / image OCR discounted to 0.85
    ==============  =======================================================

    Parameters
    ----------
    content : str
        Extracted text.
    method : str, optional
        Extraction method used to produce the text.

    Returns
    -------
    float
        Content reliability score in the inclusive range 0.0-1.0.
    """
    if not content:
        return 0.0
    raw = length_factor(content) * keyword_factor(content) * structure_factor(content)
    raw *= method_factor(method)
    return clamp_confidence(raw)


def score_extraction(content: str, cards, method: str = "unknown") -> ExtractionQuality:
    """Score a complete extraction (content reliability x card completeness).

    Parameters
    ----------
    content : str
        Extracted document text.
    cards : list of dict
        Parsed credit card dictionaries (raw values are fine - validity is
        decided with the shared normalization rules).
    method : str, optional
        Extraction method that produced ``content``.

    Returns
    -------
    ExtractionQuality
        Bounded confidence, not-extracted critical fields, issue codes and
        audit details.
    """
    content_score = score_content(content, method)
    completeness = cards_completeness(cards)
    coverage = coverage_factor(cards)

    issues = []
    if not content:
        issues.append("no_extracted_content")
    elif len(content) < MINIMUM_CONTENT_LENGTH:
        issues.append("insufficient_content")

    card_list = [card for card in (cards or []) if isinstance(card, dict)]
    if not card_list:
        issues.append("no_cards_extracted")

    missing = []
    for card in card_list:
        states = critical_field_states(card)
        for name in CRITICAL_FIELDS:
            status = states[name]
            if status == STATUS_VALID:
                continue
            if name not in missing:
                missing.append(name)
            issue = f"{'missing' if status == STATUS_MISSING else 'invalid'}_{name}"
            if issue not in issues:
                issues.append(issue)

    confidence = content_score * completeness * coverage
    return ExtractionQuality(
        confidence=clamp_confidence(confidence),
        missing_critical_fields=missing,
        issues=issues,
        details={
            "content_score": round(content_score, 4),
            "cards_completeness": round(completeness, 4),
            "coverage_factor": round(coverage, 4),
        },
    )


def coalesce_cards(parsed_data) -> List[Dict[str, Any]]:
    """Coerce a ``parsed_json`` payload into a list of card dictionaries.

    Parameters
    ----------
    parsed_data : object
        Value stored in ``CrawledContent.parsed_json`` (list of cards, dict with
        ``credit_cards``/``cards``/``data`` keys, or a single card dict).

    Returns
    -------
    list of dict
        Card dictionaries, empty when nothing usable was found.
    """
    if isinstance(parsed_data, list):
        cards = parsed_data
    elif isinstance(parsed_data, dict):
        for key in ("credit_cards", "cards", "data"):
            value = parsed_data.get(key)
            if isinstance(value, list):
                cards = value
                break
        else:
            cards = [parsed_data]
    else:
        return []
    return [card for card in cards if isinstance(card, dict)]


__all__ = [
    "CRITICAL_FIELDS",
    "FIELD_BOUNDS",
    "MISSING_SENTINELS",
    "STATUS_INVALID",
    "STATUS_MISSING",
    "STATUS_VALID",
    "ExtractionQuality",
    "card_completeness",
    "cards_completeness",
    "clamp_confidence",
    "coalesce_cards",
    "critical_field_states",
    "critical_field_status",
    "coverage_factor",
    "invalid_critical_fields",
    "is_missing",
    "keyword_factor",
    "length_factor",
    "method_factor",
    "missing_critical_fields",
    "normalize_cards",
    "normalize_missing",
    "parse_numeric_value",
    "present_critical_fields",
    "score_content",
    "score_extraction",
    "structure_factor",
]
