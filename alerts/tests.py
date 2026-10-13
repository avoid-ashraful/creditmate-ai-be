from datetime import timedelta

import pytest
from celery.exceptions import Retry
from rest_framework.test import APIClient

from django.core import mail, signing
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from alerts.models import AlertSubscription, NotificationPreference, SentAlert
from alerts.tasks import send_alert_digests
from banks.models import Bank
from credit_cards.models import CreditCard, CreditCardFieldHistory


@pytest.mark.django_db
def test_subscription_crud_is_owner_scoped(django_user_model):
    owner = django_user_model.objects.create_user(username="owner", password="pw")
    other = django_user_model.objects.create_user(username="other", password="pw")
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post("/api/v1/alerts/subscriptions/", {"kind": "fee_change"}, format="json")
    assert response.status_code == 201
    sub_id = response.data["id"]
    client.force_authenticate(other)
    assert client.get(f"/api/v1/alerts/subscriptions/{sub_id}/").status_code == 404


@pytest.mark.django_db
def test_preferences_and_public_unsubscribe(django_user_model):
    user = django_user_model.objects.create_user(username="prefs", password="pw")
    client = APIClient()
    client.force_authenticate(user)
    assert client.put("/api/v1/alerts/preferences/", {"frequency": "daily"}, format="json").status_code == 200
    sub = AlertSubscription.objects.create(user=user)
    client.force_authenticate(None)
    response = client.post(f"/api/v1/alerts/unsubscribe/{sub.unsubscribe_token}/")
    assert response.status_code == 200
    sub.refresh_from_db()
    assert not sub.is_active


@pytest.mark.django_db
def test_digest_sends_plain_and_html_and_is_idempotent(django_user_model, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALERTS_PUBLIC_BASE_URL = "https://example.test"
    user = django_user_model.objects.create_user(username="digest", email="digest@example.test", password="pw")
    NotificationPreference.objects.create(user=user, frequency="weekly")
    card = CreditCard.objects.create(bank=Bank.objects.create(name="Example Bank"), name="Example Card")
    subscription = AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
    history = CreditCardFieldHistory.objects.create(card=card, field_name="annual_fee", old_value="10", new_value="20")
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1
    assert mail.outbox[0].alternatives[0][1] == "text/html"
    assert subscription.unsubscribe_token in mail.outbox[0].body
    assert SentAlert.objects.filter(event_key=f"subscription:{subscription.pk}:history:{history.pk}").exists()
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 1


def test_digest_beat_entry_expires_before_the_next_hourly_run():
    from django.conf import settings as django_settings

    entry = django_settings.CELERY_BEAT_SCHEDULE["send-alert-digests-hourly"]
    assert entry["options"]["expires"] == entry["schedule"]


@pytest.mark.django_db
def test_digest_email_failure_is_logged_and_retried(django_user_model, settings):
    from unittest.mock import patch

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user = django_user_model.objects.create_user(
        username="digest-retry", email="retry@example.test"
    )
    NotificationPreference.objects.create(user=user, frequency="weekly")
    card = CreditCard.objects.create(
        bank=Bank.objects.create(name="Retry Bank"), name="Retry Card"
    )
    subscription = AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
    history = CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value="10", new_value="20"
    )

    with patch("alerts.tasks.EmailMultiAlternatives", side_effect=RuntimeError("smtp down")):
        with pytest.raises(Retry):
            send_alert_digests.apply(throw=True)

    assert not SentAlert.objects.filter(
        event_key=f"subscription:{subscription.pk}:history:{history.pk}"
    ).exists()


@pytest.mark.django_db
def test_duplicate_subscriptions_and_owner_scoped_update_delete(django_user_model):
    owner = django_user_model.objects.create_user(username="subowner", password="pw")
    other = django_user_model.objects.create_user(username="subother", password="pw")
    client = APIClient()
    client.force_authenticate(owner)
    url = "/api/v1/alerts/subscriptions/"
    assert client.post(url, {"kind": "fee_change"}, format="json").status_code == 201
    assert client.post(url, {"kind": "fee_change"}, format="json").status_code == 201
    sub = AlertSubscription.objects.filter(user=owner).first()
    client.force_authenticate(other)
    detail = f"/api/v1/alerts/subscriptions/{sub.pk}/"
    assert client.patch(detail, {"is_active": False}, format="json").status_code == 404
    assert client.delete(detail).status_code == 404
    assert sub.is_active


