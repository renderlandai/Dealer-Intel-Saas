"""Stand-alone scan worker — Phase 5 (minimal).

Polls Supabase for `scan_jobs` rows in `pending` status, atomically claims
one at a time, and runs it via `app.tasks.execute_persisted_task`. The
runner code lives in `app.services.scan_runners` and is FastAPI-clean per
Phase 4.5/4.6, so this entry point pulls in *only* what it needs to drive
the pipeline — no FastAPI / slowapi / auth imports.

Why HTTP-less polling instead of a queue:
    The 2026-03-28 log entry documents two prior failed attempts at moving
    scans onto a Redis-backed queue (Celery, then ARQ). Both crashed in
    production over SSL transport and stale-key bugs. Postgres is the
    shared source of truth that has never failed, and `scan_jobs` already
    has the right indexes. For the Phase 5-minimal scope (one paying
    client at 50 dealers), `WHERE status='pending' ORDER BY created_at
    LIMIT 1` polled every couple of seconds is correct AND cheap.

How a row is claimed atomically:
    The conditional UPDATE
        update({...status='running'...}).eq('id', X).eq('status', 'pending')
    is the cheapest race-free claim available through PostgREST. supabase-py
    returns the affected rows in `.data`; if `len(data) == 1` we won the
    race, if 0 someone else (a second worker, or the API in mixed mode)
    grabbed it first. Two workers polling the same row are safe — at most
    one will land the conditional update.

Lifecycle:
    Loop forever, sleeping `WORKER_POLL_INTERVAL` between empty polls.
    SIGTERM is caught and turned into a graceful shutdown that lets the
    in-flight scan finish before exiting (DigitalOcean App Platform sends
    SIGTERM with ~10s before SIGKILL, which is plenty for the worker to
    decide not to claim a *new* row; the in-flight runner respects its own
    `SCAN_TIMEOUT_SECONDS` backstop).

Env vars (in addition to the API ones):
    WORKER_POLL_INTERVAL  seconds between empty polls (default 2.0)
    WORKER_LOG_LEVEL      override LOG_LEVEL for the worker only

Run:
    python -m app.worker
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any, Dict, Optional

from .config import get_settings
from .database import supabase
from .logging_config import setup_logging
from .tasks import KNOWN_TASK_NAMES, execute_persisted_task
from .services.scan_runners import _utc_now, _normalize_scan_error


log = logging.getLogger("dealer_intel.worker")

_settings = get_settings()


def _poll_interval() -> float:
    try:
        return float(os.getenv("WORKER_POLL_INTERVAL", "2.0"))
    except ValueError:
        log.warning("Invalid WORKER_POLL_INTERVAL; falling back to 2.0s")
        return 2.0


def _claim_pending_job() -> Optional[Dict[str, Any]]:
    """Find one pending row and atomically flip it to running.

    Returns the claimed row (with id, source, metadata) or None when the
    queue is empty / another worker won the race.
    """
    try:
        candidate = supabase.table("scan_jobs") \
            .select("id, source, metadata") \
            .eq("status", "pending") \
            .order("created_at") \
            .limit(1) \
            .execute()
        rows = candidate.data or []
        if not rows:
            return None
        job = rows[0]
    except Exception as e:
        log.error("Worker poll query failed: %s", e, exc_info=True)
        return None

    job_id = job["id"]
    now = _utc_now()
    try:
        claim = supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": now,
            "last_heartbeat_at": now,
        }).eq("id", job_id).eq("status", "pending").execute()
        if not claim.data:
            # Another worker (or the API in mixed mode) won the race.
            log.debug("Lost claim race on %s — another worker took it", job_id)
            return None
    except Exception as e:
        log.error("Failed to claim %s: %s", job_id, e, exc_info=True)
        return None

    return job


def _extract_dispatch(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull `metadata.dispatch` off a claimed row.

    Returns ``{'task_name': str, 'args': list}`` or None when the row was
    never enriched (e.g. created before Phase 5-minimal shipped, or by an
    older API instance during a rolling deploy). The caller treats None as
    a hard failure for the row.
    """
    meta = (job.get("metadata") or {})
    dispatch = meta.get("dispatch") if isinstance(meta, dict) else None
    if not isinstance(dispatch, dict):
        return None
    task_name = dispatch.get("task_name")
    args = dispatch.get("args")
    if task_name not in KNOWN_TASK_NAMES or not isinstance(args, list):
        return None
    return {"task_name": task_name, "args": args}


def _mark_failed(job_id: str, message: str) -> None:
    try:
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": message[:500],
            "completed_at": _utc_now(),
        }).eq("id", job_id).execute()
    except Exception as e:
        log.error("Could not mark %s failed: %s", job_id, e, exc_info=True)


# Grace re-check budget for the insert→dispatch-persist race (see
# `_await_dispatch`). 5 × 1.5s = 7.5s, comfortably longer than the API request
# that inserts the row and then persists `metadata.dispatch`, yet trivial next
# to the 20-minute idle cleanup window.
_DISPATCH_GRACE_ATTEMPTS = 5
_DISPATCH_GRACE_SLEEP_SECONDS = 1.5


