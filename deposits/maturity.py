"""Deposit maturity mathematics and source-tax rules.

This module is the single source of truth for deposit maths; the frontend
calculators mirror these exact formulas (see
``creditmate-ai-fe/src/utils/depositCalculator.ts``).

Conventions (validated against banks' published maturity tables):

* **FDR** — lump sum grown at the nominal annual rate with the product's
  compounding frequency. Where a bank does not publish its compounding
  (everything sourced from the BB chart), **annual compounding** is used
  and the API says so. ``at_maturity`` means simple interest.
* **DPS** — equal monthly instalments paid at the *start* of each month
  (annuity due), compounded monthly. This reproduces DBBL's published
  Deposit Plus maturity table to the taka at 3/5/8/10 years
  (BDT 500/month at 9.50% -> 20,897 / 38,514 / 72,054 / 100,328).
* **Source tax (AIT)** is charged on the interest/profit portion only and
  read from :class:`deposits.models.DepositTaxRule` rows (dated config):
  bank deposits 10% with TIN / 15% without; Sanchayapatra 5% when the
  total holding is at most BDT 5 lakh, else 10%; pensioner certificates
  are exempt up to BDT 5 lakh. Excise duty is *not* netted here (it
  depends on the depositor's total balances, not the product); the UI
  states that.
* **Ranking** uses the *lower* bound of a published rate range and the
  resulting net-of-tax maturity value — never the flattering end.
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from deposits.constants import Compounding, DepositKind

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _d(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value):
    """Round a Decimal amount to 2dp (paisa), half-up."""
    return _d(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def fdr_maturity(principal, rate_pct, months, compounding=Compounding.ANNUAL):
    """Gross maturity value of a lump-sum fixed deposit.

    Parameters
    ----------
    principal : Decimal
        Amount deposited (BDT).
    rate_pct : Decimal
        Nominal annual rate in percent (e.g. Decimal('8.25')).
    months : int
        Horizon in months.
    compounding : str
        One of the Compounding values.
    """
    principal = _d(principal)
    r = _d(rate_pct) / Decimal("100")
    m = int(months)
    if principal <= 0 or m <= 0:
        return money(principal)
    if compounding == Compounding.MONTHLY:
        value = principal * (1 + r / 12) ** m
    elif compounding == Compounding.QUARTERLY:
        value = principal * (1 + r / 4) ** (Decimal(m) / 3)
    elif compounding == Compounding.AT_MATURITY:
        value = principal * (1 + r * m / 12)
    else:  # ANNUAL (default; also the BB-chart assumption)
        value = principal * (1 + r) ** (Decimal(m) / 12)
    return money(value)


def dps_maturity(instalment, rate_pct, months):
    """Gross maturity value of a DPS (annuity due, monthly compounding)."""
    instalment = _d(instalment)
    r = _d(rate_pct) / Decimal("100")
    m = int(months)
    if instalment <= 0 or m <= 0:
        return money(0)
    if r == 0:
        return money(instalment * m)
    i = r / 12
    value = instalment * (((1 + i) ** m - 1) / i) * (1 + i)
    return money(value)


def dps_instalment_for_target(target, rate_pct, months):
    """Monthly instalment needed to reach ``target`` in ``months`` (goal-seek)."""
    target = _d(target)
    r = _d(rate_pct) / Decimal("100")
    m = int(months)
    if target <= 0 or m <= 0:
        return money(0)
    if r == 0:
        return money(target / m)
    i = r / 12
    factor = (((1 + i) ** m - 1) / i) * (1 + i)
    return money(target / factor)


def dps_effective_yield_pct(instalment, months, net_maturity):
    """Effective annual yield (%) of a DPS, given its net maturity value.

    Solves the monthly internal rate of return of the instalment stream
    (annuity due, matching :func:`dps_maturity`) whose future value equals
    ``net_maturity``, then annualises that monthly rate as an effective
    rate. Instalments are paid in over time, so annualising
    net/contributions as if every taka were invested up-front (the lump-sum
    formula) understates a DPS yield by roughly half.
    """
    instalment_f = float(_d(instalment))
    target = float(_d(net_maturity))
    m = int(months)
    if instalment_f <= 0 or m <= 0 or target <= 0:
        return 0.0
    paid_in = instalment_f * m
    if target == paid_in:
        return 0.0

    def future_value(monthly_rate):
        if monthly_rate == 0:
            return paid_in
        return (
            instalment_f
            * (((1 + monthly_rate) ** m - 1) / monthly_rate)
            * (1 + monthly_rate)
        )

    # future_value is monotonically increasing in the monthly rate on
    # (-1, ...); bisect on a generous bracket. Targets outside the bracket
    # converge to the nearer bound.
    lo, hi = -0.09, 0.05
    for _ in range(200):
        mid = (lo + hi) / 2
        if future_value(mid) < target:
            lo = mid
        else:
            hi = mid
    monthly = (lo + hi) / 2
    return ((1 + monthly) ** 12 - 1) * 100


def get_tax_rule_params(key, on=None):
    """Return the params dict of the latest DepositTaxRule effective ``on``.

    When no rule row exists the caller falls back to hard-coded defaults.
    That fallback is deliberately loud (a warning): tax rates are exactly
    the kind of thing that must come from dated data, not code.
    """
    from deposits.models import DepositTaxRule

    on = on or date.today()
    rule = (
        DepositTaxRule.objects.filter(key=key, effective_from__lte=on)
        .order_by("-effective_from")
        .first()
    )
    if rule is None:
        logger.warning(
            "No DepositTaxRule row for key=%s effective on %s; "
            "falling back to hard-coded source-tax defaults.",
            key,
            on,
        )
        return {}
    return rule.params


def resolve_tax_params(on=None):
    """Resolve every tax rule a scenario needs, once per request.

    Passing the result into :func:`evaluate_product` /
    :func:`source_tax_rate_pct` as ``tax_params`` avoids one DB query per
    product in a scenario loop.
    """
    return {
        "bank_interest_source_tax": get_tax_rule_params("bank_interest_source_tax", on),
        "sanchayapatra_source_tax": get_tax_rule_params("sanchayapatra_source_tax", on),
    }


def _tax_params_for(tax_params, key, on):
    """Params for ``key``: the pre-resolved dict if given, else a DB lookup."""
    if tax_params is not None:
        return tax_params.get(key) or {}
    return get_tax_rule_params(key, on)


def source_tax_rate_pct(
    product, *, has_tin=True, total_holding=None, on=None, tax_params=None
):
    """Source-tax percentage applying to a product's interest/profit.

    ``total_holding`` is the depositor's total holding relevant to the
    Sanchayapatra threshold; the scenario amount is used as the proxy when
    not supplied. ``tax_params`` may carry params pre-resolved by
    :func:`resolve_tax_params` (one lookup per request instead of per
    product).
    """
    if getattr(product, "is_benchmark", False):
        params = _tax_params_for(tax_params, "sanchayapatra_source_tax", on)
        threshold = _d(params.get("threshold", "500000"))
        holding = _d(total_holding) if total_holding is not None else threshold
        if getattr(product, "is_pensioner_scheme", False) and holding <= _d(
            params.get("pensioner_exempt_up_to", "500000")
        ):
            return Decimal("0")
        if holding <= threshold:
            return _d(params.get("at_or_below_threshold", "5"))
        return _d(params.get("above_threshold", "10"))
    params = _tax_params_for(tax_params, "bank_interest_source_tax", on)
    if has_tin:
        return _d(params.get("with_tin", "10"))
    return _d(params.get("without_tin", "15"))


def evaluate_product(
    product,
    rate_row,
    *,
    months,
    amount=None,
    instalment=None,
    has_tin=True,
    on=None,
    tax_params=None,
):
    """Evaluate one product/rate-row for a scenario.

    ``amount`` is the lump sum for FDR-like kinds; ``instalment`` the
    monthly payment for DPS. Ranking uses ``rate_row.rate_min`` (the lower
    bound); the at-max figure is returned for range display only.
    ``tax_params`` may carry params pre-resolved by
    :func:`resolve_tax_params`.
    Returns a dict of Decimals/strings ready for serialisation.
    """
    if product.kind == DepositKind.DPS:
        paid_in = _d(instalment) * months
        gross = dps_maturity(instalment, rate_row.rate_min, months)
        gross_max = (
            dps_maturity(instalment, rate_row.rate_max, months)
            if rate_row.rate_max != rate_row.rate_min
            else None
        )
    else:
        paid_in = _d(amount)
        gross = fdr_maturity(amount, rate_row.rate_min, months, product.compounding)
        gross_max = (
            fdr_maturity(amount, rate_row.rate_max, months, product.compounding)
            if rate_row.rate_max != rate_row.rate_min
            else None
        )
    interest = gross - paid_in
    tax_pct = source_tax_rate_pct(
        product,
        has_tin=has_tin,
        total_holding=paid_in,
        on=on,
        tax_params=tax_params,
    )
    tax = money(interest * tax_pct / Decimal("100")) if interest > 0 else money(0)
    net = gross - tax
    if gross_max is not None:
        interest_max = gross_max - paid_in
        tax_max = (
            money(interest_max * tax_pct / Decimal("100"))
            if interest_max > 0
            else money(0)
        )
        net_max = gross_max - tax_max
    else:
        net_max = None
    if product.kind == DepositKind.DPS and paid_in > 0 and months > 0:
        # Instalments trickle in over the term, so the yield is the IRR of
        # the instalment stream — not the lump-sum annualisation, which
        # would understate it by roughly half.
        net_yield = dps_effective_yield_pct(instalment, months, net)
    elif paid_in > 0 and months > 0:
        net_yield = ((float(net) / float(paid_in)) ** (12 / months) - 1) * 100
    else:
        net_yield = 0.0
    return {
        "rate_min": rate_row.rate_min,
        "rate_max": rate_row.rate_max,
        "is_range": rate_row.rate_max != rate_row.rate_min,
        "is_derived_rate": rate_row.is_derived,
        "total_contributions": money(paid_in),
        "gross_maturity": gross,
        "interest_earned": money(interest),
        "source_tax": tax,
        "source_tax_pct": tax_pct,
        "net_maturity": money(net),
        "net_maturity_at_max_rate": money(net_max) if net_max is not None else None,
        "effective_yield_pct": round(net_yield, 2),
    }


def pick_rate_row(product, *, months, amount):
    """Pick the most specific rate row covering (months, amount).

    Specificity = narrowest tenure span, then narrowest amount span (the
    same rule the docs promise). Returns None when nothing covers.
    """
    covering = [row for row in product.rates.all() if row.covers(months, amount)]
    if not covering:
        return None
    covering.sort(key=lambda row: (row.tenure_span, row.amount_span))
    return covering[0]
