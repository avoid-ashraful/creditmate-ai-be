import secrets

from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint
from django.utils.text import slugify

from bank_accounts.models import AccountProduct
from common.models import Audit
from credit_cards.models import CreditCard
from deposits.models import DepositProduct
from loans.models import LoanProduct
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


class ShortlistItem(Audit):
    """One product in a user's server-backed shortlist (redesign Phase 3).

    The shortlist spans all four verticals; exactly one of the four product
    foreign keys is set, and the set key decides the vertical. Identity for
    clients is (vertical, key): the card id as a string for cards, the
    product slug for deposits, loans and accounts — the same keys the
    on-device shortlist already used, so a device shortlist imports without
    translation. Cascades mean a withdrawn product leaves the shortlist
    instead of dangling.
    """

    class Vertical(models.TextChoices):
        CARDS = "cards", "Cards"
        DEPOSITS = "deposits", "Deposits"
        LOANS = "loans", "Loans"
        ACCOUNTS = "accounts", "Accounts"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shortlist_items",
    )
    card = models.ForeignKey(
        CreditCard,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shortlist_items",
    )
    deposit_product = models.ForeignKey(
        DepositProduct,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shortlist_items",
    )
    loan_product = models.ForeignKey(
        LoanProduct,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shortlist_items",
    )
    account_product = models.ForeignKey(
        AccountProduct,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shortlist_items",
    )

    class Meta:
        ordering = ["created", "id"]
        constraints = [
            CheckConstraint(
                condition=(
                    Q(
                        card__isnull=False,
                        deposit_product__isnull=True,
                        loan_product__isnull=True,
                        account_product__isnull=True,
                    )
                    | Q(
                        card__isnull=True,
                        deposit_product__isnull=False,
                        loan_product__isnull=True,
                        account_product__isnull=True,
                    )
                    | Q(
                        card__isnull=True,
                        deposit_product__isnull=True,
                        loan_product__isnull=False,
                        account_product__isnull=True,
                    )
                    | Q(
                        card__isnull=True,
                        deposit_product__isnull=True,
                        loan_product__isnull=True,
                        account_product__isnull=False,
                    )
                ),
                name="shortlist_item_exactly_one_product",
            ),
            UniqueConstraint(
                fields=["user", "card"], name="shortlist_unique_card_per_user"
            ),
            UniqueConstraint(
                fields=["user", "deposit_product"],
                name="shortlist_unique_deposit_per_user",
            ),
            UniqueConstraint(
                fields=["user", "loan_product"], name="shortlist_unique_loan_per_user"
            ),
            UniqueConstraint(
                fields=["user", "account_product"],
                name="shortlist_unique_account_per_user",
            ),
        ]

    @property
    def product(self):
        return (
            self.card or self.deposit_product or self.loan_product or self.account_product
        )

    @property
    def vertical(self) -> str:
        if self.card_id is not None:
            return self.Vertical.CARDS
        if self.deposit_product_id is not None:
            return self.Vertical.DEPOSITS
        if self.loan_product_id is not None:
            return self.Vertical.LOANS
        return self.Vertical.ACCOUNTS

    @property
    def key(self) -> str:
        """The client-side identity key within the vertical."""
        if self.card_id is not None:
            return str(self.card_id)
        return self.product.slug

    def __str__(self):
        return f"{self.vertical}: {self.product}"


class SavedSearch(Audit):
    """A user's saved discovery search (redesign Phase 3, D4).

    A saved search is a stored discovery URL: the path plus its query
    string, under a user-chosen name. Server-side so searches follow the
    account across devices; imports de-duplicate on (name, path, query).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_searches",
    )
    name = models.CharField(max_length=120)
    path = models.CharField(max_length=200)
    query = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created", "-id"]
        constraints = [
            UniqueConstraint(
                fields=["user", "name", "path", "query"],
                name="saved_search_unique_per_user",
            )
        ]

    def __str__(self):
        return self.name


class SavedScenario(Audit):
    """A named Plan-workspace scenario saved by a user (redesign Phase 3).

    ``params`` holds the tool's own URL-state inputs verbatim (amounts and
    tenures as strings, exactly as the tool encodes them in its URL), so
    reopening a scenario is just navigating to /plan/<tool>?<params>.
    """

    class Tool(models.TextChoices):
        EMI = "emi", "EMI"
        PAYOFF = "payoff", "Payoff"
        REWARDS = "rewards", "Rewards"
        DEPOSIT = "deposit", "Deposit"
        LOAN = "loan", "Loan"
        ACCOUNT = "account", "Account"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_scenarios",
    )
    tool = models.CharField(max_length=20, choices=Tool.choices)
    name = models.CharField(max_length=120)
    params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return f"{self.tool}: {self.name}"
