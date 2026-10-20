"""Classify free-text lounge access values into explicit statuses.

Lounge access is stored as free text, one value per direction
(``lounge_access_international`` and ``lounge_access_domestic``). This module
is the single place that decides what such a value means, so the model
helpers, API filters, facets, the search index and typeahead all agree.

Statuses
--------
UNKNOWN
    Empty or a placeholder such as ``""``, ``"-"`` or ``"unknown"``. Nothing
    was recorded, so the card may or may not have access.
NONE
    The value states there is no access, e.g. ``"0"``, ``"0 visits"``,
    ``"None"``, ``"N/A"``, ``"Not applicable"`` or ``"No lounge access"``.
    A negation followed by a single clarifying parenthesis also counts, so
    ``"None (complimentary access not applicable)"`` and ``"N/A (Classic)"``
    are none rather than an entitlement.
UNLIMITED
    The value states unlimited access, e.g. ``"Unlimited"``. Unlimited is a
    status, not a number: it has no finite visit count, so it never matches
    a minimum-count filter.
LIMITED
    Any other value that grants access, e.g. ``"4 per year"`` or
    ``"Priority Pass"``. The visit count is the first integer of up to nine
    digits in the text, or ``None`` when the text has no such number.

Classification order is UNKNOWN, then UNLIMITED, then NONE, then LIMITED.

Card-level values are ``True`` (any direction has access), ``False`` (every
direction is a known NONE) or ``None`` (unknown: nothing shows access and at
least one direction was not stated).

The SQL helpers use the same patterns as the Python helpers, so database
filters and Python code give the same answer for every value.
"""

import re

from django.db import models
from django.db.models import Q
from django.db.models.functions import Cast, Coalesce

UNKNOWN = "unknown"
NONE = "none"
UNLIMITED = "unlimited"
LIMITED = "limited"

#: Values that mean "not recorded". Compared case-insensitively after trimming.
UNKNOWN_VALUES = (
    "",
    "-",
    "?",
    "unknown",
    "not specified",
    "not mentioned",
    "no information",
    "tbd",
    "null",
)


def _alternation(values):
    """Build a non-capturing regex alternation from literal values."""
    return "(?:" + "|".join(re.escape(value) for value in values) + ")"


# Shared by Python (re) and PostgreSQL (regex operators). Keep the syntax to
# constructs both engines read the same way.
UNKNOWN_PATTERN = r"^\s*" + _alternation(UNKNOWN_VALUES) + r"\s*\.?\s*\Z"
UNLIMITED_PATTERN = r"unlimited|no\s+limit|without\s+(?:any\s+)?limit"
NONE_PATTERN = (
    r"^\s*(?:0+(?:[.,]0+)?|n\s*/?\s*a|none|nil|no|not)"
    r"(?:\s+[a-z]+)*(?:\s*\([^)]*\))?\s*\.?\s*\Z"
)
COUNT_PATTERN = r"\d{1,9}"

#: Entitlement score used for unlimited access so it sorts above any count.
UNLIMITED_ENTITLEMENT = 10**9

_UNKNOWN_RE = re.compile(UNKNOWN_PATTERN, re.IGNORECASE)
_UNLIMITED_RE = re.compile(UNLIMITED_PATTERN, re.IGNORECASE)
_NONE_RE = re.compile(NONE_PATTERN, re.IGNORECASE)
_COUNT_RE = re.compile(COUNT_PATTERN)


def classify_lounge_access(value):
    """Return the status of one free-text lounge access value.

    Parameters
    ----------
    value : str | None
        Raw lounge access text for one direction, e.g. ``"5 visits"``.

    Returns
    -------
    str
        One of ``UNKNOWN``, ``NONE``, ``UNLIMITED`` or ``LIMITED``.
    """
    text = "" if value is None else str(value)
    if _UNKNOWN_RE.match(text):
        return UNKNOWN
    if _UNLIMITED_RE.search(text):
        return UNLIMITED
    if _NONE_RE.match(text):
        return NONE
    return LIMITED


def lounge_access_count(value):
    """Return the finite number of lounge visits stated in a value.

    Parameters
    ----------
    value : str | None
        Raw lounge access text for one direction.

    Returns
    -------
    int | None
        ``0`` for a known NONE, the first number in a LIMITED value, or
        ``None`` when the count is unknown or unlimited.
    """
    status = classify_lounge_access(value)
    if status == NONE:
        return 0
    if status != LIMITED:
        return None
    match = _COUNT_RE.search(str(value))
    return int(match.group()) if match else None


def direction_has_access(value):
    """Return whether one direction grants lounge access.

    Parameters
    ----------
    value : str | None
        Raw lounge access text for one direction.

    Returns
    -------
    bool | None
        ``True`` for LIMITED or UNLIMITED, ``False`` for NONE, and ``None``
        for UNKNOWN.
    """
    status = classify_lounge_access(value)
    if status == UNKNOWN:
        return None
    return status in (LIMITED, UNLIMITED)


def card_has_lounge_access(international, domestic):
    """Return the card-level lounge access flag.

    Parameters
    ----------
    international : str | None
        Raw international lounge access text.
    domestic : str | None
        Raw domestic lounge access text.

    Returns
    -------
    bool | None
        ``True`` if any direction has access, ``False`` if both directions
        are a known NONE, and ``None`` otherwise (unknown).
    """
    statuses = {classify_lounge_access(international), classify_lounge_access(domestic)}
    if statuses & {LIMITED, UNLIMITED}:
        return True
    if statuses == {NONE}:
        return False
    return None


