"""Normalization rules for critical numeric fields (fees and APR).

This module is the single source of truth for deciding whether a value in a
critical numeric field (``annual_fee``, ``interest_rate_apr``) is:

* ``valid``   - a finite number inside the documented bounds (including a
  genuine ``0`` for a free card),
* ``missing`` - the document never stated a value (``None``, ``""``,
  ``"N/A"``, ``"unknown"``, ...), or
* ``invalid`` - a value that cannot be trusted (``"abc"``, ``True``,
  ``NaN``/``Infinity``, negative numbers, out-of-range percentages).

Only *valid* values count towards extraction confidence; ``missing`` and
``invalid`` values are both stored as ``NULL`` so a bad value can never be
silently written as ``0`` (which would turn "not extracted" into "free card").

The rules are intentionally pure and dependency-free so both the validators and
the scoring services can share them without import cycles.
"""

import math
import re

# Fields that must be present for an extraction to be considered complete.
CRITICAL_FIELDS = ("annual_fee", "interest_rate_apr")

# Documented bounds, kept in sync with CreditCard model validators:
# annual_fee >= 0 (max_digits=10, decimal_places=2 -> 99999999.99 absolute cap,
# we use a sanity bound of 100000) and interest_rate_apr within 0-100%.
FIELD_BOUNDS = {
    "annual_fee": (0.0, 100000.0),
    "interest_rate_apr": (0.0, 100.0),
}

# Strings that explicitly mean "no data available".
MISSING_SENTINELS = {
    "",
    "-",
    "--",
    "?",
    "n/a",
    "na",
    "n.a.",
    "null",
    "none",
    "unknown",
    "tbd",
    "not mentioned",
    "not specified",
    "not available",
    "no data",
    "no information",
}

# Field-specific strings that mean a genuine zero. These are only accepted for
# fields where the wording is unambiguous: a schedule of charges saying
# "Annual Fee: NIL / Free / No annual fee" really does mean a free card.
# Percentage fields (APR) have no such wording, so a "free"-like string there
# stays missing rather than being turned into a fabricated 0% rate.
ZERO_EQUIVALENT_STRINGS = {
    "annual_fee": {
        "free",
        "free of charge",
        "nil",
        "no annual fee",
        "no fee",
        "exempted",
        "exempt",
        "waived",
        "waiver",
    },
    "interest_rate_apr": set(),
}

# Words that may surround a number in a fee/rate cell without invalidating it.
NOISE_WORDS = {
    "tk",
    "taka",
    "bdt",
    "usd",
    "rs",
    "bd",
    "pct",
    "percent",
    "percentage",
    "per",
    "annum",
    "year",
    "years",
    "month",
    "months",
    "p.a",
    "pa",
    "a.p.r",
    "apr",
    "interest",
    "rate",
    "annual",
    "fee",
    "charge",
    "charges",
    "approx",
    "approximately",
    "about",
    "approx.",
}

# Regexes used to strip currency/percentage words before float parsing.
_NOISE_PATTERNS = (
    re.compile(r"\btk\.?"),
    re.compile(r"\bbdt\b"),
    re.compile(r"\b(usd|taka|rs)\b"),
    re.compile(r"[%$€£]"),
    re.compile(r"\b(per annum|per year|p\.a\.?|percent|percentage)\b"),
)

# Extract a numeric token from a string such as "TK 5,000" or "20% p.a.".
_NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")

STATUS_VALID = "valid"
STATUS_MISSING = "missing"
STATUS_INVALID = "invalid"


