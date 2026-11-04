"""Regulatory-cap flagging for loan products.

Compares a product's published terms against the latest dated
``RegulatoryCap`` rows (BB circular ceilings, seeded as data) and returns
human-readable WARNING strings. Flags are advisory, never hard errors:
NBFI regimes differ and some facilities are explicitly exempt (loans
against liquid securities are exempt from the personal-loan ceiling).

Seeded cap keys (see ``loans.ingestion.catalogue.REGULATORY_CAPS``):
``personal_loan_ceiling``, ``auto_loan_ceiling``, ``housing_loan_ceiling``.
"""

from .constants import LoanType
from .models import RegulatoryCap


def _params(key):
    rule = RegulatoryCap.latest(key)
    return rule.params if rule else {}


def product_cap_flags(product):
    """Return a list of warning strings for terms exceeding BB ceilings."""
    if product.loan_type == LoanType.PERSONAL:
        return _personal_flags(product)
    if product.loan_type == LoanType.CAR:
        return _car_flags(product)
    if product.loan_type == LoanType.HOME:
        return _home_flags(product)
    # Secured-against-deposit products are exempt from the personal ceiling
    # (loans against liquid securities, Regulation 30) — no flags by design.
    return []


def _personal_flags(product):
    flags = []
    params = _params("personal_loan_ceiling")
    ceiling = params.get("max_amount_bdt")
    if ceiling and product.amount_max_bdt and product.amount_max_bdt > ceiling:
        flags.append(
            f"Published maximum Tk {product.amount_max_bdt:,} exceeds the "
            f"Bangladesh Bank personal-loan ceiling of Tk {ceiling:,}."
        )
    unsecured_ceiling = params.get("unsecured_max_bdt")
    if unsecured_ceiling:
        marketed_unsecured = (
            product.unsecured_max_bdt
            if product.unsecured_max_bdt is not None
            else (product.amount_max_bdt if not product.secured_by else None)
        )
        if marketed_unsecured and marketed_unsecured > unsecured_ceiling:
            flags.append(
                f"Marketed as unsecured up to Tk {marketed_unsecured:,}, above "
                f"the Tk {unsecured_ceiling:,} ceiling for unsecured personal "
                "loans — security will likely be required above that amount."
            )
    max_tenure = params.get("max_tenure_months")
    if (
        max_tenure
        and product.tenure_max_months
        and product.tenure_max_months > max_tenure
    ):
        flags.append(
            f"Published tenure up to {product.tenure_max_months} months exceeds "
            f"the {max_tenure}-month regulatory maximum for personal loans."
        )
    return flags


def _car_flags(product):
    flags = []
    params = _params("auto_loan_ceiling")
    ceiling = params.get("max_amount_bdt")
    ev_ceiling = params.get("max_amount_ev_hybrid_bdt")
    if ceiling and product.amount_max_bdt:
        by_purpose = product.max_amount_by_purpose or {}
        conventional_max = by_purpose.get("conventional", product.amount_max_bdt)
        if conventional_max and conventional_max > ceiling:
            flags.append(
                f"Published maximum Tk {conventional_max:,} for conventional "
                f"vehicles exceeds the Tk {ceiling:,} auto-loan ceiling."
            )
        if ev_ceiling and product.amount_max_bdt > max(ev_ceiling, ceiling):
            flags.append(
                f"Published maximum Tk {product.amount_max_bdt:,} exceeds even "
                f"the Tk {ev_ceiling:,} ceiling for EV/hybrid vehicles."
            )
    ltv = params.get("ltv_percent")
    if ltv and product.ltv_percent and float(product.ltv_percent) > float(ltv):
        ltv_by_type = product.ltv_by_vehicle_type or {}
        ev_ltv = params.get("ltv_ev_hybrid_percent")
        exceeds_ev = not ev_ltv or float(product.ltv_percent) > float(ev_ltv)
        only_ev = bool(ltv_by_type) and all(
            float(v) <= float(ev_ltv or 0) for v in ltv_by_type.values()
        )
        if exceeds_ev and not only_ev:
            flags.append(
                f"Published LTV of {product.ltv_percent}% exceeds the {ltv}% "
                "regulatory maximum for conventional vehicles."
            )
    return flags


def _home_flags(product):
    flags = []
    params = _params("housing_loan_ceiling")
    ceiling = params.get("max_amount_bdt")
    if ceiling and product.amount_max_bdt and product.amount_max_bdt > ceiling:
        flags.append(
            f"Published maximum Tk {product.amount_max_bdt:,} exceeds the "
            f"Tk {ceiling:,} housing-loan ceiling for eligible lenders."
        )
    ltv = params.get("ltv_percent")
    if ltv and product.ltv_percent and float(product.ltv_percent) > float(ltv):
        flags.append(
            f"Published LTV of {product.ltv_percent}% exceeds the {ltv}% "
            "(70:30) regulatory anchor for housing loans."
        )
    return flags
