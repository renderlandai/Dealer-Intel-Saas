# Scan Dispatch Flow

> **Audience:** anyone touching the scan pipeline — adding a new source,
> debugging a stuck job, or planning the eventual `worker/` split-out.
> **Last verified:** 2026-04-21 against `main`.

This doc traces every function called when a scan runs, in order, with
the I/O surface (DB tables touched, external APIs called) at each step.
It exists because the scan path crosses ~10 files and three layers
(HTTP → dispatch → source-specific runner → AI pipeline → post-scan),
and that crossing is the single biggest source of "where does X happen"
questions.

---

## 1. The 30-second mental model

```
HTTP route (or APScheduler cron)
        │
        ▼
   row in scan_jobs (status=pending)
        │
        ▼
   tasks.dispatch_task(...)  ── asyncio.create_task in-process ──┐
        │                                                         │
        ▼                                                         │
   one of: run_website_scan / run_google_ads_scan /               │ runs in
           run_facebook_scan / run_instagram_scan                 │ the API
        │                                                         │ event loop
        ▼                                                         │ (no Redis,
   discovery service (extraction / serpapi / apify)               │  no worker)
        │                                                         │
        ▼  for each image                                         │
   ai_service.process_discovered_image  (7-stage pipeline)        │
        │                                                         │
        ▼  per match                                              │
   _analyze_single_image → MatchBuffer (bulk insert)              │
        │                                                         │
        ▼  end-of-scan                                            │
   _prune_duplicate_matches → cost persist → notifications ───────┘
        │
        ▼
   scan_jobs.status = completed
```

Key invariant: **the API process is the worker.** `tasks.py` literally
does `asyncio.create_task(coro)` and tracks the task in a module-level
set so the GC doesn't drop it. There is no message broker. This is the
one thing that has to change before the `worker/` separation can ship.

---

## 2. Entry points (where a scan can start)

There are exactly **6** code paths that create a row in `scan_jobs` and
hand it to the dispatcher. All of them go through `tasks.dispatch_task`.

| # | Trigger                                  | Code                                                | Notes                                                                |
|---|------------------------------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| 1 | `POST /scans/start`                      | `routers/scanning.py::start_scan` (~line 187)       | User-initiated, single source.                                       |
| 2 | `POST /scans/batch`                      | `routers/scanning.py::batch_scan` (~line 1478)      | Pro+ plans only; loops every allowed channel up to concurrency cap.  |
| 3 | `POST /scans/quick-scan`                 | `routers/scanning.py::quick_scan` (~line 1581)      | Thin wrapper over `start_scan`.                                      |
| 4 | `POST /scans/{job_id}/retry`             | `routers/scanning.py::retry_scan_job` (~line 1181)  | Clones source/campaign of a failed job, dispatches a new job row.    |
| 5 | `POST /scans/{job_id}/analyze` and `POST /scans/reprocess-unprocessed` | `routers/scanning.py` (~lines 1334, 1605) | Skip discovery; dispatch only the analyze step on existing rows.     |
| 6 | APScheduler cron                         | `services/scheduler_service.py::_trigger_scan` (~line 93) | Plan/quota/distributor checks, then same dispatch as `start_scan`.   |

Plan/quota guards used by 1–4: `check_channel_allowed`, `check_scan_quota`,
`check_concurrent_scans` (in `services/plan_limits` / `routers/scanning.py`).
The scheduler runs the equivalent checks inline in `_trigger_scan`.

### What gets written before dispatch

For every entry point above, the same row shape is inserted into
`scan_jobs`:

```python
{
    "organization_id": ...,
    "campaign_id": ... or None,
    "source": "website" | "google_ads" | "facebook" | "instagram",
    "status": "pending",
}
```

`status` flips to `running` either inside the source runner (websites
flips it first thing in `run_website_scan`) or by the scheduler
immediately after a successful dispatch.

---

## 3. The dispatch layer — `app/tasks.py`

Single function: `dispatch_task(task_name, args, scan_job_id, source)`.

```
dispatch_task
  ├── looks up task_name in task_map (6 entries)
  ├── asyncio.create_task(coro_fn(*args), name=f"{task_name}:{scan_job_id}")
  ├── _running_tasks.add(task)        ← keeps GC away
  ├── task.add_done_callback(_task_done)
  └── returns scan_job_id (success) or None (failure → _mark_job_failed)
```

`task_map` contents:

