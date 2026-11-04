"""Net-annual-value engine tests with hand-computed examples.

The 50,000-taka cases mirror real published products (City Bank
General/Basic savings, EBL Classic) so the arithmetic is anchored to
the researched data, not invented fixtures.
"""

from decimal import Decimal

import pytest

from bank_accounts.models import AccountProduct
from bank_accounts.netvalue import (
    evaluate_product,
    pick_fee_slab,
    pick_slab,
    rate_for_balance,
)

BB_MAINT = [
    {"balance_min": "0", "balance_max": "10000", "fee": "0"},
    {"balance_min": "10001", "balance_max": "25000", "fee": "100"},
    {"balance_min": "25001", "balance_max": "200000", "fee": "200"},
    {"balance_min": "200001", "balance_max": "1000000", "fee": "250"},
    {"balance_min": "1000001", "balance_max": None, "fee": "300"},
]


def product(**kwargs):
    defaults = {"account_type": "savings", "name": "P"}
    defaults.update(kwargs)
    return AccountProduct(**defaults)


# --- slab picking ------------------------------------------------------------


def test_pick_slab_boundaries():
    slabs = [
        {"balance_min": "0", "balance_max": "100000", "rate": "0"},
        {"balance_min": "100000", "balance_max": None, "rate": "0.25"},
    ]
    assert pick_slab(slabs, Decimal("99999"))["rate"] == "0"
    # A balance exactly at a boundary belongs to the upper slab ([min, max)).
    assert pick_slab(slabs, Decimal("100000"))["rate"] == "0.25"
    assert pick_slab(slabs, Decimal("0"))["rate"] == "0"


def test_pick_slab_no_covering_slab_returns_none():
    slabs = [{"balance_min": "100000", "balance_max": None, "rate": "0.50"}]
    assert pick_slab(slabs, Decimal("50000")) is None


def test_rate_for_balance_none_when_unpublished():
    p = product(rate_slabs=[])
    assert rate_for_balance(p, Decimal("50000")) is None


def test_pick_fee_slab_inclusive_ceilings():
    # BB bands as printed: exactly Tk 10,000 is still free.
    assert pick_fee_slab(BB_MAINT, Decimal("10000"))["fee"] == "0"
    assert pick_fee_slab(BB_MAINT, Decimal("10001"))["fee"] == "100"
    assert pick_fee_slab(BB_MAINT, Decimal("50000"))["fee"] == "200"
    assert pick_fee_slab(BB_MAINT, Decimal("250000"))["fee"] == "250"
    assert pick_fee_slab(BB_MAINT, Decimal("1000001"))["fee"] == "300"


def test_pick_fee_slab_config_schedule_boundaries():
    # The same thresholds through the *config* schedule shape used by
    # maintenance_cap_at: 10,000 -> 0; 10,001 -> 100; 50,000 -> 200;
    # 1,000,001 -> 300.
    from bank_accounts.netvalue import maintenance_cap_at

    params = {
        "slabs": [
            {"up_to": "10000", "fee": "0"},
            {"up_to": "25000", "fee": "100"},
            {"up_to": "200000", "fee": "200"},
            {"up_to": "1000000", "fee": "250"},
            {"up_to": None, "fee": "300"},
        ]
    }
    assert maintenance_cap_at(params, Decimal("10000")) == Decimal("0")
    assert maintenance_cap_at(params, Decimal("10001")) == Decimal("100")
    assert maintenance_cap_at(params, Decimal("50000")) == Decimal("200")
    assert maintenance_cap_at(params, Decimal("1000001")) == Decimal("300")


# --- hand-computed evaluations at BDT 50,000 ---------------------------------

CITY_GENERAL = dict(
    rate_slabs=[
        {"balance_min": "0", "balance_max": "100000", "rate": "0"},
        {"balance_min": "100000", "balance_max": None, "rate": "0.25"},
    ],
    maintenance_fee_slabs=BB_MAINT,
    debit_card_fee_annual=Decimal("600"),
    sms_fee_annual=Decimal("300"),
    online_banking_fee_annual=Decimal("0"),
)


def test_city_general_at_50k_hand_computed():
    # 0% slab below Tk 1 lakh: interest 0. Fees: maintenance 200 x2 = 400,
    # card 600, SMS 300, online 0 -> total 1,300; net -1,300.
    result = evaluate_product(product(**CITY_GENERAL), Decimal("50000"))
    assert result["interest_earned"] == Decimal("0")
    assert result["maintenance_fee_annual"] == Decimal("400")
    assert result["debit_card_fee_annual"] == Decimal("600")
    assert result["sms_fee_annual"] == Decimal("300")
    assert result["total_fees"] == Decimal("1300")
    assert result["fees_complete"] is True
    assert result["net_annual_value"] == Decimal("-1300")


def test_city_basic_at_50k_hand_computed():
    # Flat 3.00% at every balance: interest 1,500. No maintenance fee;
    # card fee unpublished for this product (null), SMS 300, online 0
    # -> known total 300, net +1,200, flagged fees_complete=False.
    result = evaluate_product(
        product(
            rate_slabs=[{"balance_min": "0", "balance_max": None, "rate": "3.00"}],
            maintenance_fee_slabs=[{"balance_min": "0", "balance_max": None, "fee": "0"}],
            debit_card_fee_annual=None,
            sms_fee_annual=Decimal("300"),
            online_banking_fee_annual=Decimal("0"),
        ),
        Decimal("50000"),
    )
    assert result["interest_earned"] == Decimal("1500")
    assert result["debit_card_fee_annual"] is None
    assert result["total_fees"] == Decimal("300")
    assert result["fees_complete"] is False
    assert result["net_annual_value"] == Decimal("1200")


