"""Durable outbox queue that feeds the search index.

The queue decouples database writes from index writes so a model save never
depends on the search engine being reachable::

    model save (post_save/post_delete)
        -> transaction.on_commit()
        -> SearchIndexUpdate row (status=pending)
        -> drainer leases the rows (status=processing)
        -> Elasticsearch bulk index/delete
        -> status=done

Rows are coalesced per object *while they are pending*: repeated saves of the
same object only refresh the existing pending row, and a delete always
supersedes any pending index row for that object.  A row that a drainer has
already leased is deliberately **not** coalescable, so a save that lands while
a batch is being shipped to the engine writes a fresh pending row instead of
being swallowed by the in-flight one.

Draining is scheduled, never implicit: the default configuration
(``SEARCH_SYNC_MODE=queue``) is drained periodically by the Celery beat entry
``search-index-queue-drain`` (``credit_mate_ai/celery.py``), which runs
:func:`search.tasks.process_index_queue` on a worker every
``SEARCH_QUEUE_DRAIN_INTERVAL`` seconds.  Nothing in the save path talks to
the broker or to the engine.
"""

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from search.models import SearchIndexUpdate
from search.queries import index_name as configured_index_name

logger = logging.getLogger(__name__)

__all__ = [
    "SearchIndexUpdate",
    "claim_batch",
    "dispatch",
    "drain",
    "enqueue",
    "pending_count",
    "prune_done",
    "queue_depth",
    "reclaim_expired_leases",
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

    Only ``pending`` rows take part in coalescing.  A row a drainer has
    already leased (``processing``) is skipped on purpose: the drainer works
    from a snapshot of the object taken at claim time, so folding a newer save
    into it would silently drop that update.  The new save therefore gets its
    own pending row and is drained right after the in-flight one.

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
    """Return the number of outbox rows that still owe work.

    Includes rows a drainer currently holds (``processing``), so the number
    stays truthful while a batch is in flight.

    Returns
    -------
    int
        Count of ``pending`` + ``processing`` rows.
    """
    return SearchIndexUpdate.objects.filter(
        status__in=SearchIndexUpdate.OUTSTANDING_STATUSES
    ).count()


def queue_depth():
    """Return per-index queue depth for diagnostics.

    Returns
    -------
    dict
        Mapping of index name to outstanding row count plus a ``total`` key.
    """
    counts = dict(
        SearchIndexUpdate.objects.filter(
            status__in=SearchIndexUpdate.OUTSTANDING_STATUSES
        )
        .values_list("index_name")
        .annotate(total=models.Count("id"))
    )
    counts["total"] = sum(value for key, value in counts.items() if key != "total")
    return counts


def _lease_seconds():
    """Return the drainer lease duration in seconds.

    Returns
    -------
    float
        ``settings.SEARCH_QUEUE_LEASE_SECONDS`` (default 120).
    """
    return float(getattr(settings, "SEARCH_QUEUE_LEASE_SECONDS", 120))


def reclaim_expired_leases():
    """Hand rows back to the pool when their drainer died mid-flight.

    A batch is leased (``status=processing`` + ``claimed_by``) while it is
    being shipped to the engine.  If the process crashes, the lease simply
    ages out and the next drain picks the row up again, so a crash can never
    strand a row forever.

    Returns
    -------
    int
        Number of rows returned to ``pending``.
    """
    now = timezone.now()
    cutoff = now - timedelta(seconds=_lease_seconds())
    reclaimed = SearchIndexUpdate.objects.filter(
        status=SearchIndexUpdate.STATUS_PROCESSING,
        claimed_at__lt=cutoff,
    ).update(
        status=SearchIndexUpdate.STATUS_PENDING,
        claimed_by="",
        claimed_at=None,
        last_error="lease expired before the row was written; requeued",
        modified=now,
    )
    if reclaimed:
        logger.warning(
            "Recovered %s outbox row(s) whose drainer lease expired", reclaimed
        )
    return reclaimed


def claim_batch(batch_size=None, token=None):
    """Atomically lease the next batch of due rows for one drainer.

    The two statements below are the mutual exclusion point of the whole
    queue: the ``UPDATE ... WHERE status='pending'`` only ever flips rows that
    are still free, so two workers racing for the same rows end up with
    disjoint claims instead of processing the same rows twice.

    Parameters
    ----------
    batch_size : int | None
        Maximum number of rows to lease.  Defaults to
        ``settings.SEARCH_QUEUE_BATCH_SIZE``.
    token : str | None
        Lease token identifying this drainer (generated when omitted).

    Returns
    -------
    tuple of (str, list of SearchIndexUpdate)
        The lease token and the rows this drainer now owns, ordered by
        ``created, id``.
    """
    batch_size = batch_size or getattr(settings, "SEARCH_QUEUE_BATCH_SIZE", 200)
    token = token or uuid.uuid4().hex
    now = timezone.now()
    candidates = list(
        SearchIndexUpdate.objects.filter(
            status=SearchIndexUpdate.STATUS_PENDING,
            available_at__lte=now,
        )
        .order_by("created", "id")
        .values_list("pk", flat=True)[:batch_size]
    )
    if not candidates:
        return token, []
    SearchIndexUpdate.objects.filter(
        pk__in=candidates,
        status=SearchIndexUpdate.STATUS_PENDING,
    ).update(
        status=SearchIndexUpdate.STATUS_PROCESSING,
        claimed_by=token,
        claimed_at=now,
        modified=now,
    )
    rows = list(
        SearchIndexUpdate.objects.filter(
            claimed_by=token,
            status=SearchIndexUpdate.STATUS_PROCESSING,
        ).order_by("created", "id")
    )
    if not rows:
        logger.debug("Another drainer claimed every candidate row first")
    return token, rows


def _holds_lease(token, rows):
    """Return True when this drainer still owns every row of the batch.

    Parameters
    ----------
    token : str
        Lease token of the calling drainer.
    rows : list of SearchIndexUpdate
        Rows the drainer believes it owns.

    Returns
    -------
    bool
        ``False`` as soon as any row was reclaimed by another drainer.
    """
    pks = [row.pk for row in rows]
    if not pks:
        return True
    held = SearchIndexUpdate.objects.filter(
        pk__in=pks,
        claimed_by=token,
        status=SearchIndexUpdate.STATUS_PROCESSING,
    ).count()
    return held == len(pks)


def drain(batch_size=None, service=None, token=None):  # noqa: C901
    """Lease pending outbox rows and push them to the index.

    The batch is claimed up front (:func:`claim_batch`), so two concurrent
    drainers always work on disjoint rows and a save that lands mid-drain
    writes a fresh pending row instead of coalescing into the row that is
    already being shipped.  Every write back to the table is guarded by the
    lease token: a row that was taken over after its lease expired is never
    marked ``done`` by its previous owner, so the newest drainer's view wins.

    Parameters
    ----------
    batch_size : int | None
        Maximum number of rows to process in this call.  Defaults to
        ``settings.SEARCH_QUEUE_BATCH_SIZE``.
    service : SearchService | None
        Optional service instance (mainly for tests).
    token : str | None
        Lease token; generated per call.  Passing one lets a test simulate a
        second, competing drainer.

    Returns
    -------
    dict
        Summary with ``processed``, ``indexed``, ``deleted``, ``failed``,
        ``stale``, ``reclaimed``, ``remaining`` and ``errors`` keys.
    """
    from search.service import SearchService

    if service is None:
        service = SearchService()
    batch_size = batch_size or getattr(settings, "SEARCH_QUEUE_BATCH_SIZE", 200)
    max_attempts = getattr(settings, "SEARCH_QUEUE_MAX_ATTEMPTS", 5)

    # Recovery: a drainer that died with a batch in flight leaves rows in
    # `processing`; once the lease ages out they are drained again.
    reclaimed = reclaim_expired_leases()
    summary = {
        "processed": 0,
        "indexed": 0,
        "deleted": 0,
        "failed": 0,
        "stale": 0,
        "reclaimed": reclaimed,
        "remaining": 0,
        "errors": [],
    }
    token, rows = claim_batch(batch_size=batch_size, token=token)
    summary["remaining"] = pending_count()
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

        if not _holds_lease(token, index_rows):
            # The lease expired while the documents were built (slow engine,
            # paused worker). Another drainer owns these rows now, so writing
            # would push a snapshot that may be older than theirs: stand down
            # and leave the batch to its current owner.
            summary["stale"] += len(index_rows)
            logger.warning(
                "Lost the lease on %s %s outbox row(s); skipped a stale write",
                len(index_rows),
                kind,
            )
            continue

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
                attempts = row.attempts + 1
                if attempts >= max_attempts:
                    status = SearchIndexUpdate.STATUS_FAILED
                    available_at = timezone.now()
                else:
                    status = SearchIndexUpdate.STATUS_PENDING
                    # Exponential backoff: 5s, 10s, 20s ... capped at 5 minutes.
                    delay = min(300, 5 * (2 ** (attempts - 1)))
                    available_at = timezone.now() + timedelta(seconds=delay)
                SearchIndexUpdate.objects.filter(
                    pk=row.pk,
                    claimed_by=token,
                    status=SearchIndexUpdate.STATUS_PROCESSING,
                ).update(
                    status=status,
                    attempts=attempts,
                    last_error=str(exc)[:2000],
                    available_at=available_at,
                    modified=timezone.now(),
                    claimed_by="",
                    claimed_at=None,
                )
                summary["failed"] += 1
            continue

        now = timezone.now()
        for row in index_rows:
            updated = SearchIndexUpdate.objects.filter(
                pk=row.pk,
                claimed_by=token,
                status=SearchIndexUpdate.STATUS_PROCESSING,
            ).update(
                status=SearchIndexUpdate.STATUS_DONE,
                attempts=row.attempts + 1,
                last_error="",
                available_at=now,
                modified=now,
                claimed_by="",
                claimed_at=None,
            )
            if updated:
                summary["processed"] += 1
            else:
                # Reclaimed after an expired lease: the row already belongs to
                # another drainer, which will re-read the object itself.
                summary["stale"] += 1

    service.refresh()
    summary["remaining"] = pending_count()
    return summary


def dispatch():
    """Drain the queue now, optionally routing through Celery first.

    This is the *explicit* path used by ``SEARCH_SYNC_MODE=sync`` and by
    manual/admin triggers.  The default (``SEARCH_SYNC_MODE=queue``) never
    calls it: there the outbox is drained periodically by the Celery beat
    entry ``search-index-queue-drain``.

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
        claimed_by="",
        claimed_at=None,
        modified=timezone.now(),
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
