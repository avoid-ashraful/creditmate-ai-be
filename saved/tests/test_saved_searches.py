"""Tests for server-side saved searches (redesign Phase 3, D4).

Endpoints:
- /api/v1/saved/searches/          — list/create (own rows only)
- /api/v1/saved/searches/<id>/     — retrieve/update/delete (own rows only)
- /api/v1/saved/searches/import/   — merge on-device searches, idempotent
"""

import pytest

from saved.models import SavedSearch

LIST_URL = "/api/v1/saved/searches/"
IMPORT_URL = "/api/v1/saved/searches/import/"


def create(client, name="Travel cards", path="/cards", query="categories=travel"):
    return client.post(
        LIST_URL, {"name": name, "path": path, "query": query}, format="json"
    )


@pytest.mark.django_db
def test_anonymous_is_rejected(anonymous_client):
    assert anonymous_client.get(LIST_URL).status_code in (401, 403)
    assert create(anonymous_client).status_code in (401, 403)


@pytest.mark.django_db
def test_create_and_list(owner_client):
    response = create(owner_client)
    assert response.status_code == 201
    assert response.data["name"] == "Travel cards"
    assert response.data["path"] == "/cards"
    assert response.data["query"] == "categories=travel"

    listing = owner_client.get(LIST_URL)
    rows = listing.data["results"] if "results" in listing.data else listing.data
    assert len(rows) == 1


@pytest.mark.django_db
def test_creating_the_identical_search_twice_returns_the_same_row(owner_client):
    first = create(owner_client)
    second = create(owner_client)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert SavedSearch.objects.count() == 1


@pytest.mark.django_db
def test_same_query_under_a_different_name_is_a_distinct_search(owner_client):
    create(owner_client, name="One")
    response = create(owner_client, name="Two")
    assert response.status_code == 201
    assert SavedSearch.objects.count() == 2


@pytest.mark.django_db
def test_other_users_searches_are_invisible_and_untouchable(owner_client, other_client):
    created = create(owner_client).data

    listing = other_client.get(LIST_URL)
    rows = listing.data["results"] if "results" in listing.data else listing.data
    assert rows == []

    detail = f"{LIST_URL}{created['id']}/"
    assert other_client.get(detail).status_code == 404
    assert other_client.delete(detail).status_code == 404
    assert SavedSearch.objects.count() == 1


@pytest.mark.django_db
def test_rename_to_an_exact_duplicate_returns_400_not_500(owner_client):
    create(owner_client, name="One")
    second = create(owner_client, name="Two").data

    response = owner_client.patch(
        f"{LIST_URL}{second['id']}/", {"name": "One"}, format="json"
    )
    assert response.status_code == 400
    # Both rows survive, and the renamed row keeps its original name.
    assert SavedSearch.objects.count() == 2
    assert SavedSearch.objects.get(id=second["id"]).name == "Two"


@pytest.mark.django_db
def test_full_update_to_an_exact_duplicate_returns_400(owner_client):
    create(owner_client, name="One")
    second = create(owner_client, name="Two").data

    response = owner_client.put(
        f"{LIST_URL}{second['id']}/",
        {"name": "One", "path": "/cards", "query": "categories=travel"},
        format="json",
    )
    assert response.status_code == 400
    assert SavedSearch.objects.count() == 2
    assert SavedSearch.objects.get(id=second["id"]).name == "Two"


@pytest.mark.django_db
def test_rename_to_a_free_name_still_works(owner_client):
    created = create(owner_client, name="Before").data
    response = owner_client.patch(
        f"{LIST_URL}{created['id']}/", {"name": "After"}, format="json"
    )
    assert response.status_code == 200
    assert SavedSearch.objects.get(id=created["id"]).name == "After"


@pytest.mark.django_db
def test_owner_can_delete(owner_client):
    created = create(owner_client).data
    assert owner_client.delete(f"{LIST_URL}{created['id']}/").status_code == 204
    assert SavedSearch.objects.count() == 0


@pytest.mark.django_db
def test_import_dedupes_and_is_rerunnable(owner_client):
    create(owner_client, name="Existing", query="categories=cashback")
    payload = {
        "searches": [
            {"name": "Existing", "path": "/cards", "query": "categories=cashback"},
            {"name": "Low fee", "path": "/cards", "query": "annual_fee_max=1000"},
            {"name": "FDR 12m", "path": "/deposits", "query": "months=12"},
        ]
    }
    response = owner_client.post(IMPORT_URL, payload, format="json")
    assert response.status_code == 200
    assert response.data["imported"] == 2
    assert response.data["skipped"] == 1
    assert len(response.data["results"]) == 3

    again = owner_client.post(IMPORT_URL, payload, format="json")
    assert again.data["imported"] == 0
    assert SavedSearch.objects.count() == 3
