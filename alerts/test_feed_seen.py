"""Tests for the per-user what-changed watermark (redesign Phase 4, D4).

Endpoints:
- GET  /api/v1/alerts/feed/        — gains ``seen_at`` + per-entry ``is_new``
- POST /api/v1/alerts/feed/seen/   — advances the watermark

Semantics under test (see alerts.models.FeedSeenState): the watermark is
the newest change timestamp the user has been shown; a change is new iff
strictly newer than the watermark; reading never moves it; marking never
moves it backwards or into the future.
"""

from datetime import timedelta

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.utils import timezone

from alerts.models import BankFollow, FeedSeenState
from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCardFieldHistory

FEED_URL = "/api/v1/alerts/feed/"
SEEN_URL = "/api/v1/alerts/feed/seen/"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="seen-reader", password="<redacted>"
    )


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def change(user):
    """One followed bank with one recorded change; returns the history row."""
    bank = BankFactory()
    BankFollow.objects.create(user=user, bank=bank)
    card = CreditCardFactory(bank=bank)
    return CreditCardFieldHistory.objects.create(
        card=card, field_name="annual_fee", old_value=1000, new_value=1500
    )


@pytest.mark.django_db
def test_feed_without_watermark_marks_nothing_new(auth_client, change):
    res = auth_client.get(FEED_URL)
    assert res.status_code == 200
    assert res.data["seen_at"] is None
    assert [entry["is_new"] for entry in res.data["results"]] == [False]


@pytest.mark.django_db
def test_reading_the_feed_does_not_move_the_watermark(auth_client, change):
    auth_client.get(FEED_URL)
    assert not FeedSeenState.objects.exists()


@pytest.mark.django_db
def test_change_after_mark_is_new_older_is_not(auth_client, user, change):
    res = auth_client.post(SEEN_URL, {"through": change.created.isoformat()}, format="json")
    assert res.status_code == 200

    bank = change.card.bank
    newer_card = CreditCardFactory(bank=bank)
    newer = CreditCardFieldHistory.objects.create(
        card=newer_card, field_name="apr", old_value="20", new_value="21"
    )
    # Backdate the second row so ordering is explicit, not clock-dependent.
    CreditCardFieldHistory.objects.filter(pk=newer.pk).update(
        created=change.created + timedelta(hours=1)
    )

    res = auth_client.get(FEED_URL)
    assert res.data["seen_at"] is not None
    by_field = {e["field_name"]: e["is_new"] for e in res.data["results"]}
    assert by_field == {"annual_fee": False, "apr": True}


@pytest.mark.django_db
def test_mark_seen_never_moves_backwards(auth_client, user):
    later = timezone.now() + timedelta(days=1)  # clamped to now
    res = auth_client.post(SEEN_URL, {"through": later.isoformat()}, format="json")
    first = res.data["last_seen_at"]
    earlier = timezone.now() - timedelta(days=3)
    res = auth_client.post(SEEN_URL, {"through": earlier.isoformat()}, format="json")
    assert res.data["last_seen_at"] == first
    assert FeedSeenState.objects.get(user=user).last_seen_at == first


@pytest.mark.django_db
def test_mark_seen_without_through_marks_up_to_now(auth_client, user):
    before = timezone.now()
    res = auth_client.post(SEEN_URL, {}, format="json")
    assert res.status_code == 200
    assert res.data["last_seen_at"] >= before


@pytest.mark.django_db
def test_watermark_is_per_user(auth_client, user, change):
    auth_client.post(SEEN_URL, {}, format="json")
    other = get_user_model().objects.create_user(
        username="seen-other", password="<redacted>"
    )
    BankFollow.objects.create(user=other, bank=change.card.bank)
    client = APIClient()
    client.force_authenticate(other)
    res = client.get(FEED_URL)
    assert res.data["seen_at"] is None
    assert [entry["is_new"] for entry in res.data["results"]] == [False]


@pytest.mark.django_db
def test_mark_seen_requires_auth(db):
    res = APIClient().post(SEEN_URL, {}, format="json")
    assert res.status_code in (401, 403)
