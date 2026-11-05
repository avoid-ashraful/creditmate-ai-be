"""Tests for the D4 "Your numbers" profile defaults (redesign Phase 3).

Endpoint: GET/PATCH /api/v1/auth/me/defaults/

The defaults are exactly three voluntary scenario numbers. Eligibility
inputs (income, employment, TIN, CIB) are never stored server-side, so
they must not appear anywhere in this payload.
"""

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

URL = "/api/v1/auth/me/defaults/"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="defaults-owner", email="owner@example.com", password="x"
    )


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(
        username="defaults-other", email="other@example.com", password="x"
    )


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_anonymous_is_rejected():
    response = APIClient().get(URL)
    assert response.status_code in (401, 403)
    response = APIClient().patch(URL, {"typical_balance": "100"}, format="json")
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_get_returns_nulls_when_unset(auth_client):
    response = auth_client.get(URL)
    assert response.status_code == 200
    assert response.data == {
        "typical_balance": None,
        "monthly_card_spend": None,
        "planned_loan_amount": None,
    }


@pytest.mark.django_db
def test_patch_sets_and_get_reads_back(auth_client):
    response = auth_client.patch(
        URL,
        {
            "typical_balance": "75000.00",
            "monthly_card_spend": "42000",
            "planned_loan_amount": "800000",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["typical_balance"] == "75000.00"
    assert response.data["monthly_card_spend"] == "42000.00"
    assert response.data["planned_loan_amount"] == "800000.00"

    again = auth_client.get(URL)
    assert again.data["typical_balance"] == "75000.00"


@pytest.mark.django_db
def test_patch_is_partial_and_can_clear_with_null(auth_client):
    auth_client.patch(URL, {"typical_balance": "1000"}, format="json")
    response = auth_client.patch(URL, {"monthly_card_spend": "5000"}, format="json")
    assert response.status_code == 200
    assert response.data["typical_balance"] == "1000.00"
    assert response.data["monthly_card_spend"] == "5000.00"

    cleared = auth_client.patch(URL, {"typical_balance": None}, format="json")
    assert cleared.status_code == 200
    assert cleared.data["typical_balance"] is None


@pytest.mark.django_db
def test_negative_amounts_are_rejected(auth_client):
    for field in ("typical_balance", "monthly_card_spend", "planned_loan_amount"):
        response = auth_client.patch(URL, {field: "-1"}, format="json")
        assert response.status_code == 400, field


@pytest.mark.django_db
def test_defaults_are_scoped_to_the_owner(auth_client, other_user):
    auth_client.patch(URL, {"typical_balance": "12345"}, format="json")

    other_client = APIClient()
    other_client.force_authenticate(other_user)
    response = other_client.get(URL)
    assert response.status_code == 200
    assert response.data["typical_balance"] is None

    # The other user writing their own defaults must not touch the owner's.
    other_client.patch(URL, {"typical_balance": "999"}, format="json")
    assert auth_client.get(URL).data["typical_balance"] == "12345.00"


@pytest.mark.django_db
def test_no_eligibility_fields_exist_on_the_payload(auth_client):
    response = auth_client.get(URL)
    for banned in ("income", "monthly_income", "employment", "tin", "cib"):
        assert banned not in response.data
