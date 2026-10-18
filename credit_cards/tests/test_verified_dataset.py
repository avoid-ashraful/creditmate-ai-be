"""Schema checks for the verified card dataset fixture (verified_cards_2026-10-18.json)."""

import json
from collections import Counter
from pathlib import Path

import pytest

from django.core.management import call_command

from banks.models import Bank
from credit_cards.constants import MAX_INTEREST_RATE_APR, CardNetwork
from credit_cards.models import CreditCard

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "verified_cards_2026-10-18.json"
)
BANKS_SEED = Path(__file__).resolve().parents[2] / "all_banks.json"
ROWS = json.loads(FIXTURE.read_text(encoding="utf-8"))
VERIFIED = [row for row in ROWS if row["verification_status"] == "verified"]
HELD = [row for row in ROWS if row["verification_status"] == "draft"]


def test_fixture_has_only_verified_and_draft_rows():
    assert ROWS and VERIFIED and HELD
    assert {row["verification_status"] for row in ROWS} == {"verified", "draft"}


def test_every_verified_card_has_a_source_and_fee_data():
    for row in VERIFIED:
        assert row["source_url"].startswith("https://"), row["name"]
        assert " " not in row["source_url"], row["name"]
        assert row["verified_at"].startswith("2026-10-18"), row["name"]
        has_fee_data = (
            row["annual_fee"] is not None or row["interest_rate_apr"] is not None
        )
        has_fee_text = any(
            row[field]
            for field in (
                "cash_advance_fee",
                "late_payment_fee",
                "supplementary_card_fee",
                "foreign_transaction_fee",
            )
        )
        assert has_fee_data or has_fee_text, row["name"]


def test_numbers_are_sane():
    for row in ROWS:
        if row["interest_rate_apr"] is not None:
            assert 0 <= row["interest_rate_apr"] <= MAX_INTEREST_RATE_APR, row["name"]
        if row["annual_fee"] is not None:
            assert row["annual_fee"] >= 0, row["name"]
        if row["min_monthly_income"] is not None:
            assert row["min_monthly_income"] > 0, row["name"]
        assert row["card_network"] in {"", *CardNetwork.values}, row["name"]


def test_card_names_are_unique_per_bank():
    duplicates = [
        key for key, n in Counter((r["bank"], r["name"]) for r in ROWS).items() if n > 1
    ]
    assert duplicates == []


def test_banks_exist_in_seed_and_hsbc_is_inactive():
    seed = {b["fields"]["name"]: b["fields"] for b in json.loads(BANKS_SEED.read_text())}
    assert {row["bank"] for row in ROWS} <= set(seed)
    assert seed["HSBC"]["is_active"] is False
    assert seed["LankaBangla Finance PLC"]["schedule_charge_url"]
    assert not any(row["bank"] == "HSBC" for row in ROWS)


@pytest.mark.django_db()
def test_fixture_imports_and_only_verified_cards_are_public():
    call_command("import_cards", str(FIXTURE))
    assert CreditCard.objects.count() == len(ROWS)
    assert CreditCard.objects.public().count() == len(VERIFIED)
    assert Bank.objects.filter(credit_cards__verification_status="draft").exists()
    assert not CreditCard.objects.public().filter(verification_status="draft").exists()
