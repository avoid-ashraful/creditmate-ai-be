"""Phase 3B: generalised reviews for deposits, loans and bank accounts.

The lifecycle mirrors card reviews exactly: authenticated + verified
email to write, pending until a moderator approves, approved-only
public reads, one review per (user, product) at API and DB level,
idempotent helpful votes, and a summary whose ``community_reviewed``
flag flips at exactly 50 approved reviews.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from bank_accounts.models import AccountProduct
from banks.models import Bank
from credit_cards.constants import VerificationStatus
from deposits.models import DepositProduct
from loans.models import LoanProduct
from reviews.models import AccountReview, DepositReview, LoanReview

User = get_user_model()

VERIFIED = VerificationStatus.VERIFIED


def verified_user(username):
    user = User.objects.create_user(username=username)
    user.profile.email_verified = True
    user.profile.save()
    return user


def staff_user(username="staff"):
    return User.objects.create_superuser(
        username=username, email=f"{username}@example.test", password="pw"
    )


def make_deposit(**kwargs):
    defaults = {"kind": "fdr", "name": "Test FDR", "verification_status": VERIFIED}
    defaults.update(kwargs)
    return DepositProduct.objects.create(**defaults)


def make_loan(bank=None, **kwargs):
    bank = bank or Bank.objects.create(name="Loan Bank")
    defaults = {
        "bank": bank,
        "loan_type": "personal",
        "name": "Test Personal Loan",
        "verification_status": VERIFIED,
        "is_active": True,
    }
    defaults.update(kwargs)
    return LoanProduct.objects.create(**defaults)


def make_account(bank=None, **kwargs):
    bank = bank or Bank.objects.create(name="Account Bank")
    defaults = {
        "bank": bank,
        "name": "Test Savings",
        "account_type": "savings",
        "verification_status": VERIFIED,
        "rate_slabs": [{"balance_min": "0", "balance_max": None, "rate": "3.00"}],
        "maintenance_fee_slabs": [],
        "debit_card_fee_annual": Decimal("600"),
        "sms_fee_annual": Decimal("300"),
        "online_banking_fee_annual": Decimal("0"),
    }
    defaults.update(kwargs)
    return AccountProduct.objects.create(**defaults)


# product_type -> (list url name, mine-list name, detail name, helpful name,
#                  summary name, product factory, review model)
TYPES = {
    "deposit": (
        "deposit-review-list",
        "deposit-review-mine-list",
        "deposit-review-detail",
        "deposit-review-helpful",
        "deposit-review-summary",
        make_deposit,
        DepositReview,
    ),
    "loan": (
        "loan-review-list",
        "loan-review-mine-list",
        "loan-review-detail",
        "loan-review-helpful",
        "loan-review-summary",
        make_loan,
        LoanReview,
    ),
    "account": (
        "account-review-list",
        "account-review-mine-list",
        "account-review-detail",
        "account-review-helpful",
        "account-review-summary",
        make_account,
        AccountReview,
    ),
}


def payload(product, **overrides):
    data = {"product": product.pk, "rating": 5, "title": "Great", "body": "Works well"}
    data.update(overrides)
    return data


@pytest.mark.parametrize("product_type", list(TYPES))
def test_create_requires_auth_verified_email_and_is_pending(db, product_type):
    list_name, _, _, _, _, make_product, model = TYPES[product_type]
    product = make_product()
    client = APIClient()
    url = reverse(list_name)
    assert client.post(url, payload(product)).status_code == 401

    unverified = User.objects.create_user(username=f"unv-{product_type}")
    client.force_authenticate(unverified)
    response = client.post(url, payload(product))
    assert response.status_code == 403
    assert response.data["code"] == "email_not_verified"

    user = verified_user(f"member-{product_type}")
    client.force_authenticate(user)
    response = client.post(url, payload(product))
    assert response.status_code == 201
    assert response.data["product_type"] == product_type
    review = model.objects.get(user=user)
    assert review.status == model.Status.PENDING
    # Pending reviews are never public.
    assert APIClient().get(url, {"product": product.pk}).data["count"] == 0


@pytest.mark.parametrize("product_type", list(TYPES))
def test_moderation_flow_and_summary(db, product_type):
    list_name, _, _, _, summary_name, make_product, model = TYPES[product_type]
    product = make_product()
    author = verified_user(f"author-{product_type}")
    client = APIClient()
    client.force_authenticate(author)
    created = client.post(reverse(list_name), payload(product))
    assert created.status_code == 201
    review_id = created.data["id"]

    # Non-staff cannot see or use the moderation queue.
    queue = reverse("product-review-moderation-queue")
    assert client.get(queue).status_code == 403
    action = reverse(
        "product-review-moderation-action", args=[product_type, review_id]
    )
    assert client.post(action, {"status": "approved"}).status_code == 403

    staff = staff_user(f"staff-{product_type}")
    client.force_authenticate(staff)
    queue_items = client.get(queue).data
    assert any(item["id"] == review_id for item in queue_items)
    response = client.post(action, {"status": "approved"})
    assert response.status_code == 200
    assert response.data["status"] == "approved"

    public = APIClient().get(reverse(list_name), {"product": product.pk})
    assert public.data["count"] == 1
    assert public.data["results"][0]["reviewer_name"] == author.username

    summary = APIClient().get(reverse(summary_name, args=[product.pk])).data
    assert summary["product_type"] == product_type
    assert summary["product"] == product.pk
    assert summary["review_count"] == 1
    assert summary["approved_count"] == 1
    assert summary["average_rating"] == 5.0
    assert summary["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1}
    assert summary["community_reviewed"] is False


@pytest.mark.parametrize("product_type", list(TYPES))
def test_summary_aggregates_approved_only(db, product_type):
    _, _, _, _, summary_name, make_product, model = TYPES[product_type]
    product = make_product()
    for index, (rating, status) in enumerate(
        [(5, "approved"), (4, "approved"), (4, "approved"), (1, "pending"), (2, "rejected")]
    ):
        model.objects.create(
            user=User.objects.create_user(username=f"agg-{product_type}-{index}"),
            product=product,
            rating=rating,
            title="T",
            body="B",
            status=status,
        )
    summary = APIClient().get(reverse(summary_name, args=[product.pk])).data
    assert summary["review_count"] == 3
    assert summary["average_rating"] == pytest.approx(13 / 3)
    assert summary["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 2, "5": 1}
    # Unknown product -> 404.
    assert (
        APIClient().get(reverse(summary_name, args=[999999])).status_code == 404
    )


@pytest.mark.parametrize("product_type", list(TYPES))
def test_one_review_per_user_product_api_and_db(db, product_type):
    list_name, _, _, _, _, make_product, model = TYPES[product_type]
    product = make_product()
    user = verified_user(f"once-{product_type}")
    model.objects.create(user=user, product=product, rating=3, title="First", body="B")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(reverse(list_name), payload(product, rating=5))
    assert response.status_code == 400

    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(
            user=user, product=product, rating=4, title="Again", body="B"
        )


@pytest.mark.parametrize("product_type", list(TYPES))
def test_own_review_visibility_edit_and_delete(db, product_type):
    list_name, mine_name, detail_name, _, _, make_product, model = TYPES[product_type]
    product = make_product()
    owner = verified_user(f"owner-{product_type}")
    other = verified_user(f"other-{product_type}")
    review = model.objects.create(
        user=owner, product=product, rating=4, title="Mine", body="B"
    )
    client = APIClient()

    # Anonymous cannot read the mine list.
    assert client.get(reverse(mine_name)).status_code == 401

    # The author sees their own pending review, with its status.
    client.force_authenticate(owner)
    mine = client.get(reverse(mine_name), {"product": product.pk})
    assert mine.data["count"] == 1
    assert mine.data["results"][0]["status"] == "pending"
    assert mine.data["results"][0]["product"] == product.pk

    # Another user sees none of it, and the detail is a 404 for them.
    client.force_authenticate(other)
    assert client.get(reverse(mine_name), {"product": product.pk}).data["count"] == 0
    detail = reverse(detail_name, args=[review.pk])
    assert client.get(detail).status_code == 404
    assert client.patch(detail, {"title": "Hijack"}).status_code == 404
    assert client.delete(detail).status_code == 404

    # The author can edit; editing returns the review to pending and the
    # author cannot self-approve via the writable payload.
    review.status = model.Status.APPROVED
    review.save()
    client.force_authenticate(owner)
    response = client.patch(detail, {"title": "Edited", "status": "approved"})
    assert response.status_code == 200
    review.refresh_from_db()
    assert review.title == "Edited"
    assert review.status == model.Status.PENDING

    assert client.delete(detail).status_code == 204
    assert not model.objects.filter(pk=review.pk).exists()


@pytest.mark.parametrize("product_type", list(TYPES))
def test_helpful_vote_idempotent_and_no_self_vote(db, product_type):
    _, _, _, helpful_name, _, make_product, model = TYPES[product_type]
    product = make_product()
    author = User.objects.create_user(username=f"vauthor-{product_type}")
    voter = User.objects.create_user(username=f"voter-{product_type}")
    review = model.objects.create(
        user=author, product=product, rating=5, title="T", body="B", status="approved"
    )
    client = APIClient()
    url = reverse(helpful_name, args=[review.pk])
    assert client.post(url).status_code == 401
    client.force_authenticate(voter)
    assert client.post(url).status_code == 201
    response = client.post(url)
    assert response.status_code == 200
    assert response.data["helpful_count"] == 1
    review.refresh_from_db()
    assert review.helpful_count == 1
    assert review.votes.count() == 1
    client.force_authenticate(author)
    assert client.post(url).status_code == 403


@pytest.mark.parametrize("product_type", list(TYPES))
def test_review_on_unpublished_product_is_rejected(db, product_type):
    list_name, _, _, _, _, make_product, model = TYPES[product_type]
    draft = make_product(verification_status=VerificationStatus.DRAFT)
    client = APIClient()
    client.force_authenticate(verified_user(f"draft-{product_type}"))
    response = client.post(reverse(list_name), payload(draft))
    assert response.status_code == 400
    assert not model.objects.exists()


@pytest.mark.parametrize("product_type", list(TYPES))
def test_community_reviewed_threshold_is_50_approved(db, product_type):
    _, _, _, _, summary_name, make_product, model = TYPES[product_type]
    product = make_product()
    users = [
        User.objects.create_user(username=f"bulk-{product_type}-{i}") for i in range(50)
    ]
    model.objects.bulk_create(
        [
            model(
                user=user,
                product=product,
                rating=5,
                title="T",
                body="B",
                status=model.Status.APPROVED,
            )
            for user in users[:49]
        ]
    )
    cache.clear()
    summary = APIClient().get(reverse(summary_name, args=[product.pk])).data
    assert summary["approved_count"] == 49
    assert summary["community_reviewed"] is False

    model.objects.create(
        user=users[49], product=product, rating=5, title="T", body="B",
        status=model.Status.APPROVED,
    )
    cache.clear()
    summary = APIClient().get(reverse(summary_name, args=[product.pk])).data
    assert summary["approved_count"] == 50
    assert summary["community_reviewed"] is True


def test_card_summary_gains_generalised_keys_without_losing_originals(db):
    from credit_cards.models import CreditCard
    from reviews.models import CardReview

    bank = Bank.objects.create(name="Card Bank", website="https://example.com")
    card = CreditCard.objects.create(
        bank=bank, name="Summary Card", is_active=True, verification_status=VERIFIED
    )
    CardReview.objects.create(
        user=User.objects.create_user(username="card-summary"),
        card=card,
        rating=4,
        title="T",
        body="B",
        status="approved",
    )
    cache.clear()
    data = APIClient().get(reverse("review-card-summary", args=[card.pk])).data
    # Original payload unchanged...
    assert data["card"] == card.pk
    assert data["review_count"] == 1
    assert data["average_rating"] == 4.0
    # ...plus the additive generalised keys.
    assert data["product_type"] == "card"
    assert data["product"] == card.pk
    assert data["approved_count"] == 1
    assert data["community_reviewed"] is False


def test_card_mine_list_shows_own_pending_review(db):
    from credit_cards.models import CreditCard
    from reviews.models import CardReview

    bank = Bank.objects.create(name="Mine Bank", website="https://example.com")
    card = CreditCard.objects.create(
        bank=bank, name="Mine Card", is_active=True, verification_status=VERIFIED
    )
    owner = User.objects.create_user(username="mine-owner")
    review = CardReview.objects.create(
        user=owner, card=card, rating=3, title="Pending one", body="B"
    )
    client = APIClient()
    assert client.get(reverse("review-mine-list")).status_code == 401
    client.force_authenticate(owner)
    data = client.get(reverse("review-mine-list"), {"card": card.pk}).data
    assert data["count"] == 1
    assert data["results"][0]["id"] == review.pk
    assert data["results"][0]["status"] == "pending"
    # Another user's list is empty for this card.
    client.force_authenticate(User.objects.create_user(username="mine-other"))
    assert client.get(reverse("review-mine-list"), {"card": card.pk}).data["count"] == 0
