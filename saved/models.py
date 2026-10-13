import secrets

from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint
from django.utils.text import slugify

from common.models import Audit
from credit_cards.models import CreditCard
from saved.constants import (
    MAX_CARDS_PER_COMPARISON,
    SHARE_TOKEN_BYTES,
    SLUG_BASE_MAX_LENGTH,
)


def generate_share_token():
    """Generate an unguessable token for a public comparison share link.

    Parameters
    ----------
    None

    Returns
    -------
    str
        URL-safe random token carrying SHARE_TOKEN_BYTES bytes of entropy
    """
    return secrets.token_urlsafe(SHARE_TOKEN_BYTES)


def generate_collection_slug(name):
    """Build a unique, URL-safe slug for a collection.

    The slug is the slugified name followed by a random suffix, retried until
    no existing collection uses it.

    Parameters
    ----------
    name : str
        The collection name the slug is derived from

    Returns
    -------
    str
        A slug that does not match any existing Collection
    """
    base = slugify(name)[:SLUG_BASE_MAX_LENGTH].strip("-") or "collection"
    while True:
        candidate = f"{base}-{secrets.token_hex(4)}"
        if not Collection.objects.filter(slug=candidate).exists():
            return candidate


class SavedComparison(Audit):
    """A user's named set of up to MAX_CARDS_PER_COMPARISON cards, in order.

    The card order lives on SavedComparisonItem.position. A comparison is
    private to its owner unless is_public is turned on, in which case the
    share_token resolves it through the public read-only endpoint.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_comparisons",
    )
    name = models.CharField(max_length=120)
    notes = models.TextField(blank=True, default="")
    is_public = models.BooleanField(default=False)
    share_token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_share_token,
        editable=False,
    )
    cards = models.ManyToManyField(
        CreditCard,
        through="SavedComparisonItem",
        related_name="saved_comparisons",
    )

    class Meta:
        ordering = ["-modified", "-id"]

    def __str__(self):
        return self.name


class SavedComparisonItem(Audit):
    """Ordered membership of a card in a saved comparison."""

    comparison = models.ForeignKey(
        SavedComparison,
        on_delete=models.CASCADE,
        related_name="items",
    )
    card = models.ForeignKey(
        CreditCard,
        on_delete=models.CASCADE,
        related_name="saved_comparison_items",
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            UniqueConstraint(
                fields=["comparison", "card"],
                name="saved_comparison_item_unique_card",
            ),
            UniqueConstraint(
                fields=["comparison", "position"],
                name="saved_comparison_item_unique_position",
            ),
            CheckConstraint(
                condition=Q(position__lt=MAX_CARDS_PER_COMPARISON),
                name="saved_comparison_item_position_max",
            ),
        ]


class Collection(Audit):
    """A user's named, optionally public, list of cards with per-card notes.

    The slug is generated once on first save and is globally unique so that
    a public collection can be addressed without exposing its owner.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_collections",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    is_public = models.BooleanField(default=False)
    slug = models.SlugField(max_length=80, unique=True, editable=False, blank=True)
    cards = models.ManyToManyField(
        CreditCard,
        through="CollectionItem",
        related_name="collections",
    )

    class Meta:
        ordering = ["-modified", "-id"]

    def save(self, *args, **kwargs):
        """Assign a slug on first save, then persist the collection.

        Parameters
        ----------
        *args
            Passed through to ``models.Model.save``
        **kwargs
            Passed through to ``models.Model.save``

        Returns
        -------
        None
        """
        if not self.slug:
            self.slug = generate_collection_slug(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CollectionItem(Audit):
    """A card held in a collection, with the owner's notes about that card."""

    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        related_name="items",
    )
    card = models.ForeignKey(
        CreditCard,
        on_delete=models.CASCADE,
        related_name="collection_items",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created", "id"]
        constraints = [
            UniqueConstraint(
                fields=["collection", "card"],
                name="collection_item_unique_card",
            ),
        ]