def is_missing_marker(value):
    """Return True when a value is an explicit "no data" marker.

    Parameters
    ----------
    value : any
        Raw value.

    Returns
    -------
    bool
        True for ``None`` and for sentinel strings such as ``""`` or ``"N/A"``.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_SENTINELS
    return False


def _normalize_text(text):
    """Strip currency/percentage noise from a numeric string.

    ``"TK 5,000"`` becomes ``"5000"`` and ``"20% p.a."`` becomes ``"20"``.

    Parameters
    ----------
    text : str
        Raw string such as ``"TK 5,000"`` or ``"20% p.a."``.

    Returns
    -------
    str
        Normalized string, whitespace collapsed (may still be unparseable,
        in which case the caller treats the value as invalid).
    """
    cleaned = text.strip().lower().replace(",", "")
    for pattern in _NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return " ".join(cleaned.split()).strip()


def _parse_string_number(raw):
    """Parse a fee/rate string into a number, or None when unparseable.

    The fast path removes currency/percentage noise and parses the remainder.
    The fallback path accepts exactly one number surrounded by known noise
    words (``"tk 5,000"``, ``"20 percent per annum"``); anything else - for
    example ``"12 months free"`` or ``"ask your RM"`` - is rejected instead of
    being guessed.

    Parameters
    ----------
    raw : str
        Raw string value.

    Returns
    -------
    float or None
        Parsed number, or None when the string cannot be trusted.
    """
    cleaned = _normalize_text(raw)
    if cleaned:
        try:
            return float(cleaned)
        except (TypeError, ValueError):
            pass

    numbers = []
    for token in raw.strip().lower().split():
        bare = token.strip(",%$")
        if not bare:
            continue
        try:
            numbers.append(float(bare.replace(",", "").rstrip(".")))
            continue
        except (TypeError, ValueError):
            pass
        word = bare.rstrip(".").replace(".", "")
        if word in NOISE_WORDS or bare.rstrip(".") in NOISE_WORDS:
            continue
        return None

    return numbers[0] if len(numbers) == 1 else None


def _coerce_string_number(raw_value, field):
    """Coerce a raw string into a finite number for a critical field.

    Parameters
    ----------
    raw_value : str
        Raw string from an LLM response or a source document.
    field : str
        Critical field name (used for the zero-equivalent wording table).

    Returns
    -------
    tuple of (float or None, str)
        ``(number, status)`` where status is ``"valid"``/``"missing"``/``"invalid"``.
    """
    raw = raw_value.strip()
    if not raw:
        return None, STATUS_MISSING
    if raw.lower() in ZERO_EQUIVALENT_STRINGS.get(field, set()):
        return 0.0, STATUS_VALID
    if is_missing_marker(raw):
        return None, STATUS_MISSING
    number = _parse_string_number(raw)
    if number is None or not math.isfinite(number):
        return None, STATUS_INVALID
    return number, STATUS_VALID


def _coerce_to_number(value, field):
    """Coerce any raw input to a finite float without trusting it.

    Parameters
    ----------
    value : any
        Raw value from an LLM response or a source document.
    field : str
        Critical field name.

    Returns
    -------
    tuple of (float or None, str)
        ``(number, status)`` before bounds are applied.
    """
    if isinstance(value, bool):
        # ``True``/``False`` are never fee amounts (they would become 1.0/0.0).
        return None, STATUS_INVALID
    if value is None:
        return None, STATUS_MISSING
    if isinstance(value, (int, float)):
        return (float(value), STATUS_VALID) if math.isfinite(value) else (
            None,
            STATUS_INVALID,
        )
    if isinstance(value, str):
        return _coerce_string_number(value, field)
    # lists, dicts, dates, ... are never fee values
    return None, STATUS_INVALID


def parse_numeric_value(value, field):
    """Parse a critical numeric field into a normalized value and a status.

    Parameters
    ----------
    value : any
        Raw value from an LLM response or a source document.
    field : str
        Critical field name (``annual_fee`` or ``interest_rate_apr``).

    Returns
    -------
    tuple of (float or None, str)
        ``(normalized value, status)`` where status is one of
        ``"valid"``, ``"missing"`` or ``"invalid"``. The normalized value is a
        float for valid input and ``None`` otherwise.
    """
    number, status = _coerce_to_number(value, field)
    if status != STATUS_VALID:
        return None, status

    lower_bound, upper_bound = FIELD_BOUNDS.get(field, (None, None))
    if lower_bound is not None and number < lower_bound:
        return None, STATUS_INVALID
    if upper_bound is not None and number > upper_bound:
        return None, STATUS_INVALID

    return number, STATUS_VALID


def is_valid_critical_value(value, field):
    """Check whether a critical field holds a usable, bounded number.

    Parameters
    ----------
    value : any
        Raw value.
    field : str
        Critical field name.

    Returns
    -------
    bool
        True only when the value parses to a finite in-range number
        (including a genuine ``0``).
    """
    return parse_numeric_value(value, field)[1] == STATUS_VALID


def critical_field_status(card, field):
    """Get the extraction status of one critical field on a card.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.
    field : str
        Critical field name.

    Returns
    -------
    str
        ``"valid"``, ``"missing"`` or ``"invalid"``.
    """
    if not isinstance(card, dict):
        return STATUS_MISSING
    if field not in card:
        return STATUS_MISSING
    return parse_numeric_value(card.get(field), field)[1]


def normalize_critical_fields(card):
    """Normalize every critical field of a card, keeping only valid numbers.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary.

    Returns
    -------
    tuple of (dict, dict)
        Copy of the card with critical fields set to a float (valid) or
        ``None`` (missing/invalid), plus a mapping of field -> status.
    """
    if not isinstance(card, dict):
        return {}, {}

    normalized = dict(card)
    statuses = {}
    for field in CRITICAL_FIELDS:
        value, status = parse_numeric_value(card.get(field), field)
        normalized[field] = value
        statuses[field] = status
    return normalized, statuses


def normalize_cards(cards):
    """Normalize a list of cards for validation, scoring and storage.

    Parameters
    ----------
    cards : list of dict
        Parsed credit card dictionaries.

    Returns
    -------
    tuple of (list of dict, list of dict)
        Normalized cards and one status mapping per input card.
    """
    normalized_cards = []
    statuses = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        normalized, card_statuses = normalize_critical_fields(card)
        normalized_cards.append(normalized)
        statuses.append(card_statuses)
    return normalized_cards, statuses
