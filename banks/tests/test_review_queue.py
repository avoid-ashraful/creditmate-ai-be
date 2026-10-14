"""Focused tests for the manual review queue."""

import logging
from decimal import Decimal
from unittest.mock import patch

import pytest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse

from banks.enums import ProcessingStatus, ReviewPriority, ReviewStatus
from banks.factories import CrawledContentFactory
from banks.models import ReviewQueue
from banks.services import ReviewQueueService
from credit_cards.factories import CreditCardFactory


@pytest.mark.django_db
class TestEnqueue:
    """Eligibility and idempotency rules for enqueueing."""

    @pytest.mark.parametrize(
        "status",
        [ProcessingStatus.PENDING, ProcessingStatus.PROCESSING, ProcessingStatus.FAILED],
    )
    def test_only_completed_crawls_are_queued(self, status):
        content = CrawledContentFactory(
            processing_status=status,
            needs_manual_review=True,
        )

        assert content.enqueue_for_manual_review() is None
        assert ReviewQueue.objects.count() == 0

    def test_completed_low_confidence_crawl_is_queued_once(self):
        content = CrawledContentFactory(
            extraction_confidence=0.2,
            needs_manual_review=True,
        )

        first = content.enqueue_for_manual_review()
        second = content.enqueue_for_manual_review()

        assert first == second
        assert ReviewQueue.objects.count() == 1
        assert first.bank == content.data_source.bank
        assert first.priority == ReviewPriority.HIGH

    def test_completed_non_review_crawl_is_not_queued(self):
        content = CrawledContentFactory(
            extraction_confidence=0.8,
            needs_manual_review=False,
        )

        assert content.enqueue_for_manual_review() is None
        assert ReviewQueue.objects.count() == 0

    @override_settings(REVIEW_QUEUE_NOTIFY_EMAILS=["review@example.test"])
    def test_high_priority_email_is_scheduled_after_commit(self):
        content = CrawledContentFactory(
            extraction_confidence=0.1,
            needs_manual_review=True,
        )
        service = ReviewQueueService()

        with patch("banks.services.review_queue.send_mail") as send_mail:
            with patch("banks.services.review_queue.transaction.on_commit") as on_commit:
                item = service.enqueue(content)
                assert item.priority == ReviewPriority.HIGH
                send_mail.assert_not_called()
                on_commit.assert_called_once()
                on_commit.call_args.args[0]()

            send_mail.assert_called_once_with(
                subject=f"High-priority credit-card review: {item.bank.name}",
                message=(
                    "A new high-priority credit-card extraction needs review. "
                    f"Bank: {item.bank.name}. Crawled content ID: {item.crawled_content_id}."
                ),
                from_email=None,
                recipient_list=["review@example.test"],
                fail_silently=False,
            )

    def test_high_priority_enqueue_emits_local_hook_once(self, caplog):
        content = CrawledContentFactory(
            extraction_confidence=0.1,
            needs_manual_review=True,
        )
        service = ReviewQueueService()

        with caplog.at_level(logging.WARNING, logger="banks.services.review_queue"):
            service.enqueue(content)
            service.enqueue(content)

        assert len(caplog.records) == 1
        assert "High-priority manual review queued" in caplog.text


@pytest.mark.django_db
class TestReviewTransitions:
    """Review decision transitions and immutability."""

    def setup_method(self):
        self.content = CrawledContentFactory(
            extraction_confidence=0.2,
            needs_manual_review=True,
        )
        self.item = ReviewQueue.objects.create(
            crawled_content=self.content,
            bank=self.content.data_source.bank,
        )
        self.service = ReviewQueueService()

    def test_approve_marks_item_approved(self):
        user = get_user_model().objects.create_user(username="reviewer", password="pw")

        self.service.approve(self.item, reviewer=user, notes="Looks correct")

        self.item.refresh_from_db()
        assert self.item.status == ReviewStatus.APPROVED
        assert self.item.reviewed_by == user
        assert self.item.reviewer_notes == "Looks correct"
        assert self.item.reviewed_at is not None


