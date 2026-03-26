"""Scheduled scan service — uses APScheduler CronTrigger for time-precise scheduling."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from uuid import UUID

import redis as redis_lib
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import supabase

log = logging.getLogger("dealer_intel.scheduler")

_scheduler: Optional[AsyncIOScheduler] = None
_LOCK_KEY = "dealer_intel:scheduler_lock"
_LOCK_TTL = 300  # seconds

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

FREQUENCY_DELTAS: Dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "biweekly": timedelta(weeks=2),
    "monthly": timedelta(days=30),
}


def _build_cron_trigger(schedule: dict) -> CronTrigger:
    """Build a CronTrigger from a schedule row's frequency, run_at_time, and run_on_day."""
    freq = schedule.get("frequency", "daily")
    time_str = schedule.get("run_at_time") or "09:00"
    parts = time_str.split(":")
    hour = int(parts[0]) if len(parts) > 0 else 9
    minute = int(parts[1]) if len(parts) > 1 else 0
    day_of_week = schedule.get("run_on_day")  # 0=Mon .. 6=Sun, None for daily

    if freq == "daily":
        return CronTrigger(hour=hour, minute=minute, timezone="UTC")

    if freq == "weekly":
        dow = DAY_NAMES[day_of_week] if day_of_week is not None else "mon"
        return CronTrigger(day_of_week=dow, hour=hour, minute=minute, timezone="UTC")

    if freq == "biweekly":
        dow = DAY_NAMES[day_of_week] if day_of_week is not None else "mon"
        return CronTrigger(day_of_week=dow, hour=hour, minute=minute, week="*/2", timezone="UTC")

    if freq == "monthly":
        return CronTrigger(day=1, hour=hour, minute=minute, timezone="UTC")

    return CronTrigger(hour=hour, minute=minute, timezone="UTC")


def compute_next_run(frequency: str, run_at_time: str = "09:00", run_on_day: Optional[int] = None) -> datetime:
    """Estimate the next run datetime for display purposes."""
    parts = run_at_time.split(":")
    hour = int(parts[0]) if len(parts) > 0 else 9
    minute = int(parts[1]) if len(parts) > 1 else 0

    now = datetime.now(timezone.utc)
    today_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if frequency == "daily":
        return today_at + timedelta(days=1) if today_at <= now else today_at

    if frequency in ("weekly", "biweekly"):
        target_dow = run_on_day if run_on_day is not None else 0  # Monday
        current_dow = now.weekday()
        days_ahead = (target_dow - current_dow) % 7
        if days_ahead == 0 and today_at <= now:
            days_ahead = 7
        nxt = today_at + timedelta(days=days_ahead)
        if frequency == "biweekly" and days_ahead < 7:
            nxt += timedelta(weeks=1)
        return nxt

    if frequency == "monthly":
        next_month = (now.month % 12) + 1
        year = now.year + (1 if next_month == 1 else 0)
        return datetime(year, next_month, 1, hour, minute, tzinfo=timezone.utc)

    return today_at + timedelta(days=1)