def test_ebl_classic_at_50k_partial_fees():
    # 0.50% slab at 50k: interest 250. Maintenance 400/yr, SMS 400,
    # card unpublished (null), online 0 -> known total 800, net -550.
    result = evaluate_product(
        product(
            rate_slabs=[
                {"balance_min": "0", "balance_max": "50000", "rate": "0"},
                {"balance_min": "50000", "balance_max": "500000", "rate": "0.50"},
                {"balance_min": "500000", "balance_max": None, "rate": "1.00"},
            ],
            maintenance_fee_slabs=BB_MAINT,
            debit_card_fee_annual=None,
            sms_fee_annual=Decimal("400"),
            online_banking_fee_annual=Decimal("0"),
        ),
        Decimal("50000"),
    )
    assert result["interest_earned"] == Decimal("250")
    assert result["total_fees"] == Decimal("800")
    assert result["fees_complete"] is False
    assert result["net_annual_value"] == Decimal("-550")


# --- waiver policy ------------------------------------------------------------


def waiver_product(balance_threshold="50000"):
    return product(
        rate_slabs=[{"balance_min": "0", "balance_max": None, "rate": "1.00"}],
        maintenance_fee_slabs=BB_MAINT,
        debit_card_fee_annual=Decimal("600"),
        debit_card_waiver_min_balance=Decimal(balance_threshold),
        sms_fee_annual=Decimal("0"),
        online_banking_fee_annual=Decimal("0"),
    )


def test_card_waiver_applies_at_threshold():
    result = evaluate_product(waiver_product(), Decimal("50000"))
    assert result["debit_card_fee_annual"] == Decimal("0")
    assert result["waivers_applied"]


def test_card_waiver_does_not_apply_one_taka_below():
    result = evaluate_product(waiver_product(), Decimal("49999"))
    assert result["debit_card_fee_annual"] == Decimal("600")
    assert result["waivers_applied"] == []


def test_first_year_waiver_does_not_reduce_steady_state():
    # A first-year-free card still charges the annual fee in the
    # steady-state (year-2) net value.
    p = waiver_product()
    p.debit_card_waiver_min_balance = None
    p.debit_card_first_year_fee = Decimal("0")
    result = evaluate_product(p, Decimal("50000"))
    assert result["debit_card_fee_annual"] == Decimal("600")


# --- min-balance-to-earn and ranges ------------------------------------------


def test_min_balance_to_earn_blocks_interest():
    p = product(
        rate_slabs=[{"balance_min": "0", "balance_max": None, "rate": "2.00"}],
        min_balance_to_earn=Decimal("10000"),
        maintenance_fee_slabs=BB_MAINT,
        debit_card_fee_annual=Decimal("0"),
        sms_fee_annual=Decimal("0"),
        online_banking_fee_annual=Decimal("0"),
    )
    result = evaluate_product(p, Decimal("5000"))
    assert result["interest_earned"] == Decimal("0")
    assert result["interest_blocked_by_min_balance"] is True


def test_range_rate_reports_both_ends():
    p = product(
        rate_type="expected_profit",
        rate_slabs=[
            {
                "balance_min": "0",
                "balance_max": None,
                "rate": "2.50",
                "rate_max": "3.85",
            }
        ],
        maintenance_fee_slabs=None,
        debit_card_fee_annual=None,
        sms_fee_annual=None,
        online_banking_fee_annual=None,
    )
    result = evaluate_product(p, Decimal("100000"))
    assert result["is_range"] is True
    assert result["interest_earned"] == Decimal("2500")
    assert result["interest_earned_at_max_rate"] == Decimal("3850")
    # No fee lines published at all -> no total, no net value.
    assert result["total_fees"] is None
    assert result["net_annual_value"] is None


def test_no_rate_at_balance_returns_none():
    p = product(
        rate_slabs=[{"balance_min": "100000", "balance_max": None, "rate": "0.50"}]
    )
    assert evaluate_product(p, Decimal("50000")) is None


def test_lowest_monthly_basis_note_discloses_assumption():
    p = product(
        rate_slabs=[{"balance_min": "0", "balance_max": None, "rate": "1.00"}],
        interest_basis="lowest_monthly_balance",
        maintenance_fee_slabs=BB_MAINT,
        debit_card_fee_annual=Decimal("0"),
        sms_fee_annual=Decimal("0"),
        online_banking_fee_annual=Decimal("0"),
    )
    result = evaluate_product(p, Decimal("50000"))
    assert "lowest" in result["basis_note"].lower()


@pytest.mark.django_db
def test_fee_schedule_params_reads_latest_effective(db):
    from datetime import date

    from bank_accounts.models import AccountFeeSchedule
    from bank_accounts.netvalue import fee_schedule_params

    AccountFeeSchedule.objects.create(
        key="savings_maintenance",
        effective_from=date(2019, 10, 1),
        params={"max_fee": "300"},
    )
    AccountFeeSchedule.objects.create(
        key="savings_maintenance",
        effective_from=date(2030, 1, 1),
        params={"max_fee": "999"},
    )
    # The future row must not leak into today's params.
    assert fee_schedule_params("savings_maintenance") == {"max_fee": "300"}
