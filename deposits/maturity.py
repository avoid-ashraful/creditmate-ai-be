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

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from deposits.constants import Compounding, DepositKind

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


def get_tax_rule_params(key, on=None):
    """Return the params dict of the latest DepositTaxRule effective ``on``."""
    from deposits.models import DepositTaxRule

    on = on or date.today()
    rule = (
        DepositTaxRule.objects.filter(key=key, effective_from__lte=on)
        .order_by("-effective_from")
        .first()
    )
    return rule.params if rule else {}


def source_tax_rate_pct(product, *, has_tin=True, total_holding=None, on=None):
    """Source-tax percentage applying to a product's interest/profit.

    ``total_holding`` is the depositor's total holding relevant to the
    Sanchayapatra threshold; the scenario amount is used as the proxy when
    not supplied.
    """
    if getattr(product, "is_benchmark", False):
        params = get_tax_rule_params("sanchayapatra_source_tax", on)
        threshold = _d(params.get("threshold", "500000"))
        holding = _d(total_holding) if total_holding is not None else threshold
        if "pensioner" in (product.slug or "") and holding <= _d(
            params.get("pensioner_exempt_up_to", "500000")
        ):
            return Decimal("0")
        if holding <= threshold:
            return _d(params.get("at_or_below_threshold", "5"))
        return _d(params.get("above_threshold", "10"))
    params = get_tax_rule_params("bank_interest_source_tax", on)
    if has_tin:
        return _d(params.get("with_tin", "10"))
    return _d(params.get("without_tin", "15"))


def evaluate_product(
    product, rate_row, *, months, amount=None, instalment=None, has_tin=True, on=None
):
    """Evaluate one product/rate-row for a scenario.

    ``amount`` is the lump sum for FDR-like kinds; ``instalment`` the
    monthly payment for DPS. Ranking uses ``rate_row.rate_min`` (the lower
    bound); the at-max figure is returned for range display only.
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
    tax_pct = source_tax_rate_pct(product, has_tin=has_tin, total_holding=paid_in, on=on)
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
    if paid_in > 0 and months > 0:
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
