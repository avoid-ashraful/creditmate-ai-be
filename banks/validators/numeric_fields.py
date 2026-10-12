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

Unit, period and waiver safety
------------------------------
Fees are stored and displayed as BDT and APR is an *annual* rate, so a value is
only accepted when it already means what the target field means:

* foreign currency amounts (``"USD 100"``, ``"$95"``, ``"Rs. 100"``) are
  rejected instead of being relabeled as BDT - no conversion rate is invented;
* non-annual periods (``"100 per month"``, ``"2% per month"``) are rejected
  instead of being annualized - no conversion factor is invented;
* conditional waiver wording (``"Waived"``, ``"Exempted"``, ``"waiver"``) is
  rejected because a waiver may depend on spending conditions; only an
  unconditional zero (``0``, ``"Free"``, ``"Nil"``, ``"No annual fee"``) is a
  genuine zero, and waiver policy stays a separate field;
* a percentage in the fee field (``"18.99%"``) is rejected: a rate is not an
  amount.

Every rejection carries an explicit machine-readable reason (see the
``REASON_*`` constants) so a reviewer can tell *why* a value became ``NULL``.

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

# Field-specific strings that mean a genuine, unconditional zero. These are only
# accepted for fields where the wording is unambiguous: a schedule of charges
# saying "Annual Fee: NIL / Free / No annual fee" really does mean a free card.
# Conditional waiver wording (waived/waiver/exempt) is deliberately NOT here -
# "annual fee waived" may depend on spending thresholds, so it is treated as an
# ambiguous value (invalid) and the waiver policy stays in its own field.
# Percentage fields (APR) have no zero wording at all, so a "free"-like string
# there stays missing rather than being turned into a fabricated 0% rate.
ZERO_EQUIVALENT_STRINGS = {
    "annual_fee": {
        "free",
        "free of charge",
        "nil",
        "no annual fee",
        "no fee",
    },
    "interest_rate_apr": set(),
}

# Words that may surround a number in a fee/rate cell without invalidating it.
# Only BDT (domestic) currency words belong here: foreign currency words would
# silently relabel a USD amount as BDT, so they reject the value instead.
NOISE_WORDS = {
    "tk",
    "taka",
    "bdt",
    "bd",
    "usd",
    "rs",
    "eur",
    "gbp",
    "inr",
    "dollars",
    "dollar",
    "euros",
    "euro",
    "pounds",
    "pound",
    "pct",
    "percent",
    "percentage",
    "per",
    "annum",
    "year",
    "years",
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
    re.compile(r"\btaka\b"),
    re.compile(r"[%$€£₹]"),
    re.compile(r"\b(per annum|per year|p\.a\.?|percent|percentage)\b"),
)

# Extract a numeric token from a string such as "TK 5,000" or "20% p.a.".
_NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")

STATUS_VALID = "valid"
STATUS_MISSING = "missing"
STATUS_INVALID = "invalid"

# Rejection reasons (machine readable) for values that cannot be trusted.
REASON_NOT_A_NUMBER = "not_a_number"
REASON_NOT_FINITE = "not_finite"
REASON_BOOLEAN = "boolean"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_FOREIGN_CURRENCY = "foreign_currency"
REASON_NON_ANNUAL_PERIOD = "non_annual_period"
REASON_CONDITIONAL_WAIVER = "conditional_waiver"
REASON_PERCENTAGE_FOR_FEE = "percentage_not_a_fee_amount"

# Amounts denominated in a currency other than BDT. Fees are stored/displayed as
# BDT, so these are rejected rather than relabeled (no conversion is invented).
_FOREIGN_CURRENCY_WORD_PATTERN = re.compile(
    r"(?<![\w])(usd|eur|gbp|inr|rs\.?|dollars?|euros?|pounds?)(?![\w])"
)

# Currency symbols match anywhere: a domestic BDT amount never contains them,
# and "$95" has a digit right after the symbol (so no word boundary exists).
_FOREIGN_CURRENCY_SYMBOL_PATTERN = re.compile(r"[$€£₹]")

# Markers that confirm an amount is already in BDT (kept for documentation and
# for tests asserting the domestic forms stay valid).
DOMESTIC_CURRENCY_PATTERN = re.compile(r"(?<![\w])(tk\.?|taka|bdt|৳)(?![\w])")

# Periods that are not annual. A monthly amount is not an annual fee and a
# monthly rate is not an annual APR; annualizing would invent a factor.
_NON_ANNUAL_PERIOD_PATTERN = re.compile(
    r"(?<![\w])(per\s+month|per\s+week|per\s+day|per\s+quarter|monthly|weekly|"
    r"daily|quarterly|bi-?monthly|p\.m\.)(?![\w])"
    # "/month" and friends are unambiguous anywhere ("500/month"): the slash
    # itself is not a word character, so no boundary guard is needed.
    r"|/(month|week|day)"
)

# Waiver wording: "waived"/"exempted" may be conditional ("waived if annual
# spend exceeds BDT 500,000"), so it is not proof of an unconditional zero fee.
_WAIVER_PATTERN = re.compile(r"(?<![\w])(waiv\w*|exempt\w*)(?![\w])")

# A percentage in a fee cell means a rate was captured, not an amount.
_PERCENT_PATTERN = re.compile(r"%|(?<![\w])percent(age|s)?(?![\w])")


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
        bare = token.strip(",%$৳")
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


