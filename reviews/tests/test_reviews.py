from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from credit_cards.models import CreditCard
from reviews.models import CardReview

User = get_user_model()


def verified_user(username, **kwargs):
    """Create a user whose email is verified (required to write reviews)."""
    user = User.objects.create_user(username=username, **kwargs)
    user.profile.email_verified = True
    user.profile.save()
    return user


def card_setup(bank_name="Review Bank"):
    bank = Bank.objects.create(name=bank_name, website="https://example.com")
    return CreditCard.objects.create(
        bank=bank,
        name="Review Card",
        is_active=True,
        verification_status=VerificationStatus.VERIFIED,
    )


def test_public_reviews_only_show_approved(db):
    card = card_setup()
    user = User.objects.create_user(username="reviewer", email="private@example.com")
    CardReview.objects.create(
        user=user, card=card, rating=5, title="Good", body="Works well", status="approved"
    )
    CardReview.objects.create(
        user=User.objects.create_user(username="pending"),
        card=card,
        rating=1,
        title="Wait",
        body="Pending",
        status="pending",
    )
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
    assert client.post(url, payload).status_code == 401
    user = verified_user("member")
    client.force_authenticate(user)
    response = client.post(url, payload)
    assert response.status_code == 201
    assert CardReview.objects.get(user=user).status == CardReview.Status.PENDING


def test_summary_aggregates_approved_only_and_invalidates(db):
    cache.clear()
    card = card_setup()
    user = User.objects.create_user(username="summary")
    review = CardReview.objects.create(
        user=user, card=card, rating=5, title="A", body="B", status="approved"
    )
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
    user = verified_user("clean")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        reverse("review-list"),
        {
            "card": card.pk,
            "rating": 4,
            "title": "<b>Nice</b>",
            "body": "<script>alert(1)</script>Useful",
        },
    )
    assert response.status_code == 201
    saved = CardReview.objects.get(user=user)
    assert "<" not in saved.title + saved.body

    empty_markup = client.post(
        reverse("review-list"),
        {"card": card.pk, "rating": 4, "title": "<b></b>", "body": "Useful"},
    )
    assert empty_markup.status_code == 400


def test_one_review_per_user_card(db):
    card = card_setup()
    user = User.objects.create_user(username="once")
    CardReview.objects.create(user=user, card=card, rating=3, title="First", body="First")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        reverse("review-list"),
        {"card": card.pk, "rating": 5, "title": "Second", "body": "Second"},
    )
    assert response.status_code == 400


def test_review_rating_bounds_and_duplicate_database_constraint(db):
    import pytest

    from django.db import IntegrityError, transaction

    card = card_setup()
    user = User.objects.create_user(username="rating")
    client = APIClient()
    client.force_authenticate(user)
    url = reverse("review-list")
    for rating in (0, 6):
        assert (
            client.post(
                url, {"card": card.pk, "rating": rating, "title": "T", "body": "B"}
            ).status_code
            == 400
        )
    CardReview.objects.create(user=user, card=card, rating=4, title="T", body="B")
    with pytest.raises(IntegrityError), transaction.atomic():
        CardReview.objects.create(
            user=user, card=card, rating=4, title="Again", body="Again"
        )


def test_pending_and_rejected_reviews_are_hidden_from_list_and_summary(db):
    card = card_setup()
    for index, status in enumerate(
        (CardReview.Status.PENDING, CardReview.Status.REJECTED)
    ):
        CardReview.objects.create(
            user=User.objects.create_user(username=f"hidden{index}"),
            card=card,
            rating=5,
            title="Hidden",
            body="Body",
            status=status,
        )
    client = APIClient()
    assert client.get(reverse("review-list"), {"card": card.pk}).data["count"] == 0
    summary = client.get(reverse("review-card-summary", args=[card.pk])).data
    assert summary["review_count"] == 0
    assert summary["average_rating"] is None


def test_summary_cache_invalidates_after_approve_reject_and_delete(db):
    card = card_setup()
    user = User.objects.create_user(username="moderated")
    review = CardReview.objects.create(
        user=user, card=card, rating=5, title="T", body="B"
    )
    url = reverse("review-card-summary", args=[card.pk])
    client = APIClient()
    assert client.get(url).data["review_count"] == 0
    review.status = CardReview.Status.APPROVED
    review.save()
    assert client.get(url).data["review_count"] == 1
    review.status = CardReview.Status.REJECTED
    review.save()
    assert client.get(url).data["review_count"] == 0
    review.delete()
    assert client.get(url).data["review_count"] == 0


