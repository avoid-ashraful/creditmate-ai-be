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

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_subscriptions")
    card = models.ForeignKey("credit_cards.CreditCard", null=True, blank=True, on_delete=models.CASCADE, related_name="alert_subscriptions")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ANY_CHANGE)
    is_active = models.BooleanField(default=True)
    unsubscribe_token = models.CharField(max_length=128, unique=True, default=make_unsubscribe_token)

    class Meta:
        ordering = ["-created"]


class NotificationPreference(Audit):
    class Frequency(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference")
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.WEEKLY)


class SentAlert(Audit):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_alerts")
    event_key = models.CharField(max_length=100, unique=True)