def lounge_status_q(field, status):
    """Build a Q object matching rows whose field has the given status.

    Parameters
    ----------
    field : str
        Name of a lounge access text field on CreditCard.
    status : str
        One of ``UNKNOWN``, ``NONE``, ``UNLIMITED`` or ``LIMITED``.

    Returns
    -------
    django.db.models.Q
        Condition equivalent to ``classify_lounge_access`` for ``status``.
    """
    unknown = Q(**{f"{field}__iregex": UNKNOWN_PATTERN})
    unlimited = Q(**{f"{field}__iregex": UNLIMITED_PATTERN}) & ~unknown
    none = Q(**{f"{field}__iregex": NONE_PATTERN}) & ~unknown & ~unlimited
    if status == UNKNOWN:
        return unknown
    if status == UNLIMITED:
        return unlimited
    if status == NONE:
        return none
    return ~(unknown | unlimited | none)


def lounge_access_q(field, has_access):
    """Build a Q object for one direction's access flag.

    Parameters
    ----------
    field : str
        Name of a lounge access text field on CreditCard.
    has_access : bool
        ``True`` matches LIMITED and UNLIMITED values; ``False`` matches
        only explicit NONE values. UNKNOWN values match neither.

    Returns
    -------
    django.db.models.Q
        Condition for the requested access flag.
    """
    if has_access:
        return lounge_status_q(field, LIMITED) | lounge_status_q(field, UNLIMITED)
    return lounge_status_q(field, NONE)


def card_lounge_access_q(has_access):
    """Build a Q object for the card-level lounge access flag.

    Parameters
    ----------
    has_access : bool
        ``True`` matches cards where any direction has access; ``False``
        matches cards where both directions are a known NONE.

    Returns
    -------
    django.db.models.Q
        Condition equivalent to ``card_has_lounge_access`` for the flag.
    """
    if has_access:
        return lounge_access_q("lounge_access_international", True) | lounge_access_q(
            "lounge_access_domestic", True
        )
    return lounge_access_q("lounge_access_international", False) & lounge_access_q(
        "lounge_access_domestic", False
    )


def annotate_lounge_count(queryset, field, alias):
    """Annotate a queryset with the parsed visit count of one direction.

    Mirrors ``lounge_access_count``: NONE is 0, LIMITED is the first number
    in the text, and UNKNOWN and UNLIMITED are NULL.

    Parameters
    ----------
    queryset : QuerySet
        CreditCard queryset to annotate.
    field : str
        Name of a lounge access text field on CreditCard.
    alias : str
        Name of the annotation to add.

    Returns
    -------
    QuerySet
        The annotated queryset.
    """
    first_number = models.Func(
        models.F(field),
        models.Value(COUNT_PATTERN),
        function="SUBSTRING",
        output_field=models.CharField(),
    )
    count = models.Case(
        models.When(lounge_status_q(field, NONE), then=models.Value(0)),
        models.When(
            lounge_status_q(field, LIMITED),
            then=Cast(first_number, output_field=models.IntegerField()),
        ),
        default=models.Value(None),
        output_field=models.IntegerField(),
    )
    return queryset.annotate(**{alias: count})


def annotate_lounge_entitlement(queryset, field, alias):
    """Annotate a queryset with an integer lounge entitlement score.

    Mirrors ``classify_lounge_access`` so that ``ordering`` can rank by
    entitlement instead of by the free-text value: a known NONE is ``0``,
    UNLIMITED is a large sentinel (above every finite count), LIMITED is its
    first integer, or ``1`` when the text grants access without a number, and
    UNKNOWN is NULL. Sorting descending therefore puts unlimited first, then
    the highest stated visit count, with unknown values last.

    Parameters
    ----------
    queryset : QuerySet
        CreditCard queryset to annotate.
    field : str
        Name of a lounge access text field on CreditCard.
    alias : str
        Name of the annotation to add.

    Returns
    -------
    QuerySet
        The annotated queryset.
    """
    first_number = models.Func(
        models.F(field),
        models.Value(COUNT_PATTERN),
        function="SUBSTRING",
        output_field=models.CharField(),
    )
    score = models.Case(
        models.When(lounge_status_q(field, NONE), then=models.Value(0)),
        models.When(
            lounge_status_q(field, UNLIMITED),
            then=models.Value(UNLIMITED_ENTITLEMENT),
        ),
        models.When(
            lounge_status_q(field, LIMITED),
            then=Coalesce(
                Cast(first_number, output_field=models.IntegerField()),
                models.Value(1),
            ),
        ),
        default=models.Value(None),
        output_field=models.IntegerField(),
    )
    return queryset.annotate(**{alias: score})


def filter_lounge_count_min(queryset, field, minimum):
    """Keep cards whose stated visit count for one direction is at least ``minimum``.

    Parameters
    ----------
    queryset : QuerySet
        CreditCard queryset to filter.
    field : str
        Name of a lounge access text field on CreditCard.
    minimum : int | float | Decimal
        Smallest visit count to keep.

    Returns
    -------
    QuerySet
        Cards with a finite stated count of at least ``minimum``. Unknown
        and unlimited values never match.
    """
    alias = f"{field}_count"
    return annotate_lounge_count(queryset, field, alias).filter(
        **{f"{alias}__gte": minimum}
    )
