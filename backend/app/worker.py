"""ARQ worker configuration for Dealer Intel background tasks.

Replaces Celery — uses redis-py directly (no kombu), native async,
and has zero SSL transport bugs on managed Redis/Valkey.
"""
import logging
import os
import re
from urllib.parse import urlparse

from arq import cron
from arq.connections import ArqRedis, RedisSettings

from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("dealer_intel.worker")
logging.basicConfig(level=logging.INFO)

redis_url = os.getenv("REDIS_URL", os.getenv("redis_url", "redis://localhost:6379/0"))
_masked = re.sub(r"://[^:]*:[^@]*@", "://***:***@", redis_url) if "@" in redis_url else redis_url
print(f"[dealer_intel.worker] Redis URL: {_masked}")


def _parse_redis_url(url: str) -> RedisSettings:
    """Convert a redis:// or rediss:// URL into ARQ RedisSettings."""
    parsed = urlparse(url)
    use_ssl = parsed.scheme == "rediss"
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        username=parsed.username or None,
        password=parsed.password,
        database=int(parsed.path.lstrip("/") or 0),
        ssl=use_ssl,
        ssl_cert_reqs="none" if use_ssl else "required",
        conn_timeout=15,
        conn_retries=5,
        conn_retry_delay=2,
        retry_on_timeout=True,
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


async def on_startup(ctx: dict) -> None:
    """Log queue state at worker startup and clear stale in-progress keys."""
    redis: ArqRedis = ctx["redis"]

    queue_entries = await redis.zrangebyscore("arq:queue", min=float("-inf"), max=float("inf"), withscores=True)
    log.info("STARTUP: arq:queue has %d entries:", len(queue_entries))
    for entry in queue_entries:
        job_id_bytes, score = entry
        job_id = job_id_bytes if isinstance(job_id_bytes, str) else job_id_bytes.decode()
        job_data = await redis.get(f"arq:job:{job_id}")
        in_prog = await redis.exists(f"arq:in-progress:{job_id}")
        log.info(
            "  job=%s score=%.0f has_data=%s in_progress=%s",
            job_id, score, job_data is not None, bool(in_prog),
        )
        if in_prog:
            log.warning("  Clearing stale in-progress key for job %s", job_id)
            await redis.delete(f"arq:in-progress:{job_id}")


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

    on_startup = on_startup

    redis_settings = REDIS_SETTINGS

    max_jobs = 2
    job_timeout = 2400
    max_tries = 1
    health_check_interval = 30
    keep_result = 3600
