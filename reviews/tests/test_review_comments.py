"""Phase 3B: comments on reviews (all four product types).

Decision (documented in the Phase 3B report and UI copy): comments are
moderated exactly like reviews — pending until a moderator approves,
editing returns them to pending, only approved comments are public.
The author always sees their own comments in place with their status.
"""

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.urls import reverse

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from credit_cards.models import CreditCard
from loans.models import LoanProduct
from reviews.models import CardReview, LoanReview, ReviewComment

User = get_user_model()
VERIFIED = VerificationStatus.VERIFIED


def verified_user(username):
    user = User.objects.create_user(username=username)
    user.profile.email_verified = True
    user.profile.save()
    return user


def staff_user(username="cstaff"):
    return User.objects.create_superuser(
        username=username, email=f"{username}@example.test", password="pw"
    )


_bank_counter = [0]


def approved_card_review():
    _bank_counter[0] += 1
    bank = Bank.objects.create(
        name=f"Comment Bank {_bank_counter[0]}", website="https://example.com"
    )
    card = CreditCard.objects.create(
        bank=bank, name="Comment Card", is_active=True, verification_status=VERIFIED
    )
    author = User.objects.create_user(username=f"review-author-{_bank_counter[0]}")
    return CardReview.objects.create(
        user=author, card=card, rating=5, title="T", body="B", status="approved"
    )


def comments_url(review_type, review_id):
    return reverse("review-comment-list", args=[review_type, review_id])


def test_comment_lifecycle_pending_invisible_public_after_approval(db):
    review = approved_card_review()
    commenter = verified_user("commenter")
    bystander = verified_user("bystander")
    client = APIClient()
    url = comments_url("card", review.pk)

    # Anonymous cannot write.
    assert client.post(url, {"body": "Nice"}).status_code == 401
    # Unverified email cannot write either.
    client.force_authenticate(User.objects.create_user(username="unv"))
    response = client.post(url, {"body": "Nice"})
    assert response.status_code == 403
    assert response.data["code"] == "email_not_verified"

    client.force_authenticate(commenter)
    created = client.post(url, {"body": "Helpful review, thanks"})
    assert created.status_code == 201
    assert created.data["status"] == "pending"
    comment_id = created.data["id"]

    # Public and other users see nothing yet; the author sees it in
    # place with its pending status.
    assert APIClient().get(url).data["count"] == 0
    client.force_authenticate(bystander)
    assert client.get(url).data["count"] == 0
    client.force_authenticate(commenter)
    mine = client.get(url).data
    assert mine["count"] == 1
    assert mine["results"][0]["id"] == comment_id
    assert mine["results"][0]["status"] == "pending"
    assert mine["results"][0]["is_own"] is True

    # Staff moderation: queue + approve.
    client.force_authenticate(staff_user())
    queue = client.get(reverse("review-comment-moderation-queue")).data
    assert any(item["id"] == comment_id for item in queue["results"])
    action = reverse("review-comment-moderation-action", args=[comment_id])
    client.force_authenticate(commenter)
    assert client.post(action, {"status": "approved"}).status_code == 403
    client.force_authenticate(staff_user("cstaff2"))
    assert client.post(action, {"status": "approved"}).status_code == 200

    public = APIClient().get(url).data
    assert public["count"] == 1
    assert public["results"][0]["body"] == "Helpful review, thanks"
    assert "status" not in public["results"][0]
    assert public["results"][0]["is_own"] is False
    assert public["results"][0]["author_name"] == "commenter"


def test_comment_on_pending_review_and_unknown_targets(db):
    review = approved_card_review()
    review.status = CardReview.Status.PENDING
    review.save()
    client = APIClient()
    client.force_authenticate(verified_user("early"))
    # A review the public cannot see cannot be commented on.
    assert client.post(comments_url("card", review.pk), {"body": "Hi"}).status_code == 404
    assert APIClient().get(comments_url("card", review.pk)).status_code == 404
    # Unknown review type / id.
    assert APIClient().get(comments_url("bond", review.pk)).status_code == 404
    assert APIClient().get(comments_url("card", 999999)).status_code == 404