# ------------------------------------------------------------------
# Trigger a single scheduled scan
# ------------------------------------------------------------------
async def _trigger_scan(schedule_id: str) -> None:
    """Look up a schedule row, create a scan job, and kick off the scan."""
    try:
        row = (
            supabase.table("scan_schedules")
            .select("*")
            .eq("id", schedule_id)
            .eq("is_active", True)
            .single()
            .execute()
        )
        sched = row.data
        if not sched:
            log.warning("Schedule %s not found or inactive — skipping", schedule_id)
            return

        org_id = sched["organization_id"]
        campaign_id = sched["campaign_id"]
        source = sched["source"]

        campaign = (
            supabase.table("campaigns")
            .select("id")
            .eq("id", campaign_id)
            .single()
            .execute()
        )
        if not campaign.data:
            log.warning("Campaign %s deleted — deactivating schedule %s", campaign_id, schedule_id)
            supabase.table("scan_schedules").update({"is_active": False}).eq("id", schedule_id).execute()
            return

        distributors = (
            supabase.table("distributors")
            .select("*")
            .eq("organization_id", org_id)
            .eq("status", "active")
            .execute()
        )
        dist_list = distributors.data or []
        if not dist_list:
            log.info("No active distributors for org %s — skipping schedule %s", org_id, schedule_id)
            _update_schedule_timestamps(sched)
            return

        job_data = {
            "organization_id": org_id,
            "campaign_id": campaign_id,
            "source": source,
            "status": "pending",
        }
        result = supabase.table("scan_jobs").insert(job_data).execute()
        scan_job = result.data[0]
        scan_job_id = UUID(scan_job["id"])

        from ..tasks import (
            run_google_ads_scan_task,
            run_facebook_scan_task,
            run_instagram_scan_task,
            run_website_scan_task,
            dispatch_task,
        )
        from ..services import apify_instagram_service

        cid_str = campaign_id
        job_id_str = str(scan_job_id)
        dispatched = False

        if source == "google_ads":
            names = [d.get("google_ads_advertiser_id") or d["name"] for d in dist_list]
            mapping = {
                (d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"]
                for d in dist_list
            }
            dispatched = dispatch_task(run_google_ads_scan_task, [names, job_id_str, mapping, cid_str], job_id_str, "google_ads")

        elif source == "instagram":
            urls = [d["instagram_url"] for d in dist_list if d.get("instagram_url")]
            mapping: Dict[str, str] = {}
            for d in dist_list:
                ig_url = d.get("instagram_url")
                if ig_url:
                    username = apify_instagram_service._extract_username(ig_url)
                    if username:
                        mapping[username.lower()] = d["id"]
                    mapping[d["name"].lower()] = d["id"]
            dispatched = dispatch_task(run_instagram_scan_task, [urls, job_id_str, mapping, cid_str], job_id_str, "instagram")

        elif source == "facebook":
            urls = [d["facebook_url"] for d in dist_list if d.get("facebook_url")]
            mapping = {d["name"].lower(): d["id"] for d in dist_list}
            dispatched = dispatch_task(run_facebook_scan_task, [urls, job_id_str, mapping, cid_str, "facebook"], job_id_str, "facebook")

        elif source == "website":
            urls = [d["website_url"] for d in dist_list if d.get("website_url")]
            mapping = {
                d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
                for d in dist_list
                if d.get("website_url")
            }
            dispatched = dispatch_task(run_website_scan_task, [urls, job_id_str, mapping, cid_str], job_id_str, "website")

        if not dispatched:
            log.error("Scheduled scan %s: task dispatch failed, job %s left as failed", schedule_id, job_id_str)
            _update_schedule_timestamps(sched)
            return

        supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", str(scan_job_id)).execute()

        _update_schedule_timestamps(sched)
        log.info("Scheduled scan triggered: schedule=%s source=%s campaign=%s", schedule_id, source, campaign_id)

    except Exception:
        log.exception("Error running scheduled scan %s", schedule_id)


def _update_schedule_timestamps(sched: dict) -> None:
    now = datetime.now(timezone.utc)
    freq = sched.get("frequency", "daily")
    time_str = sched.get("run_at_time") or "09:00"
    day = sched.get("run_on_day")
    nxt = compute_next_run(freq, time_str, day)
    supabase.table("scan_schedules").update({
        "last_run_at": now.isoformat(),
        "next_run_at": nxt.isoformat(),
        "updated_at": now.isoformat(),
    }).eq("id", sched["id"]).execute()


# ------------------------------------------------------------------
# Scheduler lifecycle
# ------------------------------------------------------------------
async def load_schedules() -> None:
    """Load all active schedules from the DB and register them with APScheduler."""
    global _scheduler
    if _scheduler is None:
        return

    try:
        rows = (
            supabase.table("scan_schedules")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
    except Exception:
        log.warning("scan_schedules table may not exist yet — skipping schedule load")
        return

    schedules = rows.data or []
    log.info("Loading %d active scan schedule(s)", len(schedules))

    for s in schedules:
        _register_job(s)


def _register_job(schedule: dict) -> None:
    """Register (or replace) an APScheduler job for a given scan_schedule row."""
    if _scheduler is None:
        return

    sid = schedule["id"]
    job_id = f"scan_schedule_{sid}"

    _scheduler.add_job(
        _trigger_scan,
        trigger=_build_cron_trigger(schedule),
        args=[sid],
        id=job_id,
        replace_existing=True,
    )


def remove_job(schedule_id: str) -> None:
    if _scheduler is None:
        return
    job_id = f"scan_schedule_{schedule_id}"
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass


def upsert_job(schedule: dict) -> None:
    """Add or update a scheduler job when schedule is created/updated via API."""
    if not schedule.get("is_active", True):
        remove_job(schedule["id"])
        return
    _register_job(schedule)


def _get_lock_redis() -> redis_lib.Redis:
    """Get a Redis client for scheduler lock operations."""
    from ..celery_app import celery_app
    broker_url = str(celery_app.conf.broker_url)
    return redis_lib.from_url(
        broker_url,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


async def _renew_scheduler_lock() -> None:
    """Renew the Redis lock so other workers don't start a second scheduler."""
    try:
        r = _get_lock_redis()
        r.expire(_LOCK_KEY, _LOCK_TTL)
        r.close()
    except Exception:
        log.warning("Failed to renew scheduler lock", exc_info=True)


async def _cleanup_stale_scans() -> None:
    """Auto-fail scans stuck in 'pending' for more than 5 minutes."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        stale = supabase.table("scan_jobs") \
            .select("id") \
            .eq("status", "pending") \
            .lt("created_at", cutoff) \
            .execute()

        for job in (stale.data or []):
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": "Scan timed out in pending state — task was not picked up by worker",
            }).eq("id", job["id"]).execute()
            log.warning("Auto-failed stale pending scan: %s", job["id"])

        if stale.data:
            log.info("Cleaned up %d stale pending scan(s)", len(stale.data))
    except Exception:
        log.exception("Error cleaning up stale scans")


async def _run_retention() -> None:
    """Wrapper for the daily data retention sweep."""
    from .retention_service import run_retention_sweep
    await run_retention_sweep()


async def start() -> None:
    """Start the APScheduler background scheduler and load persisted schedules.

    Uses a Redis lock to guarantee only one Gunicorn worker runs the
    scheduler, even when WEB_CONCURRENCY > 1.
    """
    if os.getenv("SCHEDULER_ENABLED", "true").lower() != "true":
        log.info("APScheduler disabled on this instance (SCHEDULER_ENABLED != true)")
        return

    # Singleton: only one worker should run the scheduler
    try:
        r = _get_lock_redis()
        acquired = r.set(_LOCK_KEY, str(os.getpid()), nx=True, ex=_LOCK_TTL)
        r.close()
        if not acquired:
            log.info("Scheduler already running in another worker — skipping (PID %d)", os.getpid())
            return
    except Exception:
        log.warning("Could not check scheduler lock — starting scheduler anyway", exc_info=True)

    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()
    log.info("APScheduler started (PID %d)", os.getpid())

    # Renew the Redis lock every minute so it doesn't expire
    _scheduler.add_job(
        _renew_scheduler_lock,
        trigger=CronTrigger(minute="*", timezone="UTC"),
        id="scheduler_lock_renewal",
        replace_existing=True,
    )

    # Auto-fail scans stuck in pending for too long (every 5 minutes)
    _scheduler.add_job(
        _cleanup_stale_scans,
        trigger=CronTrigger(minute="*/5", timezone="UTC"),
        id="stale_scan_cleanup",
        replace_existing=True,
    )
    log.info("Stale scan cleanup scheduled every 5 minutes")

    # Daily data retention sweep at 03:00 UTC
    _scheduler.add_job(
        _run_retention,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="data_retention_sweep",
        replace_existing=True,
    )
    log.info("Data retention sweep scheduled for 03:00 UTC daily")

    await load_schedules()


async def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        log.info("APScheduler shut down")
        _scheduler = None
        try:
            r = _get_lock_redis()
            r.delete(_LOCK_KEY)
            r.close()
        except Exception:
            pass
