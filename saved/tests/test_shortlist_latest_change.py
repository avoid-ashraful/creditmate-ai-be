"""Shortlist ``latest_change`` (redesign Phase 4, D4).

The shortlist payload carries each product's newest recorded field
change so the client can badge "Fee changed · <date>" — backed by a real
history row, or null when the product has none. No row, no marker.
"""

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCardFieldHistory
from deposits.models import DepositProduct

LIST_URL = "/api/v1/saved/shortlist/"
VERIFIED = VerificationStatus.VERIFIED


@pytest.fixture
def owner_client(db):
    user = get_user_model().objects.create_user(
        username="shortlist-owner", password="<redacted>"
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_latest_change_is_null_without_history(owner_client):
    bank = Bank.objects.create(name="Marker Bank PLC")
    card = CreditCardFactory(bank=bank)
    res = owner_client.post(
        LIST_URL, {"vertical": "cards", "key": str(card.pk)}, format="json"
    )
    assert res.status_code == 201
    assert res.data["latest_change"] is None


@pytest.mark.django_db
def test_latest_change_reports_the_newest_history_row(owner_client):
    bank = Bank.objects.create(name="Marker Bank PLC")
    card = CreditCardFactory(bank=bank)
    CreditCardFieldHistory.objects.create(
        card=card, field_name="apr", old_value="20", new_value="21"
    )
    newest = CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value=1000, new_value=1500
    )
    owner_client.post(LIST_URL, {"vertical": "cards", "key": str(card.pk)}, format="json")

    res = owner_client.get(LIST_URL)
    (item,) = res.data["results"]
    assert item["latest_change"] == {
        "field_name": "annual_fee",
        "changed_at": newest.created,
    }


@pytest.mark.django_db
def test_latest_change_works_for_slug_verticals(owner_client):
    bank = Bank.objects.create(name="Marker Bank PLC")
    deposit = DepositProduct.objects.create(
        bank=bank, kind="fdr", name="Marker FDR", verification_status=VERIFIED
    )
    from deposits.models import DepositFieldHistory

    row = DepositFieldHistory.objects.create(
        product=deposit,
        field_name="rate_0_12",
        old_value={"rate_min": "8.00", "rate_max": "8.50"},
        new_value={"rate_min": "8.25", "rate_max": "8.75"},
    )
    owner_client.post(
        LIST_URL, {"vertical": "deposits", "key": deposit.slug}, format="json"
    )
    res = owner_client.get(LIST_URL)
    (item,) = res.data["results"]
    assert item["latest_change"]["field_name"] == "rate_0_12"
    assert item["latest_change"]["changed_at"] == row.created
