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
    response = client.post(
        "/api/v1/alerts/subscriptions/", {"kind": "fee_change"}, format="json"
    )
    assert response.status_code == 201
    sub_id = response.data["id"]
    client.force_authenticate(other)
    assert client.get(f"/api/v1/alerts/subscriptions/{sub_id}/").status_code == 404


@pytest.mark.django_db
def test_preferences_and_public_unsubscribe(django_user_model):
    user = django_user_model.objects.create_user(username="prefs", password="pw")
    client = APIClient()
    client.force_authenticate(user)
    assert (
        client.put(
            "/api/v1/alerts/preferences/", {"frequency": "daily"}, format="json"
        ).status_code
        == 200
    )
    sub = AlertSubscription.objects.create(user=user)
    client.force_authenticate(None)
    response = client.post(f"/api/v1/alerts/unsubscribe/{sub.unsubscribe_token}/")
    assert response.status_code == 200
    sub.refresh_from_db()
    assert not sub.is_active


@pytest.mark.django_db
def test_digest_sends_plain_and_html_and_is_idempotent(django_user_model, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user = django_user_model.objects.create_user(
        username="digest", email="digest@example.test", password="pw"
    )
    NotificationPreference.objects.create(user=user, frequency="weekly")
    card = CreditCard.objects.create(
        bank=Bank.objects.create(name="Example Bank"), name="Example Card"
    )
    subscription = AlertSubscription.objects.create(
        user=user, card=card, kind="fee_change"
    )
    history = CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value="10", new_value="20"
    )
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1
    assert mail.outbox[0].alternatives[0][1] == "text/html"
    assert subscription.unsubscribe_token in mail.outbox[0].body
    assert SentAlert.objects.filter(
        event_key=f"subscription:{subscription.pk}:history:{history.pk}"
    ).exists()
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
    subscription = AlertSubscription.objects.create(
        user=user, card=card, kind="fee_change"
    )
    history = CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value="10", new_value="20"
    )

    with patch(
        "alerts.tasks.EmailMultiAlternatives", side_effect=RuntimeError("smtp down")
    ):
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
    monkeypatch.setattr(
        django.core.signing.time, "time", lambda: real_time() + 11 * 365 * 24 * 60 * 60
    )
    assert client.post(f"/api/v1/alerts/unsubscribe/{signed}/").status_code == 404
    sub.refresh_from_db()
    assert sub.is_active


@pytest.mark.django_db
def test_digest_frequency_windows_inactive_skip_and_history_content(
    django_user_model, settings, monkeypatch
):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    now = timezone.now()
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now)
    user = django_user_model.objects.create_user(
        username="window", email="window@example.test"
    )
    card = CreditCard.objects.create(
        bank=Bank.objects.create(name="Window Bank"), name="Window Card"
    )
    old = CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value="10", new_value="20"
    )
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
    CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value="20", new_value="30"
    )
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 1


def _immediate_setup(django_user_model, settings, monkeypatch, username="immediate"):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    now = timezone.now()
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now)
    user = django_user_model.objects.create_user(
        username=username, email=f"{username}@example.test"
    )
    card = CreditCard.objects.create(
        bank=Bank.objects.create(name=f"{username} Bank"), name=f"{username} Card"
    )
    AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
    NotificationPreference.objects.create(user=user, frequency="immediate")
    return now, user, card


def _change(card, created, new_value="1"):
    history = CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value="0", new_value=new_value
    )
    history.created = created
    history.save(update_fields=["created"])
    return history


@pytest.mark.django_db
def test_immediate_covers_the_hourly_gap_and_never_double_sends(
    django_user_model, settings, monkeypatch
):
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch)
    # 50 minutes old: missed by the old 5-minute lookback, must be sent now.
    _change(card, now - timedelta(minutes=50))
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1
    # Next hourly run still sees the same row inside the window but SentAlert dedups.
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now + timedelta(hours=1))
    assert send_alert_digests() == 0
    # A change made since the last run is sent exactly once.
    _change(card, now + timedelta(minutes=30), new_value="2")
    assert send_alert_digests() == 1
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_immediate_ignores_changes_older_than_the_window(
    django_user_model, settings, monkeypatch
):
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch)
    _change(card, now - timedelta(hours=3))
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_immediate_groups_all_changes_in_one_email(
    django_user_model, settings, monkeypatch
):
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch)
    _change(card, now - timedelta(minutes=20), new_value="1")
    _change(card, now - timedelta(minutes=10), new_value="2")
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1
    assert "changed from 0 to 1" in mail.outbox[0].body
    assert "changed from 0 to 2" in mail.outbox[0].body


