from datetime import timedelta
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from credit_cards.models import CreditCard, CreditCardFieldHistory

from .models import AlertSubscription, NotificationPreference, SentAlert

logger = logging.getLogger(__name__)


def _subscription_events(subscription, interval, now, history_rows=None, new_card_rows=None):
    history = (
        CreditCardFieldHistory.objects.filter(created__gte=now - interval).select_related("card")
        if history_rows is None
        else [row for row in history_rows if row.created >= now - interval]
    )
    if subscription.card_id:
        history = (
            history.filter(card_id=subscription.card_id)
            if history_rows is None
            else [row for row in history if row.card_id == subscription.card_id]
        )
    if subscription.kind == AlertSubscription.Kind.FEE_CHANGE:
        history = (
            history.filter(field_name__in=["annual_fee", "annual_fee_waiver_policy"])
            if history_rows is None
            else [row for row in history if row.field_name in {"annual_fee", "annual_fee_waiver_policy"}]
        )
    elif subscription.kind == AlertSubscription.Kind.APR_CHANGE:
        history = (
            history.filter(field_name="interest_rate_apr")
            if history_rows is None
            else [row for row in history if row.field_name == "interest_rate_apr"]
        )
    events = []
    if subscription.kind != AlertSubscription.Kind.NEW_CARD:
        events.extend((f"history:{change.pk}", change) for change in history)
    if subscription.kind in (
        AlertSubscription.Kind.NEW_CARD,
        AlertSubscription.Kind.ANY_CHANGE,
    ):
        new_cards = (
            CreditCard.objects.filter(created__gte=now - interval, is_active=True).select_related("bank")
            if new_card_rows is None
            else [card for card in new_card_rows if card.created >= now - interval]
        )
        if subscription.card_id:
            new_cards = (
                new_cards.filter(pk=subscription.card_id)
                if new_card_rows is None
                else [card for card in new_cards if card.pk == subscription.card_id]
            )
        events.extend((f"new-card:{card.pk}", card) for card in new_cards)
    return events


def _send_event(subscription, event_id, change):
    event_key = f"subscription:{subscription.pk}:{event_id}"
    if SentAlert.objects.filter(event_key=event_key).exists():
        return False
    log = SentAlert.objects.create(user=subscription.user, event_key=event_key)
    is_new_card = event_id.startswith("new-card:")
    context = {
        "change": None if is_new_card else change,
        "card": change if is_new_card else change.card,
        "unsubscribe_url": (
            f"{settings.ALERTS_PUBLIC_BASE_URL}/api/v1/alerts/unsubscribe/"
            f"{subscription.unsubscribe_token}/"
        ),
        "is_new_card": is_new_card,
    }
    subject = (
        f"New card: {change.name}"
        if is_new_card
        else f"Card update: {change.card.name}"
    )
    text = render_to_string("alerts/change.txt", context)
    html = render_to_string("alerts/change.html", context)
    try:
        message = EmailMultiAlternatives(
            subject, text, settings.DEFAULT_FROM_EMAIL, [subscription.user.email]
        )
        message.attach_alternative(html, "text/html")
        message.send()
    except Exception:
        log.delete()
        raise
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_alert_digests(self):
    """Send pending card change notifications, safely tolerating task retries."""
    try:
        return _send_alert_digests()
    except Exception as exc:
        logger.exception("Alert digest task failed")
        raise self.retry(
            exc=exc,
            countdown=min(300 * (2**self.request.retries), 3600),
        )


def _send_alert_digests():
    now = timezone.now()
    sent_count = 0
    subscriptions = list(
        AlertSubscription.objects.filter(is_active=True)
        .select_related("user", "card")
        .order_by("-created")
    )
    preferences = {
        pref.user_id: pref
        for pref in NotificationPreference.objects.filter(
            user_id__in={subscription.user_id for subscription in subscriptions}
        )
    }
    for subscription in subscriptions:
        if subscription.user_id not in preferences:
            preferences[subscription.user_id], _ = NotificationPreference.objects.get_or_create(
                user=subscription.user
            )
    history_rows = list(
        CreditCardFieldHistory.objects.filter(created__gte=now - timedelta(days=7))
        .select_related("card")
        .order_by("-created", "-id")
    )
    new_card_rows = list(
        CreditCard.objects.filter(created__gte=now - timedelta(days=7), is_active=True)
        .select_related("bank")
        .order_by("bank__name", "name")
    )
    for subscription in subscriptions:
        pref = preferences[subscription.user_id]
        interval = {
            "immediate": timedelta(minutes=5),
            "daily": timedelta(days=1),
            "weekly": timedelta(days=7),
        }[pref.frequency]
        for event_id, change in _subscription_events(
            subscription, interval, now, history_rows, new_card_rows
        ):
            sent_count += _send_event(subscription, event_id, change)
    return sent_count
