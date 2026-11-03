"""The CreditMate Score: one explainable 0-10 score per card.

The score is computed ONLY from a card's published catalogue data — the
same fields the API already exposes — so anyone can reproduce it from
the card detail response. The methodology is published on the site and
must stay in sync with this module:

==================  ====  ==============================================
Component           Max   What it measures
==================  ====  ==============================================
Annual cost          3.0  Annual fee level (2.5) + fee-waiver (0.5)
Interest             2.0  APR against Bangladesh Bank's 25% cap
Rewards value        2.5  Earn rate (1.5) + cashback (0.7) + a stated
                          rewards policy (0.3)
Perks                1.5  Lounge access, 0.75 per direction
Data confidence      1.0  Verification (0.4) + source link (0.2) +
                          completeness of the scored fields (0.4)
==================  ====  ==============================================

Missing-data rules (deliberate, and stated in the public methodology):

- A field the card does not publish is scored NEUTRALLY (half of that
  sub-component's points) for price-like fields where absence is not
  evidence of a bad deal: the annual fee level and the APR. Every
  Islamic card in the catalogue, for example, publishes no APR because
  it does not charge interest — scoring that as the worst APR would be
  false. The reason string always says the value is unpublished.
- Absence scores ZERO where absence is the truthful reading of the
  published record: no stated rewards rules means no rewards value we
  can credit, no stated waiver means no waiver we can credit, and
  lounge text that explicitly says "no access" earns no perk points.
  Unpublished lounge text sits between the two: a small neutral
  allowance (0.2 of 0.75 per direction), because absence of a lounge
  mention is weaker evidence than an explicit "none".
- The score is deterministic: same card data, same score, always.
  It is recomputed from live card data on every read, so it changes
  exactly when the underlying card data changes.

Nothing here uses user data, click behaviour, bank relationships or
commercial placement. Banks cannot pay to change a score.
"""

from decimal import Decimal

from credit_cards.constants import VerificationStatus
from credit_cards.lounge import (
    LIMITED,
    UNKNOWN,
    UNLIMITED,
    classify_lounge_access,
    lounge_access_count,
)

#: Component keys, in display order, with their maximum points.
COMPONENT_MAX = {
    "annual_cost": Decimal("3.0"),
    "interest": Decimal("2.0"),
    "rewards": Decimal("2.5"),
    "perks": Decimal("1.5"),
    "data_confidence": Decimal("1.0"),
}

#: Bangladesh Bank caps consumer credit card interest at 25% APR; most
#: cards in the catalogue charge exactly the cap.
APR_CAP = Decimal("25")

_FEE_BANDS = [
    # (upper bound in BDT, points of 2.5) — first matching band wins.
    (Decimal("0"), Decimal("2.5")),
    (Decimal("1000"), Decimal("2.2")),
    (Decimal("2500"), Decimal("1.9")),
    (Decimal("5000"), Decimal("1.5")),
    (Decimal("7500"), Decimal("1.2")),
    (Decimal("10000"), Decimal("0.9")),
    (Decimal("15000"), Decimal("0.6")),
    (Decimal("20000"), Decimal("0.4")),
]


def _fmt_bdt(amount):
    """Format a Decimal BDT amount, e.g. ``BDT 3,000``."""
    if amount == amount.to_integral_value():
        return f"BDT {int(amount):,}"
    return f"BDT {amount:,.2f}"


