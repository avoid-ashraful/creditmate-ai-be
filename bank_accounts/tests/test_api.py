"""API tests: filters, variant grouping, history gating, scenario ranking."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from bank_accounts.models import AccountProduct
from banks.models import Bank
from credit_cards.constants import VerificationStatus

LIST_URL = "/api/v1/account-products/"
SCENARIO_URL = "/api/v1/account-products/scenario/"

BB_MAINT = [
    {"balance_min": "0", "balance_max": "10000", "fee": "0"},
    {"balance_min": "10001", "balance_max": "25000", "fee": "100"},
    {"balance_min": "25001", "balance_max": "200000", "fee": "200"},
    {"balance_min": "200001", "balance_max": "1000000", "fee": "250"},
    {"balance_min": "1000001", "balance_max": None, "fee": "300"},
]
FLAT_3 = [{"balance_min": "0", "balance_max": None, "rate": "3.00"}]


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def bank(db):
    return Bank.objects.create(name="Test Bank PLC")


def make(bank, name, verified=True, **kwargs):
    defaults = {
        "account_type": "savings",
        "verification_status": (
            VerificationStatus.VERIFIED if verified else VerificationStatus.DRAFT
        ),
        "rate_slabs": FLAT_3,
        "maintenance_fee_slabs": BB_MAINT,
        "debit_card_fee_annual": Decimal("600"),
        "sms_fee_annual": Decimal("300"),
        "online_banking_fee_annual": Decimal("0"),
    }
    defaults.update(kwargs)
    return AccountProduct.objects.create(bank=bank, name=name, **defaults)


@pytest.mark.django_db
def test_list_excludes_drafts_and_variants_by_default(client, bank):
    base = make(bank, "Base Savings")
    make(bank, "Alo Variant", variant_of=base)
    make(bank, "Draft Savings", verified=False)
    response = client.get(LIST_URL)
    assert response.status_code == 200
    names = [row["name"] for row in response.data["results"]]
    assert names == ["Base Savings"]
    assert response.data["results"][0]["variants_count"] == 1


@pytest.mark.django_db
def test_list_include_variants(client, bank):
    base = make(bank, "Base Savings")
    make(bank, "Alo Variant", variant_of=base)
    response = client.get(LIST_URL, {"include_variants": "true"})
    names = {row["name"] for row in response.data["results"]}
    assert names == {"Base Savings", "Alo Variant"}


@pytest.mark.django_db
def test_list_filters(client, bank):
    make(bank, "Plain Savings")
    make(bank, "Plain Current", account_type="current")
    make(
        bank,
        "Mudaraba Savings",
        is_islamic=True,
        contract_type="mudaraba",
        rate_type="expected_profit",
    )
    make(bank, "Student Savings", segment="student")

    by_type = client.get(LIST_URL, {"account_type": "current"})
    assert [r["name"] for r in by_type.data["results"]] == ["Plain Current"]

    islamic = client.get(LIST_URL, {"is_islamic": "true"})
    assert [r["name"] for r in islamic.data["results"]] == ["Mudaraba Savings"]

    segment = client.get(LIST_URL, {"segment": "student"})
    assert [r["name"] for r in segment.data["results"]] == ["Student Savings"]

    by_bank = client.get(LIST_URL, {"bank": bank.id})
    assert by_bank.data["count"] == 4
    other_bank = client.get(LIST_URL, {"bank": 99999})
    assert other_bank.data["count"] == 0


@pytest.mark.django_db
def test_detail_by_slug_includes_variants(client, bank):
    base = make(bank, "Base Savings")
    variant = make(bank, "Alo Variant", variant_of=base)
    response = client.get(f"{LIST_URL}{base.slug}/")
    assert response.status_code == 200
    assert response.data["slug"] == base.slug
    assert [v["slug"] for v in response.data["variants"]] == [variant.slug]
    assert response.data["rate_slabs"] == FLAT_3


@pytest.mark.django_db
def test_detail_unknown_slug_404(client, db):
    assert client.get(f"{LIST_URL}no-such-product/").status_code == 404


@pytest.mark.django_db
def test_field_history_requires_auth(client, bank):
    product = make(bank, "Base Savings")
    response = client.get(f"{LIST_URL}{product.slug}/field-history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_field_history_for_authenticated_user(client, bank):
    product = make(bank, "Base Savings")
    product.debit_card_fee_annual = Decimal("700")
    product.save()
    user = get_user_model().objects.create_user(username="history-reader", password="x")
    client.force_authenticate(user)
    response = client.get(f"{LIST_URL}{product.slug}/field-history/")
    assert response.status_code == 200
    fields = {row["field_name"] for row in response.data["results"]}
    assert "debit_card_fee_annual" in fields


# --- scenario -----------------------------------------------------------------


@pytest.mark.django_db
def test_scenario_ranks_by_net_value(client, bank):
    # Flat 3% with BB fees: interest 1,500 - (400+600+300) = +200.
    make(bank, "Fee Heavy")
    # Flat 3% fee-free: interest 1,500 - 0 = +1,500, must rank first.
    make(
        bank,
        "Fee Free",
        maintenance_fee_slabs=[{"balance_min": "0", "balance_max": None, "fee": "0"}],
        debit_card_fee_annual=Decimal("0"),
        sms_fee_annual=Decimal("0"),
    )
    response = client.post(SCENARIO_URL, {"average_balance": "50000"}, format="json")
    assert response.status_code == 200
    names = [row["product"]["name"] for row in response.data["results"]]
    assert names == ["Fee Free", "Fee Heavy"]
    top = response.data["results"][0]
    assert Decimal(top["interest_earned"]) == Decimal("1500")
    assert Decimal(top["net_annual_value"]) == Decimal("1500")
    assert response.data["excluded_without_rate"] == 0
    # The BB-fixed maintenance explainer must be in the notes.
    assert any(
        "fixed by" in note and "Bangladesh Bank" in note
        for note in response.data["notes"]
    )
    # The net value counts recurring charges only; the exclusion of
    # one-off fees (cheque-book, closure, ...) must be disclosed.
    assert any(
        "Net value excludes cheque-book, closure and other one-off fees" in note
        for note in response.data["notes"]
    )


@pytest.mark.django_db
def test_scenario_excludes_salary_from_ranking(client, bank):
    make(bank, "Walk-in Savings")
    make(bank, "Payroll Savings", segment="salary")
    response = client.post(SCENARIO_URL, {"average_balance": "50000"}, format="json")
    ranked = [row["product"]["name"] for row in response.data["results"]]
    excluded = [row["product"]["name"] for row in response.data["segment_excluded"]]
    assert ranked == ["Walk-in Savings"]
    assert excluded == ["Payroll Savings"]


@pytest.mark.django_db
def test_scenario_unranked_without_any_fee_lines(client, bank):
    make(
        bank,
        "Mystery Fees",
        maintenance_fee_slabs=None,
        debit_card_fee_annual=None,
        sms_fee_annual=None,
        online_banking_fee_annual=None,
    )
    response = client.post(SCENARIO_URL, {"average_balance": "50000"}, format="json")
    assert response.data["results"] == []
    unranked = response.data["unranked_without_fees"]
    assert [row["product"]["name"] for row in unranked] == ["Mystery Fees"]
    assert unranked[0]["total_fees"] is None


@pytest.mark.django_db
def test_scenario_counts_products_without_rate_at_balance(client, bank):
    make(
        bank,
        "High Balance Only",
        rate_slabs=[{"balance_min": "100000", "balance_max": None, "rate": "0.50"}],
    )
    response = client.post(SCENARIO_URL, {"average_balance": "50000"}, format="json")
    assert response.data["results"] == []
    assert response.data["excluded_without_rate"] == 1


@pytest.mark.django_db
def test_scenario_account_type_filter(client, bank):
    make(bank, "Savings One")
    make(bank, "Current One", account_type="current")
    response = client.post(
        SCENARIO_URL,
        {"average_balance": "50000", "account_type": "current"},
        format="json",
    )
    names = [row["product"]["name"] for row in response.data["results"]]
    assert names == ["Current One"]
