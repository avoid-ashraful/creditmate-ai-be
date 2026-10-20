from rest_framework.exceptions import ValidationError

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404

from credit_cards.models import CreditCard
from saved.constants import (
    MAX_CARDS_PER_COLLECTION,
    MAX_COLLECTIONS_PER_USER,
    MAX_COMPARISONS_PER_USER,
)
from saved.models import Collection, CollectionItem, SavedComparison, SavedComparisonItem

COPY_SUFFIX = " (copy)"


def _require_published_cards(card_ids):
    """Reject card ids that do not point at a published card.

    The public catalogue only exposes published cards
    (``CreditCard.objects.public()``). Saved comparisons are shareable, so a
    private save must not be able to smuggle an unpublished (draft) card into
    a public payload later.

    Parameters
    ----------
    card_ids : iterable of int
        Card primary keys about to be attached to a saved object

    Returns
    -------
    None

    Raises
    ------
    ValidationError
        When any id does not match a published card
    """
    card_ids = list(card_ids)
    published = set(
        CreditCard.objects.public().filter(pk__in=card_ids).values_list("pk", flat=True)
    )
    unavailable = [card_id for card_id in card_ids if card_id not in published]
    if unavailable:
        raise ValidationError(
            {"card_ids": [f"Unknown or unpublished card ids: {unavailable}"]}
        )


def _lock_owner(user):
    """Lock the owning user row so per-user limit checks cannot be raced.

    Parameters
    ----------
    user : User
        The user whose saved objects are being created

    Returns
    -------
    None
    """
    get_user_model().objects.select_for_update().get(pk=user.pk)


def _enforce_limit(queryset, limit, noun):
    """Reject a write when the queryset already holds the maximum allowed rows.

    Parameters
    ----------
    queryset : QuerySet
        Rows that count toward the limit
    limit : int
        Maximum number of rows allowed
    noun : str
        Plural label used in the error message

    Returns
    -------
    None

    Raises
    ------
    ValidationError
        When the count is already at or above the limit
    """
    if queryset.count() >= limit:
        raise ValidationError(f"You can save at most {limit} {noun}.")


def write_comparison_cards(comparison, card_ids):
    """Replace a comparison's cards with the given ids, in the given order.

    Parameters
    ----------
    comparison : SavedComparison
        The comparison whose items are rewritten
    card_ids : list of int
        Card primary keys; list position becomes the card's position

    Returns
    -------
    None
    """
    SavedComparisonItem.objects.filter(comparison=comparison).delete()
    SavedComparisonItem.objects.bulk_create(
        SavedComparisonItem(comparison=comparison, card_id=card_id, position=position)
        for position, card_id in enumerate(card_ids)
    )


def create_comparison(user, fields, card_ids):
    """Create a comparison for a user, enforcing the per-user limit.

    Parameters
    ----------
    user : User
        The owner of the new comparison
    fields : dict
        Validated model fields such as name and notes
    card_ids : list of int
        Ordered card primary keys

    Returns
    -------
    SavedComparison
        The newly created comparison

    Raises
    ------
    ValidationError
        When the user already holds MAX_COMPARISONS_PER_USER comparisons
    """
    with transaction.atomic():
        _lock_owner(user)
        _enforce_limit(
            SavedComparison.objects.filter(user=user),
            MAX_COMPARISONS_PER_USER,
            "comparisons",
        )
        _require_published_cards(card_ids)
        comparison = SavedComparison.objects.create(user=user, **fields)
        write_comparison_cards(comparison, card_ids)
    return comparison


def update_comparison(comparison, fields, card_ids):
    """Update a comparison's fields and, when given, replace its cards.

    Parameters
    ----------
    comparison : SavedComparison
        The comparison to update
    fields : dict
        Validated model fields to set
    card_ids : list of int or None
        Replacement ordered card primary keys, or None to leave cards as-is

    Returns
    -------
    SavedComparison
        The updated comparison
    """
    with transaction.atomic():
        for attr, value in fields.items():
            setattr(comparison, attr, value)
        comparison.save()
        if card_ids is not None:
            _require_published_cards(card_ids)
            write_comparison_cards(comparison, card_ids)
    return comparison


def duplicate_comparison(user, source):
    """Copy a comparison's name, notes and ordered cards into a new comparison.

    The copy is always private, so sharing state is not carried over.

    Parameters
    ----------
    user : User
        The owner of the copy, normally the owner of source
    source : SavedComparison
        The comparison to copy

    Returns
    -------
    SavedComparison
        The newly created copy

    Raises
    ------
    ValidationError
        When the user already holds MAX_COMPARISONS_PER_USER comparisons
    """
    card_ids = list(source.items.order_by("position").values_list("card_id", flat=True))
    max_name_length = SavedComparison._meta.get_field("name").max_length
    name = f"{source.name[: max_name_length - len(COPY_SUFFIX)]}{COPY_SUFFIX}"
    with transaction.atomic():
        _lock_owner(user)
        _enforce_limit(
            SavedComparison.objects.filter(user=user),
            MAX_COMPARISONS_PER_USER,
            "comparisons",
        )
        copy = SavedComparison.objects.create(user=user, name=name, notes=source.notes)
        write_comparison_cards(copy, card_ids)
    return copy


def create_collection(user, fields):
    """Create a collection for a user, enforcing the per-user limit.

    Parameters
    ----------
    user : User
        The owner of the new collection
    fields : dict
        Validated model fields such as name, description and is_public

    Returns
    -------
    Collection
        The newly created collection

    Raises
    ------
    ValidationError
        When the user already holds MAX_COLLECTIONS_PER_USER collections
    """
    with transaction.atomic():
        _lock_owner(user)
        _enforce_limit(
            Collection.objects.filter(user=user),
            MAX_COLLECTIONS_PER_USER,
            "collections",
        )
        return Collection.objects.create(user=user, **fields)


def add_card_to_collection(collection, card_id, notes):
    """Add a card to a collection with the owner's notes.

    Parameters
    ----------
    collection : Collection
        The collection receiving the card
    card_id : int
        Primary key of an existing CreditCard
    notes : str
        Free-text notes stored on the collection item

    Returns
    -------
    CollectionItem
        The newly created item

    Raises
    ------
    ValidationError
        When the card is already present or the collection is full
    """
    with transaction.atomic():
        Collection.objects.select_for_update().get(pk=collection.pk)
        _enforce_limit(
            collection.items.all(),
            MAX_CARDS_PER_COLLECTION,
            "cards per collection",
        )
        if collection.items.filter(card_id=card_id).exists():
            raise ValidationError(
                {"card_id": ["This card is already in the collection."]}
            )
        if not CreditCard.objects.public().filter(pk=card_id).exists():
            raise ValidationError({"card_id": ["Unknown or unpublished card id."]})
        return CollectionItem.objects.create(
            collection=collection,
            card_id=card_id,
            notes=notes,
        )


def remove_card_from_collection(collection, card_id):
    """Remove a card from a collection.

    Parameters
    ----------
    collection : Collection
        The collection to remove the card from
    card_id : int
        Primary key of the card to remove

    Returns
    -------
    None

    Raises
    ------
    Http404
        When the card is not in the collection
    """
    with transaction.atomic():
        Collection.objects.select_for_update().get(pk=collection.pk)
        deleted, _ = collection.items.filter(card_id=card_id).delete()
    if not deleted:
        raise Http404("Card is not in this collection.")
