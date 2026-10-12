"""Django models for the search index service."""

from django.db import models
from django.utils import timezone

from common.models import Audit


class SearchIndexUpdate(Audit):
    """A single pending index/delete operation for the search engine.

    This is the durable outbox row behind the ``signal -> queue -> index``
    pipeline: model writes never talk to Elasticsearch directly, they only
    insert a row here once the surrounding transaction commits.

    Attributes
    ----------
    index_name : str
        Target index name (``banks`` or ``credit_cards``).
    object_id : int
        Primary key of the object to index or delete.
    action : str
        ``index`` to (re)index the object, ``delete`` to remove it.
    status : str
        ``pending``, ``done`` or ``failed``.
    attempts : int
        Number of times a worker tried to process the row.
    available_at : datetime
        Rows are only drained once this timestamp is in the past (retry backoff).
    last_error : str
        Last processing error, kept for operators.
    """

    INDEX_BANKS = "banks"
    INDEX_CREDIT_CARDS = "credit_cards"

    ACTION_INDEX = "index"
    ACTION_DELETE = "delete"
    ACTION_CHOICES = [
        (ACTION_INDEX, "Index"),
        (ACTION_DELETE, "Delete"),
    ]

    STATUS_PENDING = "pending"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    INDEX_CHOICES = [
        (INDEX_BANKS, "Banks"),
        (INDEX_CREDIT_CARDS, "Credit cards"),
    ]

    index_name = models.CharField(max_length=64, choices=INDEX_CHOICES)
    object_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default=ACTION_INDEX)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "search_searchindexupdate"
        ordering = ["created", "id"]
        indexes = [
            models.Index(
                fields=["status", "available_at"], name="search_queue_pending_idx"
            ),
            models.Index(
                fields=["index_name", "object_id"], name="search_queue_object_idx"
            ),
        ]

    def __str__(self):
        return f"{self.index_name}#{self.object_id}:{self.action} ({self.status})"

    @property
    def is_deletion(self):
        """Return True when the row removes a document.

        Returns
        -------
        bool
        """
        return self.action == self.ACTION_DELETE
