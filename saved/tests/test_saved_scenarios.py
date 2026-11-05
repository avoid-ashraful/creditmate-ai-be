"""Tests for saved Plan scenarios (redesign Phase 3, Section 4.8).

Endpoints: /api/v1/saved/scenarios/ — own rows only; params are the tool's
URL-state inputs stored verbatim so a scenario reopens as /plan/<tool>?…
"""

import pytest

from saved.models import SavedScenario

LIST_URL = "/api/v1/saved/scenarios/"


def create(client, **overrides):
    payload = {
        "tool": "emi",
        "name": "5 lakh over 3 years",
        "params": {"amount": "500000", "tenure": "36"},
    }
    payload.update(overrides)
    return client.post(LIST_URL, payload, format="json")


@pytest.mark.django_db
def test_anonymous_is_rejected(anonymous_client):
    assert anonymous_client.get(LIST_URL).status_code in (401, 403)
    assert create(anonymous_client).status_code in (401, 403)


@pytest.mark.django_db
def test_create_round_trips_params_verbatim(owner_client):
    response = create(owner_client)
    assert response.status_code == 201
    assert response.data["tool"] == "emi"
    assert response.data["params"] == {"amount": "500000", "tenure": "36"}


@pytest.mark.django_db
def test_unknown_tool_is_rejected(owner_client):
    assert create(owner_client, tool="mortgage").status_code == 400


@pytest.mark.django_db
def test_other_users_scenarios_are_invisible_and_untouchable(owner_client, other_client):
    created = create(owner_client).data

    listing = other_client.get(LIST_URL)
    rows = listing.data["results"] if "results" in listing.data else listing.data
    assert rows == []

    detail = f"{LIST_URL}{created['id']}/"
    assert other_client.get(detail).status_code == 404
    assert (
        other_client.patch(detail, {"name": "Hijacked"}, format="json").status_code == 404
    )
    assert other_client.delete(detail).status_code == 404
    assert SavedScenario.objects.count() == 1


@pytest.mark.django_db
def test_owner_can_rename_and_delete(owner_client):
    created = create(owner_client).data
    detail = f"{LIST_URL}{created['id']}/"
    renamed = owner_client.patch(detail, {"name": "Renamed"}, format="json")
    assert renamed.status_code == 200
    assert renamed.data["name"] == "Renamed"
    assert owner_client.delete(detail).status_code == 204
    assert SavedScenario.objects.count() == 0
