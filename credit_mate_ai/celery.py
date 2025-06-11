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
}
app.conf.timezone = "UTC"