@pytest.mark.django_db
class TestReviewValidationAndRollback:
    """Invalid or rejected input must not overwrite trusted card values."""

    def setup_method(self):
        self.card = CreditCardFactory(annual_fee="100", interest_rate_apr="18")
        self.content = CrawledContentFactory(
            data_source__bank=self.card.bank,
            credit_card=self.card,
            parsed_json={
                "credit_cards": [
                    {
                        "name": self.card.name,
                        "annual_fee": "250",
                        "interest_rate_apr": "20",
                    }
                ]
            },
            extraction_confidence=0.2,
            needs_manual_review=True,
        )
        self.item = ReviewQueue.objects.create(
            crawled_content=self.content,
            bank=self.card.bank,
        )
        self.service = ReviewQueueService()

    def test_reject_does_not_change_trusted_card(self):
        original_fee = Decimal(self.card.annual_fee)
        original_json = self.content.parsed_json

        self.service.reject(self.item)

        self.card.refresh_from_db()
        self.content.refresh_from_db()
        assert self.card.annual_fee == original_fee
        assert self.content.parsed_json == original_json

    def test_valid_review_updates_card_and_queue(self):
        self.service.approve_and_apply(self.item, notes="Reviewed values")

        self.card.refresh_from_db()
        self.item.refresh_from_db()
        assert self.card.annual_fee == 250
        assert self.card.interest_rate_apr == 20
        assert self.item.status == ReviewStatus.APPROVED

    def test_invalid_numeric_input_leaves_data_untouched(self):
        original_fee = Decimal(self.card.annual_fee)
        self.content.parsed_json["credit_cards"][0]["annual_fee"] = "invalid"
        self.content.save(update_fields=["parsed_json"])

        with pytest.raises(ValidationError):
            self.service.approve_and_apply(self.item)

        self.card.refresh_from_db()
        self.item.refresh_from_db()
        assert self.card.annual_fee == original_fee
        assert self.item.status == ReviewStatus.PENDING

    def test_missing_card_leaves_queue_pending(self):
        self.content.credit_card = None
        self.content.save(update_fields=["credit_card"])

        with pytest.raises(ValidationError):
            self.service.approve_and_apply(self.item)

        self.item.refresh_from_db()
        assert self.item.status == ReviewStatus.PENDING

    def test_reject_marks_item_rejected(self):
        self.service.reject(self.item, notes="Bad extraction")

        self.item.refresh_from_db()
        assert self.item.status == ReviewStatus.REJECTED
        assert self.item.reviewed_at is not None

    @pytest.mark.parametrize("action", ["approve", "reject", "approve_and_apply"])
    def test_decided_items_are_immutable(self, action):
        self.service.approve(self.item)

        with pytest.raises(ValidationError):
            getattr(self.service, action)(self.item)

        self.item.refresh_from_db()
        assert self.item.status == ReviewStatus.APPROVED


@pytest.mark.django_db
class TestReviewQueueOrdering:
    """Verify queue ordering puts high priority before medium, then low."""

    def test_queue_orders_by_priority_numeric_not_lexicographic(self):
        """High priority appears first, then medium, then low."""
        bank = CrawledContentFactory().data_source.bank

        low = ReviewQueue.objects.create(
            crawled_content=CrawledContentFactory(data_source__bank=bank),
            bank=bank,
            priority="low",
        )
        medium = ReviewQueue.objects.create(
            crawled_content=CrawledContentFactory(data_source__bank=bank),
            bank=bank,
            priority="medium",
        )
        high = ReviewQueue.objects.create(
            crawled_content=CrawledContentFactory(data_source__bank=bank),
            bank=bank,
            priority="high",
        )

        ordered = list(ReviewQueue.objects.all())
        assert ordered == [high, medium, low]
        assert [q.priority_order for q in ordered] == [3, 2, 1]


@pytest.mark.django_db
class TestReviewQueuePermissionsAndAdmin:
    """Review queue admin permissions and filtered visibility."""

    def setup_method(self):
        self.item = ReviewQueueService().enqueue(
            CrawledContentFactory(
                extraction_confidence=0.2,
                needs_manual_review=True,
            )
        )

    def _client(self, **credentials):
        client = Client()
        client.login(**credentials)
        return client

    def test_anonymous_users_cannot_view_queue(self):
        response = Client().get(reverse("admin:banks_reviewqueue_changelist"))
        assert response.status_code == 302

    def test_staff_without_permissions_cannot_view_queue(self):
        user = get_user_model().objects.create_user(
            username="staff", password="pw", is_staff=True
        )
        user.user_permissions.add(Permission.objects.get(codename="view_reviewqueue"))

        response = self._client(username="staff", password="pw").get(
            reverse("admin:banks_reviewqueue_changelist")
        )
        assert response.status_code == 403

    def test_staff_with_permissions_can_filter_and_view_queue(self):
        user = get_user_model().objects.create_user(
            username="reviewer", password="pw", is_staff=True
        )
        for codename in ("view_reviewqueue", "change_reviewqueue"):
            user.user_permissions.add(Permission.objects.get(codename=codename))

        response = self._client(username="reviewer", password="pw").get(
            reverse("admin:banks_reviewqueue_changelist"),
            {
                "bank__id__exact": self.item.bank_id,
                "priority__exact": ReviewPriority.HIGH,
                "status__exact": ReviewStatus.PENDING,
            },
        )
        assert response.status_code == 200
        assert self.item.bank.name.encode() in response.content
