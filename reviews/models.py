from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from common.models import Audit

# A product earns the public "Community reviewed" state once it has at
# least this many *approved* reviews. It is a community signal only:
# reviews are not a legal review and never affect any draft/legal status.
COMMUNITY_REVIEWED_THRESHOLD = 50

# Content-type scoping for the generic relations below: comments may be
# attached to any review model; helpful votes for the non-card product
# reviews live in ProductReviewVote.
REVIEW_MODEL_LIMIT = Q(
    app_label="reviews",
    model__in=("cardreview", "depositreview", "loanreview", "accountreview"),
)
PRODUCT_REVIEW_MODEL_LIMIT = Q(
    app_label="reviews",
    model__in=("depositreview", "loanreview", "accountreview"),
)


class CardReview(Audit):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_reviews"
    )
    card = models.ForeignKey(
        "credit_cards.CreditCard", on_delete=models.CASCADE, related_name="reviews"
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=5000)
    pros = models.TextField(max_length=1000, blank=True)
    cons = models.TextField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    helpful_count = models.PositiveIntegerField(default=0)
    comments = GenericRelation(
        "reviews.ReviewComment",
        content_type_field="content_type",
        object_id_field="object_id",
        related_query_name="card_review",
    )

    class Meta:
        ordering = ["-created", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "card"], name="reviews_one_per_user_card"
            )
        ]
        indexes = [models.Index(fields=["card", "status", "-created"])]

    def __str__(self):
        return f"{self.card}: {self.rating}/5 ({self.status})"


class ReviewVote(Audit):
    review = models.ForeignKey(CardReview, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_votes"
    )
    helpful = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "user"], name="reviews_one_vote_per_user"
            )
        ]


class ProductReviewBase(Audit):
    """Shared review shape for the non-card product verticals.

    Mirrors :class:`CardReview` field-for-field (same moderation lifecycle:
    pending -> approved/rejected; only approved reviews are public; editing
    returns a review to pending) so one moderation posture and one client
    grammar cover every product type.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=5000)
    pros = models.TextField(max_length=1000, blank=True)
    cons = models.TextField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    helpful_count = models.PositiveIntegerField(default=0)
    comments = GenericRelation(
        "reviews.ReviewComment",
        content_type_field="content_type",
        object_id_field="object_id",
    )
    votes = GenericRelation(
        "reviews.ProductReviewVote",
        content_type_field="content_type",
        object_id_field="object_id",
    )

    class Meta:
        abstract = True
        ordering = ["-created", "-id"]


class DepositReview(ProductReviewBase):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deposit_reviews"
    )
    product = models.ForeignKey(
        "deposits.DepositProduct", on_delete=models.CASCADE, related_name="reviews"
    )

    class Meta(ProductReviewBase.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"], name="reviews_one_per_user_deposit"
            )
        ]
        indexes = [models.Index(fields=["product", "status", "-created"])]

    def __str__(self):
        return f"{self.product}: {self.rating}/5 ({self.status})"


class LoanReview(ProductReviewBase):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="loan_reviews"
    )
    product = models.ForeignKey(
        "loans.LoanProduct", on_delete=models.CASCADE, related_name="reviews"
    )

    class Meta(ProductReviewBase.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"], name="reviews_one_per_user_loan"
            )
        ]
        indexes = [models.Index(fields=["product", "status", "-created"])]

    def __str__(self):
        return f"{self.product}: {self.rating}/5 ({self.status})"


class AccountReview(ProductReviewBase):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_reviews",
    )
    product = models.ForeignKey(
        "bank_accounts.AccountProduct",
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    class Meta(ProductReviewBase.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"], name="reviews_one_per_user_account"
            )
        ]
        indexes = [models.Index(fields=["product", "status", "-created"])]

    def __str__(self):
        return f"{self.product}: {self.rating}/5 ({self.status})"


class ProductReviewVote(Audit):
    """Helpfulness vote on a deposit/loan/account review (generic target).

    Card reviews keep the original :class:`ReviewVote` table untouched;
    this is its counterpart for the three generalised review models.
    """

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=PRODUCT_REVIEW_MODEL_LIMIT
    )
    object_id = models.PositiveBigIntegerField()
    review = GenericForeignKey("content_type", "object_id")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_review_votes",
    )
    helpful = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "user"],
                name="reviews_one_product_vote_per_user",
            )
        ]
        indexes = [models.Index(fields=["content_type", "object_id"])]


class ReviewComment(Audit):
    """A threaded comment on any review (card, deposit, loan, account).

    Comments follow the same moderation posture as reviews (decided for
    Phase 3B): a comment starts ``pending`` and only becomes public once a
    moderator approves it; editing a comment returns it to ``pending``.
    Threading is one level deep — ``parent`` must be a top-level comment
    on the same review.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_comments"
    )
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=REVIEW_MODEL_LIMIT
    )
    object_id = models.PositiveBigIntegerField()
    review = GenericForeignKey("content_type", "object_id")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    body = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    class Meta:
        ordering = ["created", "id"]
        indexes = [
            models.Index(fields=["content_type", "object_id", "status", "created"])
        ]

    def __str__(self):
        return f"Comment {self.pk} on review {self.object_id} ({self.status})"