| `task_name`                     | Wraps                              | Used by               |
|---------------------------------|------------------------------------|-----------------------|
| `run_website_scan_task`         | `services/scan_runners.run_website_scan`| websites          |
| `run_google_ads_scan_task`      | `services/scan_runners.run_google_ads_scan` | google_ads    |
| `run_facebook_scan_task`        | `services/scan_runners.run_facebook_scan`| facebook         |
| `run_instagram_scan_task`       | `services/scan_runners.run_instagram_scan`| instagram       |
| `run_analyze_scan_task`         | local `_run_analyze_scan` wrapper  | `/scans/{id}/analyze` |
| `run_reprocess_images_task`     | local `_run_reprocess_images` wrapper | reprocess-unprocessed |

Every wrapper is `asyncio.wait_for(..., timeout=SCAN_TIMEOUT_SECONDS)`
where `SCAN_TIMEOUT_SECONDS = 7200` (2h). On timeout or unhandled
exception → `_mark_job_failed(scan_job_id, str(e))` writes
`status=failed, error_message=...` to `scan_jobs`.

### Implications for the worker split

- The `task_map` is the **only** seam between the API and "background work."
- A real worker just needs to consume that same `(task_name, args)` tuple
  off a queue and call the same `coro_fn(*args)` — the source runners
  themselves are framework-agnostic.
- `_running_tasks` and `_mark_job_failed` are the only API-process state
  that would have to move/be replicated.

---

## 4. Per-source runners

All four live in `services/scan_runners.py` (Phase 4.5 extracted them
from `routers/scanning.py` so the worker import path stays free of
FastAPI). They share the same skeleton:

```
1.  scan_jobs.update(status=running, started_at=now)
2.  campaign_assets = _fetch_campaign_assets(campaign_id)   # assets table
3.  discovered_count = <discovery service for this source>
4.  if campaign_id and discovered_count > 0:
        await auto_analyze_scan(scan_job_id, campaign_id)   # AI pipeline
5.  _persist_cost(scan_job_id, tracker)                     # write cost cols
6.  scan_jobs.update(status=completed, completed_at=now)
7.  _send_scan_notifications(scan_job_id, scan_source=...)  # email
   on except:
        _persist_cost; scan_jobs.update(status=failed, error_message=...)
```

### 4a. Source → discovery service routing

Each runner picks one of two paths depending on whether the
provider-specific API key is configured. **All paths converge on writes
to `discovered_images`** (now buffered via `DiscoveredImageBuffer`).

| Source     | Primary path (API key set)                        | Fallback path (no API key)                                  |
|------------|---------------------------------------------------|-------------------------------------------------------------|
| Google Ads | `serpapi_service.scan_google_ads`                 | `extraction_service.scan_google_ads` (Playwright)           |
| Facebook   | `apify_meta_service.scan_meta_ads(channel="facebook")` | `extraction_service.scan_facebook_ads` (Playwright)    |
| Instagram  | `apify_instagram_service.scan_instagram_organic`  | _(none — Apify is required)_                                |
| Website    | `extraction_service.extract_dealer_website` per page (always) | _(none)_                                       |

### 4b. Website runner is the only "online" runner

`run_website_scan` does not delegate to a single discovery service. It
runs the AI pipeline **as it discovers** — page-by-page — so it can
early-stop once every campaign asset has been matched. This is the only
runner that:

- Holds a `MatchBuffer` for the entire scan and flushes it at the end
  (so dedupe sees every match and a mid-scan crash flushes in `except`).
- Pre-computes `asset_hashes` and `asset_embeddings` once and reuses
  them across pages (via `ai_service._precompute_asset_hashes` /
  `_precompute_asset_embeddings`).
- Reads/writes `page_cache_service` to bias toward "hot" pages that
  matched on a previous scan.
- Tracks `pipeline_stats` per stage for the scan-report email.

The other three runners delegate everything to the discovery service,
then call `auto_analyze_scan` once at the end (which uses the simpler
`run_image_analysis` loop in `services/scan_runners.py`).

Since Phase 4.8 those three runners are thin wrappers over a shared
`_run_source_scan(source, scan_job_id, campaign_id, discover)` driver.
Each wrapper supplies the source label and an async `discover(campaign_assets)`
callable; the driver owns the cost context, status transitions,
auto-analyse gating, cost persistence, and notifications. See section 11
for a one-line trace per runner.

### 4c. Distributor mapping (built at the entry point)

Each entry point builds a `mapping: dict[str, str]` keyed differently
per source so the discovery service can attach the correct
`distributor_id` to each row:

- **google_ads**: `(advertiser_id_or_name).lower() → distributor_id`
- **instagram**: `username.lower() → distributor_id`, plus
  `name.lower() → distributor_id` as a fallback
