"""Celery application configuration for Dealer Intel background tasks."""
import os
import ssl

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("dealer_intel")

celery_app.conf.update(
    broker_url=redis_url,
    result_backend=None,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_max_tasks_per_child=50,
    task_soft_time_limit=1800,
    task_time_limit=2400,
    include=["app.tasks"],
)

if redis_url.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
