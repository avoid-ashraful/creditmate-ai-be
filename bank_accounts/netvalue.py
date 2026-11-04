"""Net-annual-value mathematics for bank accounts.

This module is the single source of truth for the accounts scenario; the
frontend displays exactly what the API computes (it never re-derives
figures client-side).

Conventions
-----------
* **Interest/profit earned** = the rate of the slab covering the user's
  stated average balance × that balance, for one year. When the source
  publishes a rate *range* for a slab, the lower bound (``rate``) is
  used — never the flattering end — and the at-max figure is returned
  alongside. If the product publishes a minimum balance to earn interest
  and the scenario balance is below it, interest is 0 (the published
  gate wins over the slab table).
* **Basis honesty**: the estimate assumes the stated balance is held for
  the full year. For lowest-monthly-balance / monthly-minimum products
  it additionally assumes the balance never dips below the stated
  average in any month; when the bank does not publish its basis, the
  response says so (``basis_note``).
* **Fees** are annualised steady-state (year-2) figures, excluding VAT:
  maintenance is charged half-yearly, so ×2; the debit-card line uses
  the published annual fee, reduced to 0 only when the product's waiver
  is *mechanical* (a stated average-balance threshold the scenario
  meets). Prose-only waivers are shown as text, never applied.
* A fee of ``None`` means the bank does not publish that figure in the
  sources we hold. The breakdown keeps it ``None`` (the UI prints "not
  published"), the known-lines total is flagged ``fees_complete=False``,
  and a product with *no* published fee lines at all is not ranked —
  ranking it on interest alone would flatter it against fully disclosed
  products.
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from bank_accounts.constants import InterestBasis

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _d(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value):
    """Round a Decimal amount to 2dp (paisa), half-up."""
    return _d(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def pick_slab(slabs, balance):
    """Return the slab covering ``balance`` from a [min, max) slab list.

    ``balance_max`` is exclusive; ``None`` is open-ended. Returns None
    when no slab covers the balance (e.g. a bank publishes rates only
    from Tk 1 lakh up) — the caller treats that as "no published rate at
    this balance", never as 0%.
    """
    balance = _d(balance)
    for slab in slabs or []:
        low = _d(slab.get("balance_min", "0"))
        high = slab.get("balance_max")
        if balance < low:
            continue
        if high is not None and balance >= _d(high):
            continue
        return slab
    return None


def pick_fee_slab(slabs, balance):
    """Return the maintenance-fee slab covering ``balance``.

    Banks print maintenance bands with *inclusive* ceilings ("up to
    Tk 10,000: free; above Tk 10,000 to Tk 25,000: Tk 100"), so fee
    slabs are stored as printed (``balance_min`` is the first taka of
    the band, ``balance_max`` its last) and matched inclusively. A
    balance in the paisa-level gap between two bands (e.g. Tk 10,000.50,
    above the printed ceiling of the free band) resolves to the
    *upcoming* band, matching the printed "above Tk X" semantics of the
    next band. A balance above every band resolves to the top band.
    """
    balance = _d(balance)
    ordered = sorted(slabs or [], key=lambda s: _d(s.get("balance_min", "0")))
    chosen = None
    for slab in ordered:
        low = _d(slab.get("balance_min", "0"))
        high = slab.get("balance_max")
        if balance < low:
            # Below this band's floor: either below the first band or in
            # the gap after the previous band — the upcoming band applies.
            return slab
        if high is None or balance <= _d(high):
            return slab
        chosen = slab
    return chosen


def rate_for_balance(product, balance):
    """(rate, rate_max|None) for a product at ``balance``, or None."""
    slab = pick_slab(product.rate_slabs, balance)
    if slab is None:
        return None
    rate = _d(slab.get("rate", "0"))
    rate_max = slab.get("rate_max")
    return rate, (_d(rate_max) if rate_max is not None else None)


def fee_schedule_params(key, on=None):
    """Params of the latest AccountFeeSchedule row for ``key`` effective ``on``.

    When no row exists the caller gets ``{}`` (and therefore no caps to
    validate against). That fallback is deliberately loud (a warning),
    mirroring deposits' tax-rule lookup: the BB fee schedule must come
    from dated config data, so a missing seed must never fail silently.
    """
    from bank_accounts.models import AccountFeeSchedule

    on = on or date.today()
    row = (
        AccountFeeSchedule.objects.filter(key=key, effective_from__lte=on)
        .order_by("-effective_from")
        .first()
    )
    if row is None:
        logger.warning(
            "No AccountFeeSchedule row for key=%s effective on %s; "
            "maintenance-cap validation is unavailable until the "
            "fee schedule is seeded.",
            key,
            on,
        )
        return {}
    return row.params


def maintenance_cap_at(params, balance):
    """BB half-yearly maintenance cap at ``balance`` from schedule params.

    Savings params carry ``slabs`` of ``{"up_to", "fee"}`` (inclusive
    ceilings); current-account params carry a flat ``max_fee``.
    """
    balance = _d(balance)
    if "max_fee" in params:
        return _d(params["max_fee"])
    for slab in params.get("slabs", []):
        up_to = slab.get("up_to")
        if up_to is None or balance <= _d(up_to):
            return _d(slab["fee"])
    return None


def maintenance_fee_at(product, balance):
    """The product's published half-yearly maintenance fee at ``balance``.

    Returns None when the product's slabs are unpublished or no slab
    covers the balance.
    """
    if not product.maintenance_fee_slabs:
        return None
    slab = pick_fee_slab(product.maintenance_fee_slabs, balance)
    if slab is None:
        return None
    return _d(slab.get("fee", "0"))


BASIS_NOTES = {
    InterestBasis.UNKNOWN: (
        "Interest basis not published by the bank; the estimate assumes "
        "the stated balance is held for the full year."
    ),
    InterestBasis.LOWEST_MONTHLY: (
        "Interest is calculated on the lowest monthly balance; the "
        "estimate assumes the balance does not dip below the stated "
        "average in any month."
    ),
    InterestBasis.MONTHLY_MINIMUM: (
        "Interest is calculated on the monthly minimum balance; the "
        "estimate assumes the balance does not dip below the stated "
        "average in any month."
    ),
}


def evaluate_product(product, balance):
    """Evaluate one product for the net-annual-value scenario.

    Returns None when the product publishes no rate covering
    ``balance``. Otherwise returns a dict of Decimals/strings ready for
    serialisation, including the full fee breakdown and honesty flags.
    """
    balance = _d(balance)
    picked = rate_for_balance(product, balance)
    if picked is None:
        return None
    rate, rate_max = picked

    blocked_by_min_balance = product.min_balance_to_earn is not None and balance < _d(
        product.min_balance_to_earn
    )
    if blocked_by_min_balance:
        interest = money(0)
        interest_at_max = money(0) if rate_max is not None else None
    else:
        interest = money(balance * rate / Decimal("100"))
        interest_at_max = (
            money(balance * rate_max / Decimal("100"))
            if rate_max is not None and rate_max != rate
            else None
        )

    waivers = []

    maintenance_half = maintenance_fee_at(product, balance)
    maintenance_annual = (
        money(maintenance_half * 2) if maintenance_half is not None else None
    )

    if not product.debit_card_included:
        card_fee = money(0)
    elif product.debit_card_fee_annual is None:
        card_fee = None
    else:
        card_fee = money(product.debit_card_fee_annual)
        threshold = product.debit_card_waiver_min_balance
        if threshold is not None and balance >= _d(threshold):
            card_fee = money(0)
            waivers.append(
                "Debit card annual fee waived at this balance "
                f"(published waiver at average balance ≥ BDT {_d(threshold)})."
            )

    sms_fee = (
        money(product.sms_fee_annual) if product.sms_fee_annual is not None else None
    )
    online_fee = (
        money(product.online_banking_fee_annual)
        if product.online_banking_fee_annual is not None
        else None
    )

    lines = {
        "maintenance_fee_annual": maintenance_annual,
        "debit_card_fee_annual": card_fee,
        "sms_fee_annual": sms_fee,
        "online_banking_fee_annual": online_fee,
    }
    known = [value for value in lines.values() if value is not None]
    fees_complete = len(known) == len(lines)
    total_fees = money(sum(known, Decimal("0"))) if known else None
    net_value = money(interest - total_fees) if total_fees is not None else None
    net_at_max = (
        money(interest_at_max - total_fees)
        if interest_at_max is not None and total_fees is not None
        else None
    )

    return {
        "balance": money(balance),
        "rate": rate,
        "rate_max": rate_max,
        "is_range": rate_max is not None and rate_max != rate,
        "interest_basis": product.interest_basis,
        "basis_note": BASIS_NOTES.get(product.interest_basis, ""),
        "interest_blocked_by_min_balance": blocked_by_min_balance,
        "interest_earned": interest,
        "interest_earned_at_max_rate": interest_at_max,
        **lines,
        "total_fees": total_fees,
        "fees_complete": fees_complete,
        "waivers_applied": waivers,
        "net_annual_value": net_value,
        "net_annual_value_at_max_rate": net_at_max,
    }
