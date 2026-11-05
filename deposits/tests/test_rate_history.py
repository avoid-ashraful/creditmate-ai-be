"""Deposit list ``rate_history`` aggregate (redesign Phase 4).

The list payload gains a compact published-rate history for each
product's headline rate cell, reconstructed from real field-history
rows. No recorded changes -> only the current value; rates are never
interpolated or invented.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from deposits.models import DepositFieldHistory, DepositProduct, DepositRate

LIST_URL = "/api/v1/deposit-products/"
VERIFIED = VerificationStatus.VERIFIED


def _product(bank, name="History FDR"):
    return DepositProduct.objects.create(
        bank=bank, kind="fdr", name=name, verification_status=VERIFIED
    )


def _rate(product, tmin, tmax, rate):
    return DepositRate.objects.create(
        product=product,
        tenure_months_min=tmin,
        tenure_months_max=tmax,
        rate_min=Decimal(rate),
        rate_max=Decimal(rate),
    )


def _history(product, field, old, new):
    payload = lambda v: None if v is None else {"rate_min": v, "rate_max": v}
    return DepositFieldHistory.objects.create(
        product=product, field_name=field, old_value=payload(old), new_value=payload(new)
    )


@pytest.fixture
def bank(db):
    return Bank.objects.create(name="History Bank PLC")


@pytest.mark.django_db
def test_no_rates_no_history(bank):
    _product(bank)
    res = APIClient().get(LIST_URL)
    (item,) = [r for r in res.data["results"] if r["name"] == "History FDR"]
    assert item["rate_history"] is None


@pytest.mark.django_db
def test_current_value_only_without_recorded_changes(bank):
    product = _product(bank)
    _rate(product, 0, 12, "9.50")
    res = APIClient().get(LIST_URL)
    (item,) = [r for r in res.data["results"] if r["name"] == "History FDR"]
    history = item["rate_history"]
    assert history["tenure_months_min"] == 0
    assert history["tenure_months_max"] == 12
    assert [p["value"] for p in history["points"]] == ["9.5"]


@pytest.mark.django_db
def test_series_reconstructed_from_history_rows(bank):
    product = _product(bank)
    _rate(product, 0, 12, "9.75")
    _history(product, "rate_0_12", "8.50", "9.00")
    _history(product, "rate_0_12", "9.00", "9.75")
    res = APIClient().get(LIST_URL)
    (item,) = [r for r in res.data["results"] if r["name"] == "History FDR"]
    points = item["rate_history"]["points"]
    # Stepped-from value first, then each recorded step, ending at the
    # live rate — nothing interpolated in between.
    assert [p["value"] for p in points] == ["8.5", "9", "9.75"]


@pytest.mark.django_db
def test_headline_cell_prefers_the_12_month_covering_cell(bank):
    product = _product(bank)
    _rate(product, 0, 3, "7.00")
    _rate(product, 6, 12, "9.25")
    _rate(product, 12, 36, "11.00")
    res = APIClient().get(LIST_URL)
    (item,) = [r for r in res.data["results"] if r["name"] == "History FDR"]
    history = item["rate_history"]
    assert (history["tenure_months_min"], history["tenure_months_max"]) == (6, 12)
    assert [p["value"] for p in history["points"]] == ["9.25"]


@pytest.mark.django_db
def test_series_is_capped_at_six_points(bank):
    product = _product(bank)
    _rate(product, 0, 12, "10.00")
    steps = ["7.00", "7.50", "8.00", "8.50", "9.00", "9.50", "10.00"]
    for old, new in zip(steps, steps[1:]):
        _history(product, "rate_0_12", old, new)
    res = APIClient().get(LIST_URL)
    (item,) = [r for r in res.data["results"] if r["name"] == "History FDR"]
    points = item["rate_history"]["points"]
    assert len(points) == 6
    assert points[-1]["value"] == "10"