def test_threaded_replies_one_level_only(db):
    review = approved_card_review()
    parent_author = verified_user("parent-author")
    replier = verified_user("replier")
    client = APIClient()
    url = comments_url("card", review.pk)

    client.force_authenticate(parent_author)
    parent = client.post(url, {"body": "Top level"}).data
    # Approve the parent so replies can attach publicly.
    parent_obj = ReviewComment.objects.get(pk=parent["id"])
    parent_obj.status = ReviewComment.Status.APPROVED
    parent_obj.save()

    client.force_authenticate(replier)
    reply = client.post(url, {"body": "A reply", "parent": parent["id"]})
    assert reply.status_code == 201
    reply_id = reply.data["id"]
    reply_obj = ReviewComment.objects.get(pk=reply_id)
    reply_obj.status = ReviewComment.Status.APPROVED
    reply_obj.save()

    public = APIClient().get(url).data
    assert public["count"] == 1
    assert public["results"][0]["replies"][0]["id"] == reply_id

    # Replies cannot be nested further.
    response = client.post(url, {"body": "Too deep", "parent": reply_id})
    assert response.status_code == 400

    # A parent from a different review is rejected.
    other_review = approved_card_review()
    other_client = APIClient()
    other_client.force_authenticate(parent_author)
    foreign = other_client.post(
        comments_url("card", other_review.pk), {"body": "Elsewhere"}
    ).data
    response = client.post(url, {"body": "Wrong thread", "parent": foreign["id"]})
    assert response.status_code == 400


def test_comment_edit_delete_ownership(db):
    review = approved_card_review()
    owner = verified_user("cmt-owner")
    other = verified_user("cmt-other")
    client = APIClient()
    client.force_authenticate(owner)
    created = client.post(comments_url("card", review.pk), {"body": "Mine"})
    comment_id = created.data["id"]
    detail = reverse("review-comment-detail", args=[comment_id])

    client.force_authenticate(other)
    assert client.get(detail).status_code == 404
    assert client.patch(detail, {"body": "Hijack"}).status_code == 404
    assert client.delete(detail).status_code == 404

    # Editing returns the comment to pending; authors cannot self-approve.
    comment = ReviewComment.objects.get(pk=comment_id)
    comment.status = ReviewComment.Status.APPROVED
    comment.save()
    client.force_authenticate(owner)
    response = client.patch(detail, {"body": "Edited", "status": "approved"})
    assert response.status_code == 200
    comment.refresh_from_db()
    assert comment.body == "Edited"
    assert comment.status == ReviewComment.Status.PENDING

    assert client.delete(detail).status_code == 204
    assert not ReviewComment.objects.filter(pk=comment_id).exists()


def test_comment_text_is_cleaned(db):
    review = approved_card_review()
    client = APIClient()
    client.force_authenticate(verified_user("cleaner"))
    created = client.post(
        comments_url("card", review.pk), {"body": "<b>Bold</b> claim"}
    )
    assert created.status_code == 201
    assert ReviewComment.objects.get(pk=created.data["id"]).body == "Bold claim"
    abusive = client.post(comments_url("card", review.pk), {"body": "this is shit"})
    assert abusive.status_code == 400


def test_comments_work_on_generalised_product_reviews(db):
    bank = Bank.objects.create(name="Loan Comment Bank")
    loan = LoanProduct.objects.create(
        bank=bank,
        loan_type="personal",
        name="Comment Loan",
        verification_status=VERIFIED,
        is_active=True,
    )
    review = LoanReview.objects.create(
        user=User.objects.create_user(username="loan-author"),
        product=loan,
        rating=4,
        title="T",
        body="B",
        status="approved",
    )
    client = APIClient()
    client.force_authenticate(verified_user("loan-commenter"))
    url = comments_url("loan", review.pk)
    created = client.post(url, {"body": "How fast was disbursement?"})
    assert created.status_code == 201
    assert created.data["review_type"] == "loan"
    # Pending: not public yet.
    assert APIClient().get(url).data["count"] == 0
    comment = ReviewComment.objects.get(pk=created.data["id"])
    comment.status = ReviewComment.Status.APPROVED
    comment.save()
    public = APIClient().get(url).data
    assert public["count"] == 1
    assert public["results"][0]["review"] == review.pk