- **facebook**: `name.lower() → distributor_id`
  (`batch_scan` additionally maps URL slug → distributor_id)
- **website**: `domain → distributor_id` (host portion of website_url)

If a key isn't in the mapping the discovery service still writes the row
but with `distributor_id = None` — see "FK loss handling" below.

---

## 5. The AI pipeline — `ai_service.process_discovered_image`

**Per image, in order.** Each stage can short-circuit and return
`(None, "<stage_name>_rejected")` so the funnel can be tallied.

| # | Stage                | Function (in `services/ai_service.py`)        | Provider          | Skipped when                            |
|---|----------------------|-----------------------------------------------|-------------------|-----------------------------------------|
| 0 | Download bytes       | `download_image(image_url)`                   | _(HTTP fetch)_    | `source_type == "page_screenshot"`      |
| 1 | Perceptual-hash filter | `_passes_hash_prefilter`                    | local (imagehash) | screenshots, or no `asset_hashes` cache |
| 2 | CLIP embedding filter  | `_passes_clip_prefilter`                    | local (CLIP)      | screenshots, or no `asset_embeddings` cache |
| 3 | Relevance filter     | `filter_image(image_url, asset_urls=...)`     | Claude Haiku      | screenshots                             |
| 4 | Ensemble matching    | `ensemble_match(asset_url, image_url, ...)` per asset | Claude Sonnet/Opus | (always runs if previous passed) |
| 5 | Borderline verify    | `should_verify_match` → `verify_borderline_match` | Claude     | score not borderline for this source/channel |
| 6 | Confidence calibration | `calibrate_confidence(score, source, channel)` | local        | (always runs if matched)                |
| 7 | Compliance analysis  | `analyze_compliance(image, asset, brand_rules, end_date)` | Claude (model picked by `compliance` runner) | (always runs if matched) |

The adaptive threshold for stage 4 comes from
`get_adaptive_threshold(source_type, channel)` (per-channel learned
threshold; falls back to `settings.match_threshold`).

Return shape on a match:

```python
{
  "discovered_image_id", "asset_id", "confidence_score", "match_type",
  "is_modified", "modifications",
  "compliance_status",     # "compliant" | "violation"
  "compliance_issues",
  "ai_analysis": { "filter": ..., "comparison": ..., "compliance": ...,
                   "ensemble_scores": ..., "calibration_applied": ... }
}, "matched"
```

Anything not "matched" returns `(None, "<reason>")` and the caller
increments `pipeline_stats[reason]`.

---

## 6. Match writes — `_analyze_single_image`

Wraps the AI pipeline and is the only place a `matches` row gets
created/updated during a scan.

```
_analyze_single_image(image, ..., match_buffer)
  ├── result, stage = ai_service.process_discovered_image(...)
  ├── if stage != "matched":  pipeline_stats[stage] += 1
  ├── if result:
  │     ├── existing = matches.select(asset_id=..., source_url=...)
  │     ├── if existing:                  ← UPDATE path
  │     │     ├── matches.update({last_seen_at, scan_count+1, confidence,
  │     │     │                   match_type, modifications, compliance_*,
  │     │     │                   ai_analysis,
  │     │     │                   previous_compliance_status if drift})
  │     │     └── if drift && now=violation:
  │     │           alerts.insert({alert_type="compliance_drift",
  │     │                          severity="critical", match_id=existing.id})
  │     └── else:                          ← INSERT path (buffered)
  │           ├── build match_payload
  │           ├── if compliance == "violation": build alert_template
  │           └── match_buffer.add(payload, alert_template)
  └── processed_buffer.add(image_id)                ← bulk UPDATE in batches of 100 (Phase 4.7)
```

### Why the dual write model is intentional

- **New matches** flow through `MatchBuffer` because they're insert-only
  and the alert FK can wait until the batch flush gets the new ids back.
- **Updates** (and drift alerts) stay inline because they're keyed by an
  existing match id and the next image's update could conflict if we
  delayed it.

