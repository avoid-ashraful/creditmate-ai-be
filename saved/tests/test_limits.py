import pytest
from rest_framework import status

from saved import services
from saved.constants import MAX_COLLECTIONS_PER_USER, MAX_COMPARISONS_PER_USER
from saved.models import Collection, CollectionItem, SavedComparison

COMPARISONS_URL = "/api/v1/saved/comparisons/"
COLLECTIONS_URL = "/api/v1/saved/collections/"


def _cards_url(pk):
    """Return the add-card URL of a collection."""
    return f"{COLLECTIONS_URL}{pk}/cards/"


def _fill_comparisons(user, count):
    """Create ``count`` comparisons for a user in one query."""
    SavedComparison.objects.bulk_create(
        SavedComparison(user=user, name=f"Filler {index}") for index in range(count)
    )


def _fill_collections(user, count):
    """Create ``count`` collections for a user."""
    for index in range(count):
        Collection.objects.create(user=user, name=f"Filler {index}")


@pytest.mark.django_db
class TestComparisonLimit:
    """Users may hold at most MAX_COMPARISONS_PER_USER saved comparisons."""

    def test_limit_is_fifty(self):
        assert MAX_COMPARISONS_PER_USER == 50

    def test_last_allowed_comparison_is_created(self, owner, owner_client, cards):
        _fill_comparisons(owner, MAX_COMPARISONS_PER_USER - 1)

        response = owner_client.post(
            COMPARISONS_URL,
            {"name": "The fiftieth", "card_ids": [cards[0].pk]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert (
            SavedComparison.objects.filter(user=owner).count() == MAX_COMPARISONS_PER_USER
        )

    def test_create_past_limit_is_400_and_saves_nothing(self, owner, owner_client, cards):
        _fill_comparisons(owner, MAX_COMPARISONS_PER_USER)

        response = owner_client.post(
            COMPARISONS_URL,
            {"name": "Too many", "card_ids": [cards[0].pk]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert str(MAX_COMPARISONS_PER_USER) in str(response.data)
        assert (
            SavedComparison.objects.filter(user=owner).count() == MAX_COMPARISONS_PER_USER
        )

    def test_duplicate_past_limit_is_400(self, owner, owner_client):
        _fill_comparisons(owner, MAX_COMPARISONS_PER_USER - 1)
        source = SavedComparison.objects.filter(user=owner).first()
        SavedComparison.objects.create(user=owner, name="Last slot")

        response = owner_client.post(f"{COMPARISONS_URL}{source.pk}/duplicate/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            SavedComparison.objects.filter(user=owner).count() == MAX_COMPARISONS_PER_USER
        )

    def test_limit_is_per_user(self, owner, other_user, other_client, cards):
        _fill_comparisons(owner, MAX_COMPARISONS_PER_USER)

        response = other_client.post(
            COMPARISONS_URL,
            {"name": "Mine", "card_ids": [cards[0].pk]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_deleting_one_frees_a_slot(self, owner, owner_client, cards):
        _fill_comparisons(owner, MAX_COMPARISONS_PER_USER)
        victim = SavedComparison.objects.filter(user=owner).first()

        owner_client.delete(f"{COMPARISONS_URL}{victim.pk}/")
        response = owner_client.post(
            COMPARISONS_URL,
            {"name": "Replacement", "card_ids": [cards[0].pk]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestCollectionLimit:
    """Users may hold at most MAX_COLLECTIONS_PER_USER collections."""

    def test_limit_is_twenty(self):
        assert MAX_COLLECTIONS_PER_USER == 20

    def test_last_allowed_collection_is_created(self, owner, owner_client):
        _fill_collections(owner, MAX_COLLECTIONS_PER_USER - 1)

        response = owner_client.post(
            COLLECTIONS_URL, {"name": "Twentieth"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_create_past_limit_is_400_and_saves_nothing(self, owner, owner_client):
        _fill_collections(owner, MAX_COLLECTIONS_PER_USER)

        response = owner_client.post(COLLECTIONS_URL, {"name": "Too many"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert str(MAX_COLLECTIONS_PER_USER) in str(response.data)
        assert Collection.objects.filter(user=owner).count() == MAX_COLLECTIONS_PER_USER

    def test_limit_is_per_user(self, owner, other_client):
        _fill_collections(owner, MAX_COLLECTIONS_PER_USER)

        response = other_client.post(COLLECTIONS_URL, {"name": "Mine"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestCardsPerCollectionLimit:
    """A collection holds at most MAX_CARDS_PER_COLLECTION cards."""

    def test_adding_past_limit_is_400(self, owner, owner_client, cards, monkeypatch):
        monkeypatch.setattr(services, "MAX_CARDS_PER_COLLECTION", 2)
        collection = Collection.objects.create(user=owner, name="Small")
        for card in cards[:2]:
            CollectionItem.objects.create(collection=collection, card=card)

        response = owner_client.post(
            _cards_url(collection.pk), {"card_id": cards[2].pk}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CollectionItem.objects.filter(collection=collection).count() == 2