def test_helpful_vote_is_idempotent_and_disallows_self_vote(db):
    card = card_setup()
    author = User.objects.create_user(username="author")
    voter = User.objects.create_user(username="voter")
    review = CardReview.objects.create(
        user=author, card=card, rating=5, title="T", body="B", status="approved"
    )
    client = APIClient()
    client.force_authenticate(voter)
    url = reverse("review-helpful", args=[review.pk])
    assert client.post(url).status_code == 201
    response = client.post(url)
    assert response.status_code == 200
    assert response.data["helpful_count"] == 1
    assert review.votes.count() == 1
    client.force_authenticate(author)
    assert client.post(url).status_code == 403


def test_review_detail_auth_ownership_and_staff_moderation(db):
    card = card_setup()
    owner = User.objects.create_user(username="owner")
    other = User.objects.create_user(username="other")
    review = CardReview.objects.create(
        user=owner, card=card, rating=4, title="T", body="B"
    )
    client = APIClient()
    detail = reverse("review-detail", args=[review.pk])
    assert client.get(detail).status_code in (401, 403)
    client.force_authenticate(other)
    assert client.get(detail).status_code == 404
    client.force_authenticate(owner)
    assert client.get(detail).status_code == 200
    assert client.delete(detail).status_code == 204

    review = CardReview.objects.create(
        user=owner, card=card, rating=4, title="T", body="B"
    )
    moderation = reverse("review-moderation-action", args=[review.pk])
    assert client.post(moderation, {"status": "approved"}).status_code == 403
    staff = User.objects.create_superuser(
        username="staff", email="staff@example.test", password="pw"
    )
    client.force_authenticate(staff)
    assert client.get(reverse("review-moderation-queue")).status_code == 200
    assert client.post(moderation, {"status": "approved"}).status_code == 200
    review.refresh_from_db()
    assert review.status == CardReview.Status.APPROVED


def test_review_html_is_escaped_from_public_api(db):
    card = card_setup()
    user = verified_user("markup")
    client = APIClient()
    client.force_authenticate(user)
    created = client.post(
        reverse("review-list"),
        {
            "card": card.pk,
            "rating": 3,
            "title": "<script>x</script>",
            "body": "<b>hello</b>",
            "pros": "<i>Useful</i>",
            "cons": "<em>None</em>",
        },
    )
    assert created.status_code == 201
    review = CardReview.objects.get(user=user)
    assert (review.title, review.body, review.pros, review.cons) == (
        "x",
        "hello",
        "Useful",
        "None",
    )
    review.status = CardReview.Status.APPROVED
    review.save()
    response = APIClient().get(reverse("review-list"), {"card": card.pk})
    result = response.data["results"][0]
    assert result["title"] == "x"
    assert result["body"] == "hello"
    assert all(
        "<" not in result[field] and ">" not in result[field]
        for field in ("title", "body", "pros", "cons")
    )


def test_review_throttle_and_public_list_query_count(db, django_assert_num_queries):
    card = card_setup()
    for index in range(3):
        CardReview.objects.create(
            user=User.objects.create_user(username=f"listed{index}"),
            card=card,
            rating=5,
            title="T",
            body="B",
            status="approved",
        )
    with django_assert_num_queries(2):
        response = APIClient().get(reverse("review-list"), {"card": card.pk})
    assert response.data["count"] == 3
    cache.clear()
    client = APIClient()
    client.force_authenticate(verified_user("throttled"))
    url = reverse("review-list")
    payload = {"card": card.pk, "rating": 3, "title": "T", "body": "B"}
    assert client.post(url, payload).status_code == 201
    for index in range(1, 5):
        second_card = card_setup(f"Review Bank {index}")
        payload["card"] = second_card.pk
        assert client.post(url, payload).status_code == 201
    last_card = card_setup("Review Bank 6")
    payload["card"] = last_card.pk
    assert client.post(url, payload).status_code == 429


def test_public_review_reads_are_not_write_throttled(db):
    """Anonymous reads must not consume the 5/hour review_write scope."""
    cache.clear()
    card = card_setup()
    client = APIClient()
    for _ in range(6):
        response = client.get(reverse("review-list"), {"card": card.pk})
        assert response.status_code == 200


def test_non_integer_card_param_returns_400(db):
    response = APIClient().get(reverse("review-list"), {"card": "abc"})
    assert response.status_code == 400
    assert list(response.data.keys()) == ["card"]


def test_unverified_email_cannot_create_review(db):
    card = card_setup()
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="unverified"))
    response = client.post(
        reverse("review-list"),
        {"card": card.pk, "rating": 4, "title": "Great", "body": "Good rewards"},
    )
    assert response.status_code == 403
    assert response.data["code"] == "email_not_verified"
    assert not CardReview.objects.exists()
