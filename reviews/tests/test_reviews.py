from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from banks.models import Bank
from credit_cards.models import CreditCard
from reviews.models import CardReview


User = get_user_model()


def card_setup():
    bank = Bank.objects.create(name="Review Bank", website="https://example.com")
    return CreditCard.objects.create(bank=bank, name="Review Card")


def test_public_reviews_only_show_approved(db):
    card = card_setup()
    user = User.objects.create_user(username="reviewer", email="private@example.com")
    CardReview.objects.create(user=user, card=card, rating=5, title="Good", body="Works well", status="approved")
    CardReview.objects.create(user=User.objects.create_user(username="pending"), card=card, rating=1, title="Wait", body="Pending", status="pending")
    response = APIClient().get(reverse("review-list"), {"card": card.pk})
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["reviewer_name"] == "reviewer"
    assert "private@example.com" not in str(response.data)


def test_create_review_requires_auth_and_is_pending(db):
    card = card_setup()
    client = APIClient()
    url = reverse("review-list")
    payload = {"card": card.pk, "rating": 4, "title": "Great", "body": "Good rewards"}
    assert client.post(url, payload).status_code == 403
    user = User.objects.create_user(username="member")
    client.force_authenticate(user)
    response = client.post(url, payload)
    assert response.status_code == 201
    assert CardReview.objects.get(user=user).status == CardReview.Status.PENDING


def test_summary_aggregates_approved_only_and_invalidates(db):
    cache.clear()
    card = card_setup()
    user = User.objects.create_user(username="summary")
    review = CardReview.objects.create(user=user, card=card, rating=5, title="A", body="B", status="approved")
    url = reverse("review-card-summary", args=[card.pk])
    client = APIClient()
    assert client.get(url).data["average_rating"] == 5.0
    review.status = CardReview.Status.PENDING
    review.save()
    response = client.get(url)
    assert response.data["review_count"] == 0
    assert response.data["average_rating"] is None


def test_review_html_and_spam_are_rejected_or_stripped(db):
    card = card_setup()
    user = User.objects.create_user(username="clean")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(reverse("review-list"), {
        "card": card.pk, "rating": 4, "title": "<b>Nice</b>", "body": "<script>alert(1)</script>Useful"
    })
    assert response.status_code == 201
    saved = CardReview.objects.get(user=user)
    assert "<" not in saved.title + saved.body


def test_one_review_per_user_card(db):
    card = card_setup()
    user = User.objects.create_user(username="once")
    CardReview.objects.create(user=user, card=card, rating=3, title="First", body="First")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(reverse("review-list"), {"card": card.pk, "rating": 5, "title": "Second", "body": "Second"})
    assert response.status_code == 400
