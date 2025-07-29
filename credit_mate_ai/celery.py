import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "credit_mate_ai.settings")

app = Celery("credit_mate_ai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "crawl-bank-data-weekly": {
        "task": "banks.tasks.crawl_all_bank_data",
        "schedule": 604800.0,  # 7 days in seconds
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
