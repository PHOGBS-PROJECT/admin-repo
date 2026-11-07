"""Celery app for background jobs. Run a worker with:

    celery -A config worker --loglevel=info
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

app = Celery("phogbs")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
