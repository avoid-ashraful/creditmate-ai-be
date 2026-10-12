"""Celery application: worker entry point and beat (periodic) schedule.

Everything scheduled here runs on the *existing* Celery infrastructure used
by the crawler — ``celery -A credit_mate_ai worker`` and
``celery -A credit_mate_ai beat`` (see ``docker-compose.yml`` /
``docker-compose.dev.yml``), broker ``CELERY_BROKER_URL``.

``beat_schedule`` is assigned directly on ``app.conf`` on purpose: the
assignment is recorded in Celery's pre-configuration and therefore survives
the lazy ``config_from_object("django.conf:settings")`` load that happens
later, while a ``CELERY_BEAT_SCHEDULE`` Django setting would be *replaced* by
this dictionary.  New periodic work should therefore be appended here.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "credit_mate_ai.settings")

app = Celery("credit_mate_ai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "crawl-bank-data-weekly": {
        "task": "banks.tasks.crawl_all_bank_data",
        "schedule": 604800.0,  # 7 days in seconds
    },
    # Daily crawl of every active bank (2:00 UTC, expires after 6 hours so a
    # missed window does not replay stale work)
    "daily-crawl-all-active-banks": {
        "task": "banks.tasks.daily_crawl_all_active_banks",
        "schedule": crontab(hour=2, minute=0),
        "options": {"expires": 6 * 60 * 60},
    },
    # Monthly tasks - run on 1st day of each month at 2 AM UTC
    "monthly-data-quality-check": {
        "task": "banks.tasks.monthly_data_quality_check",
        "schedule": 30 * 24 * 60 * 60,  # 30 days in seconds
        "options": {"expires": 24 * 60 * 60},  # Expire after 24 hours if not run
    },
    "monthly-schedule-charge-discovery": {
        "task": "banks.tasks.monthly_schedule_charge_url_discovery",
        "schedule": 30 * 24 * 60 * 60,  # 30 days in seconds
        "options": {"expires": 24 * 60 * 60},
    },
    "monthly-comprehensive-crawl": {
        "task": "banks.tasks.monthly_comprehensive_crawl",
        "schedule": 30 * 24 * 60 * 60,  # 30 days in seconds
        "options": {"expires": 24 * 60 * 60},
    },
}

SEARCH_DRAIN_BEAT_ENTRY = "search-index-queue-drain"


def search_queue_drain_entry():
    """Build the periodic drain entry for the search outbox queue.

    This is what turns the default ``SEARCH_SYNC_MODE=queue`` mode from
    "enqueue only" into a working signal -> queue -> index pipeline: beat
    publishes ``search.process_index_queue`` every
    ``settings.SEARCH_QUEUE_DRAIN_INTERVAL`` seconds and a worker drains the
    outbox rows (including expired retry backoffs and leases).

    The schedule is omitted when the drain would have nothing to do:
    ``SEARCH_ENABLED=False``, ``SEARCH_SYNC_MODE=off`` or a non-positive
    interval (which is also how the schedule can be switched off).

    Returns
    -------
    dict | None
        Beat entry, or ``None`` when automatic draining is disabled.
    """
    # Read the knob from Django settings so ``settings.py`` stays the single
    # source of truth for the SEARCH_* defaults.  ``credit_mate_ai/__init__.py``
    # imports this module while Django is still importing its settings module;
    # Django resolves that re-entrant lookup itself (the settings module simply
    # finishes loading first), so reading a setting from here is safe.
    from django.conf import settings

    if not getattr(settings, "SEARCH_ENABLED", True):
        return None
    if getattr(settings, "SEARCH_SYNC_MODE", "queue") == "off":
        return None
    interval = float(getattr(settings, "SEARCH_QUEUE_DRAIN_INTERVAL", 15))
    if interval <= 0:
        return None
    return {
        "task": "search.process_index_queue",
        "schedule": interval,
        # Do not replay a burst of stale drains when a worker comes back
        # after being down; the queue itself is durable and is simply
        # drained on the next tick.
        "options": {"expires": max(60, int(interval * 4))},
    }


_search_drain_entry = search_queue_drain_entry()
if _search_drain_entry is not None:
    app.conf.beat_schedule[SEARCH_DRAIN_BEAT_ENTRY] = _search_drain_entry

app.conf.timezone = "UTC"
