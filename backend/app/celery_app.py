"""Celery application configuration for Dealer Intel background tasks."""
import os
import re
import ssl

from dotenv import load_dotenv
load_dotenv()

from celery import Celery

# REDIS_URL is the canonical env var for both Celery and app config.
# Pydantic Settings (config.py) reads it case-insensitively as `redis_url`,
# but Celery is configured before FastAPI boots, so we read the env directly.
redis_url = os.getenv("REDIS_URL", os.getenv("redis_url", "redis://localhost:6379/0"))

_masked = re.sub(r"://[^:]*:[^@]*@", "://***:***@", redis_url) if "@" in redis_url else redis_url
print(f"[dealer_intel.celery] Broker URL: {_masked}")

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
    broker_connection_retry_on_startup=True,
)

if redis_url.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
