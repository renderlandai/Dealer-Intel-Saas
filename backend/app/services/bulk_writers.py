"""
Bulk-write helpers for the scan pipeline.

Two hot tables are written from many call sites in tight loops:

- `discovered_images` — every URL extracted from a website / SerpApi / Apify
  becomes one row. A typical 50-page website scan produces hundreds of inserts.
- `matches` — every confirmed asset detection becomes one row, with an
  optional follow-up `alerts` row for compliance violations / drift.

Doing one HTTP round-trip per row pegs the Supabase REST API and, at scale,
makes the scan worker spend more time waiting on the database than running AI.
This module provides:

- `bulk_insert_discovered_images(rows)` — single-call insert with per-row
  fallback that preserves the FK-23503 ("distributor deleted mid-scan") retry
  semantics that previously lived only in `extraction_service`.
- `DiscoveredImageBuffer` — collect rows, auto-flush at a threshold, return
  the cumulative count after a final `flush_all()`.
- `bulk_insert_matches(items)` — bulk insert match rows AND any associated
  alert rows in two HTTP calls. Falls back to per-row on batch failure so a
  single bad payload cannot lose the rest of the batch.
- `MatchBuffer` — collect (match_payload, alert_template_or_none) pairs,
  auto-flush at a threshold, flushed by the caller at end-of-scan.
- `bulk_mark_images_processed(image_ids)` — flip `is_processed=True` on many
  `discovered_images` rows in a single HTTP call.
- `ProcessedImageBuffer` — collect ids as the analyse loop finishes each
  image, auto-flush at a threshold, drained by the caller at end-of-scan.
  Mirrors `MatchBuffer` but for the trailing UPDATE that previously fired
  one HTTP round-trip per image inside `_analyze_single_image`.

All helpers are sync (the supabase-py client is sync); they are safe to call
from async functions without `await` because they do not block the event loop
any more than the existing per-row inserts already do.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..database import supabase

log = logging.getLogger("dealer_intel.bulk_writers")


# ---------------------------------------------------------------------------
# discovered_images
# ---------------------------------------------------------------------------

# Threshold chosen so a typical multi-page website scan flushes ~once per page
# while keeping payloads under Supabase REST limits.
_DI_BATCH_SIZE = 50


def _safe_insert_discovered_image(row: Dict[str, Any]) -> bool:
    """Insert one discovered_image row, retrying without distributor on FK loss.

    If the distributor was deleted mid-scan (Postgres FK violation 23503),
    the row is re-inserted with `distributor_id = None` so the scan keeps
    running. Returns True on success, False on permanent failure.
    """
    try:
        supabase.table("discovered_images").insert(row).execute()
        return True
    except Exception as err:
        if "23503" in str(err) and row.get("distributor_id"):
            log.warning(
                "Distributor %s deleted mid-scan — saving image without distributor",
                row["distributor_id"],
            )
            row = dict(row)
            row["distributor_id"] = None
            try:
                supabase.table("discovered_images").insert(row).execute()
                return True
            except Exception as retry_err:
                log.error("Insert still failed after clearing distributor_id: %s", retry_err)
                return False
        log.error("discovered_images insert failed: %s", err)
        return False


def bulk_insert_discovered_images(rows: List[Dict[str, Any]]) -> int:
    """Insert many discovered_images rows in a single HTTP call.

    Falls back to per-row insertion (with FK-23503 retry) if the bulk call
    fails for any reason — this preserves the prior behaviour that one bad
    row never killed an entire scan.

    Returns the number of rows successfully inserted.
    """
    if not rows:
        return 0

    try:
        result = supabase.table("discovered_images").insert(rows).execute()
        # supabase-py returns the inserted rows in `.data`; trust its length.
        return len(result.data) if result.data is not None else len(rows)
    except Exception as err:
        log.warning(
            "Bulk discovered_images insert (%d rows) failed, falling back per-row: %s",
            len(rows), err,
        )
        return sum(1 for r in rows if _safe_insert_discovered_image(r))


class DiscoveredImageBuffer:
    """Buffered writer for `discovered_images`.

    Usage:
        buf = DiscoveredImageBuffer()
        for img in images:
            buf.add({...})
        discovered_count = buf.flush_all()

    Auto-flushes whenever the buffer reaches `batch_size` rows. The caller
    MUST call `flush_all()` (or `flush()`) at the end to persist any remainder.
    """

    def __init__(self, batch_size: int = _DI_BATCH_SIZE):
        self.batch_size = batch_size
        self._pending: List[Dict[str, Any]] = []
        self.total_inserted = 0

    def add(self, row: Dict[str, Any]) -> None:
        self._pending.append(row)
        if len(self._pending) >= self.batch_size:
            self.flush()

    def flush(self) -> int:
        """Flush the current buffer. Returns rows inserted in this flush."""
        if not self._pending:
            return 0
        batch, self._pending = self._pending, []
        n = bulk_insert_discovered_images(batch)
        self.total_inserted += n
        return n

    def flush_all(self) -> int:
        """Flush remainder and return cumulative inserted count for the buffer."""
        self.flush()
        return self.total_inserted


# ---------------------------------------------------------------------------
# matches (+ alerts)
# ---------------------------------------------------------------------------

# Smaller than discovered_images because match payloads carry the full
# `ai_analysis` JSON and can be 5–20× larger per row.
_MATCH_BATCH_SIZE = 25


@dataclass
class PendingMatch:
    """A queued match insert plus an optional alert payload.

    The alert payload must NOT contain `match_id` — it is filled in after the
    match row is actually inserted and its UUID is known.
    """
    payload: Dict[str, Any]
    alert_template: Optional[Dict[str, Any]] = None


def bulk_insert_matches(items: List[PendingMatch]) -> List[Optional[Dict[str, Any]]]:
    """Insert match rows and (where attached) the corresponding alert rows.

    Returns a list parallel to `items` containing the inserted match row dict
    (with at least `id`) or `None` for any row that failed.

    On batch insert failure, falls back to per-row inserts so individual bad
    payloads do not lose the rest of the batch.
    """
    if not items:
        return []

    rows = [it.payload for it in items]
    inserted: List[Optional[Dict[str, Any]]] = []

    try:
        result = supabase.table("matches").insert(rows).execute()
        data = result.data or []
        if len(data) == len(rows):
            inserted = list(data)
        else:
            # Defensive: API returned fewer rows than requested. Trust position
            # for what came back; mark the rest unknown.
            inserted = list(data) + [None] * (len(rows) - len(data))
            log.warning(
                "matches bulk insert returned %d rows for %d sent — alert linkage may be incomplete",
                len(data), len(rows),
            )
    except Exception as err:
        log.warning(
            "Bulk matches insert (%d rows) failed, falling back per-row: %s",
            len(rows), err,
        )
        for row in rows:
            try:
                res = supabase.table("matches").insert(row).execute()
                inserted.append(res.data[0] if res.data else None)
            except Exception as ind_err:
                log.error("Individual match insert failed: %s", ind_err)
                inserted.append(None)

    # Build and bulk-insert alerts (only for matches that actually landed and
    # had a template attached).
    alert_rows: List[Dict[str, Any]] = []
    for item, ins in zip(items, inserted):
        if not ins or not item.alert_template:
            continue
        alert = dict(item.alert_template)
        alert["match_id"] = ins.get("id")
        alert_rows.append(alert)

    if alert_rows:
        try:
            supabase.table("alerts").insert(alert_rows).execute()
        except Exception as err:
            log.warning(
                "Bulk alerts insert (%d rows) failed, falling back per-row: %s",
                len(alert_rows), err,
            )
            for alert in alert_rows:
                try:
                    supabase.table("alerts").insert(alert).execute()
                except Exception as ind_err:
                    log.error("Individual alert insert failed: %s", ind_err)

    return inserted


@dataclass
class MatchBuffer:
    """Buffered writer for `matches` (with attached alerts).

    Usage:
        buf = MatchBuffer()
        for image in images:
            ...
            if new_match:
                buf.add(payload, alert_template=...)
        buf.flush_all()

    Auto-flushes whenever the buffer reaches `batch_size`. The caller MUST
    call `flush_all()` (or `flush()`) at the end. Not safe for concurrent
    `add()` calls from multiple coroutines — each scan worker should own
    its own buffer.
    """
    batch_size: int = _MATCH_BATCH_SIZE
    _pending: List[PendingMatch] = field(default_factory=list)
    total_inserted: int = 0
    total_failed: int = 0

    def add(
        self,
        payload: Dict[str, Any],
        alert_template: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._pending.append(PendingMatch(payload=payload, alert_template=alert_template))
        if len(self._pending) >= self.batch_size:
            self.flush()

    def flush(self) -> int:
        """Flush the current buffer. Returns rows inserted in this flush."""
        if not self._pending:
            return 0
        batch, self._pending = self._pending, []
        results = bulk_insert_matches(batch)
        ok = sum(1 for r in results if r)
        self.total_inserted += ok
        self.total_failed += len(results) - ok
        return ok

    def flush_all(self) -> int:
        """Flush remainder and return cumulative inserted count."""
        self.flush()
        return self.total_inserted


# ---------------------------------------------------------------------------
# discovered_images.is_processed (trailing UPDATE per analysed image)
# ---------------------------------------------------------------------------

# Larger than the insert batches because UPDATE-by-id payloads are tiny
# (just a list of UUIDs) and we want this to keep up with very long scans
# without flushing more often than necessary.
_PI_BATCH_SIZE = 100


def bulk_mark_images_processed(image_ids: List[str]) -> int:
    """Flip `is_processed=True` on many `discovered_images` rows in one call.

    Falls back to per-row updates if the bulk call fails so a single bad id
    cannot wedge an entire scan's progress flag. Returns the number of rows
    successfully marked.
    """
    if not image_ids:
        return 0

    try:
        supabase.table("discovered_images")\
            .update({"is_processed": True})\
            .in_("id", image_ids)\
            .execute()
        return len(image_ids)
    except Exception as err:
        log.warning(
            "Bulk discovered_images.is_processed update (%d rows) failed, "
            "falling back per-row: %s",
            len(image_ids), err,
        )
        marked = 0
        for image_id in image_ids:
            try:
                supabase.table("discovered_images")\
                    .update({"is_processed": True})\
                    .eq("id", image_id)\
                    .execute()
                marked += 1
            except Exception as ind_err:
                log.error(
                    "Individual is_processed update failed for %s: %s",
                    image_id, ind_err,
                )
        return marked


class ProcessedImageBuffer:
    """Buffered writer for the trailing `is_processed=True` UPDATE.

    Usage:
        buf = ProcessedImageBuffer()
        for image in images:
            ... analyse ...
            buf.add(image["id"])
        buf.flush_all()

    Auto-flushes whenever the buffer reaches `batch_size` ids. The caller
    MUST call `flush_all()` (or `flush()`) at the end so any remainder is
    persisted before the scan reports its status. Not safe for concurrent
    `add()` calls from multiple coroutines — each scan worker should own
    its own buffer.
    """

    def __init__(self, batch_size: int = _PI_BATCH_SIZE):
        self.batch_size = batch_size
        self._pending: List[str] = []
        self.total_marked = 0

    def add(self, image_id: str) -> None:
        if not image_id:
            return
        self._pending.append(str(image_id))
        if len(self._pending) >= self.batch_size:
            self.flush()

    def flush(self) -> int:
        """Flush the current buffer. Returns rows marked in this flush."""
        if not self._pending:
            return 0
        batch, self._pending = self._pending, []
        n = bulk_mark_images_processed(batch)
        self.total_marked += n
        return n

    def flush_all(self) -> int:
        """Flush remainder and return cumulative marked count for the buffer."""
        self.flush()
        return self.total_marked