`MatchBuffer` is **per scan**, not per process — each `run_website_scan`
or `run_image_analysis` allocates its own and flushes it at end-of-scan
(and again on `except` so partial work isn't lost). See
`services/bulk_writers.py` for buffer semantics.

### FK loss handling (distributor deleted mid-scan)

`bulk_writers._safe_insert_discovered_image` handles Postgres error
code `23503` by retrying the insert with `distributor_id = None`. This
is the only place that quirk lives now. Bulk inserts fall back to this
helper if the bulk call fails.

---

## 7. Post-scan steps (in order)

These run inside the source runner's `try` block, after every page /
image has been processed, BEFORE `status` is flipped to `completed`:

1. **`match_buffer.flush_all()`** — websites only; ensures every
   buffered match is persisted before dedupe queries `matches`.
1a. **`processed_buffer.flush_all()`** — drains queued
   `discovered_images.is_processed=True` updates so the scan's
   `processed_items` count and the actual row state agree (Phase 4.7).
   `run_image_analysis` does the same flush at the end of its loop.
2. **`_prune_duplicate_matches(scan_job_id)`** — keeps the highest-
   confidence match per `(asset_id, distributor_id)` for this scan;
   chunked `DELETE ... IN (...)` since 4.3.
3. **`page_cache_service.record_page_hits(...)`** — websites only;
   remembers which `page_url`s matched which `asset_id`s so the next
   scan can skip discovery if the cache covers everything.
4. **`_persist_cost(scan_job_id, tracker)`** — writes
   `total_input_tokens / total_output_tokens / total_cost_usd /
   cost_breakdown` onto the `scan_jobs` row from the `ScanCostTracker`
   context manager (`services/cost_tracking_service`).
5. **`scan_jobs.update({status: "completed", completed_at, total_items,
   processed_items, matches_count, pipeline_stats})`**.
6. **`_send_scan_notifications(scan_job_id, scan_source, pipeline_stats)`** —
   queries `scan_jobs`, `discovered_images`, `matches`, `alerts` and
   fires a single combined "scan report + violations" email.

On exception, the `except` branch:
- flushes `match_buffer` (websites only) so partial matches are saved
- flushes `processed_buffer` (websites only) so partially-analysed
  images don't get re-processed on the next run
- calls `_persist_cost` best-effort
- writes `status=failed, error_message=str(e)`

`_send_scan_notifications` is **not** called on the failure path.

---

## 8. Background jobs (not scans, but on the same scheduler)

Registered in `services/scheduler_service.start()` alongside the per-
schedule scan jobs:

| Job id                  | Cron                       | Function                                | Purpose                                                |
|-------------------------|----------------------------|-----------------------------------------|--------------------------------------------------------|
| `scheduler_lock_renewal`| every minute               | `_renew_scheduler_lock`                 | Renews the Redis lock so only one Gunicorn worker runs the scheduler. |
| `data_retention_sweep`  | daily at 03:00 UTC         | `_run_retention`                        | Deletes old scans/images per retention policy.         |
| `cleanup_stale_scans`   | every 5 minutes            | `_cleanup_stale_scans`                  | Marks scans stuck in `running` past the timeout as failed. |
| `salesforce_inbound_sync` | every 30 minutes         | `salesforce_sync_service.run_salesforce_sync_all` | Inbound CRM sync.                                |
| `hubspot_inbound_sync`  | every 30 minutes           | `hubspot_sync_service.run_hubspot_sync_all` | Inbound CRM sync.                                  |
| `scan_schedule_<id>`    | per-row CronTrigger        | `_trigger_scan(schedule_id)`            | Per-customer scheduled scan.                           |

Scheduler is gated by `SCHEDULER_ENABLED=true` and a Redis lock keyed
`dealer_intel:scheduler_lock`, so multiple Gunicorn workers don't each
fire the cron.

---

## 9. I/O surface — DB tables & external APIs by phase

### DB tables touched per phase (read = R, write = W)

| Phase                          | scan_jobs | scan_schedules | distributors | campaigns | assets | discovered_images | matches | alerts | compliance_rules | scan_page_hits |
|--------------------------------|:---------:|:--------------:|:------------:|:---------:|:------:|:-----------------:|:-------:|:------:|:----------------:|:--------------:|
| Entry point                    |    W      |       —        |      R       |     R     |   —    |         —         |    —    |   —    |        —         |       —        |
| Scheduler trigger              |    W      |      R/W       |      R       |     R     |   —    |         —         |    —    |   —    |        —         |       —        |
| Source runner setup            |   R/W     |       —        |      —       |     —     |   R    |         —         |    —    |   —    |        R         |       —        |
| Discovery (per source)         |    —      |       —        |      —       |     —     |   —    |         W         |    —    |   —    |        —         |      R/W       |
| AI pipeline (per image)        |    —      |       —        |      —       |     —     |   —    |         W *       |   R/W   |   W    |        —         |       —        |
| Dedupe                         |    —      |       —        |      —       |     —     |   —    |         R         |   R/W   |   —    |        —         |       —        |
| Cost persist + completion      |    W      |       —        |      —       |     —     |   —    |         —         |    —    |   —    |        —         |       —        |
| Notifications                  |    R      |       —        |      —       |     —     |   —    |         R         |    R    |   R    |        —         |       —        |

\* `discovered_images.update(is_processed=True)` is now buffered through
`ProcessedImageBuffer` and flushed in batches of 100 (Phase 4.7). The
trailing flush in the post-scan steps below ensures the row state and the
reported `processed_items` count agree.

### External APIs called per source

| Source       | External calls (per scan)                                                                       |
|--------------|-------------------------------------------------------------------------------------------------|
| **website**  | Playwright (Chromium) → page HTML/screenshots; Anthropic Claude (Haiku/Sonnet/Opus) per image; OpenAI/HF for CLIP embeddings (local-ish if model is bundled) |
| **google_ads** | SerpApi (`google_ads_transparency_center`) for ad listing + creatives; then Claude pipeline per image |
| **facebook** | Apify (`Meta Ads Scraper Pro` actor) for ad listing + creatives; then Claude pipeline per image |
| **instagram**| Apify (`Instagram scraper` actor) for organic posts; then Claude pipeline per image             |
| **all sources** | Supabase REST (PostgREST) for every DB read/write; Supabase Storage for screenshot uploads (websites) |

---

## 10. Known open items (visible from this trace)

These are **not** bugs — they are observed friction points worth
revisiting after the worker split is real:

1. ~~`discovered_images.update(is_processed=True)` is per-row inside
   `_analyze_single_image`.~~ **Resolved in Phase 4.7** — the trailing
   UPDATE is now buffered through `ProcessedImageBuffer` (mirrors
   `MatchBuffer`), auto-flushes every 100 ids, and is drained before the
   scan reports `processed_items` so the row state and the reported count
   agree. Failure path drains too, so partially-analysed images aren't
   re-processed forever.
2. The website runner builds a brand-new `MatchBuffer` per call.
   Acceptable today (one website scan = one runner instance), but if
   the worker split fans out by page or by URL, the buffer will need
   to live one level up to keep dedupe / cache / cost on the same
   transactional boundary.
3. `auto_analyze_scan` and `run_image_analysis` duplicate the same
   "load assets / load brand_rules / loop images" code three times
   (in `auto_analyze_scan`, `_run_analyze_scan`, `_run_reprocess_images`).
   A single shared loader would make worker extraction cleaner.
4. ~~`dispatch_task` calls `from .routers.scanning import run_*_scan`
   inside each wrapper.~~ **Resolved in Phase 4.5** — the four runners
   (and their helpers) now live in `services/scan_runners.py`.
   `tasks.py` imports `from .services.scan_runners import run_*_scan`
   and an import-isolation guard in CI ensures `scan_runners` never
   re-acquires a FastAPI dependency.
5. ~~Google / Facebook / Instagram runners duplicate the same scan
   skeleton (mark running → fetch assets → discover → auto-analyse →
   persist cost → mark completed → notify).~~ **Resolved in Phase 4.8**
   — collapsed onto `_run_source_scan(source, scan_job_id, campaign_id,
   discover)`. Each public runner is now a ~15-line wrapper that
   supplies the source label and a source-specific async `discover`
   callable (SerpApi vs Playwright, Apify Meta vs Playwright, Apify
   Instagram). `run_website_scan` deliberately stays separate because
   its early-stop + page-cache logic does not fit the post-scan-analyse
   model the others share. Phase 5 now ports one driver instead of three
   near-identical ones.

---

## 11. Quick reference — where to look next

| Question                                             | File                                                |
|------------------------------------------------------|-----------------------------------------------------|
| "Where does a scan start?"                           | `routers/scanning.py::start_scan`                   |
| "How does a scan get to a coroutine?"                | `tasks.py::dispatch_task`                           |
| "Where do website pages get crawled?"                | `services/extraction_service.py`                    |
| "Where do Google Ads creatives come from?"           | `services/serpapi_service.py`                       |
| "Where do Facebook/Instagram ads come from?"         | `services/apify_meta_service.py`, `services/apify_instagram_service.py` |
| "Where is the per-image AI funnel?"                  | `services/ai_service.py::process_discovered_image`  |
| "Where do match rows get written?"                   | `services/scan_runners.py::_analyze_single_image` + `services/bulk_writers.py` |
| "Where are duplicate matches pruned?"                | `services/scan_runners.py::_prune_duplicate_matches`|
| "Where does the scheduler fire?"                     | `services/scheduler_service.py::_trigger_scan`      |
| "Where are completion emails sent?"                  | `services/scan_runners.py::_send_scan_notifications`|
| "Where is cost tracked?"                             | `services/cost_tracker.py` + `services/scan_runners.py::_persist_cost` |
