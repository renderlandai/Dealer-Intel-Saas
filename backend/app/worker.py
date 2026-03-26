"""ARQ worker configuration for Dealer Intel background tasks.

Replaces Celery — uses redis-py directly (no kombu), native async,
and has zero SSL transport bugs on managed Redis/Valkey.
"""
import logging
import os
import re

from arq import cron
from arq.connections import RedisSettings

from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("dealer_intel.worker")

redis_url = os.getenv("REDIS_URL", os.getenv("redis_url", "redis://localhost:6379/0"))
_masked = re.sub(r"://[^:]*:[^@]*@", "://***:***@", redis_url) if "@" in redis_url else redis_url
print(f"[dealer_intel.worker] Redis URL: {_masked}")


def _parse_redis_url(url: str) -> RedisSettings:
    """Convert a redis:// or rediss:// URL into ARQ RedisSettings."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password,
        database=int(parsed.path.lstrip("/") or 0),
        ssl=parsed.scheme == "rediss",
        conn_timeout=15,
        conn_retries=5,
        conn_retry_delay=2,
    )


REDIS_SETTINGS = _parse_redis_url(redis_url)


# -- Import task functions (they live in tasks.py) -------------------------
from .tasks import (  # noqa: E402
    run_website_scan_task,
    run_google_ads_scan_task,
    run_facebook_scan_task,
    run_instagram_scan_task,
    run_analyze_scan_task,
    run_reprocess_images_task,
    cleanup_stale_scans,
)


class WorkerSettings:
    """ARQ worker settings — this class is passed to `arq worker`."""

    functions = [
        run_website_scan_task,
        run_google_ads_scan_task,
        run_facebook_scan_task,
        run_instagram_scan_task,
        run_analyze_scan_task,
        run_reprocess_images_task,
        cleanup_stale_scans,
    ]

    cron_jobs = [
        cron(cleanup_stale_scans, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]

    redis_settings = REDIS_SETTINGS

    max_jobs = 2
    job_timeout = 2400
    max_tries = 3
    health_check_interval = 30
    keep_result = 0
