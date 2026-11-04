"""Loan cost maths — the single source of truth for EMI / total cost.

Conventions (stated here because every number the API returns follows
them; they mirror the existing frontend EMI/payoff calculator in
``src/utils/emiPayoffCalculator.ts`` and the CreditMate EMI conventions):

* Reducing-balance amortisation: monthly rate = annual % / 100 / 12.
* The EMI is the standard closed form ``P·r·(1+r)^n / ((1+r)^n − 1)``;
  for a 0% rate it degenerates to ``P / n``.
* Totals come from a month-by-month simulation: each month the borrower
  pays the EMI, except the final month pays only the remaining balance
  plus that month's interest. Total interest / total cost are therefore
  computed from the simulated schedule, not ``EMI × n``.
* Money is quantised to 2 dp, ROUND_HALF_UP (deposits convention).
* Simple-interest products (BHBFC): interest = principal × rate ×
  months/12 exactly once (no compounding, no reducing balance);
  EMI = (principal + interest) / months.
* Scenario total cost = principal + total interest + processing fee
  (incl. 15% VAT on the fee, the standard VAT on Bangladeshi bank fees).
  The processing fee is computed on the scenario amount with the
  product's published cap applied; where a bank publishes a fee RANGE,
  the highest published percentage is used and the response notes say so.
* Supervision charges (e.g. IDLC 1%) are returned separately and are NOT
  included in total cost — the response notes state this explicitly.
"""

from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")
VAT_ON_FEES = Decimal("0.15")


def _d(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value):
    return _d(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def monthly_emi(principal, annual_rate_percent, months, simple_interest=False):
    """Monthly instalment for ``principal`` at ``annual_rate_percent`` %."""
    principal = _d(principal)
    rate = _d(annual_rate_percent)
    months = int(months)
    if months <= 0:
        raise ValueError("months must be positive")
    if simple_interest:
        interest = principal * rate / Decimal("100") * Decimal(months) / Decimal("12")
        return money((principal + interest) / Decimal(months))
    r = rate / Decimal("100") / Decimal("12")
    if r == 0:
        return money(principal / Decimal(months))
    factor = (Decimal("1") + r) ** months
    return money(principal * r * factor / (factor - Decimal("1")))


def amortisation_totals(principal, annual_rate_percent, months, simple_interest=False):
    """Simulate the schedule; return (emi, total_interest, total_cost_of_credit).

    total_cost_of_credit here = principal + total interest (fees excluded —
    the scenario layer adds the processing fee explicitly).
    """
    principal = money(principal)
    rate = _d(annual_rate_percent)
    months = int(months)
    emi = monthly_emi(principal, rate, months, simple_interest=simple_interest)
    if simple_interest:
        total_interest = money(
            principal * rate / Decimal("100") * Decimal(months) / Decimal("12")
        )
        return emi, total_interest, money(principal + total_interest)
    r = rate / Decimal("100") / Decimal("12")
    balance = principal
    total_interest = Decimal("0")
    for month in range(months):
        interest = money(balance * r)
        total_interest += interest
        if month == months - 1:
            payment = money(balance + interest)
        else:
            payment = emi
        principal_part = payment - interest
        balance = money(balance - principal_part)
        if balance <= 0:
            break
    return emi, money(total_interest), money(principal + total_interest)


def processing_fee(product, amount):
    """Processing fee (excl. VAT) for a scenario amount, honouring the cap.

    Uses the highest published percentage when the bank publishes a range.
    Returns None when the product publishes no processing fee.
    """
    amount = _d(amount)
    percent = product.processing_fee_percent
    if percent is None:
        return None
    percent = _d(percent)
    if product.processing_fee_percent_max is not None:
        percent = max(percent, _d(product.processing_fee_percent_max))
    fee = amount * percent / Decimal("100")
    if product.processing_fee_cap_bdt:
        fee = min(fee, _d(product.processing_fee_cap_bdt))
    return money(fee)


def fee_with_vat(fee):
    if fee is None:
        return None
    return money(_d(fee) * (Decimal("1") + VAT_ON_FEES))