def detect_unit_issue(value, field):
    """Detect unit/period/waiver problems that block safe interpretation.

    Fees are BDT amounts and the APR is an annual rate, so a value that is
    denominated in another currency, that covers a non-annual period, that
    describes a conditional waiver, or that is a percentage in the fee field
    cannot be relabeled into the target field without inventing data.

    Parameters
    ----------
    value : any
        Raw value from an LLM response or a source document.
    field : str
        Critical field name.

    Returns
    -------
    str or None
        Rejection reason (``REASON_*``) when the value must not be used, else
        ``None``. The caller still parses the number: a value of exactly ``0``
        is unambiguous in every currency and period, so it stays valid.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if field == "annual_fee" and _WAIVER_PATTERN.search(text):
        return REASON_CONDITIONAL_WAIVER
    if _NON_ANNUAL_PERIOD_PATTERN.search(text):
        return REASON_NON_ANNUAL_PERIOD
    if _FOREIGN_CURRENCY_WORD_PATTERN.search(text) or (
        _FOREIGN_CURRENCY_SYMBOL_PATTERN.search(text)
    ):
        return REASON_FOREIGN_CURRENCY
    if field == "annual_fee" and _PERCENT_PATTERN.search(text):
        return REASON_PERCENTAGE_FOR_FEE
    return None


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
    tuple of (float or None, str, str or None)
        ``(number, status, reason)`` before bounds are applied.
    """
    raw = raw_value.strip()
    if not raw:
        return None, STATUS_MISSING, None
    if raw.lower() in ZERO_EQUIVALENT_STRINGS.get(field, set()):
        return 0.0, STATUS_VALID, None
    if is_missing_marker(raw):
        return None, STATUS_MISSING, None

    unit_issue = detect_unit_issue(raw, field)
    number = _parse_string_number(raw)
    if number is None or not math.isfinite(number):
        # A value that is already suspicious (e.g. a monthly amount) reports
        # the more specific reason; otherwise it is simply not a number.
        return None, STATUS_INVALID, unit_issue or REASON_NOT_A_NUMBER
    if unit_issue is not None and number != 0.0:
        return None, STATUS_INVALID, unit_issue
    return number, STATUS_VALID, None


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
    tuple of (float or None, str, str or None)
        ``(number, status, reason)`` before bounds are applied.
    """
    if isinstance(value, bool):
        # ``True``/``False`` are never fee amounts (they would become 1.0/0.0).
        return None, STATUS_INVALID, REASON_BOOLEAN
    if value is None:
        return None, STATUS_MISSING, None
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None, STATUS_INVALID, REASON_NOT_FINITE
        return float(value), STATUS_VALID, None
    if isinstance(value, str):
        return _coerce_string_number(value, field)
    # lists, dicts, dates, ... are never fee values
    return None, STATUS_INVALID, REASON_NOT_A_NUMBER


def parse_numeric_value_detailed(value, field):
    """Parse a critical field and explain any rejection.

    Parameters
    ----------
    value : any
        Raw value from an LLM response or a source document.
    field : str
        Critical field name (``annual_fee`` or ``interest_rate_apr``).

    Returns
    -------
    tuple of (float or None, str, str or None)
        ``(normalized value, status, reason)``. ``reason`` is ``None`` for
        valid and missing values and one of the ``REASON_*`` codes for
        invalid values.
    """
    number, status, reason = _coerce_to_number(value, field)
    if status != STATUS_VALID:
        return None, status, reason

    lower_bound, upper_bound = FIELD_BOUNDS.get(field, (None, None))
    if lower_bound is not None and number < lower_bound:
        return None, STATUS_INVALID, REASON_OUT_OF_RANGE
    if upper_bound is not None and number > upper_bound:
        return None, STATUS_INVALID, REASON_OUT_OF_RANGE

    return number, STATUS_VALID, None


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
        float for valid input and ``None`` otherwise. Use
        :func:`parse_numeric_value_detailed` when the rejection reason is
        needed as well.
    """
    number, status, _ = parse_numeric_value_detailed(value, field)
    return number, status


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


def card_invalid_reasons(card):
    """Explain why the critical fields of one card were rejected.

    Parameters
    ----------
    card : dict
        Parsed credit card dictionary (raw values, before normalization).

    Returns
    -------
    dict
        Mapping of field name to ``REASON_*`` code for every critical field
        whose value is invalid (missing fields have no reason).
    """
    if not isinstance(card, dict):
        return {}
    reasons = {}
    for field in CRITICAL_FIELDS:
        if field not in card:
            continue
        _, status, reason = parse_numeric_value_detailed(card.get(field), field)
        if status == STATUS_INVALID:
            reasons[field] = reason or REASON_NOT_A_NUMBER
    return reasons


def cards_invalid_reasons(cards):
    """Collect rejection reasons across a list of cards.

    Parameters
    ----------
    cards : list of dict
        Parsed credit card dictionaries.

    Returns
    -------
    dict
        Mapping of field name to ``REASON_*`` code. When several cards reject
        the same field for different reasons, the first reason wins (the field
        is already reported once per extraction).
    """
    merged = {}
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        for field, reason in card_invalid_reasons(card).items():
            merged.setdefault(field, reason)
    return merged