@pytest.mark.django_db
def test_daily_sends_one_digest_per_day_grouping_changes(
    django_user_model, settings, monkeypatch
):
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch, "daily")
    pref = user.notification_preference
    pref.frequency = "daily"
    pref.save()
    other = CreditCard.objects.create(bank=card.bank, name="Second Card")
    AlertSubscription.objects.create(user=user, card=other, kind="fee_change")
    _change(card, now - timedelta(hours=5), new_value="1")
    _change(card, now - timedelta(hours=3), new_value="2")
    _change(other, now - timedelta(hours=2), new_value="9")
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1
    assert "3 card updates" in mail.outbox[0].subject
    for value in ("to 1", "to 2", "to 9"):
        assert value in mail.outbox[0].body

    # Later the same day: a new change is held (one digest per day), not mailed.
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now + timedelta(minutes=30))
    _change(card, now + timedelta(minutes=10), new_value="3")
    assert send_alert_digests() == 0
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 1

    # Next day the held change goes out once, and the earlier ones are not repeated.
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: now + timedelta(days=1))
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 2
    assert "to 3" in mail.outbox[1].body
    assert "to 1" not in mail.outbox[1].body
    assert send_alert_digests() == 0


@pytest.mark.django_db
def test_weekly_sends_one_digest_per_week_and_respects_daily_cap(
    django_user_model, settings, monkeypatch
):
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch, "weekly")
    pref = user.notification_preference
    pref.frequency = "weekly"
    pref.save()
    # Anchor to a Monday so day offsets below stay inside one ISO week.
    monday = (now - timedelta(days=now.weekday())).replace(hour=1, minute=0)
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: monday)
    _change(card, monday - timedelta(days=3), new_value="1")
    _change(card, monday - timedelta(days=1), new_value="2")
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 1
    assert "to 1" in mail.outbox[0].body and "to 2" in mail.outbox[0].body

    # Same week, later day: held.
    wednesday = monday + timedelta(days=2)
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: wednesday)
    _change(card, wednesday - timedelta(hours=1), new_value="3")
    assert send_alert_digests() == 0

    # Following week: exactly one more digest with only the new change.
    monkeypatch.setattr("alerts.tasks.timezone.now", lambda: monday + timedelta(days=7))
    assert send_alert_digests() == 1
    assert len(mail.outbox) == 2
    assert "to 3" in mail.outbox[1].body and "to 1" not in mail.outbox[1].body
    assert send_alert_digests() == 0


@pytest.mark.django_db
def test_switching_frequency_cannot_exceed_one_digest_per_day(
    django_user_model, settings, monkeypatch
):
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch, "switch")
    pref = user.notification_preference
    pref.frequency = "daily"
    pref.save()
    _change(card, now - timedelta(hours=2), new_value="1")
    assert send_alert_digests() == 1
    pref.frequency = "weekly"
    pref.save()
    _change(card, now - timedelta(minutes=5), new_value="2")
    assert send_alert_digests() == 0
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_alert_email_links_to_frontend_unsubscribe_page(
    django_user_model, settings, monkeypatch
):
    settings.FRONTEND_URL = "https://app.example.test"
    now, user, card = _immediate_setup(django_user_model, settings, monkeypatch, "link")
    sub = AlertSubscription.objects.get(user=user)
    _change(card, now - timedelta(minutes=5))
    assert send_alert_digests() == 1
    expected = f"https://app.example.test/unsubscribe?token={sub.unsubscribe_token}"
    assert expected in mail.outbox[0].body
    assert expected in mail.outbox[0].alternatives[0][0]


@pytest.mark.django_db
def test_unsubscribe_get_is_read_only_and_post_cancels_all(django_user_model):
    user = django_user_model.objects.create_user(username="getsafe")
    card = CreditCard.objects.create(
        bank=Bank.objects.create(name="Get Bank"), name="Get Card"
    )
    sub = AlertSubscription.objects.create(user=user, card=card)
    other_sub = AlertSubscription.objects.create(user=user, kind="new_card")
    client = APIClient()
    url = f"/api/v1/alerts/unsubscribe/{sub.unsubscribe_token}/"
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == {
        "confirm_required": True,
        "is_active": True,
        "kind": "any_change",
        "card_name": "Get Card",
    }
    sub.refresh_from_db()
    assert sub.is_active
    assert client.get(url + "x/").status_code == 404

    assert client.post(url).status_code == 200
    sub.refresh_from_db()
    other_sub.refresh_from_db()
    assert not sub.is_active and not other_sub.is_active


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

    # 5 fixed queries + 3 per emailed user (savepoint, SentAlert insert, release).
    assert len(captured) == 5 + 3 * 30


@pytest.mark.django_db
def test_subscription_exposes_card_and_bank_names(django_user_model):
    from rest_framework.test import APIClient

    from banks.factories import BankFactory
    from credit_cards.factories import CreditCardFactory

    user = django_user_model.objects.create_user(
        username="names@example.com", password="x"
    )
    bank = BankFactory(name="Names Bank")
    card = CreditCardFactory(bank=bank, name="Names Card")
    client = APIClient()
    client.force_authenticate(user)
    created = client.post(
        "/api/v1/alerts/subscriptions/", {"card": card.pk, "kind": "any_change"}
    )
    assert created.status_code == 201
    listing = client.get("/api/v1/alerts/subscriptions/")
    row = (
        listing.data["results"][0] if isinstance(listing.data, dict) else listing.data[0]
    )
    assert row["card_name"] == "Names Card"
    assert row["bank_name"] == "Names Bank"
