"""Tests for the bank-follow change feed (redesign Phase 3, D4).

Endpoint: GET /api/v1/alerts/feed/?page=&page_size=

The feed merges field-history rows from all four verticals for the banks
the user follows — nothing for banks they do not follow, nothing invented.
"""

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from alerts.models import BankFollow
from bank_accounts.models import AccountFieldHistory, AccountProduct
from banks.factories import BankFactory
from credit_cards.constants import VerificationStatus
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCardFieldHistory
from deposits.models import DepositFieldHistory, DepositProduct
from loans.models import LoanFieldHistory, LoanProduct

FEED_URL = "/api/v1/alerts/feed/"
VERIFIED = VerificationStatus.VERIFIED


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="feed-reader", password="x")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="feed-other", password="x")


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def banks(db):
    return BankFactory.create_batch(2)


@pytest.fixture
def history(banks):
    """One change at the first bank, two at the second, across verticals."""
    bank_a, bank_b = banks
    card = CreditCardFactory(bank=bank_a)
    CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value=1000, new_value=1500
    )
    deposit = DepositProduct.objects.create(
        bank=bank_b, kind="fdr", name="Feed FDR", verification_status=VERIFIED
    )
    DepositFieldHistory.objects.create(
        product=deposit,
        field_name="rate_0_12",
        old_value={"rate_min": "8.00", "rate_max": "8.50"},
        new_value={"rate_min": "8.25", "rate_max": "8.75"},
    )
    loan = LoanProduct.objects.create(
        bank=bank_b,
        loan_type="personal",
        name="Feed Loan",
        verification_status=VERIFIED,
        is_active=True,
    )
    LoanFieldHistory.objects.create(
        product=loan,
        field_name="rate_max",
        old_value="13.00",
        new_value="13.50",
        source="bb_chart",
    )
    account = AccountProduct.objects.create(
        bank=bank_b,
        account_type="savings",
        name="Feed Savings",
        verification_status=VERIFIED,
        rate_slabs=[],
    )
    AccountFieldHistory.objects.create(
        product=account, field_name="sms_fee_annual", old_value=300, new_value=345
    )
    return bank_a, bank_b


@pytest.mark.django_db
def test_anonymous_is_rejected():
    assert APIClient().get(FEED_URL).status_code in (401, 403)


@pytest.mark.django_db
def test_user_following_nothing_gets_an_empty_feed(auth_client):
    response = auth_client.get(FEED_URL)
    assert response.status_code == 200
    assert response.data["results"] == []
    assert response.data["has_more"] is False


@pytest.mark.django_db
def test_feed_shows_only_followed_banks(auth_client, user, history):
    bank_a, _bank_b = history
    BankFollow.objects.create(user=user, bank=bank_a)
    response = auth_client.get(FEED_URL)
    rows = response.data["results"]
    assert len(rows) == 1
    row = rows[0]
    assert row["vertical"] == "cards"
    assert row["field_name"] == "annual_fee"
    assert row["old_value"] == 1000
    assert row["new_value"] == 1500
    assert row["bank_id"] == bank_a.id
    assert row["changed_at"]


@pytest.mark.django_db
def test_feed_merges_all_verticals_newest_first(auth_client, user, history):
    bank_a, bank_b = history
    BankFollow.objects.create(user=user, bank=bank_a)
    BankFollow.objects.create(user=user, bank=bank_b)
    response = auth_client.get(FEED_URL)
    rows = response.data["results"]
    assert len(rows) == 4
    verticals = {row["vertical"] for row in rows}
    assert verticals == {"cards", "deposits", "loans", "accounts"}
    stamps = [row["changed_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True)
    loan_row = next(row for row in rows if row["vertical"] == "loans")
    assert loan_row["source"] == "bb_chart"
    assert loan_row["product_key"]


@pytest.mark.django_db
def test_feed_is_scoped_per_user(auth_client, other_user, history):
    bank_a, _bank_b = history
    BankFollow.objects.create(user=other_user, bank=bank_a)
    response = auth_client.get(FEED_URL)
    assert response.data["results"] == []


@pytest.mark.django_db
def test_feed_pagination_and_has_more(auth_client, user, history):
    bank_a, bank_b = history
    BankFollow.objects.create(user=user, bank=bank_a)
    BankFollow.objects.create(user=user, bank=bank_b)

    page1 = auth_client.get(FEED_URL, {"page": 1, "page_size": 3})
    assert len(page1.data["results"]) == 3
    assert page1.data["has_more"] is True

    page2 = auth_client.get(FEED_URL, {"page": 2, "page_size": 3})
    assert len(page2.data["results"]) == 1
    assert page2.data["has_more"] is False

    ids = {row["id"] for row in page1.data["results"]} | {
        row["id"] for row in page2.data["results"]
    }
    assert len(ids) == 4