@pytest.mark.django_db
def test_unsubscribe_rejects_tampered_and_expired_tokens(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="unsubscribe")
    sub = AlertSubscription.objects.create(user=user)
    client = APIClient()
    url = f"/api/v1/alerts/unsubscribe/{sub.unsubscribe_token}"
    assert client.post(url + "x/").status_code == 404
    signed = signing.dumps({"nonce": "old"}, salt="alerts.unsubscribe")
    import django.core.signing
    real_time = django.core.signing.time.time
    monkeypatch.setattr(django.core.signing.time, "time", lambda: real_time() + 11 * 365 * 24 * 60 * 60)
    assert client.post(f"/api/v1/alerts/unsubscribe/{signed}/").status_code == 404
    sub.refresh_from_db()
    assert sub.is_active


@pytest.mark.django_db
def test_digest_frequency_windows_inactive_skip_and_history_content(django_user_model, settings, monkeypatch):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALERTS_PUBLIC_BASE_URL = "https://example.test"
    now = timezone.now()
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now)
    user = django_user_model.objects.create_user(username="window", email="window@example.test")
    card = CreditCard.objects.create(bank=Bank.objects.create(name="Window Bank"), name="Window Card")
    old = CreditCardFieldHistory.objects.create(card=card, field_name="annual_fee", old_value="10", new_value="20")
    old.created = now - timedelta(days=2)
    old.save(update_fields=["created"])
    sub = AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
    NotificationPreference.objects.create(user=user, frequency="daily")
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 0
    pref = user.notification_preference
    pref.frequency = "weekly"
    pref.save()
    assert send_alert_digests() == 1
    assert "annual_fee changed from 10 to 20" in mail.outbox[0].body
    assert "Window Card" in mail.outbox[0].subject
    sub.is_active = False
    sub.save()
    CreditCardFieldHistory.objects.create(card=card, field_name="annual_fee", old_value="20", new_value="30")
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_immediate_frequency_window_and_timezone_boundary(django_user_model, settings, monkeypatch):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALERTS_PUBLIC_BASE_URL = "https://example.test"
    now = timezone.now()
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now)
    user = django_user_model.objects.create_user(username="immediate", email="immediate@example.test")
    card = CreditCard.objects.create(bank=Bank.objects.create(name="Time Bank"), name="Time Card")
    AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
    NotificationPreference.objects.create(user=user, frequency="immediate")
    history = CreditCardFieldHistory.objects.create(card=card, field_name="annual_fee", old_value="0", new_value="1")
    history.created = now - timedelta(minutes=6)
    history.save(update_fields=["created"])
    assert send_alert_digests() == 0
    history.created = now - timedelta(minutes=4)
    history.save(update_fields=["created"])
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_digest_query_count_with_30_populated_subscriptions(django_user_model, settings):
    """Digest discovery stays bounded as active subscriptions grow."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    now = timezone.now()
    for index in range(30):
        user = django_user_model.objects.create_user(username=f"digest-audit-{index}")
        bank = Bank.objects.create(name=f"Digest Audit Bank {index:02d}")
        card = CreditCard.objects.create(bank=bank, name=f"Digest Audit Card {index:02d}")
        AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
        NotificationPreference.objects.create(user=user, frequency="weekly")
        history = CreditCardFieldHistory.objects.create(
            card=card, field_name="annual_fee", old_value="10", new_value="20"
        )
        history.created = now - timedelta(days=1)
        history.save(update_fields=["created"])

    with CaptureQueriesContext(connection) as captured:
        assert send_alert_digests() == 30

    assert len(captured) == 64
