"""Tests for bank follows (redesign D4: server-backed bank-follow alerts).

Endpoints:
- GET    /api/v1/alerts/bank-follows/           — list my follows
- POST   /api/v1/alerts/bank-follows/           — follow (idempotent)
- DELETE /api/v1/alerts/bank-follows/<bank_id>/ — unfollow (idempotent)
"""

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from alerts.models import BankFollow
from banks.factories import BankFactory

LIST_URL = "/api/v1/alerts/bank-follows/"


def detail_url(bank_id: int) -> str:
    return f"{LIST_URL}{bank_id}/"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="follower", password="x")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="someone-else", password="x")


@pytest.fixture
def bank(db):
    return BankFactory()


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
class TestBankFollow:
    def test_anonymous_cannot_list_follow_or_unfollow(self, bank):
        client = APIClient()
        assert client.get(LIST_URL).status_code in (401, 403)
        assert client.post(LIST_URL, {"bank": bank.id}, format="json").status_code in (
            401,
            403,
        )
        assert client.delete(detail_url(bank.id)).status_code in (401, 403)
        assert BankFollow.objects.count() == 0

    def test_follow_creates_row_and_returns_bank(self, auth_client, user, bank):
        response = auth_client.post(LIST_URL, {"bank": bank.id}, format="json")
        assert response.status_code == 201
        assert response.data["bank"] == bank.id
        assert response.data["bank_name"] == bank.name
        assert BankFollow.objects.filter(user=user, bank=bank).count() == 1

    def test_follow_is_idempotent(self, auth_client, user, bank):
        first = auth_client.post(LIST_URL, {"bank": bank.id}, format="json")
        second = auth_client.post(LIST_URL, {"bank": bank.id}, format="json")
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.data["id"] == first.data["id"]
        assert BankFollow.objects.filter(user=user, bank=bank).count() == 1

    def test_follow_unknown_bank_is_a_client_error(self, auth_client):
        response = auth_client.post(LIST_URL, {"bank": 999999}, format="json")
        assert response.status_code == 400
        assert BankFollow.objects.count() == 0

    def test_list_returns_only_my_follows(self, auth_client, user, other_user, bank):
        other_bank = BankFactory()
        BankFollow.objects.create(user=user, bank=bank)
        BankFollow.objects.create(user=other_user, bank=other_bank)

        response = auth_client.get(LIST_URL)
        assert response.status_code == 200
        results = response.data["results"] if "results" in response.data else response.data
        assert [row["bank"] for row in results] == [bank.id]

    def test_unfollow_removes_row(self, auth_client, user, bank):
        BankFollow.objects.create(user=user, bank=bank)
        response = auth_client.delete(detail_url(bank.id))
        assert response.status_code == 204
        assert BankFollow.objects.filter(user=user, bank=bank).count() == 0

    def test_unfollow_is_idempotent(self, auth_client, bank):
        response = auth_client.delete(detail_url(bank.id))
        assert response.status_code == 204

    def test_unfollow_does_not_touch_other_users(self, auth_client, other_user, bank):
        BankFollow.objects.create(user=other_user, bank=bank)
        response = auth_client.delete(detail_url(bank.id))
        assert response.status_code == 204
        assert BankFollow.objects.filter(user=other_user, bank=bank).count() == 1

    def test_two_users_can_follow_the_same_bank(self, auth_client, user, other_user, bank):
        auth_client.post(LIST_URL, {"bank": bank.id}, format="json")
        client = APIClient()
        client.force_authenticate(other_user)
        response = client.post(LIST_URL, {"bank": bank.id}, format="json")
        assert response.status_code == 201
        assert BankFollow.objects.filter(bank=bank).count() == 2
