"""Model tests: Islamic rule, variant validation, BB maintenance cap."""

import logging
from datetime import date

import pytest

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from bank_accounts.constants import (
    SCHEDULE_CURRENT_MAINTENANCE_CAP,
    SCHEDULE_SAVINGS_MAINTENANCE,
)
from bank_accounts.models import AccountFeeSchedule, AccountProduct
from banks.models import Bank


@pytest.fixture
def bank(db):
    return Bank.objects.create(name="Test Bank PLC")


@pytest.fixture
def fee_schedules(db):
    AccountFeeSchedule.objects.create(
        key=SCHEDULE_SAVINGS_MAINTENANCE,
        effective_from=date(2019, 10, 1),
        params={
            "period": "half_yearly",
            "slabs": [
                {"up_to": "10000", "fee": "0"},
                {"up_to": "25000", "fee": "100"},
                {"up_to": "200000", "fee": "200"},
                {"up_to": "1000000", "fee": "250"},
                {"up_to": None, "fee": "300"},
            ],
        },
    )
    AccountFeeSchedule.objects.create(
        key=SCHEDULE_CURRENT_MAINTENANCE_CAP,
        effective_from=date(2019, 10, 1),
        params={"period": "half_yearly", "max_fee": "300"},
    )


def make(bank, **kwargs):
    defaults = {"account_type": "savings", "name": "Test Savings"}
    defaults.update(kwargs)
    return AccountProduct.objects.create(bank=bank, **defaults)


@pytest.mark.django_db
def test_islamic_product_cannot_use_interest_rate_type(bank):
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            make(
                bank,
                is_islamic=True,
                contract_type="mudaraba",
                rate_type="interest",
            )


@pytest.mark.django_db
def test_islamic_clean_rejects_interest(bank):
    product = AccountProduct(
        bank=bank,
        account_type="savings",
        name="Bad Islamic",
        is_islamic=True,
        contract_type="mudaraba",
        rate_type="interest",
    )
    with pytest.raises(ValidationError):
        product.clean()


@pytest.mark.django_db
def test_islamic_expected_profit_is_accepted(bank):
    product = make(
        bank, is_islamic=True, contract_type="mudaraba", rate_type="expected_profit"
    )
    assert product.rate_type == "expected_profit"


@pytest.mark.django_db
def test_variant_must_be_same_bank(bank, db):
    other = Bank.objects.create(name="Other Bank PLC")
    base = make(bank, name="Base")
    variant = AccountProduct(
        bank=other, account_type="savings", name="Variant", variant_of=base
    )
    with pytest.raises(ValidationError):
        variant.clean()


@pytest.mark.django_db
def test_variant_cannot_be_itself(bank):
    product = make(bank, name="Self")
    product.variant_of = product
    with pytest.raises(ValidationError):
        product.clean()


@pytest.mark.django_db
def test_slug_auto_generated_from_bank_and_name(bank):
    product = make(bank, name="My Savings")
    assert product.slug == "test-bank-plc-my-savings"


def bb_slabs(top_fee="300"):
    return [
        {"balance_min": "0", "balance_max": "10000", "fee": "0"},
        {"balance_min": "10001", "balance_max": "25000", "fee": "100"},
        {"balance_min": "25001", "balance_max": "200000", "fee": "200"},
        {"balance_min": "200001", "balance_max": "1000000", "fee": "250"},
        {"balance_min": "1000001", "balance_max": None, "fee": top_fee},
    ]


@pytest.mark.django_db
def test_bb_slab_product_has_no_maintenance_warnings(bank, fee_schedules):
    product = make(bank, maintenance_fee_slabs=bb_slabs())
    assert product.maintenance_warnings() == []


@pytest.mark.django_db
def test_over_cap_maintenance_fee_warns(bank, fee_schedules):
    product = make(bank, maintenance_fee_slabs=bb_slabs(top_fee="350"))
    warnings = product.maintenance_warnings()
    assert warnings
    assert any("350" in w for w in warnings)


@pytest.mark.django_db
def test_free_above_top_band_does_not_warn(bank, fee_schedules):
    # Charging less than the cap is legitimate (e.g. BRAC Golden Benefit
    # is free above Tk 10 lakh) — only exceeding it warns.
    product = make(bank, maintenance_fee_slabs=bb_slabs(top_fee="0"))
    assert product.maintenance_warnings() == []


@pytest.mark.django_db
def test_maintenance_warnings_accepts_preresolved_params(bank):
    # The admin changelist resolves the schedule params once and passes
    # them in; validation must work from the dict alone (no schedule
    # rows in the DB here) and still flag an over-cap fee.
    params_by_key = {
        SCHEDULE_SAVINGS_MAINTENANCE: {
            "period": "half_yearly",
            "slabs": [
                {"up_to": "10000", "fee": "0"},
                {"up_to": "25000", "fee": "100"},
                {"up_to": "200000", "fee": "200"},
                {"up_to": "1000000", "fee": "250"},
                {"up_to": None, "fee": "300"},
            ],
        },
        SCHEDULE_CURRENT_MAINTENANCE_CAP: {"period": "half_yearly", "max_fee": "300"},
    }
    product = make(bank, maintenance_fee_slabs=bb_slabs(top_fee="350"))
    warnings = product.maintenance_warnings(params_by_key=params_by_key)
    assert warnings
    assert any("350" in w for w in warnings)


@pytest.mark.django_db
def test_missing_fee_schedule_config_logs_loud_warning(bank, caplog):
    # No AccountFeeSchedule rows seeded: validation cannot run, and that
    # must be loud (mirrors deposits' missing tax-rule warning), never a
    # silent pass.
    product = make(bank, maintenance_fee_slabs=bb_slabs())
    with caplog.at_level(logging.WARNING, logger="bank_accounts.netvalue"):
        assert product.maintenance_warnings() == []
    assert any(
        SCHEDULE_SAVINGS_MAINTENANCE in record.getMessage()
        and record.levelno == logging.WARNING
        for record in caplog.records
    )


@pytest.mark.django_db
def test_current_account_over_cap_warns(bank, fee_schedules):
    product = make(
        bank,
        account_type="current",
        name="Pricey Current",
        maintenance_fee_slabs=[{"balance_min": "0", "balance_max": None, "fee": "400"}],
    )
    warnings = product.maintenance_warnings()
    assert warnings
    assert any("300" in w for w in warnings)
