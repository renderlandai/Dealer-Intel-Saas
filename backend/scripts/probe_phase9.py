#!/usr/bin/env python
"""Phase-9 fix sprint smoke probe.

Runs a 2-dealer ``run_website_scan`` in-process so the operator can
verify that the Phase-9 changes (per-phase timing, sub-budgets, dealer
cap drop, telemetry-gap fix) all fire cleanly and that the new fields
land in ``scan_jobs.pipeline_stats``.

Usage::

    cd backend && source venv/bin/activate
    python scripts/probe_phase9.py [--dealers N] [--campaign UUID]

The script will:
  1. Insert a fresh ``scan_jobs`` row (status=running) attached to the
     specified campaign + organization.
  2. Pick the first N active distributors with a ``website_url`` for
     that organization.
  3. Call ``run_website_scan`` directly (bypasses the API+auth layer
     but exercises the same runner code path the dispatcher would).
  4. Print the final ``pipeline_stats`` so the new Phase-9 keys are
     visible at a glance.

By default it scans 2 dealers (small enough to finish in a few
minutes, large enough to exercise every code path including
parallel dealer fan-out).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from uuid import UUID, uuid4

# Make the ``app`` package importable when run from backend/scripts/.
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from app.config import get_settings  # noqa: E402
from app.database import supabase  # noqa: E402
from app.services.scan_runners import run_website_scan  # noqa: E402


DEFAULT_CAMPAIGN_ID = "d15b6216-5587-4218-9f45-24292a70b099"  # Consistency Craver
DEFAULT_ORG_ID = "6a2edbc0-c6ba-47f2-810b-9adc78c2d026"


PHASE9_KEYS = (
    "extract_ms_total",
    "analyze_ms_total",
    "images_in_flight_total",
    "slowest_page_ms",
    "slowest_page_url",
    "page_hard_timeout_seconds",
    "page_extract_timeout_seconds",
    "page_analyze_timeout_seconds",
    "dealer_hard_timeout_seconds",
)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dealers", type=int, default=2)
    parser.add_argument("--campaign", default=DEFAULT_CAMPAIGN_ID)
    parser.add_argument("--org", default=DEFAULT_ORG_ID)
    args = parser.parse_args()

    settings = get_settings()
    print(
        "Phase-9 settings in effect:",
        json.dumps(
            {
                "page_hard_timeout_seconds": settings.page_hard_timeout_seconds,
                "page_extract_timeout_seconds": settings.page_extract_timeout_seconds,
                "page_analyze_timeout_seconds": settings.page_analyze_timeout_seconds,
                "dealer_hard_timeout_seconds": settings.dealer_hard_timeout_seconds,
                "max_concurrent_dealers": settings.max_concurrent_dealers,
                "pages_per_dealer_concurrency": settings.pages_per_dealer_concurrency,
            },
            indent=2,
        ),
    )

    dists = (
        supabase.table("distributors")
        .select("id,name,website_url,status")
        .eq("organization_id", args.org)
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    with_urls = [d for d in dists if d.get("website_url")][: args.dealers]
    if not with_urls:
        print("No active distributors with website_url found", file=sys.stderr)
        return 2

    urls = [d["website_url"] for d in with_urls]
    mapping = {d["website_url"]: UUID(d["id"]) for d in with_urls}
    print(f"\nProbing with {len(urls)} dealer(s):")
    for d in with_urls:
        print(f"  - {d['name']}  ({d['website_url']})")

    scan_id = uuid4()
    insert_payload = {
        "id": str(scan_id),
        "organization_id": args.org,
        "campaign_id": args.campaign,
        "status": "running",
        "source": "website",
        "started_at": "now()",
        "total_items": 0,
        "processed_items": 0,
        "matches_count": 0,
        "metadata": {"label": "phase9-probe", "started_by": "scripts/probe_phase9.py"},
    }
    # `now()` doesn't work via supabase-py — drop it and let the column
    # default if there is one; otherwise stamp ISO now.
    insert_payload.pop("started_at")
    import datetime as _dt
    insert_payload["started_at"] = _dt.datetime.utcnow().isoformat() + "Z"

    supabase.table("scan_jobs").insert(insert_payload).execute()
    print(f"\nInserted scan_jobs row id={scan_id}")

    t0 = time.monotonic()
    try:
        await run_website_scan(
            urls,
            scan_id,
            mapping,
            UUID(args.campaign),
        )
    except Exception as e:
        print(f"\nScan raised: {e}", file=sys.stderr)
        # leave row as-is so the operator can inspect

    elapsed = time.monotonic() - t0
    print(f"\nScan returned in {elapsed:.1f}s")

    final = (
        supabase.table("scan_jobs")
        .select("status,total_items,processed_items,matches_count,pipeline_stats,error_message")
        .eq("id", str(scan_id))
        .single()
        .execute()
        .data
        or {}
    )
    ps = final.pop("pipeline_stats", None) or {}
    print("\n=== scan_jobs row (header) ===")
    print(json.dumps(final, default=str, indent=2))

    print("\n=== pipeline_stats — Phase-9 NEW keys ===")
    for k in PHASE9_KEYS:
        present = "OK" if k in ps else "MISSING"
        print(f"  [{present}] {k} = {ps.get(k)!r}")

    print("\n=== pipeline_stats — funnel + dealer status ===")
    for k in (
        "pages_scanned", "pages_failed", "pages_blocked", "pages_empty",
        "total_images", "download_failed", "hash_rejected", "clip_rejected",
        "filter_rejected", "below_threshold", "matched_new", "matched_confirmed",
        "errors", "dealers_total", "dealers_ok", "dealers_partial",
        "dealers_blocked", "dealers_failed", "dealers_empty",
        "concurrent_dealers",
    ):
        if k in ps:
            print(f"  {k} = {ps[k]}")

    print("\n=== blocked_details (telemetry-gap fix verification) ===")
    bd = ps.get("blocked_details") or []
    print(f"  entries: {len(bd)} (pages_failed = {ps.get('pages_failed', 0)})")
    for entry in bd[:10]:
        print(f"   - {json.dumps(entry, default=str)}")

    print("\n=== dealer_outcomes ===")
    do = ps.get("dealer_outcomes") or []
    for d in do:
        print(
            "   - {base_url:<60s}  status={status:<8s}  pages={pages_scanned}  duration={duration_seconds}s".format(
                base_url=str(d.get("base_url"))[:60],
                status=str(d.get("status")),
                pages_scanned=d.get("pages_scanned", "?"),
                duration_seconds=d.get("duration_seconds", "?"),
            )
        )

    print("\nProbe scan_id (inspect via supabase):", scan_id)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
