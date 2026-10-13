import pytest
from rest_framework import status

from saved.models import SavedComparison, SavedComparisonItem

COMPARISONS_URL = "/api/v1/saved/comparisons/"


def _detail_url(pk):
    """Return the detail URL of a saved comparison."""
    return f"{COMPARISONS_URL}{pk}/"


def _card_ids(payload):
    """Return the card ids of a serialized comparison in order."""
    return [card["id"] for card in payload["cards"]]


def _create(client, name, card_ids, **extra):
    """POST a comparison and return the response."""
    return client.post(
        COMPARISONS_URL,
        {"name": name, "card_ids": card_ids, **extra},
        format="json",
    )


@pytest.mark.django_db
class TestCreateComparison:
    """POST /api/v1/saved/comparisons/."""

    def test_create_returns_201_with_cards_in_submitted_order(
        self, owner_client, owner, cards
    ):
        submitted = [cards[2].pk, cards[0].pk, cards[1].pk]

        response = _create(owner_client, "Ordered", submitted, notes="Keep it short")

        assert response.status_code == status.HTTP_201_CREATED
        assert _card_ids(response.data) == submitted
        assert response.data["notes"] == "Keep it short"
        comparison = SavedComparison.objects.get(pk=response.data["id"])
        assert comparison.user == owner
        assert (
            list(comparison.items.order_by("position").values_list("card_id", flat=True))
            == submitted
        )

    def test_cards_are_nested_as_card_list_serializer_rows(self, owner_client, cards):
        response = _create(owner_client, "Nested", [cards[0].pk])

        card = response.data["cards"][0]
        assert card["id"] == cards[0].pk
        assert card["bank_name"] == cards[0].bank.name
        assert "bank" in card
        assert "annual_fee" in card

    def test_client_cannot_set_owner_or_share_token(
        self, owner_client, other_user, cards
    ):
        response = _create(
            owner_client,
            "Spoof",
            [cards[0].pk],
            user=other_user.pk,
            share_token="client-chosen",
            is_public=True,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["share_token"] != "client-chosen"
        assert SavedComparison.objects.get(pk=response.data["id"]).user != other_user

    def test_is_public_is_opt_in(self, owner_client, cards):
        response = _create(owner_client, "Private by default", [cards[0].pk])

        assert response.data["is_public"] is False
        assert response.data["share_token"]

    def test_card_ids_are_required_on_create(self, owner_client):
        response = owner_client.post(COMPARISONS_URL, {"name": "No cards"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "card_ids" in response.data

    def test_empty_card_ids_are_rejected(self, owner_client):
        response = _create(owner_client, "Empty", [])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "card_ids" in response.data

    def test_more_than_four_cards_are_rejected(self, owner_client, cards):
        response = _create(owner_client, "Too many", [card.pk for card in cards])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "card_ids" in response.data
        assert SavedComparison.objects.count() == 0

    def test_exactly_four_cards_are_accepted(self, owner_client, cards):
        response = _create(owner_client, "Four", [card.pk for card in cards[:4]])

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["cards"]) == 4

    def test_duplicate_card_is_rejected(self, owner_client, cards):
        response = _create(owner_client, "Dupes", [cards[0].pk, cards[0].pk])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "card_ids" in response.data

    def test_unknown_card_is_rejected(self, owner_client, cards):
        missing = cards[-1].pk + 1000

        response = _create(owner_client, "Ghost", [cards[0].pk, missing])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "card_ids" in response.data
        assert SavedComparison.objects.count() == 0

    def test_non_integer_card_id_is_rejected(self, owner_client):
        response = _create(owner_client, "Bad", ["abc"])

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_name_is_required(self, owner_client, cards):
        response = owner_client.post(
            COMPARISONS_URL, {"card_ids": [cards[0].pk]}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "name" in response.data


@pytest.mark.django_db
class TestListAndRetrieveComparisons:
    """Listing and reading are scoped to the requesting user."""

    def test_list_returns_only_my_comparisons(
        self, owner, other_user, owner_client, cards
    ):
        mine = SavedComparison.objects.create(user=owner, name="Mine")
        SavedComparison.objects.create(user=other_user, name="Theirs")

        response = owner_client.get(COMPARISONS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.data["results"]] == [mine.pk]

    def test_retrieve_returns_ordered_cards(self, owner, owner_client, cards):
        comparison = SavedComparison.objects.create(user=owner, name="Ordered")
        SavedComparisonItem.objects.bulk_create(
            [
                SavedComparisonItem(comparison=comparison, card=cards[3], position=0),
                SavedComparisonItem(comparison=comparison, card=cards[1], position=1),
            ]
        )

        response = owner_client.get(_detail_url(comparison.pk))

        assert response.status_code == status.HTTP_200_OK
        assert _card_ids(response.data) == [cards[3].pk, cards[1].pk]

    def test_retrieve_other_users_comparison_is_404(
        self, other_user, other_client, owner
    ):
        comparison = SavedComparison.objects.create(user=owner, name="Private")

        response = other_client.get(_detail_url(comparison.pk))

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestUpdateComparison:
    """PATCH and PUT on owned comparisons."""

    def test_patch_name_keeps_cards(self, owner, owner_client, cards):
        comparison = SavedComparison.objects.create(user=owner, name="Old")
        SavedComparisonItem.objects.bulk_create(
            [
                SavedComparisonItem(comparison=comparison, card=cards[0], position=0),
                SavedComparisonItem(comparison=comparison, card=cards[1], position=1),
            ]
        )

        response = owner_client.patch(
            _detail_url(comparison.pk), {"name": "New"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "New"
        assert _card_ids(response.data) == [cards[0].pk, cards[1].pk]

    def test_patch_card_ids_reorders_cards(self, owner, owner_client, cards):
        comparison = SavedComparison.objects.create(user=owner, name="Reorder")
        SavedComparisonItem.objects.bulk_create(
            [
                SavedComparisonItem(comparison=comparison, card=cards[0], position=0),
                SavedComparisonItem(comparison=comparison, card=cards[1], position=1),
                SavedComparisonItem(comparison=comparison, card=cards[2], position=2),
            ]
        )
        reordered = [cards[2].pk, cards[0].pk, cards[1].pk]

        response = owner_client.patch(
            _detail_url(comparison.pk), {"card_ids": reordered}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert _card_ids(response.data) == reordered
        assert comparison.items.count() == 3

    def test_patch_card_ids_replaces_membership(self, owner, owner_client, cards):
        comparison = SavedComparison.objects.create(user=owner, name="Swap")
        SavedComparisonItem.objects.create(
            comparison=comparison, card=cards[0], position=0
        )

        response = owner_client.patch(
            _detail_url(comparison.pk), {"card_ids": [cards[4].pk]}, format="json"
        )

        assert _card_ids(response.data) == [cards[4].pk]
        assert not comparison.items.filter(card=cards[0]).exists()

    def test_patch_with_five_cards_is_rejected_and_nothing_changes(
        self, owner, owner_client, cards
    ):
        comparison = SavedComparison.objects.create(user=owner, name="Stable")
        SavedComparisonItem.objects.create(
            comparison=comparison, card=cards[0], position=0
        )

        response = owner_client.patch(
            _detail_url(comparison.pk),
            {"card_ids": [card.pk for card in cards]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert list(comparison.items.values_list("card_id", flat=True)) == [cards[0].pk]

    def test_toggling_is_public_updates_share_state(self, owner, owner_client, cards):
        comparison = SavedComparison.objects.create(user=owner, name="Share me")

        response = owner_client.patch(
            _detail_url(comparison.pk), {"is_public": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_public"] is True
        assert response.data["share_token"] == comparison.share_token

    def test_patch_other_users_comparison_is_404(self, other_client, owner):
        comparison = SavedComparison.objects.create(user=owner, name="Not yours")

        response = other_client.patch(
            _detail_url(comparison.pk), {"name": "Hijacked"}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        comparison.refresh_from_db()
        assert comparison.name == "Not yours"


@pytest.mark.django_db
class TestDeleteAndDuplicateComparison:
    """DELETE and POST .../duplicate/."""

    def test_delete_own_comparison(self, owner, owner_client):
        comparison = SavedComparison.objects.create(user=owner, name="Bye")

        response = owner_client.delete(_detail_url(comparison.pk))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SavedComparison.objects.filter(pk=comparison.pk).exists()

    def test_delete_other_users_comparison_is_404_and_keeps_row(
        self, other_client, owner
    ):
        comparison = SavedComparison.objects.create(user=owner, name="Keep")

        response = other_client.delete(_detail_url(comparison.pk))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SavedComparison.objects.filter(pk=comparison.pk).exists()

    def test_duplicate_copies_name_notes_and_card_order(self, owner, owner_client, cards):
        source = SavedComparison.objects.create(
            user=owner, name="Source", notes="n", is_public=True
        )
        SavedComparisonItem.objects.bulk_create(
            [
                SavedComparisonItem(comparison=source, card=cards[2], position=0),
                SavedComparisonItem(comparison=source, card=cards[0], position=1),
            ]
        )

        response = owner_client.post(f"{_detail_url(source.pk)}duplicate/")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["id"] != source.pk
        assert response.data["name"] == "Source (copy)"
        assert response.data["notes"] == "n"
        assert _card_ids(response.data) == [cards[2].pk, cards[0].pk]
        assert response.data["share_token"] != source.share_token

    def test_duplicate_is_private_even_when_source_is_public(
        self, owner, owner_client, cards
    ):
        source = SavedComparison.objects.create(user=owner, name="Public", is_public=True)
        SavedComparisonItem.objects.create(comparison=source, card=cards[0], position=0)

        response = owner_client.post(f"{_detail_url(source.pk)}duplicate/")

        assert response.data["is_public"] is False

    def test_duplicate_other_users_comparison_is_404(self, other_client, owner):
        source = SavedComparison.objects.create(user=owner, name="Theirs")

        response = other_client.post(f"{_detail_url(source.pk)}duplicate/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SavedComparison.objects.count() == 1
