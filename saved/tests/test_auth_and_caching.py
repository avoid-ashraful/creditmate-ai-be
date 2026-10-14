import pytest
from rest_framework import status

from saved.models import Collection, SavedComparison

AUTH_REQUIRED_ENDPOINTS = [
    ("get", "/api/v1/saved/comparisons/"),
    ("post", "/api/v1/saved/comparisons/"),
    ("get", "/api/v1/saved/comparisons/1/"),
    ("patch", "/api/v1/saved/comparisons/1/"),
    ("delete", "/api/v1/saved/comparisons/1/"),
    ("post", "/api/v1/saved/comparisons/1/duplicate/"),
    ("get", "/api/v1/saved/collections/"),
    ("post", "/api/v1/saved/collections/"),
    ("get", "/api/v1/saved/collections/1/"),
    ("patch", "/api/v1/saved/collections/1/"),
    ("delete", "/api/v1/saved/collections/1/"),
    ("post", "/api/v1/saved/collections/1/cards/"),
    ("delete", "/api/v1/saved/collections/1/cards/1/"),
]


@pytest.mark.django_db
class TestAnonymousAccess:
    """Every owner-scoped endpoint refuses anonymous callers.

    The default authentication classes differ between this branch (session)
    and the JWT branch (401 with a WWW-Authenticate header), so both codes
    count as refusal.
    """

    @pytest.mark.parametrize("method, url", AUTH_REQUIRED_ENDPOINTS)
    def test_anonymous_is_refused(self, anonymous_client, method, url):
        payload = {"name": "x", "card_ids": [1]} if method in ("post", "patch") else None

        response = getattr(anonymous_client, method)(url, payload, format="json")

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_anonymous_create_writes_nothing(self, anonymous_client, cards):
        anonymous_client.post(
            "/api/v1/saved/comparisons/",
            {"name": "x", "card_ids": [cards[0].pk]},
            format="json",
        )
        anonymous_client.post("/api/v1/saved/collections/", {"name": "x"}, format="json")

        assert SavedComparison.objects.count() == 0
        assert Collection.objects.count() == 0


@pytest.mark.django_db
class TestCacheHeaders:
    """Per-user responses must never be stored by a shared cache."""

    def test_owner_list_response_is_not_shared_cacheable(self, owner_client):
        response = owner_client.get("/api/v1/saved/comparisons/")

        cache_control = response["Cache-Control"]
        assert "private" in cache_control
        assert "no-store" in cache_control

    def test_owner_collection_response_is_not_shared_cacheable(self, owner, owner_client):
        collection = Collection.objects.create(user=owner, name="Cache me not")

        response = owner_client.get(f"/api/v1/saved/collections/{collection.pk}/")

        assert "no-store" in response["Cache-Control"]
        assert "private" in response["Cache-Control"]

    def test_public_share_response_is_not_shared_cacheable(
        self, owner, cards, anonymous_client
    ):
        comparison = SavedComparison.objects.create(
            user=owner, name="Live", is_public=True
        )

        response = anonymous_client.get(f"/api/v1/saved/shared/{comparison.share_token}/")

        assert "no-store" in response["Cache-Control"]

    def test_refused_anonymous_response_is_not_cacheable(self, anonymous_client):
        response = anonymous_client.get("/api/v1/saved/comparisons/")

        assert "no-store" in response["Cache-Control"]
