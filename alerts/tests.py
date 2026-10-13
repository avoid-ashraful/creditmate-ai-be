import pytest
from django.core import mail
from rest_framework.test import APIClient

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
