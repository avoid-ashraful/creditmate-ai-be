import pytest
from rest_framework import status

from saved.models import Collection, CollectionItem, SavedComparison, SavedComparisonItem

SHARED_URL = "/api/v1/saved/shared/{token}/"
SHARED_COLLECTION_URL = "/api/v1/saved/shared/collections/{slug}/"
PUBLIC_COMPARISON_KEYS = {"name", "notes", "cards", "modified"}
PUBLIC_COLLECTION_KEYS = {"name", "description", "slug", "cards", "modified"}


def _public_comparison(user, cards, name="Shared set"):
    """Create a public comparison with the given cards in order."""
    comparison = SavedComparison.objects.create(
        user=user, name=name, notes="Why I picked these", is_public=True
    )
    SavedComparisonItem.objects.bulk_create(
        SavedComparisonItem(comparison=comparison, card=card, position=position)
        for position, card in enumerate(cards)
    )
    return comparison


@pytest.mark.django_db
class TestSharedComparison:
    """GET /api/v1/saved/shared/<token>/ is anonymous, read-only and opt-in."""

    def test_anonymous_can_read_public_comparison(self, owner, cards, anonymous_client):
        comparison = _public_comparison(owner, cards[:3])

        response = anonymous_client.get(SHARED_URL.format(token=comparison.share_token))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Shared set"
        assert response.data["notes"] == "Why I picked these"
        assert [card["id"] for card in response.data["cards"]] == [
            card.pk for card in cards[:3]
        ]

    def test_response_has_exact_public_fields_only(self, owner, cards, anonymous_client):
        comparison = _public_comparison(owner, cards[:1])

        response = anonymous_client.get(SHARED_URL.format(token=comparison.share_token))

        assert set(response.data.keys()) == PUBLIC_COMPARISON_KEYS

    def test_response_never_leaks_owner_identity(self, owner, cards, anonymous_client):
        comparison = _public_comparison(owner, cards[:2])

        response = anonymous_client.get(SHARED_URL.format(token=comparison.share_token))
        body = response.content.decode()

        assert owner.username not in body
        assert owner.email not in body
        assert "share_token" not in body
        assert comparison.share_token not in body

    def test_shared_cards_keep_card_list_shape(self, owner, cards, anonymous_client):
        comparison = _public_comparison(owner, cards[:1])

        response = anonymous_client.get(SHARED_URL.format(token=comparison.share_token))

        assert response.data["cards"][0]["bank_name"] == cards[0].bank.name

    def test_private_comparison_token_is_404(self, owner, cards, anonymous_client):
        comparison = SavedComparison.objects.create(user=owner, name="Private")
        SavedComparisonItem.objects.create(
            comparison=comparison, card=cards[0], position=0
        )

        response = anonymous_client.get(SHARED_URL.format(token=comparison.share_token))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unknown_token_is_404(self, anonymous_client):
        response = anonymous_client.get(SHARED_URL.format(token="does-not-exist"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_revoking_public_flag_stops_the_link(
        self, owner, owner_client, cards, anonymous_client
    ):
        comparison = _public_comparison(owner, cards[:1])
        url = SHARED_URL.format(token=comparison.share_token)
        assert anonymous_client.get(url).status_code == status.HTTP_200_OK

        owner_client.patch(
            f"/api/v1/saved/comparisons/{comparison.pk}/",
            {"is_public": False},
            format="json",
        )

        assert anonymous_client.get(url).status_code == status.HTTP_404_NOT_FOUND

    def test_shared_endpoint_is_read_only(self, owner, cards, anonymous_client):
        comparison = _public_comparison(owner, cards[:1])
        url = SHARED_URL.format(token=comparison.share_token)

        response = anonymous_client.post(url, {"name": "Overwrite"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        comparison.refresh_from_db()
        assert comparison.name == "Shared set"

    def test_share_tokens_differ_between_comparisons(self, owner, cards):
        first = _public_comparison(owner, cards[:1], name="One")
        second = _public_comparison(owner, cards[:1], name="Two")

        assert first.share_token != second.share_token

    def test_public_comparison_hides_its_id(self, owner, cards, anonymous_client):
        comparison = _public_comparison(owner, cards[:1])

        response = anonymous_client.get(SHARED_URL.format(token=comparison.share_token))

        assert "id" not in response.data


@pytest.mark.django_db
class TestSharedCollection:
    """GET /api/v1/saved/shared/collections/<slug>/ is anonymous and opt-in."""

    def test_anonymous_can_read_public_collection(self, owner, cards, anonymous_client):
        collection = Collection.objects.create(
            user=owner, name="Public list", description="Good ones", is_public=True
        )
        CollectionItem.objects.create(collection=collection, card=cards[0], notes="top")

        response = anonymous_client.get(
            SHARED_COLLECTION_URL.format(slug=collection.slug)
        )

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) == PUBLIC_COLLECTION_KEYS
        assert response.data["cards"][0]["notes"] == "top"
        assert response.data["cards"][0]["card"]["id"] == cards[0].pk

    def test_public_collection_hides_owner(self, owner, anonymous_client):
        collection = Collection.objects.create(
            user=owner, name="Hidden owner", is_public=True
        )

        response = anonymous_client.get(
            SHARED_COLLECTION_URL.format(slug=collection.slug)
        )

        body = response.content.decode()
        assert owner.username not in body
        assert owner.email not in body

    def test_private_collection_slug_is_404(self, owner, anonymous_client):
        collection = Collection.objects.create(user=owner, name="Private list")

        response = anonymous_client.get(
            SHARED_COLLECTION_URL.format(slug=collection.slug)
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unknown_slug_is_404(self, anonymous_client):
        response = anonymous_client.get(SHARED_COLLECTION_URL.format(slug="nope-0000"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_collection_share_is_read_only(self, owner, anonymous_client):
        collection = Collection.objects.create(
            user=owner, name="Read only", is_public=True
        )

        response = anonymous_client.delete(
            SHARED_COLLECTION_URL.format(slug=collection.slug)
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert Collection.objects.filter(pk=collection.pk).exists()
