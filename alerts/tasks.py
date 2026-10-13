from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from credit_cards.models import CreditCard, CreditCardFieldHistory

from .models import AlertSubscription, NotificationPreference, SentAlert


def _subscription_events(subscription, interval, now):
    history = CreditCardFieldHistory.objects.filter(created__gte=now - interval)
    if subscription.card_id:
        history = history.filter(card_id=subscription.card_id)
    if subscription.kind == AlertSubscription.Kind.FEE_CHANGE:
        history = history.filter(field_name__in=["annual_fee", "annual_fee_waiver_policy"])
    elif subscription.kind == AlertSubscription.Kind.APR_CHANGE:
        history = history.filter(field_name="interest_rate_apr")
    events = []
    if subscription.kind != AlertSubscription.Kind.NEW_CARD:
        events.extend(
            (f"history:{change.pk}", change)
            for change in history.select_related("card")
        )
    if subscription.kind in (
        AlertSubscription.Kind.NEW_CARD,
        AlertSubscription.Kind.ANY_CHANGE,
    ):
        new_cards = CreditCard.objects.filter(
            created__gte=now - interval, is_active=True
        ).select_related("bank")
        if subscription.card_id:
            new_cards = new_cards.filter(pk=subscription.card_id)
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


@shared_task
def send_alert_digests():
    """Send pending card change notifications, safely tolerating task retries."""
    now = timezone.now()
    sent_count = 0
    for subscription in AlertSubscription.objects.filter(is_active=True).select_related("user", "card"):
        pref, _ = NotificationPreference.objects.get_or_create(user=subscription.user)
        interval = {
            "immediate": timedelta(minutes=5),
            "daily": timedelta(days=1),
            "weekly": timedelta(days=7),
        }[pref.frequency]
        for event_id, change in _subscription_events(subscription, interval, now):
            sent_count += _send_event(subscription, event_id, change)
    return sent_count
