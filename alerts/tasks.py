import logging
from datetime import timedelta

from celery import shared_task

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from credit_cards.models import CreditCard, CreditCardFieldHistory

from .models import AlertSubscription, NotificationPreference, SentAlert

logger = logging.getLogger(__name__)


def _subscription_events(
    subscription, interval, now, history_rows=None, new_card_rows=None
):
    history = (
        CreditCardFieldHistory.objects.filter(created__gte=now - interval).select_related(
            "card"
        )
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
            else [
                row
                for row in history
                if row.field_name in {"annual_fee", "annual_fee_waiver_policy"}
            ]
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
            CreditCard.objects.filter(
                created__gte=now - interval, is_active=True
            ).select_related("bank")
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


def _alert_windows(beat_interval):
    """Return the event lookback window for each notification frequency.

    The task runs every ``beat_interval``. Windows are wider than the run interval
    (immediate: twice it) so a delayed run cannot skip events; ``SentAlert`` keys
    make the overlap safe, so nothing is missed and nothing is sent twice.

    Parameters
    ----------
    beat_interval : timedelta
        How often the beat schedule runs the task

    Returns
    -------
    dict
        Mapping of frequency value to lookback timedelta
    """
    return {
        NotificationPreference.Frequency.IMMEDIATE: max(
            timedelta(minutes=5), beat_interval
        )
        * 2,
        NotificationPreference.Frequency.DAILY: timedelta(days=1) + beat_interval,
        NotificationPreference.Frequency.WEEKLY: timedelta(days=7) + beat_interval,
    }


def _send_user_email(user, pending, marker_keys):
    """Send one email grouping all pending events and record them as sent.

    Parameters
    ----------
    user : User
        Recipient
    pending : list of tuple
        ``(subscription, event_key, event_id, event_object)`` rows, none yet sent
    marker_keys : list of str
        Extra ``SentAlert`` keys (digest period markers) to record with the events

    Returns
    -------
    None

    Raises
    ------
    Exception
        Any send failure; the ``SentAlert`` rows are rolled back so a retry resends
    """
    items = {}
    for _subscription, _key, event_id, obj in pending:
        is_new_card = event_id.startswith("new-card:")
        items.setdefault(
            event_id,
            {
                "is_new_card": is_new_card,
                "card": obj if is_new_card else obj.card,
                "change": None if is_new_card else obj,
            },
        )
    items = list(items.values())
    context = {
        "events": items,
        "unsubscribe_url": (
            f"{settings.FRONTEND_URL}/unsubscribe?token={pending[0][0].unsubscribe_token}"
        ),
    }
    if len(items) == 1:
        card = items[0]["card"]
        subject = (
            f"New card: {card.name}"
            if items[0]["is_new_card"]
            else f"Card update: {card.name}"
        )
    else:
        subject = f"{len(items)} card updates on CreditMate"
    with transaction.atomic():
        SentAlert.objects.bulk_create(
            [
                SentAlert(user=user, event_key=key)
                for key in [p[1] for p in pending] + marker_keys
            ]
        )
        message = EmailMultiAlternatives(
            subject,
            render_to_string("alerts/change.txt", context),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
        message.attach_alternative(
            render_to_string("alerts/change.html", context), "text/html"
        )
        message.send()


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


def _period_markers(user_id, frequency, now):
    """Return the ``SentAlert`` keys marking a user's digest as sent this period.

    Immediate users have none. Daily users get a per-day key; weekly users also get
    a per-ISO-week key, and the shared per-day key caps every digest at one per day.
    """
    if frequency == NotificationPreference.Frequency.IMMEDIATE:
        return []
    markers = [f"digest-day:{user_id}:{now:%Y-%m-%d}"]
    if frequency == NotificationPreference.Frequency.WEEKLY:
        iso = now.isocalendar()
        markers.append(f"digest-week:{user_id}:{iso.year}-W{iso.week:02d}")
    return markers


def _send_alert_digests():
    """Send one email per due user; return the number of emails sent.

    Immediate users get every unsent change each run. Daily and weekly users get a
    single digest per period (a per-day marker also caps total digests at one per
    user per day), holding later changes for the next period.
    """
    now = timezone.now()
    beat_interval = timedelta(seconds=settings.ALERTS_BEAT_INTERVAL_SECONDS)
    windows = _alert_windows(beat_interval)
    horizon = max(windows.values())
    subscriptions = list(
        AlertSubscription.objects.filter(is_active=True)
        .select_related("user", "card")
        .order_by("-created")
    )
    by_user = {}
    for subscription in subscriptions:
        by_user.setdefault(subscription.user_id, []).append(subscription)
    preferences = {
        pref.user_id: pref
        for pref in NotificationPreference.objects.filter(user_id__in=by_user)
    }
    for user_id, user_subscriptions in by_user.items():
        if user_id not in preferences:
            preferences[user_id], _ = NotificationPreference.objects.get_or_create(
                user=user_subscriptions[0].user
            )
    history_rows = list(
        CreditCardFieldHistory.objects.filter(created__gte=now - horizon)
        .select_related("card")
        .order_by("-created", "-id")
    )
    new_card_rows = list(
        CreditCard.objects.filter(created__gte=now - horizon, is_active=True)
        .select_related("bank")
        .order_by("bank__name", "name")
    )
    # shortcut: loads every key sent inside the horizon in one query, upgrade to a
    # per-batch lookup if SentAlert grows beyond what fits comfortably in memory.
    sent_keys = set(
        SentAlert.objects.filter(
            user_id__in=by_user, created__gte=now - horizon
        ).values_list("event_key", flat=True)
    )
    sent_count = 0
    for user_id, user_subscriptions in by_user.items():
        frequency = preferences[user_id].frequency
        marker_keys = _period_markers(user_id, frequency, now)
        if sent_keys.intersection(marker_keys):
            continue
        pending = []
        for subscription in user_subscriptions:
            for event_id, change in _subscription_events(
                subscription, windows[frequency], now, history_rows, new_card_rows
            ):
                key = f"subscription:{subscription.pk}:{event_id}"
                if key not in sent_keys:
                    pending.append((subscription, key, event_id, change))
        if pending:
            _send_user_email(user_subscriptions[0].user, pending, marker_keys)
            sent_count += 1
    return sent_count
