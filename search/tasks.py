"""Celery entry point for draining the search outbox queue.

Workers are optional: ``SEARCH_QUEUE_VIA_CELERY=False`` (the default) drains
the queue inline after each commit, while enabling it routes batches through
the existing Celery/Redis infrastructure used by the crawler.
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


@shared_task(name=TASK_NAME, bind=True, max_retries=3, default_retry_delay=60)
def process_search_index_queue(self, batch_size=None):
    """Drain pending outbox rows into the search index.

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
    """Queue a drain on Celery when enabled.

    Parameters
    ----------
    batch_size : int | None
        Optional override for the number of rows per run.

    Returns
    -------
    str | None
        Celery task id, or ``None`` when Celery is disabled.
    """
    if not getattr(settings, "SEARCH_QUEUE_VIA_CELERY", False):
        return None
    try:
        return process_search_index_queue.delay(batch_size=batch_size).id
    except Exception as exc:  # noqa: BLE001 - broker may be down
        logger.warning("Could not dispatch search queue drain: %s", exc)
        return None
