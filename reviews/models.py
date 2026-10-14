from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common.models import Audit


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