def _num(value):
    """Format a Decimal without trailing zeros or exponent notation."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fee_level_points(fee):
    """Points (of 2.5) for the annual fee level alone."""
    for upper, points in _FEE_BANDS:
        if fee <= upper:
            return points
    return Decimal("0.2")


def _annual_cost(card):
    fee = card.annual_fee
    if fee is None:
        level = Decimal("1.25")  # neutral: half of 2.5
        fee_reason = "annual fee not published, scored neutrally"
    else:
        level = _fee_level_points(fee)
        fee_reason = "no annual fee" if fee == 0 else f"annual fee {_fmt_bdt(fee)}"
    waiver = Decimal("0")
    waiver_reason = "no fee waiver published"
    if fee is not None and fee == 0:
        waiver = Decimal("0.5")
        waiver_reason = "nothing to waive"
    elif card.annual_fee_waiver_policy:
        waiver = Decimal("0.5")
        waiver_reason = "fee waiver available"
    return level + waiver, f"{fee_reason}; {waiver_reason}"


def _interest(card):
    apr = card.interest_rate_apr
    if apr is None:
        if card.is_islamic:
            return Decimal("1.0"), (
                "Islamic card — no interest rate applies; scored neutrally"
            )
        return Decimal("1.0"), "APR not published; scored neutrally"
    # 18% (the lowest APR in the catalogue) earns full points; the 25%
    # cap earns the floor. Linear between the two.
    fraction = (Decimal("26") - apr) / Decimal("8")
    fraction = max(Decimal("0.15"), min(Decimal("1"), fraction))
    points = Decimal("2.0") * fraction
    if apr >= APR_CAP:
        reason = f"APR {_num(apr)}% — at the 25% regulatory cap most cards charge"
    else:
        reason = f"APR {_num(apr)}% — below the 25% regulatory cap"
    return points, reason


def _best_earn_per_100(card):
    """Best published earn rate, in points per BDT 100 spent."""
    best = Decimal("0")
    for rule in card.reward_earn_rules or []:
        unit = rule.get("spend_unit_bdt")
        points = rule.get("points_per_unit")
        if unit and points:
            rate = Decimal(str(points)) / Decimal(str(unit)) * 100
            best = max(best, rate)
    return best


def _band_points(value, bands, positive_points):
    """First band whose threshold ``value`` meets, else a small
    positive-value score, else zero."""
    for threshold, points in bands:
        if value >= threshold:
            return points
    return positive_points if value > 0 else Decimal("0")


def _earn_points(earn_rate):
    """Points (of 1.5) for the best published earn rate per BDT 100."""
    return _band_points(
        earn_rate,
        [
            (Decimal("5"), Decimal("1.5")),
            (Decimal("3"), Decimal("1.25")),
            (Decimal("2"), Decimal("1.0")),
            (Decimal("1.25"), Decimal("0.75")),
        ],
        Decimal("0.5"),
    )


def _cashback_points(best_cashback):
    """Points (of 0.7) for the best published cashback percent."""
    return _band_points(
        best_cashback,
        [
            (Decimal("10"), Decimal("0.7")),
            (Decimal("5"), Decimal("0.55")),
            (Decimal("2"), Decimal("0.4")),
            (Decimal("1"), Decimal("0.3")),
        ],
        Decimal("0.15"),
    )


def _rewards(card):
    earn_rate = _best_earn_per_100(card)
    earn = _earn_points(earn_rate)

    percents = [
        Decimal(str(rule["percent"]))
        for rule in (card.cashback_rules or [])
        if rule.get("percent")
    ]
    best_cashback = max(percents, default=Decimal("0"))
    cashback = _cashback_points(best_cashback)

    documented = (
        Decimal("0.3") if (card.reward_points_policy or "").strip() else Decimal("0")
    )

    parts = []
    if earn_rate > 0:
        parts.append(f"earns up to {_num(earn_rate)} pts per BDT 100")
    if best_cashback > 0:
        parts.append(f"cashback up to {_num(best_cashback)}%")
    if not parts:
        parts.append("no published rewards earn or cashback rules")
    elif documented:
        parts.append("rewards policy published")
    return earn + cashback + documented, "; ".join(parts)


def _direction_points(value):
    """Points (of 0.75) for one lounge direction's free-text value."""
    status = classify_lounge_access(value)
    if status == UNLIMITED:
        return Decimal("0.75")
    if status == LIMITED:
        count = lounge_access_count(value)
        if count is None:
            return Decimal("0.4")
        if count >= 6:
            return Decimal("0.65")
        if count >= 3:
            return Decimal("0.55")
        return Decimal("0.45")
    if status == UNKNOWN:
        return Decimal("0.2")  # neutral: unpublished, not a stated "none"
    return Decimal("0")  # NONE: the card states there is no access


