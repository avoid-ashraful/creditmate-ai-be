import pytest
from rest_framework import status

from saved.models import Collection, CollectionItem

COLLECTIONS_URL = "/api/v1/saved/collections/"


def _detail_url(pk):
    """Return the detail URL of a collection."""
    return f"{COLLECTIONS_URL}{pk}/"


def _cards_url(pk):
    """Return the add-card URL of a collection."""
    return f"{_detail_url(pk)}cards/"


def _card_url(pk, card_id):
    """Return the remove-card URL for one card in a collection."""
    return f"{_detail_url(pk)}cards/{card_id}/"


@pytest.mark.django_db
class TestCollectionCrud:
    """Create, read, update and delete for collections."""

    def test_create_assigns_owner_and_generated_slug(self, owner, owner_client):
        response = owner_client.post(
            COLLECTIONS_URL,
            {"name": "Travel", "description": "Lounge friendly", "is_public": False},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["slug"].startswith("travel-")
        assert response.data["cards"] == []
        assert Collection.objects.get(pk=response.data["id"]).user == owner

    def test_client_cannot_choose_slug(self, owner_client):
        response = owner_client.post(
            COLLECTIONS_URL,
            {"name": "Mine", "slug": "chosen-by-client"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["slug"] != "chosen-by-client"

    def test_list_returns_only_my_collections(self, owner, other_user, owner_client):
        mine = Collection.objects.create(user=owner, name="Mine")
        Collection.objects.create(user=other_user, name="Theirs")

        response = owner_client.get(COLLECTIONS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.data["results"]] == [mine.pk]

    def test_patch_updates_name_and_public_flag(self, owner, owner_client):
        collection = Collection.objects.create(user=owner, name="Old")
        original_slug = collection.slug

        response = owner_client.patch(
            _detail_url(collection.pk),
            {"name": "New", "is_public": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "New"
        assert response.data["is_public"] is True
        assert response.data["slug"] == original_slug

    def test_delete_own_collection(self, owner, owner_client):
        collection = Collection.objects.create(user=owner, name="Bye")

        response = owner_client.delete(_detail_url(collection.pk))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Collection.objects.filter(pk=collection.pk).exists()

    def test_retrieve_other_users_collection_is_404(self, owner, other_client):
        collection = Collection.objects.create(user=owner, name="Private")

        assert other_client.get(_detail_url(collection.pk)).status_code == (
            status.HTTP_404_NOT_FOUND
        )

    def test_patch_other_users_collection_is_404(self, owner, other_client):
        collection = Collection.objects.create(user=owner, name="Not yours")

        response = other_client.patch(
            _detail_url(collection.pk), {"name": "Hijacked"}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        collection.refresh_from_db()
        assert collection.name == "Not yours"

    def test_delete_other_users_collection_is_404_and_keeps_row(
        self, owner, other_client
    ):
        collection = Collection.objects.create(user=owner, name="Keep")

        response = other_client.delete(_detail_url(collection.pk))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Collection.objects.filter(pk=collection.pk).exists()


@pytest.mark.django_db
class TestCollectionCardActions:
    """Adding and removing cards on a collection."""

    def test_add_card_returns_201_with_nested_card_and_notes(
        self, owner, owner_client, cards
    ):
        collection = Collection.objects.create(user=owner, name="Cards")

        response = owner_client.post(
            _cards_url(collection.pk),
            {"card_id": cards[0].pk, "notes": "Best for travel"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["cards"]) == 1
        item = response.data["cards"][0]
        assert item["card"]["id"] == cards[0].pk
        assert item["card"]["bank_name"] == cards[0].bank.name
        assert item["notes"] == "Best for travel"

    def test_notes_are_optional(self, owner, owner_client, cards):
        collection = Collection.objects.create(user=owner, name="Plain")

        response = owner_client.post(
            _cards_url(collection.pk), {"card_id": cards[0].pk}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["cards"][0]["notes"] == ""

    def test_adding_same_card_twice_is_400(self, owner, owner_client, cards):
        collection = Collection.objects.create(user=owner, name="Dupes")
        CollectionItem.objects.create(collection=collection, card=cards[0])

        response = owner_client.post(
            _cards_url(collection.pk), {"card_id": cards[0].pk}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CollectionItem.objects.filter(collection=collection).count() == 1

    def test_unknown_card_is_400(self, owner, owner_client, cards):
        collection = Collection.objects.create(user=owner, name="Ghost")

        response = owner_client.post(
            _cards_url(collection.pk),
            {"card_id": cards[-1].pk + 1000},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "card_id" in response.data

    def test_card_id_is_required(self, owner, owner_client):
        collection = Collection.objects.create(user=owner, name="Missing")

        response = owner_client.post(_cards_url(collection.pk), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_add_to_other_users_collection_is_404_and_adds_nothing(
        self, owner, other_client, cards
    ):
        collection = Collection.objects.create(user=owner, name="Theirs")

        response = other_client.post(
            _cards_url(collection.pk), {"card_id": cards[0].pk}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not CollectionItem.objects.filter(collection=collection).exists()

    def test_remove_card_returns_204_and_keeps_card_record(
        self, owner, owner_client, cards
    ):
        collection = Collection.objects.create(user=owner, name="Remove")
        CollectionItem.objects.create(collection=collection, card=cards[0])
        CollectionItem.objects.create(collection=collection, card=cards[1])

        response = owner_client.delete(_card_url(collection.pk, cards[0].pk))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert list(
            CollectionItem.objects.filter(collection=collection).values_list(
                "card_id", flat=True
            )
        ) == [cards[1].pk]

    def test_remove_card_not_in_collection_is_404(self, owner, owner_client, cards):
        collection = Collection.objects.create(user=owner, name="Empty")

        response = owner_client.delete(_card_url(collection.pk, cards[0].pk))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_remove_from_other_users_collection_is_404_and_keeps_item(
        self, owner, other_client, cards
    ):
        collection = Collection.objects.create(user=owner, name="Theirs")
        CollectionItem.objects.create(collection=collection, card=cards[0])

        response = other_client.delete(_card_url(collection.pk, cards[0].pk))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert CollectionItem.objects.filter(collection=collection).exists()

    def test_cards_are_listed_in_the_order_added(self, owner, owner_client, cards):
        collection = Collection.objects.create(user=owner, name="Order")
        for card in (cards[3], cards[0], cards[2]):
            owner_client.post(
                _cards_url(collection.pk), {"card_id": card.pk}, format="json"
            )

        response = owner_client.get(_detail_url(collection.pk))

        assert [item["card"]["id"] for item in response.data["cards"]] == [
            cards[3].pk,
            cards[0].pk,
            cards[2].pk,
        ]
