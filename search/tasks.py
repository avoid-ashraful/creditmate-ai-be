"""Celery entry point for draining the search outbox queue.

Scheduling model (default configuration, ``SEARCH_SYNC_MODE=queue``)::

    model save  ->  transaction.on_commit()  ->  outbox row (pending)
                                               ^
    celery beat (search-index-queue-drain) ----+  every SEARCH_QUEUE_DRAIN_INTERVAL s
    celery worker -> process_search_index_queue -> drain() -> Elasticsearch

Model saves never touch the broker and never touch the engine: they only
append an outbox row.  The row becomes an index update when the periodic
Celery beat entry ``search-index-queue-drain`` (``credit_mate_ai/celery.py``)
publishes :func:`process_search_index_queue`, which therefore **requires a
running Celery worker and beat** — without them the queue only grows
(manageable with ``python manage.py search_index --sync``).

Opt-in variations:

* ``SEARCH_QUEUE_VIA_CELERY=True`` — additionally publish a drain task right
  after each commit (lower latency, needs a reachable broker in the request
  path; failures are logged and the row simply stays queued);
* ``SEARCH_SYNC_MODE=sync`` — drain inline after every commit (blocking, no
  worker needed);
* ``SEARCH_SYNC_MODE=off`` — do not queue anything at all.
"""

import logging

from django.conf import settings

try:
    from celery import shared_task
except ImportError:  # pragma: no cover - Celery is a hard dependency in prod

    def shared_task(*args, **kwargs):  # type: ignore[misc]
        """Fallback decorator when Celery is unavailable."""

        def decorator(func):
            func.delay = lambda *a, **k: func(*a, **k)  # noqa: E731
            return func

        if args and callable(args[0]):
            return args[0]
        return decorator


logger = logging.getLogger(__name__)

TASK_NAME = "search.process_index_queue"


@shared_task(
    name=TASK_NAME,
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    ignore_result=True,
)
def process_search_index_queue(self, batch_size=None):
    """Drain pending outbox rows into the search index.

    This is the task Celery beat dispatches every
    ``settings.SEARCH_QUEUE_DRAIN_INTERVAL`` seconds, and it is the only
    thing the default ``SEARCH_SYNC_MODE=queue`` configuration relies on.

    Parameters
    ----------
    self : celery.Task
        Task instance (``bind=True``).
    batch_size : int | None
        Optional override for the number of rows per run.

    Returns
    -------
    dict
        Drain summary produced by :func:`search.queue.drain`.
    """
    from search.queue import drain

    batch_size = batch_size or getattr(settings, "SEARCH_QUEUE_BATCH_SIZE", 200)
    summary = drain(batch_size=batch_size)
    logger.info("Search queue drained: %s", summary)
    return summary


@shared_task(name="search.rebuild_index", bind=True, max_retries=1)
def rebuild_search_index(self, drop=True):
    """Rebuild both search indexes from the database.

    Parameters
    ----------
    self : celery.Task
        Task instance (``bind=True``).
    drop : bool
        Drop existing index definitions before rebuilding.

    Returns
    -------
    dict
        Per index rebuild summary.
    """
    from search.service import SearchService

    summary = SearchService().rebuild(drop=drop)
    logger.info("Search index rebuilt: %s", summary)
    return summary


def dispatch_queue_drain(batch_size=None):
    """Publish a drain task right after a commit (opt-in low latency path).

    Only used when ``SEARCH_QUEUE_VIA_CELERY=True``.  A broker failure is
    logged and swallowed: the outbox row stays ``pending`` and the periodic
    beat drain picks it up, so this call never falls back to a blocking
    inline drain inside a request.

    Parameters
    ----------
    batch_size : int | None
        Optional override for the number of rows per run.

    Returns
    -------
    str | None
        Celery task id, or ``None`` when Celery dispatch is disabled or the
        broker is unreachable.
    """
    if not getattr(settings, "SEARCH_QUEUE_VIA_CELERY", False):
        return None
    try:
        return process_search_index_queue.delay(batch_size=batch_size).id
    except Exception as exc:  # noqa: BLE001 - broker may be down
        logger.warning("Could not dispatch search queue drain: %s", exc)
        return None