async def _await_dispatch(job_id: str) -> Optional[Dict[str, Any]]:
    """Re-read a claimed row's dispatch payload a few times before giving up.

    Closes a write-after-claim race: a scan row is inserted with
    ``status='pending'`` (immediately claimable) a beat BEFORE the API writes
    ``metadata.dispatch`` (the create flow is insert → build args →
    ``dispatch_task`` → ``_persist_dispatch_args``). A fast worker can win the
    claim in that window and see no dispatch yet, even though one lands
    milliseconds later. Re-reading the row with a short grace lets the
    slightly-late persist arrive. Only a row that *truly* never gets a
    dispatch (e.g. the persist itself failed) returns None here and is then
    hard-failed by the caller.
    """
    for attempt in range(1, _DISPATCH_GRACE_ATTEMPTS + 1):
        await asyncio.sleep(_DISPATCH_GRACE_SLEEP_SECONDS)
        try:
            refreshed = supabase.table("scan_jobs") \
                .select("id, source, metadata") \
                .eq("id", job_id) \
                .single() \
                .execute()
        except Exception as e:
            log.warning(
                "Dispatch re-read failed for %s (attempt %d/%d): %s",
                job_id, attempt, _DISPATCH_GRACE_ATTEMPTS, e,
            )
            continue
        dispatch = _extract_dispatch(refreshed.data or {})
        if dispatch is not None:
            log.info(
                "Dispatch payload for %s landed after grace (attempt %d/%d)",
                job_id, attempt, _DISPATCH_GRACE_ATTEMPTS,
            )
            return dispatch
    return None


async def _process_one_job(job: Dict[str, Any]) -> None:
    """Run a single claimed job to completion (success OR failure)."""
    job_id = job["id"]
    source = job.get("source") or "unknown"
    dispatch = _extract_dispatch(job)
    if dispatch is None:
        # Possible insert→dispatch-persist race — give the late write a
        # brief window to land before treating the row as unrunnable.
        dispatch = await _await_dispatch(job_id)
    if dispatch is None:
        log.error(
            "Claimed %s but it still has no replayable dispatch payload "
            "after grace — failing",
            job_id,
        )
        _mark_failed(job_id, "Worker: no dispatch args on row")
        return

    task_name = dispatch["task_name"]
    args = dispatch["args"]
    log.info(
        "Worker running job=%s source=%s task=%s argc=%d",
        job_id, source, task_name, len(args),
    )

    # The runners themselves write `status=completed` on success and
    # `status=failed` (with normalised error message) on raised exceptions.
    # We catch here only as a safety net — execute_persisted_task should
    # never propagate an unexpected exception out of the runner.
    try:
        await execute_persisted_task(job_id, task_name, args)
        log.info("Worker finished job=%s task=%s", job_id, task_name)
    except Exception as e:
        log.error(
            "Worker task crashed for job=%s task=%s: %s",
            job_id, task_name, e, exc_info=True,
        )
        _mark_failed(job_id, _normalize_scan_error(e))


async def _run_forever(stop: asyncio.Event) -> None:
    interval = _poll_interval()
    log.info(
        "Worker poll loop starting (interval=%.1fs, settings.frontend_url=%s)",
        interval, _settings.frontend_url,
    )
    while not stop.is_set():
        job = _claim_pending_job()
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            continue

        # Run the job in this loop — only one job at a time per worker.
        # If you need parallelism across jobs, scale by adding more
        # worker instances; intra-job concurrency lives in the runner.
        try:
            await _process_one_job(job)
        except Exception:
            # _process_one_job already logs and best-effort marks failed;
            # a bare except here just guarantees we never bubble out and
            # break the loop.
            log.exception("Unexpected error processing job %s", job.get("id"))


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    def _handler(signame: str) -> None:
        log.info("Worker received %s — finishing current job and exiting", signame)
        stop.set()

    for signame in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(
                getattr(signal, signame),
                _handler, signame,
            )
        except NotImplementedError:
            # Windows / restricted environments — fall back to default.
            pass


def main() -> None:
    """Entry point: ``python -m app.worker``."""
    log_level = os.getenv("WORKER_LOG_LEVEL") or os.getenv("LOG_LEVEL", "info")
    setup_logging(debug=(log_level.lower() == "debug"))
    log.info("Dealer-Intel scan worker booting (PID %d)", os.getpid())

    # Sentry boot mirrors the API path — if SENTRY_DSN is set, errors get
    # the same downstream reporting. Import lazily so the worker can run
    # without the dep installed in dev sandboxes.
    if _settings.sentry_dsn:
        try:
            import sentry_sdk  # type: ignore
            sentry_sdk.init(dsn=_settings.sentry_dsn, traces_sample_rate=0.0)
            log.info("Sentry initialised for worker")
        except Exception as e:
            log.warning("Sentry init failed: %s", e)

    # Pre-warm CLIP so the first job does not pay model-load latency on
    # top of its actual scan time.
    try:
        from .services.embedding_service import warmup as _clip_warmup
        if _clip_warmup():
            log.info("CLIP model warmed up")
        else:
            log.warning("CLIP warmup returned False — Stage 2 will be skipped")
    except Exception as e:
        log.warning("CLIP warmup raised: %s", e)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop = asyncio.Event()
    _install_signal_handlers(loop, stop)

    try:
        loop.run_until_complete(_run_forever(stop))
    finally:
        log.info("Worker exiting")
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
