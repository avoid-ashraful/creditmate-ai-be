import secrets

from django.conf import settings
from django.core import signing
from django.db import models

from common.models import Audit


def make_unsubscribe_token():
    return signing.dumps({"nonce": secrets.token_urlsafe(24)}, salt="alerts.unsubscribe")


class AlertSubscription(Audit):
    class Kind(models.TextChoices):
        FEE_CHANGE = "fee_change", "Fee change"
        APR_CHANGE = "apr_change", "APR change"
        NEW_CARD = "new_card", "New card"
        ANY_CHANGE = "any_change", "Any change"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="alert_subscriptions",
    )
    card = models.ForeignKey(
        "credit_cards.CreditCard",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="alert_subscriptions",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ANY_CHANGE)
    is_active = models.BooleanField(default=True)
    unsubscribe_token = models.CharField(
        max_length=128, unique=True, default=make_unsubscribe_token
    )

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(
                fields=["-created"],
                condition=models.Q(is_active=True),
                name="alerts_active_created_idx",
            ),
        ]


class BankFollow(Audit):
    """A user's follow of a bank (redesign D4: server-backed bank follows).

    Following a bank is the subscription half of bank-follow alerts: the
    nightly sync detects rate/fee changes per bank, and this row is what
    ties a user to a bank. One row per (user, bank) — re-following is a
    no-op, enforced by the unique constraint.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bank_follows",
    )
    bank = models.ForeignKey(
        "banks.Bank",
        on_delete=models.CASCADE,
        related_name="followers",
    )

    class Meta:
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "bank"], name="unique_bank_follow_per_user"
            )
        ]


class FeedSeenState(Audit):
    """Per-user "seen" watermark for what-changed surfaces (Phase 4, D4).

    Semantics (deliberate, and relied on by the client):

    - ``last_seen_at`` is the newest change timestamp the user has
      actually been *shown* on a what-changed surface (the /my/alerts
      feed, or the personalised Home what-changed section). It is a
      watermark over change timestamps, not a wall-clock "last visit":
      marking seen advances it to the newest change the surface
      displayed (the client passes that as ``through``), never beyond
      "now", and never backwards.
    - A change is "new for this user" iff its ``changed_at`` is strictly
      greater than ``last_seen_at``. With no row (or a null watermark)
      nothing is marked new — the first view establishes the baseline
      instead of claiming everything is new.
    - Reading the feed never moves the watermark; only the explicit
      mark-seen call does, so pagination and refetches can't silently
      consume changes the user hasn't seen.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feed_seen_state",
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)


class NotificationPreference(Audit):
    class Frequency(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    frequency = models.CharField(
        max_length=10, choices=Frequency.choices, default=Frequency.WEEKLY
    )


class SentAlert(Audit):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_alerts"
    )
    event_key = models.CharField(max_length=100, unique=True)
