"""Durable outbox queue that feeds the search index.

The queue decouples database writes from index writes so a model save never
depends on the search engine being reachable::

    model save (post_save/post_delete)
        -> transaction.on_commit()
        -> SearchIndexUpdate row (status=pending)
        -> worker drains rows in batches
        -> Elasticsearch bulk index/delete

Rows are coalesced per object: repeated saves of the same object while a row
is pending only refresh the existing pending row, and a delete always
supersedes any pending index row for that object.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from search.models import SearchIndexUpdate
from search.queries import index_name as configured_index_name

logger = logging.getLogger(__name__)

__all__ = [
    "SearchIndexUpdate",
    "dispatch",
    "drain",
    "enqueue",
    "pending_count",
    "prune_done",
    "queue_depth",
    "retry_failed",
]


def enqueue(index_name, object_id, action=SearchIndexUpdate.ACTION_INDEX):
    """Queue an index/delete operation once the current transaction commits.

    Parameters
    ----------
    index_name : str
        Target index name.
    object_id : int
        Primary key of the object.
    action : str
        ``index`` or ``delete``.

    Returns
    -------
    None
    """

    def _write():
        _write_row(index_name, object_id, action)

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_write)
    else:
        _write()


def _write_row(index_name, object_id, action):
    """Insert or coalesce an outbox row (runs after commit).

    Parameters
    ----------
    index_name : str
        Target index name.
    object_id : int
        Primary key of the object.
    action : str
        ``index`` or ``delete``.

    Returns
    -------
    SearchIndexUpdate
        The row that was created or updated.
    """
    pending = SearchIndexUpdate.objects.filter(
        index_name=index_name,
        object_id=object_id,
        status=SearchIndexUpdate.STATUS_PENDING,
    )
    if action == SearchIndexUpdate.ACTION_DELETE:
        # A deletion supersedes any queued (re)index for the same object.
        deleted, _ = pending.delete()
        if deleted:
            logger.debug(
                "Superseded %s pending row(s) for %s#%s", deleted, index_name, object_id
            )
        return SearchIndexUpdate.objects.create(
            index_name=index_name,
            object_id=object_id,
            action=SearchIndexUpdate.ACTION_DELETE,
        )

    existing = (
        pending.filter(action=SearchIndexUpdate.ACTION_INDEX)
        .order_by("-created", "-id")
        .first()
    )
    if existing is not None:
        # Already queued for indexing: keep a single row per object.
        logger.debug("Coalesced index row for %s#%s", index_name, object_id)
        return existing

    return SearchIndexUpdate.objects.create(
        index_name=index_name,
        object_id=object_id,
        action=SearchIndexUpdate.ACTION_INDEX,
    )


def _load_object(index_name, object_id):
    """Return the model instance for a queued row.

    Parameters
    ----------
    index_name : str
        Target index name.
    object_id : int
        Primary key of the object.

    Returns
    -------
    Model | None
        Instance or ``None`` when it no longer exists.
    """
    if index_name == SearchIndexUpdate.INDEX_BANKS:
        from banks.models import Bank

        return Bank.objects.filter(pk=object_id).first()
    from credit_cards.models import CreditCard

    return CreditCard.objects.select_related("bank").filter(pk=object_id).first()


def _document_for(index_name, obj):
    """Serialize a model instance for the given index.

    Parameters
    ----------
    index_name : str
        Target index name.
    obj : Model
        Instance to serialize.

    Returns
    -------
    dict
        Index document.
    """
    if index_name == SearchIndexUpdate.INDEX_BANKS:
        from search.documents import bank_to_document

        return bank_to_document(obj)
    from search.documents import credit_card_to_document

    return credit_card_to_document(obj)


def pending_count():
    """Return the number of pending outbox rows.

    Returns
    -------
    int
        Count of ``pending`` rows.
    """
    return SearchIndexUpdate.objects.filter(
        status=SearchIndexUpdate.STATUS_PENDING
    ).count()


def queue_depth():
    """Return per-index queue depth for diagnostics.

    Returns
    -------
    dict
        Mapping of index name to pending row count plus a ``total`` key.
    """
    counts = dict(
        SearchIndexUpdate.objects.filter(status=SearchIndexUpdate.STATUS_PENDING)
        .values_list("index_name")
        .annotate(total=models.Count("id"))
    )
    counts["total"] = sum(value for key, value in counts.items() if key != "total")
    return counts


def drain(batch_size=None, service=None):
    """Process pending outbox rows and push them to the index.

    Parameters
    ----------
    batch_size : int | None
        Maximum number of rows to process in this call.  Defaults to
        ``settings.SEARCH_QUEUE_BATCH_SIZE``.
    service : SearchService | None
        Optional service instance (mainly for tests).

    Returns
    -------
    dict
        Summary with ``processed``, ``indexed``, ``deleted``, ``failed``,
        ``remaining`` and ``errors`` keys.
    """
    from search.service import SearchService

    if service is None:
        service = SearchService()
    batch_size = batch_size or getattr(settings, "SEARCH_QUEUE_BATCH_SIZE", 200)
    max_attempts = getattr(settings, "SEARCH_QUEUE_MAX_ATTEMPTS", 5)

    rows = list(
        SearchIndexUpdate.objects.filter(
            status=SearchIndexUpdate.STATUS_PENDING,
            available_at__lte=timezone.now(),
        ).order_by("created", "id")[:batch_size]
    )
    summary = {
        "processed": 0,
        "indexed": 0,
        "deleted": 0,
        "failed": 0,
        "remaining": pending_count(),
        "errors": [],
    }
    if not rows:
        return summary

    # Group work per index so the engine only sees a handful of bulk calls.
    by_index = {}
    for row in rows:
        by_index.setdefault(row.index_name, []).append(row)

    for kind, index_rows in by_index.items():
        # Queue rows store the logical kind so an index prefix can change
        # between environments without invalidating queued work.
        target_index = configured_index_name(kind)
        documents, vanished_ids = [], []
        for row in index_rows:
            if row.is_deletion:
                continue
            obj = _load_object(kind, row.object_id)
            if obj is None:
                # Object vanished between commit and drain: remove the document.
                vanished_ids.append(row.object_id)
                continue
            documents.append((row.object_id, _document_for(kind, obj)))
        delete_ids = [row.object_id for row in index_rows if row.is_deletion]
        delete_ids.extend(vanished_ids)
        try:
            # The index must exist before the first write: an engine that
            # auto-creates it would apply dynamic mappings, losing the
            # analyzers, synonyms and filterable fields.
            service.create_index(kind)
            if documents:
                service.bulk_index(target_index, documents)
                summary["indexed"] += len(documents)
            if delete_ids:
                service.delete_documents(target_index, delete_ids)
                summary["deleted"] += len(delete_ids)
        except Exception as exc:  # noqa: BLE001 - queue must survive engine errors
            logger.exception("Failed to drain %s search queue rows", kind)
            summary["errors"].append(f"{kind}: {exc}")
            for row in index_rows:
                row.attempts += 1
                row.last_error = str(exc)[:2000]
                if row.attempts >= max_attempts:
                    row.status = SearchIndexUpdate.STATUS_FAILED
                else:
                    # Exponential backoff: 5s, 10s, 20s ... capped at 5 minutes.
                    delay = min(300, 5 * (2 ** (row.attempts - 1)))
                    row.available_at = timezone.now() + timedelta(seconds=delay)
                row.save(
                    update_fields=["attempts", "last_error", "status", "available_at"]
                )
                summary["failed"] += 1
            continue

        now = timezone.now()
        for row in index_rows:
            row.status = SearchIndexUpdate.STATUS_DONE
            row.attempts += 1
            row.last_error = ""
            row.available_at = now
            row.modified = now
            row.save(update_fields=["status", "attempts", "last_error", "available_at"])
            summary["processed"] += 1

    service.refresh()
    summary["remaining"] = pending_count()
    return summary


def dispatch():
    """Send the current queue to a worker, falling back to inline draining.

    Returns
    -------
    dict
        Drain summary, or ``{"task_id": ...}`` when routed through Celery.
    """
    if getattr(settings, "SEARCH_QUEUE_VIA_CELERY", False):
        try:
            from search.tasks import process_search_index_queue

            result = process_search_index_queue.delay()
            return {"task_id": getattr(result, "id", None)}
        except Exception as exc:  # noqa: BLE001 - broker may be unreachable
            logger.warning("Celery dispatch failed, draining inline: %s", exc)
    return drain()


def retry_failed():
    """Re-queue rows that previously exhausted their attempts.

    Returns
    -------
    int
        Number of rows moved back to ``pending``.
    """
    return SearchIndexUpdate.objects.filter(
        status=SearchIndexUpdate.STATUS_FAILED
    ).update(
        status=SearchIndexUpdate.STATUS_PENDING,
        attempts=0,
        available_at=timezone.now(),
    )


def prune_done(older_than_hours=24):
    """Delete completed outbox rows to keep the table small.

    Parameters
    ----------
    older_than_hours : int
        Age threshold in hours for ``done`` rows.

    Returns
    -------
    int
        Number of rows removed.
    """
    cutoff = timezone.now() - timedelta(hours=older_than_hours)
    deleted, _ = SearchIndexUpdate.objects.filter(
        status=SearchIndexUpdate.STATUS_DONE, modified__lt=cutoff
    ).delete()
    return deleted
