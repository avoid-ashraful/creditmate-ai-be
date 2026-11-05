"""Tests for the server-backed shortlist (redesign Phase 3, Section 4.7).

Endpoints:
- GET    /api/v1/saved/shortlist/                     — list my shortlist
- POST   /api/v1/saved/shortlist/                     — add (idempotent)
- POST   /api/v1/saved/shortlist/import/              — merge a device list
- DELETE /api/v1/saved/shortlist/<vertical>/<key>/    — remove (idempotent)

Identity is (vertical, key): card id as a string for cards, product slug
for deposits, loans and accounts — the on-device shortlist's own keys.
"""

import pytest

from django.db import IntegrityError, transaction

from bank_accounts.models import AccountProduct
from banks.models import Bank
from credit_cards.constants import VerificationStatus
from deposits.models import DepositProduct
from loans.models import LoanProduct
from saved.models import ShortlistItem

LIST_URL = "/api/v1/saved/shortlist/"
IMPORT_URL = "/api/v1/saved/shortlist/import/"

VERIFIED = VerificationStatus.VERIFIED


@pytest.fixture
def bank(db):
    return Bank.objects.create(name="Shortlist Bank PLC")


@pytest.fixture
def deposit(bank):
    return DepositProduct.objects.create(
        bank=bank, kind="fdr", name="Alpha FDR", verification_status=VERIFIED
    )


@pytest.fixture
def loan(bank):
    return LoanProduct.objects.create(
        bank=bank,
        loan_type="personal",
        name="Alpha Personal Loan",
        verification_status=VERIFIED,
        is_active=True,
    )


def add(client, vertical, key):
    return client.post(LIST_URL, {"vertical": vertical, "key": key}, format="json")


@pytest.mark.django_db
def test_anonymous_cannot_read_or_write(anonymous_client, cards):
    assert anonymous_client.get(LIST_URL).status_code in (401, 403)
    response = add(anonymous_client, "cards", str(cards[0].id))
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_add_card_returns_client_item_shape(owner_client, cards):
    card = cards[0]
    response = add(owner_client, "cards", str(card.id))
    assert response.status_code == 201
    assert response.data["vertical"] == "cards"
    assert response.data["key"] == str(card.id)
    assert response.data["card_id"] == card.id
    assert response.data["slug"] is None
    assert response.data["name"] == card.name
    assert response.data["bank_name"] == card.bank.name


@pytest.mark.django_db
def test_add_is_idempotent(owner_client, cards):
    card = cards[0]
    assert add(owner_client, "cards", str(card.id)).status_code == 201
    assert add(owner_client, "cards", str(card.id)).status_code == 200
    assert ShortlistItem.objects.count() == 1


@pytest.mark.django_db
def test_add_slug_verticals(owner_client, deposit, loan):
    response = add(owner_client, "deposits", deposit.slug)
    assert response.status_code == 201
    assert response.data["key"] == deposit.slug
    assert response.data["slug"] == deposit.slug
    assert response.data["card_id"] is None

    response = add(owner_client, "loans", loan.slug)
    assert response.status_code == 201
    assert response.data["bank_name"] == loan.bank.name


@pytest.mark.django_db
def test_add_unknown_product_is_404(owner_client):
    assert add(owner_client, "deposits", "no-such-slug").status_code == 404
    assert add(owner_client, "cards", "999999").status_code == 404
    assert add(owner_client, "cards", "not-a-number").status_code == 404


@pytest.mark.django_db
def test_add_unknown_vertical_is_400(owner_client, cards):
    response = add(owner_client, "bonds", str(cards[0].id))
    assert response.status_code == 400


@pytest.mark.django_db
def test_vertical_cap_is_enforced(owner_client, cards):
    for card in cards[:4]:
        assert add(owner_client, "cards", str(card.id)).status_code == 201
    response = add(owner_client, "cards", str(cards[4].id))
    assert response.status_code == 400
    assert ShortlistItem.objects.count() == 4


@pytest.mark.django_db
def test_list_is_scoped_to_the_owner(owner_client, other_client, cards):
    add(owner_client, "cards", str(cards[0].id))
    add(other_client, "cards", str(cards[1].id))

    mine = owner_client.get(LIST_URL)
    assert mine.status_code == 200
    keys = [row["key"] for row in mine.data["results"]]
    assert keys == [str(cards[0].id)]


@pytest.mark.django_db
def test_remove_is_idempotent_and_scoped(owner_client, other_client, cards):
    card = cards[0]
    add(owner_client, "cards", str(card.id))
    url = f"{LIST_URL}cards/{card.id}/"

    # Another user removing the same key must not touch the owner's row.
    assert other_client.delete(url).status_code == 204
    assert ShortlistItem.objects.count() == 1

    assert owner_client.delete(url).status_code == 204
    assert ShortlistItem.objects.count() == 0
    # Removing again is still a 204, never an error.
    assert owner_client.delete(url).status_code == 204


@pytest.mark.django_db
def test_import_merges_dedupes_and_is_rerunnable(owner_client, cards, deposit):
    add(owner_client, "cards", str(cards[0].id))
    payload = {
        "items": [
            {"vertical": "cards", "key": str(cards[0].id)},  # already held
            {"vertical": "cards", "key": str(cards[1].id)},
            {"vertical": "deposits", "key": deposit.slug},
            {"vertical": "deposits", "key": "missing-slug"},  # skipped
            {"vertical": "bonds", "key": "x"},  # skipped
        ]
    }
    response = owner_client.post(IMPORT_URL, payload, format="json")
    assert response.status_code == 200
    assert response.data["imported"] == 2
    assert response.data["skipped"] == 3
    assert len(response.data["results"]) == 3

    again = owner_client.post(IMPORT_URL, payload, format="json")
    assert again.data["imported"] == 0
    assert ShortlistItem.objects.count() == 3


@pytest.mark.django_db
def test_import_respects_the_vertical_cap(owner_client, cards):
    payload = {"items": [{"vertical": "cards", "key": str(card.id)} for card in cards]}
    response = owner_client.post(IMPORT_URL, payload, format="json")
    assert response.data["imported"] == 4
    assert response.data["skipped"] == 1
    assert ShortlistItem.objects.count() == 4


@pytest.mark.django_db
def test_exactly_one_product_constraint_rejects_two_fks(owner, cards, deposit):
    """The DB-level CheckConstraint — not just the service layer — refuses
    a row pointing at two products at once."""
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ShortlistItem.objects.create(
                user=owner, card=cards[0], deposit_product=deposit
            )
    assert ShortlistItem.objects.count() == 0


@pytest.mark.django_db
def test_exactly_one_product_constraint_rejects_zero_fks(owner):
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ShortlistItem.objects.create(user=owner)
    assert ShortlistItem.objects.count() == 0


@pytest.mark.django_db
def test_exactly_one_product_constraint_accepts_a_single_fk(owner, bank, cards):
    account = AccountProduct.objects.create(
        bank=bank, account_type="savings", name="Alpha Savings"
    )
    ShortlistItem.objects.create(user=owner, card=cards[0])
    ShortlistItem.objects.create(user=owner, account_product=account)
    assert ShortlistItem.objects.count() == 2