def _direction_label(value):
    """Short display label for one lounge direction's status."""
    status = classify_lounge_access(value)
    if status == UNLIMITED:
        return "unlimited access"
    if status == LIMITED:
        count = lounge_access_count(value)
        return f"{count} visits/year" if count else "access included"
    if status == UNKNOWN:
        return "not published"
    return "no access"


def _perks(card):
    intl = _direction_points(card.lounge_access_international)
    dom = _direction_points(card.lounge_access_domestic)
    reason = (
        f"international lounge: {_direction_label(card.lounge_access_international)}"
        f"; domestic lounge: {_direction_label(card.lounge_access_domestic)}"
    )
    return intl + dom, reason


#: Fields whose presence the completeness sub-score inspects — exactly
#: the fields the other components read.
_COMPLETENESS_CHECKS = [
    lambda c: c.annual_fee is not None,
    lambda c: c.interest_rate_apr is not None,
    lambda c: bool(c.annual_fee_waiver_policy),
    lambda c: bool(
        (c.lounge_access_international or "").strip()
        or (c.lounge_access_domestic or "").strip()
    ),
    lambda c: bool(
        c.reward_earn_rules or c.cashback_rules or (c.reward_points_policy or "").strip()
    ),
    lambda c: c.reward_point_value_bdt is not None,
    lambda c: bool((c.source_url or "").strip()),
    lambda c: c.verified_at is not None,
]


def _data_confidence(card):
    verified = (
        Decimal("0.4")
        if card.verification_status == VerificationStatus.VERIFIED
        else Decimal("0.1")
    )
    sourced = Decimal("0.2") if (card.source_url or "").strip() else Decimal("0")
    present = sum(1 for check in _COMPLETENESS_CHECKS if check(card))
    completeness = Decimal("0.4") * Decimal(present) / Decimal(len(_COMPLETENESS_CHECKS))
    status = (
        "verified card data"
        if card.verification_status == VerificationStatus.VERIFIED
        else "card data not yet verified"
    )
    reason = f"{status}; {present} of {len(_COMPLETENESS_CHECKS)} scored fields published"
    return verified + sourced + completeness, reason


_COMPONENT_FUNCS = {
    "annual_cost": _annual_cost,
    "interest": _interest,
    "rewards": _rewards,
    "perks": _perks,
    "data_confidence": _data_confidence,
}


def score_breakdown(card):
    """Return the per-component breakdown for a card.

    Parameters
    ----------
    card : CreditCard
        The card to score. Only its published fields are read.

    Returns
    -------
    dict
        ``{component: {"points": float, "max": float, "reason": str}}``
        in display order. Points are rounded to 2 decimals.
    """
    breakdown = {}
    for key, func in _COMPONENT_FUNCS.items():
        points, reason = func(card)
        points = min(points, COMPONENT_MAX[key])
        breakdown[key] = {
            "points": float(points.quantize(Decimal("0.01"))),
            "max": float(COMPONENT_MAX[key]),
            "reason": reason,
        }
    return breakdown


def evaluate_score(card):
    """Return ``{"score": float, "breakdown": dict}`` for a card.

    The score is 0-10 with one decimal place: the rounded sum of the
    rounded component points, so the published breakdown always adds
    up to the published score (within the final one-decimal rounding).
    The result is cached on the card instance, so serializers asking
    for both the score and the breakdown score the card only once.
    """
    cached = getattr(card, "_creditmate_score_cache", None)
    if cached is not None:
        return cached
    breakdown = score_breakdown(card)
    total = round(sum(item["points"] for item in breakdown.values()), 1)
    result = {"score": total, "breakdown": breakdown}
    try:
        card._creditmate_score_cache = result
    except (AttributeError, TypeError):
        pass
    return result
