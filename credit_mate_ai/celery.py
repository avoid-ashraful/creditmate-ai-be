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
app.conf.timezone = "UTC"
