import pytest

from django.db import IntegrityError, transaction

from credit_cards.models import CreditCard
from saved.constants import MAX_CARDS_PER_COMPARISON
from saved.models import Collection, CollectionItem, SavedComparison, SavedComparisonItem


def _make_comparison(user, cards, name="Starter set"):
    """Create a comparison whose items follow the order of cards."""
    comparison = SavedComparison.objects.create(user=user, name=name)
    SavedComparisonItem.objects.bulk_create(
        SavedComparisonItem(comparison=comparison, card=card, position=position)
        for position, card in enumerate(cards)
    )
    return comparison


@pytest.mark.django_db
class TestSavedComparisonModel:
    """Defaults and identity fields of SavedComparison."""

    def test_is_private_by_default(self, owner):
        comparison = SavedComparison.objects.create(user=owner, name="Mine")

        assert comparison.is_public is False

    def test_share_token_is_generated_and_unguessably_long(self, owner):
        comparison = SavedComparison.objects.create(user=owner, name="Mine")

        assert len(comparison.share_token) >= 40

    def test_share_tokens_are_unique_per_comparison(self, owner):
        first = SavedComparison.objects.create(user=owner, name="One")
        second = SavedComparison.objects.create(user=owner, name="Two")

        assert first.share_token != second.share_token

    def test_timestamps_come_from_audit_base(self, owner):
        comparison = SavedComparison.objects.create(user=owner, name="Mine")

        assert comparison.created is not None
        assert comparison.modified is not None


@pytest.mark.django_db
class TestSavedComparisonItemConstraints:
    """Database-level guarantees behind the ordered card list."""

    def test_same_card_cannot_appear_twice(self, owner, cards):
        comparison = _make_comparison(owner, cards[:1])

        with pytest.raises(IntegrityError), transaction.atomic():
            SavedComparisonItem.objects.create(
                comparison=comparison, card=cards[0], position=1
            )

    def test_position_cannot_be_reused(self, owner, cards):
        comparison = _make_comparison(owner, cards[:1])

        with pytest.raises(IntegrityError), transaction.atomic():
            SavedComparisonItem.objects.create(
                comparison=comparison, card=cards[1], position=0
            )

    def test_position_beyond_maximum_is_rejected(self, owner, cards):
        comparison = SavedComparison.objects.create(user=owner, name="Too many")

        with pytest.raises(IntegrityError), transaction.atomic():
            SavedComparisonItem.objects.create(
                comparison=comparison,
                card=cards[0],
                position=MAX_CARDS_PER_COMPARISON,
            )

    def test_fourth_position_is_accepted(self, owner, cards):
        comparison = _make_comparison(owner, cards[:4])

        assert comparison.items.count() == MAX_CARDS_PER_COMPARISON


@pytest.mark.django_db
class TestCollectionModel:
    """Slug generation and item uniqueness for Collection."""

    def test_slug_is_generated_from_name(self, owner):
        collection = Collection.objects.create(user=owner, name="Travel Cards!")

        assert collection.slug.startswith("travel-cards-")

    def test_slug_is_unique_for_identical_names(self, owner):
        first = Collection.objects.create(user=owner, name="Same")
        second = Collection.objects.create(user=owner, name="Same")

        assert first.slug != second.slug

    def test_slug_does_not_change_on_rename(self, owner):
        collection = Collection.objects.create(user=owner, name="Before")
        original = collection.slug

        collection.name = "After"
        collection.save()
        collection.refresh_from_db()

        assert collection.slug == original

    def test_card_cannot_be_added_twice(self, owner, cards):
        collection = Collection.objects.create(user=owner, name="Dupes")
        CollectionItem.objects.create(collection=collection, card=cards[0])

        with pytest.raises(IntegrityError), transaction.atomic():
            CollectionItem.objects.create(collection=collection, card=cards[0])

    def test_item_notes_default_to_blank(self, owner, cards):
        collection = Collection.objects.create(user=owner, name="Notes")
        item = CollectionItem.objects.create(collection=collection, card=cards[0])

        assert item.notes == ""


@pytest.mark.django_db
class TestCardDeletionCascades:
    """Deleting a credit card must not break saved comparisons or collections."""

    def test_deleting_card_removes_only_its_comparison_item(self, owner, cards):
        comparison = _make_comparison(owner, cards[:4])

        cards[1].delete()

        remaining = list(
            comparison.items.order_by("position").values_list("card_id", flat=True)
        )
        assert remaining == [cards[0].pk, cards[2].pk, cards[3].pk]
        assert SavedComparison.objects.filter(pk=comparison.pk).exists()

    def test_deleting_card_keeps_surviving_positions_ordered(self, owner, cards):
        comparison = _make_comparison(owner, cards[:4])

        cards[0].delete()

        positions = list(comparison.items.values_list("position", flat=True))
        assert positions == sorted(positions)
        assert len(positions) == 3

    def test_deleting_card_removes_collection_item_only(self, owner, cards):
        collection = Collection.objects.create(user=owner, name="Keep")
        CollectionItem.objects.create(collection=collection, card=cards[0], notes="a")
        CollectionItem.objects.create(collection=collection, card=cards[1], notes="b")

        cards[0].delete()

        assert list(collection.items.values_list("notes", flat=True)) == ["b"]
        assert Collection.objects.filter(pk=collection.pk).exists()

    def test_deleting_last_card_leaves_empty_comparison(self, owner, cards):
        comparison = _make_comparison(owner, cards[:1])

        cards[0].delete()

        assert comparison.items.count() == 0
        assert not CreditCard.objects.filter(pk=cards[0].pk).exists()


@pytest.mark.django_db
class TestUserDeletionCascades:
    """Deleting a user removes their saved objects."""

    def test_deleting_user_removes_comparisons_and_collections(self, owner, cards):
        comparison = _make_comparison(owner, cards[:2])
        collection = Collection.objects.create(user=owner, name="Gone")
        CollectionItem.objects.create(collection=collection, card=cards[0])

        owner.delete()

        assert not SavedComparison.objects.filter(pk=comparison.pk).exists()
        assert not Collection.objects.filter(pk=collection.pk).exists()
        assert CreditCard.objects.filter(pk=cards[0].pk).exists()
