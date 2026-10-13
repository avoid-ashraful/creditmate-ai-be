import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from banks.enums import ReviewPriority, ReviewStatus
from banks.services.credit_card_data_service import CreditCardDataService
from banks.validators.numeric_fields import parse_numeric_value

logger = logging.getLogger(__name__)


class ReviewQueueService:
    """Transactional actions for the manual credit-card review queue."""

    @transaction.atomic
    def enqueue(self, crawled_content, notify=True):
        """Create a queue item for a completed, low-confidence crawl.

        Parameters
        ----------
        crawled_content : CrawledContent
            Crawl to queue for review.
        notify : bool, optional
            Whether to emit the local high-priority hook when a new item is
            created. No external notification is sent.

        Returns
        -------
        ReviewQueue or None
            The new or existing queue item, or ``None`` for an ineligible crawl.
        """
        from banks.models import ReviewQueue as RQ
        queue_item, created = RQ.objects.get_or_create(
            crawled_content=crawled_content,
            defaults={
                "bank": crawled_content.data_source.bank,
                "priority": crawled_content.review_priority,
            },
        )
        if notify and created and queue_item.priority == ReviewPriority.HIGH:
            self.notify_high_priority(queue_item)
        return queue_item

    def notify_high_priority(self, queue_item):
        """Record a high-priority review event locally without an external send."""
        logger.warning(
            "High-priority manual review queued for crawled content %s (bank %s)",
            queue_item.crawled_content_id,
            queue_item.bank_id,
        )

    @transaction.atomic
    def approve(self, queue_item, reviewer=None, notes=""):
        """Mark an extraction approved without changing trusted card data."""
        self._validate_pending(queue_item)
        return self._record_decision(queue_item, ReviewStatus.APPROVED, reviewer, notes)

    @transaction.atomic
    def reject(self, queue_item, reviewer=None, notes=""):
        """Mark an extraction rejected without changing trusted card data."""
        self._validate_pending(queue_item)
        return self._record_decision(queue_item, ReviewStatus.REJECTED, reviewer, notes)

    @transaction.atomic
    def approve_and_apply(self, queue_item, reviewer=None, notes=""):
        """Apply validated reviewed values and mark the item approved.

        Invalid input raises before any database write. The entire update is
        atomic, so a later failure rolls back both card and queue changes.

        Returns
        -------
        ReviewQueue
            Approved queue item.
        """
        self._validate_pending(queue_item)
        crawled_content = queue_item.crawled_content
        card = crawled_content.credit_card
        card_data = crawled_content.review_card_data
        if card is None or card_data is None:
            raise ValidationError("A linked credit card with extracted data is required.")

        reviewed_values = CreditCardDataService()._prepare_card_defaults(card_data)
        self._validate_card_values(card_data)
        for field, value in reviewed_values.items():
            if field in {"annual_fee", "interest_rate_apr"} and value is None:
                continue
            setattr(card, field, value)

        card.full_clean(exclude=["bank_id", "creditcard_ptr_id"])
        card.save(update_fields=list(reviewed_values) + ["modified"])
        self._sync_reviewed_card_data(crawled_content, card_data)
        return self._record_decision(queue_item, ReviewStatus.APPROVED, reviewer, notes)

    def _validate_pending(self, queue_item):
        if queue_item.status != ReviewStatus.PENDING:
            raise ValidationError("Only pending review queue items can be changed.")

    def _validate_card_values(self, card_data):
        for field in ("annual_fee", "interest_rate_apr"):
            value, status = parse_numeric_value(card_data.get(field), field)
            if status == "invalid":
                raise ValidationError({field: "Enter a valid numeric value."})

    def _sync_reviewed_card_data(self, crawled_content, card_data):
        parsed_json = crawled_content.parsed_json if isinstance(crawled_content.parsed_json, dict) else {}
        cards = parsed_json.get("credit_cards")
        if not isinstance(cards, list):
            cards = []
            parsed_json["credit_cards"] = cards

        card_data = dict(card_data)
        card_data["name"] = crawled_content.credit_card.name
        for index, candidate in enumerate(cards):
            if isinstance(candidate, dict) and candidate.get("name") == card_data["name"]:
                cards[index] = card_data
                break
        else:
            cards.append(card_data)

        crawled_content.parsed_json = parsed_json
        crawled_content.save(update_fields=["parsed_json"])

    def _record_decision(self, queue_item, status, reviewer, notes):
        if not isinstance(notes, str):
            raise ValidationError("Reviewer notes must be text.")

        queue_item.status = status
        queue_item.reviewed_by = reviewer
        queue_item.reviewer_notes = notes
        queue_item.reviewed_at = timezone.now()
        queue_item.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewer_notes",
                "reviewed_at",
                "modified",
            ]
        )
        return queue_item
