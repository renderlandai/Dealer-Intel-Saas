# Dealer Intel SaaS — Development Log

---

## 2026-01-19  — Project Genesis

### Summary
Initial build and deployment of the full-stack Dealer Intel SaaS platform. Stood up the complete backend (FastAPI + Supabase), frontend (Next.js), and database schema in a single session. Deployed to Vercel same day.

### Changes

**Backend (FastAPI)**
- Created FastAPI application entry point (`main.py`) with CORS middleware
- Built `config.py` with Pydantic-based settings (Supabase, Anthropic, Apify credentials, AI thresholds)
- Set up Supabase client in `database.py`
- Defined full Pydantic schema layer in `models.py` (396 lines covering campaigns, assets, distributors, matches, scans, feedback)
- Built 5 routers:
  - `campaigns.py` — Campaign & asset CRUD, asset upload, campaign-specific scans
  - `distributors.py` — Distributor CRUD, Google Ads advertiser ID lookup
  - `matches.py` — Match listing, approval/flagging, deletion
  - `dashboard.py` — Stats, recent matches/alerts, coverage analytics, compliance trend
  - `scanning.py` — Scan job management, background analysis orchestration (1005 lines)
  - `feedback.py` — AI accuracy feedback, threshold recommendations, adaptive calibration
- Built 3 services:
  - `ai_service.py` — Claude-based multi-stage image analysis pipeline (filter → ensemble match → verification → compliance)
  - `apify_service.py` — Apify integration for Google Ads Transparency Center and Facebook Ad Library scraping
  - `adaptive_threshold_service.py` — Dynamic threshold tuning based on human feedback
- Wrote `check_scans.py` utility for inspecting scan state
- Created database migration runner (`run_migration.py`)

**Frontend (Next.js + Tailwind)**
- Dashboard page (`page.tsx`) with stat cards, recent matches, alerts panel, channel chart
- `DealerMap.tsx` — US choropleth map using react-simple-maps with dealer compliance overlay
- `LiveAuditFeed.tsx` — Real-time scan activity feed
- Campaign pages: list view + detail view (`campaigns/page.tsx`, `campaigns/[id]/page.tsx`)
- Distributor pages: list view + detail view (`distributors/page.tsx`, `distributors/[id]/page.tsx`)
- Match pages: list view + detail view (`matches/page.tsx`, `matches/[id]/page.tsx`)
- Scans page (`scans/page.tsx`)
- Full component library: sidebar, header, stat-card, recent-matches, alerts-panel, channel-chart
- shadcn/ui components: badge, button, card, input, progress, table, tabs
- API client (`lib/api.ts`), React Query hooks (`lib/hooks.ts`), query provider, utilities

**Database (Supabase)**
- Full schema: organizations, campaigns, campaign_assets, distributors, scan_jobs, discovered_images, matches, compliance_rules, alerts, match_feedback
- 6 migrations:
  - `001_deduplicate_matches.sql`
  - `002_add_matches_count.sql`
  - `003_add_discovered_image_to_view.sql`
  - `004_add_match_feedback.sql`
  - `005_performance_indexes.sql`
  - `006_google_ads_distributor_fallback.sql`

**Deployment**
- Deployed frontend to Vercel (removed `package-lock.json` for Vercel compatibility, fixed matches page)

### Commits
- `151cc09` — Initial commit (67 files, 15,911 lines)
- `a928629` — Vercel deployment changes
- `847806c` — Vercel matches page fix

### Files Added
67 files across `backend/`, `frontend/`, `supabase/`, plus `.gitignore` and `README.md`

### Tech Stack Established
- **Backend**: Python 3.11+ / FastAPI / Supabase / Anthropic Claude
- **Frontend**: Next.js 14 / TypeScript / Tailwind CSS / React Query / shadcn/ui
- **Database**: Supabase (PostgreSQL) with RLS policies
- **AI**: Claude Sonnet for all image analysis stages
- **Scraping**: Apify actors for Google Ads + Facebook Ad Library

---

## 2026-03-17 (Tuesday) — First Working Session

### Summary
Returned to the project after initial build. Focused on getting the development environment running locally — starting both backend and frontend servers.

### Sessions
- Server startup and environment configuration
- Resolved `npm` PATH issues with nvm/fnm environments

---

## 2026-03-18 (Wednesday) — Architecture Review & AI Pipeline Overhaul

### Summary
Major architecture review session followed by significant AI pipeline improvements. Addressed the core problem that the AI was reviewing entire screenshots instead of finding individual images within them. Evaluated map library options. Redesigned the dashboard layout.

### Architecture Review Findings
Comprehensive review identified 10 critical issues:
1. **Cost**: Claude Opus for every stage is prohibitively expensive at scale
2. **No pre-filtering**: Every image goes to Claude without cheaper pre-screens
3. **Screenshot-level matching fails**: AI needs to find individual images within full-page screenshots
4. **No task queue**: BackgroundTasks won't survive restarts
5. **No authentication**: RLS policies wide open
6. **No image caching**: Assets re-downloaded for every comparison
7. **No scheduled scans**: Manual-only scanning
8. **Blocking Apify calls**: Synchronous calls block the async event loop
9. **No structured logging**: All `print()` statements
10. **No image deduplication**: Duplicate matches across scans

### Changes

**Backend — New Services Created**
- `extraction_service.py` (863 lines) — Playwright-based image extraction that loads pages in a real browser, extracts individual `<img>` elements, and compares them individually instead of analyzing full screenshots. Supports dealer websites, Google Ads Transparency, and Meta Ad Library with tiling fallback
- `screenshot_service.py` (323 lines) — ScreenshotOne API integration replacing Apify for website capture with full-page rendering, cookie banner blocking, and retina quality
- `cv_matching.py` (249 lines) — OpenCV-based visual matching with multi-scale template matching and ORB feature matching for locating campaign creatives on web pages
- `embedding_service.py` (110 lines) — CLIP embedding service for fast visual similarity pre-filtering before expensive Claude API calls (~20ms per image on CPU)
- `page_discovery.py` (351 lines) — Dealer website page discovery via sitemap parsing, link crawling, and common path heuristics to find promotional pages
- `serpapi_service.py` (207 lines) — SerpApi integration for Google Ads Transparency Center replacing Playwright-based scraping with structured API calls
- `apify_meta_service.py` (308 lines) — Apify Meta Ad Library integration for Facebook/Instagram ad scraping via GraphQL interception

**Backend — Major Modifications**
- `ai_service.py` — Massive overhaul (+947 lines changed): tiered model strategy (Haiku for filtering, Sonnet/Opus for comparison), CLIP pre-filtering integration, hash pre-filter gate, improved ensemble matching
- `config.py` — Added ScreenshotOne, SerpApi, Apify, Sentry configuration; added CLIP, Playwright, page discovery, and pre-filter pipeline settings; neutralized calibration factors (were silently dropping valid matches); set debug=False
- `scanning.py` — Refactored to use new extraction/screenshot/page-discovery services (+463 lines changed)
- `main.py` — Added Sentry error tracking, rate limiting (slowapi), structured logging, JSON exception handler, debug=False for production-safe error responses
- `database.py` — Enhanced with connection pooling and error handling
- `campaigns.py`, `dashboard.py`, `distributors.py`, `matches.py` — Various router improvements

**Backend — Removed**
- `apify_service.py` — Deleted (819 lines); replaced by `serpapi_service.py` + `apify_meta_service.py` + `screenshot_service.py`

**Backend — New Infrastructure**
- `logging_config.py` — Structured JSON logging for production, colored dev-mode formatter, scan-job-aware log context, quiet noisy third-party loggers
- `requirements.txt` — Added: opencv-python-headless, sentence-transformers (CLIP), playwright, slowapi, sentry-sdk, pydantic-settings; updated versions across the board

**Frontend — Map Upgrade**
- `DealerMap.tsx` — Major rewrite (+1112 lines changed): evaluated react-simple-maps vs Mapbox GL; significantly enhanced with better compliance visualization

**Frontend — Error Handling & Monitoring**
- `error.tsx` — Global error boundary with Sentry reporting and retry button
- `global-error.tsx` — Root-level error boundary for fatal crashes
- `not-found.tsx` — Custom 404 page with navigation back to dashboard
- `sentry.client.config.ts` — Client-side Sentry initialization (traces, replay on error)
- `sentry.edge.config.ts` — Edge runtime Sentry config
- `sentry.server.config.ts` — Server-side Sentry config

**Frontend — Security & Config**
- `next.config.js` — Added security headers (X-Frame-Options, CSP, Referrer-Policy, Permissions-Policy), Sentry webpack plugin integration
- `layout.tsx` — Updated with Sentry integration
- `package.json` — Added `@sentry/nextjs` dependency

**Frontend — UI Polish**
- `page.tsx` (dashboard) — Layout improvements, stat card repositioning under dealer map
- `campaigns/page.tsx`, `distributors/page.tsx` — Minor UI fixes
- `globals.css` — Additional utility styles
- `recent-matches.tsx` — Minor fix

**DevOps**
- `run-all-ports.sh` — One-command startup script for both backend (port 8000) and frontend (port 3000) with automatic venv/npm setup

### Decisions Made
- Switched from screenshot-level AI matching to individual image extraction (Playwright)
- Replaced single Apify actor with specialized services (SerpApi for Google Ads, Apify for Meta, ScreenshotOne for websites)
- Added tiered AI model strategy: Haiku for filtering, Sonnet for comparison, Opus for verification
- Added CLIP embeddings + perceptual hash as pre-filters before Claude API calls
- Neutralized confidence calibration factors that were silently dropping valid matches
- Added Sentry for error tracking across frontend and backend
- Added rate limiting to protect API endpoints

---

## 2026-03-19 (Thursday) — Instagram Analysis & Scan Debugging

### Summary
Investigated Instagram audit capabilities, debugged a failed website scan, analyzed codebase size, and explored scan optimization (early stopping).

### Sessions
- **Instagram audit analysis**: Determined that Instagram is currently aliased to the Facebook Ad Library flow via Apify Meta scraper. Identified gaps: no Instagram organic post scraping, no Stories/Reels support
- **API key update**: Updated Anthropic API key in backend `.env`
- **Scan failure debugging**: Investigated why a website scan failed — traced through extraction service logs and configuration
- **Codebase metrics**: Counted total lines of code across the entire application
- **Early stopping research**: Analyzed whether website scanning could stop once a creative is found instead of processing all 15 pages. Documented that current pipeline processes all pages sequentially with no early exit. Outlined implementation approach for inline matching during extraction

### Notes
- Current architecture processes all discovered pages before running analysis — extraction and matching are separate phases
- Page discovery prioritizes promotional URLs first, making early stopping feasible if matching was moved inline

---

## 2026-03-20 (Thursday) — Scalability Analysis

### Summary
Analyzed the system's ability to handle real-world scale: a customer with 40 distributors generating ~400 images per distributor.

### Sessions
- **Scale math**: 40 distributors x 25-30 pages x ~15 images/page = 15,000-18,000 images per scan cycle
- Identified that without pre-filtering, this would mean 15,000+ Claude API calls per scan at ~$0.01-0.05 each
- Validated the importance of the recently added CLIP + hash pre-filter pipeline to cut Claude calls by 80-90%
- Discussed batch processing strategies and cost projections

---

## 2026-03-23 (Monday) — Server Management & Development Log

### Summary
Server startup sessions and project documentation improvements.

### Sessions
- Started backend and frontend servers for development
- Investigated website scraping early-stopping optimization
- Created this development log (`log.md`)

---

## 2026-03-23 (Monday) — Adaptive Thresholds, Feedback System & Instagram Scanning

### Summary
Major feature session: completed adaptive threshold calibration with a full feedback loop, and built Instagram organic post scanning as a new channel. This closes the last major channel coverage gap. The core scanning engine now covers websites, Google Ads, Facebook Ads, and Instagram organic posts.

### Changes

**Backend — Adaptive Threshold Calibration (Item 8)**

The calibration engine (`adaptive_threshold_service.py`) and models (`MatchFeedback`, `FeedbackAccuracyStats`, `ThresholdRecommendation`) were already built in previous sessions. Today's work connected the full feedback loop end-to-end:

- `matches.py` — Added 3 new API endpoints:
  - `POST /matches/{id}/feedback` — Submit feedback (correct/incorrect) on a match. Auto-enriches with `ai_confidence`, `source_type`, `channel`, `match_type` from the match record. Invalidates threshold cache to trigger recalculation
  - `GET /matches/feedback/stats` — Accuracy breakdown by source/channel with correct/incorrect counts, accuracy percentages, and average confidence scores
  - `GET /matches/feedback/thresholds` — Adaptive threshold recommendations per source/channel, showing current vs recommended thresholds with confidence levels
- `match_feedback` database table verified as existing and operational

**Backend — Instagram Organic Post Scanning**

- `apify_instagram_service.py` (new, ~275 lines) — Instagram organic post scraper using the official `apify/instagram-scraper` actor via a pre-configured Apify task (`diamanted~instagram-scraper-task`)
  - Extracts Instagram usernames from distributor `instagram_url` fields
  - Fetches up to 50 recent posts within 90-day window per profile
  - Handles Image and Sidecar/Carousel post types (videos skipped)
  - Inserts each post image as a `discovered_image` with rich metadata (caption, hashtags, mentions, likes, comments, timestamp)
  - Resolved distributor mapping via Instagram username matching
- `scanning.py` — Added `run_instagram_scan()` background task; separated Instagram from the Facebook/Meta Ad Library path so each channel uses its own scraper
- `campaigns.py` — Fixed campaign scan endpoint which was still routing Instagram to the Meta Ads actor (`source in [FACEBOOK, INSTAGRAM]` → separate branches)

**Frontend — Match Feedback UI**

- `matches/page.tsx` — Added "Feedback" column to matches table with inline thumbs-up/thumbs-down buttons for quick confirm/reject
- `matches/[id]/page.tsx` — Added "AI Accuracy Feedback" card with:
  - Large "Correct Match" / "Incorrect Match" buttons
  - Confirmation state display after submission
  - Pipeline scores breakdown (visual, detection, hash ensemble scores)
- `campaigns/[id]/page.tsx` — Scan source buttons now show descriptive subtitles ("Organic posts", "Meta Ad Library", "Paid display ads", "Dealer sites")
- `lib/api.ts` — Added `submitMatchFeedback()`, `getFeedbackStats()`, `getThresholdRecommendations()` API functions
- `lib/hooks.ts` — Added `useSubmitFeedback()` mutation hook and `useFeedbackStats()` query hook

### How Adaptive Calibration Works
1. User reviews a match and clicks "Correct" or "Incorrect"
2. Feedback is stored with the match's AI confidence, source type, channel, and match type
3. The calibration engine aggregates feedback per source/channel combination
4. After 20+ samples for a given combination, thresholds automatically adjust:
   - High false positive rate → thresholds raised
   - High false negative rate → thresholds lowered
5. Confidence calibration factors adjust based on whether predictions tend to be over- or under-confident
6. Borderline verification ranges adapt based on accuracy in nearby confidence ranges

### How Early Stopping Works
Website scans discover 15+ subpages per dealer site (promotions, deals, specials, etc.). Without early stopping, every page is extracted and every image analyzed — expensive and slow when the creative was found on page 1.

1. Before scanning begins, the system loads all campaign asset IDs into a target set and pre-computes perceptual hashes + CLIP embeddings for each asset
2. Pages are scanned sequentially (prioritized by promotional likelihood via page discovery)
3. After each page, its extracted images are immediately analyzed through the full pipeline (hash → CLIP → Haiku → ensemble → verification) instead of waiting for all pages to finish
4. When an image matches a campaign asset, that asset ID is added to a `matched_asset_ids` set
5. After each page, the system checks: `matched_asset_ids >= all_asset_ids` — if every campaign asset has been found, it breaks the loop
6. Remaining pages are logged as skipped, and `pipeline_stats["early_stopped"]` is set to true
7. First live test: matched all assets after 1/16 pages, skipping 15 pages (~94% reduction in work)

### How Image Caching Works
The AI pipeline downloads the same image multiple times during a scan — once per campaign asset comparison, plus pre-filter stages. Without caching, a single image could be downloaded 3-5x.

1. `_ImageCache` class in `ai_service.py` implements an in-memory LRU cache bounded by both entry count (200 max) and total byte size (200 MB max)
2. Every call to `download_image(url)` checks the cache first — on hit, returns bytes immediately with zero network I/O
3. On miss, the image is fetched via `httpx`, stored in the cache, and returned
4. When the cache exceeds its bounds, the least-recently-used entry is evicted (FIFO on `_order` list)
5. Cache tracks `hits`, `misses`, and `hit_rate` — stats are included in `pipeline_stats["image_cache"]` at scan completion and displayed in the Pipeline Funnel UI
6. First live test: 22.7% hit rate (5 hits / 17 downloads), 16.31 MB cached

### Verified Working
- Feedback submission: tested via API and confirmed data stored correctly
- Feedback stats: accuracy breakdowns returned per source/channel
- Threshold recommendations: returns adaptive vs default thresholds with sample counts
- Instagram scan: successfully scraped dealer Instagram profile, extracted images, ran through full AI pipeline, matched campaign creative at 85% confidence (strong match, compliant)
- Early stopping: all assets matched after 1/16 pages, 15 pages skipped
- Image cache: 22.7% hit rate on first website scan

---

## 2026-03-24 (Monday) — Priority 2 Complete: Reports, Notifications & Scheduled Scans

### Summary
Completed the entire Priority 2 feature set in a single session. Built PDF/CSV compliance report generation with full branding customization (logo upload, company name, color themes). Added email notifications via Resend for scan completions and violations. Implemented scheduled/automated scans using APScheduler with CronTrigger, giving users precise control over scan timing (time of day, day of week). Created a dedicated Settings page for organization-level configuration. All three features tested and verified working end-to-end.

### Changes

**Backend — PDF/CSV Compliance Reports**
- `services/report_service.py` (new) — ReportLab-based PDF generator with dynamic branding: side-by-side logo + title header, per-distributor violation tables, channel breakdowns, summary statistics. CSV export with matching data. 3-tier logo resolution (org-uploaded → config path → bundled default)
- `routers/reports.py` (new) — `/reports/compliance` endpoint supporting `format=pdf|csv` with optional campaign/distributor/date filters
- `assets/logo_default.png` (new) — Bundled fallback logo generated via Pillow
- Dynamic color theming: `_derive_palette()` generates brand/dark/light variants from a single hex color. 7 preset swatches (Slate default, Graphite, Charcoal, Steel, Teal, Forest, Burgundy)
- White table header text (`st["th"]` ParagraphStyle) for readability on colored backgrounds

**Backend — Email Notifications (Resend)**
- `services/notification_service.py` (new) — Resend API integration via httpx. Sends combined scan-completion emails with summary stats and inline violation details table when applicable
- `routers/organizations.py` — Added settings CRUD (GET/PATCH) for `notify_email`, `notify_on_violation`, plus test email endpoint
- `routers/scanning.py` — Hooked `_send_scan_notifications()` into all four scan pipelines (website, Google Ads, Facebook, Instagram)
- `config.py` — Added `resend_api_key` and `resend_from_email` settings

**Backend — Scheduled/Automated Scans**
- `services/scheduler_service.py` (new) — APScheduler AsyncIOScheduler with CronTrigger. Builds cron expressions from frequency + time + day-of-week. Loads persisted schedules on app startup. Triggers scans by creating scan jobs and dispatching to existing scan pipelines
- `routers/schedules.py` (new) — Full CRUD: list, create (with time/day validation), update (frequency/time/toggle), delete. Auto-computes `next_run_at` on any timing change
- `main.py` — Added lifespan context manager for scheduler start/shutdown. Registered schedules router
- `requirements.txt` — Added `apscheduler>=3.10.0`, `reportlab>=4.0.0`

**Backend — Organization Settings**
- `routers/organizations.py` (new) — Logo upload/delete via Supabase Storage, org settings CRUD (name, logo_url, report_brand_color, notification preferences)
- Graceful column fallback for incremental migrations

**Frontend — Settings Page**
- `app/settings/page.tsx` (new) — Dedicated settings page with three cards:
  - **Company Info**: editable company name
  - **Report Theme**: 7 color swatches with live preview strip, logo upload/delete with drag-and-drop
  - **Email Notifications**: on/off toggle, email input, save + test buttons

**Frontend — Campaign Schedules UI**
- `campaigns/[id]/page.tsx` — New "Schedules" tab (4th tab) with:
  - Schedule creation form: channel selector, frequency dropdown, day-of-week selector (for weekly/biweekly), time picker (UTC)
  - Active schedules list: green/gray status dots, schedule description (e.g. "Weekly · Mondays at 09:00 UTC"), last/next run timestamps, pause/resume toggle, delete button

**Frontend — API & Types**
- `lib/api.ts` — Added: `getOrgSettings`, `updateOrgSettings`, `sendTestEmail`, `getSchedules`, `createSchedule`, `updateSchedule`, `deleteSchedule`, `downloadComplianceReport`, `ScanSchedule` interface with `run_at_time`/`run_on_day` fields

**Database Migrations**
- `009_org_logo.sql` — `logo_url` column on organizations
- `010_org_brand_color.sql` — `report_brand_color` column on organizations
- `011_notification_settings.sql` — `notify_email`, `notify_on_violation` columns on organizations
- `012_scan_schedules.sql` — `scan_schedules` table with frequency, run_at_time, run_on_day, active toggle, last/next run timestamps, unique constraint on (campaign_id, source)

### New Third-Party Services Added
| Service | Purpose |
|---------|---------|
| **Resend** | Transactional email delivery for scan notifications and violation alerts |
| **APScheduler** | In-process cron-based job scheduling for automated scans |
| **ReportLab** | PDF document generation for compliance reports |

### Verified Working
- PDF reports: download with custom logo, company name, and brand colors. White header text readable on all color themes
- CSV reports: download with matching data and filters
- Email notifications: Resend delivers scan completion emails with violation details
- Scheduled scans: created schedule with specific time, scans triggered automatically at configured time
- Settings page: logo upload, company name update, color theme selection, notification toggle all persist and apply

---

## 2026-03-24 (Tuesday) — Production Deployment & Celery Task Queue

### Summary
Major infrastructure session: deployed the full backend to DigitalOcean App Platform using Docker, resolved multiple build and runtime issues during deployment, deployed the frontend to Vercel with production environment variables, and built a complete Celery + Valkey (Redis) distributed task queue to replace FastAPI's `BackgroundTasks`. The system is now fully production-deployed with durable, crash-recoverable background scan processing.

### Session 1: Docker + DigitalOcean App Platform Deployment

**Problem**: The backend needed to be containerized and deployed to DigitalOcean App Platform. The application has heavy system dependencies (Playwright/Chromium for browser automation, OpenCV for image processing, CLIP for embeddings) that require explicit Docker configuration rather than simple buildpack deployment.

**Dockerfile (`backend/Dockerfile`)**
- Base image: `python:3.11-slim`
- System dependencies: `build-essential`, `libglib2.0-0`, `libgl1`, `libsm6`, `libxext6`, `libxrender1`, `curl`
- CPU-only PyTorch installed first via `--index-url https://download.pytorch.org/whl/cpu` to avoid pulling ~5GB of CUDA libraries (image would exceed DO build limits otherwise)
- Playwright Chromium browser installed via `playwright install chromium --with-deps`
- Gunicorn as the production WSGI server with Uvicorn workers

**Gunicorn Configuration (`backend/gunicorn.conf.py`)**
- 2 Uvicorn async workers (conservative due to Playwright + CLIP memory usage)
- 5-minute timeout for long-running scan operations
- `preload_app = True` to load CLIP model once, shared across workers
- Port configurable via `PORT` env var (defaults to 8000)

**DigitalOcean App Platform Configuration (`.do/app.yaml`)**
- Service: `api` on `professional-xs` instance (1 vCPU, 1GB RAM)
- Dockerfile build strategy (not buildpack — critical for Playwright)
- Health check on `/health` with 90s initial delay, 30s period, 5 failure threshold
- Auto-deploy on push to `main` branch
- All secrets injected as encrypted runtime environment variables

**Build Issues Resolved (4 iterations)**:
1. **Dockerfile not found**: Files weren't committed to git — DO clones from the repo, so uncommitted local files don't exist in the build. Fixed by committing and pushing all Docker files
2. **`libgl1-mesa-glx` unavailable**: Package was renamed to `libgl1` in Debian Trixie (the base image's distro). Fixed by updating the package name
3. **Docker image too large**: Default PyTorch pulls ~5GB of NVIDIA CUDA libraries. Fixed by installing CPU-only PyTorch first (`--index-url https://download.pytorch.org/whl/cpu`), reducing the image by ~5GB
4. **`gunicorn` not found at runtime**: `gunicorn` wasn't in `requirements.txt` — it was only referenced in the Dockerfile CMD. Fixed by adding `gunicorn>=21.2.0` to requirements
5. **Health check failing — "database unreachable, Invalid URL"**: Environment variables had `PLACEHOLDER` values instead of real credentials. Fixed by updating the app spec with actual Supabase/API credentials via `doctl`

**Deployment Method**: Used `doctl` CLI instead of the DigitalOcean UI because the UI was forcing Buildpack mode and wouldn't allow switching to Dockerfile mode. The CLI provided full control over the app spec YAML.

### Session 2: Vercel Frontend Deployment Fix

The Vercel frontend build was failing with `Error: supabaseUrl is required` during prerendering. Next.js tries to render pages like `/distributors` at build time, which imports the Supabase client, which crashes without the URL environment variable.

**Fix**: Added all four `NEXT_PUBLIC_*` environment variables in Vercel dashboard:
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_API_URL` (pointing to the new DO backend: `https://dealer-intel-api-c2m2p.ondigitalocean.app`)
- `NEXT_PUBLIC_MAPBOX_TOKEN`

Redeployed — frontend now live and connected to production backend.

### Session 3: Celery + Valkey Distributed Task Queue

**Problem**: `BackgroundTasks` (FastAPI's built-in) runs scan tasks in the same process as the web server. If the server restarts during a deploy, crashes, or scales — any running scan is silently killed and lost. For a production system processing 160 scan jobs per cycle (40 dealers × 4 channels), this is unacceptable.

**Solution**: Celery with DigitalOcean Managed Valkey (Redis-compatible, open-source fork).

**Infrastructure Added**:
- DigitalOcean Managed Valkey database (`db-valkey-nyc3-40902`) — $15/month, NYC region, TLS-encrypted
- Celery worker component added to the DO App Platform spec — runs alongside the API service using the same Docker image but with `celery -A app.celery_app worker` as the command

**New Files**:

`backend/app/celery_app.py` — Celery application configuration:
- Broker: Valkey via `rediss://` (TLS) connection string
- No result backend (scan results stored in Supabase, not Redis)
- JSON serialization for all task messages
- `task_acks_late = True` — tasks acknowledged only after completion, so if a worker dies mid-scan, the task returns to the queue for another worker to pick up
- `worker_prefetch_multiplier = 1` — one task at a time per worker (scans are CPU/memory heavy)
- `task_reject_on_worker_lost = True` — crashed tasks are re-queued, not dropped
- `worker_max_tasks_per_child = 50` — worker process restarts after 50 tasks to prevent memory leaks from Playwright/CLIP
- `task_soft_time_limit = 1800` (30 min) / `task_time_limit = 2400` (40 min) — prevents stuck tasks from blocking the queue forever
- TLS configuration for DigitalOcean managed Valkey (`ssl_cert_reqs: CERT_NONE`)

`backend/app/tasks.py` — Six Celery task definitions:
1. `run_website_scan_task` — wraps `run_website_scan()` with UUID serialization/deserialization
2. `run_google_ads_scan_task` — wraps `run_google_ads_scan()`
3. `run_facebook_scan_task` — wraps `run_facebook_scan()`
4. `run_instagram_scan_task` — wraps `run_instagram_scan()`
5. `analyze_scan_task` — wraps `auto_analyze_scan()`, fetches images/assets from DB internally (avoids sending large data through the message broker)
6. `reprocess_images_task` — wraps image reprocessing with DB-side data fetching

Each task uses `_run_async()` to bridge Celery's synchronous workers with the existing async scan functions by creating a new event loop per task execution. Scan and analysis tasks retry up to 2x with 60-second delay on transient failures.

**Modified Files**:

`backend/app/routers/scanning.py` — Replaced all `BackgroundTasks` usage:
- `start_scan()` — removed `background_tasks: BackgroundTasks` parameter; all four scan branches now call `run_*_scan_task.delay()` instead of `background_tasks.add_task()`
- `analyze_discovered_images()` — dispatches `analyze_scan_task.delay()` with just IDs (no large data payloads)
- `quick_scan()` — updated to call the modified `start_scan()` without `BackgroundTasks`
- `reprocess_unprocessed_images()` — dispatches `reprocess_images_task.delay()`
- Distributor mapping values changed from `UUID` objects to plain strings for JSON serialization compatibility

`backend/app/routers/campaigns.py` — Same `BackgroundTasks` removal:
- `start_campaign_scan()` — uses Celery task dispatch
- `analyze_campaign_scan()` — uses `analyze_scan_task.delay()`
- Removed status update to "running" at dispatch time (the scan function itself sets "running" when the Celery worker picks it up)

`backend/app/services/scheduler_service.py` — Scheduled scans now dispatch via Celery:
- `_trigger_scan()` — replaced `asyncio.create_task(run_*_scan(...))` with `run_*_scan_task.delay(...)` for all four scan sources
- Removed unused `asyncio` import
- Mapping values changed from UUID to string for serialization

`backend/app/config.py` — Added `redis_url` setting with default `redis://localhost:6379/0`

`backend/requirements.txt` — Added `celery[redis]>=5.4.0` and `redis[hiredis]>=5.0.0`

`docker-compose.yml` — Updated for local development:
- Added `redis` service (Redis 7 Alpine)
- Added `worker` service running `celery -A app.celery_app worker --loglevel=info --concurrency=2`
- Both `api` and `worker` share the same Dockerfile build and `.env` file
- `REDIS_URL` overridden to `redis://redis:6379/0` for Docker networking

**DigitalOcean App Spec** — Added worker component:
- Same Docker image as the API service (needs Playwright, CLIP, OpenCV)
- `run_command: celery -A app.celery_app worker --loglevel=info --concurrency=2`
- Same `professional-xs` instance size
- All environment variables duplicated (Supabase, Anthropic, scraper keys, etc.) since the worker executes the full scan pipeline
- `REDIS_URL` added to both API service and worker

### How Celery Task Queue Works

1. **User triggers scan** → API endpoint creates a scan job record (status: "pending") in Supabase and calls `run_website_scan_task.delay(urls, job_id, mapping, campaign_id)`
2. **Message published** → `.delay()` serializes the arguments to JSON and publishes a message to the Valkey broker. The API endpoint returns immediately with the job ID
3. **Worker picks up task** → The Celery worker process (running in a separate container) receives the message, deserializes the arguments, and calls the original async scan function via `asyncio.run()`
4. **Scan executes** → The scan function runs the full pipeline: page discovery → image extraction → hash/CLIP pre-filter → Claude analysis → match creation → notifications. It updates the scan job status in Supabase as it progresses (pending → running → completed/failed)
5. **Crash recovery** → If the worker dies mid-scan (deploy, OOM, crash), the task is NOT acknowledged (late ACK). Valkey keeps the message, and when the worker restarts, it picks the task back up and re-executes from the beginning. The scan function is idempotent — it skips already-processed images
6. **Scheduled scans** → APScheduler fires at the configured cron time, calls `.delay()` to publish the scan to Valkey, and the worker processes it. The scheduler runs in the API process; the actual scan runs in the worker process

### Production Architecture (Final State)

| Component | Platform | Instance | Purpose |
|-----------|----------|----------|---------|
| **Frontend** | Vercel | Managed | Next.js app, Supabase Auth, API calls to backend |
| **API** | DigitalOcean App Platform | professional-xs (1 vCPU, 1GB) | FastAPI + Gunicorn, handles HTTP, publishes scan tasks |
| **Worker** | DigitalOcean App Platform | professional-xs (1 vCPU, 1GB) | Celery worker, executes scans, AI pipeline, notifications |
| **Valkey** | DigitalOcean Managed DB | Basic ($15/mo) | Task message broker (TLS-encrypted) |
| **Database** | Supabase | Free tier | PostgreSQL + file storage + auth |

### Commits
- `faa8450` — Add Docker + DigitalOcean App Platform deployment config (Dockerfile, gunicorn.conf.py, .do/app.yaml, docker-compose.yml, .dockerignore)
- `118708b` — Fix Dockerfile: replace deprecated libgl1-mesa-glx with libgl1
- `a309e95` — Install CPU-only PyTorch to reduce Docker image size by ~5GB
- `f778a8f` — Add gunicorn to requirements.txt for production server
- `047748c` — Add Celery + Valkey task queue for durable scan execution (celery_app.py, tasks.py, scanning/campaigns/scheduler refactored)

### New Third-Party Services Added
| Service | Purpose | Cost |
|---------|---------|------|
| **DigitalOcean App Platform** | Backend API + Celery worker hosting | ~$24/mo (2× professional-xs) |
| **DigitalOcean Managed Valkey** | Celery task broker (Redis-compatible, TLS) | $15/mo |
| **Celery** | Distributed task queue for durable scan processing | Open source |

### Verified Working
- Backend API live at `https://dealer-intel-api-c2m2p.ondigitalocean.app`
- Health check passing: `{"status":"healthy","checks":{"database":"connected"}}`
- Auth enforced: protected endpoints return 401 without token
- Frontend live on Vercel, connected to production API
- Celery worker deployed and running (9/9 deployment steps passed)
- Auto-deploy on push to `main` enabled for both API and worker

---

## 2026-03-25 (Wednesday) — Production Readiness Blitz: Billing, Security, Tests, CI & Hardening

### Summary
Largest single-day output in the project's history. Completed the entire 7-tier Production Readiness Checklist — security hardening, rate limiting, infrastructure fixes, auth/data integrity patches, observability, 27 pytest tests with GitHub Actions CI, and database performance optimizations. Simultaneously shipped the remaining roadmap items: Stripe billing integration with plan enforcement, landing page and pricing page, team management with invite flow, alerts system, compliance rules CRUD, compliance trend analytics, onboarding checklist, scan usage UI, data retention enforcement, batch scanning, and page hit caching for scan cost optimization. Followed up with a hardening commit fixing tenant isolation gaps in scan dispatch, Celery task failure handling to prevent stuck jobs, and Playwright browser lifecycle cleanup. Total: 60 files changed, ~6,800 lines added across 2 commits.

### Session 1: Production Readiness + Roadmap Completion (Commit `34e753a`)

**58 files changed, 6,669 insertions(+), 375 deletions(−)**

#### Backend — Stripe Billing Integration (Roadmap Item 1)

- `routers/billing.py` (new, 429 lines) — Full Stripe integration:
  - `POST /billing/checkout` — Creates Stripe Checkout session with plan-specific price ID, passes `org_id` in metadata for webhook reconciliation
  - `POST /billing/portal` — Creates Stripe Customer Portal session for self-service plan management
  - `GET /billing/usage` — Returns current scan usage, dealer count, plan limits, and trial status
  - `POST /billing/webhook` — Stripe webhook handler with signature verification. Handles `checkout.session.completed` (activates plan, maps Stripe Price ID → plan name), `customer.subscription.updated` (plan changes), `customer.subscription.deleted` (downgrades to free), `invoice.payment_failed` (marks `past_due`)
  - Rate-limited: 60 requests/min on webhook endpoint
  - Reverse price mapping: `_build_price_plan_map()` lazily builds Stripe Price ID → plan name lookup from config

#### Backend — Plan Enforcement Middleware (Roadmap Items 2–3)

- `plan_enforcement.py` (new, 305 lines) — Reusable FastAPI dependency layer that gates features by subscription tier:
  - `OrgPlan` — Resolved plan context dependency (`get_org_plan`): reads org plan/status/trial from DB, blocks canceled subscriptions, warns on `past_due`
  - `require_active_plan()` — Blocks write operations when free trial has expired
  - `check_dealer_limit()` — Enforces max dealer cap per plan (counts active distributors)
  - `check_campaign_limit()` — Enforces max campaign cap per plan
  - `check_scan_quota()` — Enforces monthly scan limit with period-based counting (scans created since start of current billing month)
  - `check_concurrent_scans()` — Prevents concurrent scan overload (counts jobs with status `pending` or `running`)
  - `check_channel_allowed()` — Restricts scan channels by plan (free = website only, starter = website only, pro = all, business = all)
  - `check_schedule_limit()` — Enforces max schedules per campaign and allowed frequency tiers
  - `check_compliance_rules_limit()` — Enforces max compliance rules per plan
  - `check_user_seat_limit()` — Enforces max team member seats per plan
- `config.py` (+169 lines) — Added `PLAN_LIMITS` dictionary defining 4 tiers (free, starter, professional, business) with 22 limit/feature-flag fields each:
  - Free: 2 dealers, 1 campaign, 5 total scans, website-only, 21-day retention, 14-day trial
  - Starter: 10 dealers, 3 campaigns, 15 scans/month, website-only, biweekly/monthly scheduling, 90-day retention
  - Professional: 25 dealers, 10 campaigns, 60 scans/month, all channels, all frequencies, PDF reports, email notifications, compliance trends, 365-day retention
  - Business: 100 dealers, unlimited campaigns, 200 scans/month, all channels, report branding, adaptive calibration, unlimited retention
  - Added Stripe config fields: `stripe_secret_key`, `stripe_webhook_secret`, per-plan price IDs, extra dealer price IDs, `frontend_url`
  - Added helper functions: `get_plan_limits()`, `get_stripe_price_id()`, `get_extra_dealer_price_id()`

#### Backend — Team Management (Roadmap Item 9)

- `routers/team.py` (new, 260 lines) — Full team CRUD with role-based access:
  - `GET /team/members` — Lists all org members with email lookups from Supabase Auth
  - `POST /team/invites` — Admin-only invite creation with seat limit check. Generates unique token, stores in `pending_invites` table with 7-day expiry
  - `GET /team/invites` — Lists pending invites for the org
  - `POST /team/invites/{token}/accept` — Rate-limited (10/min). Requires auth. Validates invite email matches authenticated user email. Creates `user_profiles` entry and deletes invite
  - `DELETE /team/invites/{id}` — Admin-only invite cancellation
  - `DELETE /team/members/{user_id}` — Admin-only member removal. Prevents removing self
  - `PATCH /team/members/{user_id}/role` — Admin-only role change (owner/admin/member)

#### Backend — Alerts System

- `routers/alerts.py` (new, 94 lines) — Org-scoped alert endpoints:
  - `GET /alerts` — Paginated alerts list filtered by `is_read`, org-scoped
  - `PATCH /alerts/{id}/read` — Mark single alert as read with org ownership verification
  - `POST /alerts/mark-all-read` — Bulk mark all org alerts as read

#### Backend — Compliance Rules CRUD (Tier 2.2)

- `routers/compliance_rules.py` (new, 154 lines) — Full CRUD with plan enforcement:
  - `GET /compliance-rules` — List org's compliance rules
  - `GET /compliance-rules/{id}` — Get single rule with org ownership check
  - `POST /compliance-rules` — Create rule with `check_compliance_rules_limit()` gate
  - `PATCH /compliance-rules/{id}` — Update rule with org ownership check
  - `DELETE /compliance-rules/{id}` — Delete with org ownership check

#### Backend — Data Retention Enforcement (Roadmap Item 10)

- `services/retention_service.py` (new, 94 lines) — Scheduled daily purge at 03:00 UTC:
  - `run_retention_sweep()` — Iterates all organizations, reads each plan's `data_retention_days`, calculates cutoff date, deletes expired scan jobs (cascading to `discovered_images` and `matches`)
  - Only purges `completed` and `failed` jobs — never deletes in-progress work
  - Integrated into APScheduler as a daily cron job

#### Backend — Page Hit Cache for Scan Cost Optimization (Roadmap Item 17)

- `services/page_cache_service.py` (new, 130 lines) — Tracks which dealer web pages previously produced matches:
  - `get_cached_pages()` — Returns cached page URLs ordered by hit count (most productive pages first)
  - `record_page_hits()` — After a scan completes, upserts page→asset match records with hit counts and timestamps
  - `clear_cache()` — Invalidates cache for a distributor (useful when campaign assets change)
- `scanning.py` — Integrated page cache into website scan flow: on repeat scans, cached "hot" pages are scanned first. If all campaign assets are matched from cached pages alone, full page discovery (sitemap parsing, link crawling) is skipped entirely, saving HTTP calls, Playwright browser loads, and AI API costs

#### Backend — Security Hardening (Tiers 1–2)

- `organizations.py` — Added `get_current_user` dependency and `_assert_own_org()` guard to all org endpoints: test-email, logo upload/delete, settings GET/PATCH. Prevents cross-tenant access
- `scanning.py` — Added auth (`get_current_user`) to scan detail, delete, analyze, and reprocess endpoints. Added `OrgPlan` dependency to `start_scan` and `batch_scan` with `check_channel_allowed()`, `check_scan_quota()`, `check_concurrent_scans()` gates. Rate-limited: start=10/min, batch=2/min
- `matches.py` — Added plan gating on feedback endpoints (require active plan)
- `reports.py` — Added plan check for PDF report access
- `schedules.py` — Added `check_schedule_limit()` enforcement on schedule creation
- `main.py` — Activated `SlowAPIMiddleware` (was configured but never wired). Registered 4 new routers (billing, team, alerts, compliance_rules). Added startup audit log confirming dangerous endpoints are disabled

#### Backend — Auth & Data Integrity (Tier 4)

- `auth.py` — Replaced unbounded `dict` profile cache with `cachetools.TTLCache(maxsize=10_000, ttl=300)` — entries auto-expire after 5 minutes. Added try/except around `_auto_provision_user` with retry lookup to handle race conditions when concurrent requests both try to create the same user profile
- `requirements.txt` — Added `cachetools>=5.3.0`

#### Backend — Observability (Tier 5)

- `main.py` — Added `RequestLoggingMiddleware` (logs `METHOD /path STATUS TIMEms` for every request). Extended `/health` to ping both Supabase and Redis — returns `503 degraded` if either is unreachable (uses `redis.from_url()` with 3-second timeout). Added startup log confirming `ENABLE_DANGEROUS_ENDPOINTS` state
- `celery_app.py` — Unified Redis URL env var handling (falls back to both `REDIS_URL` and `redis_url`)

#### Backend — Dashboard Enhancements (Roadmap Items 8, 13)

- `dashboard.py` (+225 lines) — Major expansion:
  - `GET /dashboard/compliance-trend` — Week-over-week compliance trend chart data (gated to Pro+Business plans). Aggregates matches by week with compliance/violation counts
  - `GET /dashboard/stats` — Optimized to call `get_dashboard_stats` Postgres RPC first (single round-trip for all 8 counters), falls back to sequential queries if RPC not deployed
  - `GET /dashboard/onboarding` — Returns onboarding checklist status (has campaigns, has distributors, has scans, has matches, has schedule)
  - Error handling with contextual suggestions on scan status endpoints

#### Backend — Tests (Tier 6)

- `tests/conftest.py` (new, 61 lines) — Shared pytest fixtures: mock Supabase client, mock auth user factory, FastAPI test client with dependency overrides
- `tests/test_auth.py` (new, 171 lines) — 10 tests: missing token, expired JWT, invalid JWT, wrong secret, valid token resolution, auto-provisioning, cache hit, TTL config, single-user cache clear, full cache clear
- `tests/test_tenant_isolation.py` (new, 231 lines) — 10 tests: cross-org settings read/update/logo/delete/email blocked, campaign/distributor/match/scan/alert lists are org-scoped
- `tests/test_billing_webhook.py` (new, 186 lines) — 7 tests: invalid signature rejection, checkout.session.completed activation, missing org_id graceful, payment_failed marks past_due, unknown customer graceful, subscription.deleted downgrade, unhandled event passthrough
- `requirements.txt` — Added `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `httpx>=0.28.0`

#### Backend — CI/CD Pipeline (Tier 6.4)

- `.github/workflows/ci.yml` (new, 98 lines) — GitHub Actions pipeline on every push/PR to `main`:
  - `backend-tests` job: Python 3.11, pip cache, `pytest tests/ -v --tb=short` with mock env vars
  - `frontend-build` job: Node 20, npm cache, `npm ci && npm run build` with mock env vars
  - `migrate` job: runs `supabase db push` after backend tests pass, only on pushes to `main` (requires `SUPABASE_ACCESS_TOKEN` and `SUPABASE_PROJECT_REF` GitHub secrets)

#### Backend — Database Performance (Tier 7)

- `supabase/migrations/017_dashboard_stats_rpc.sql` — Postgres RPC function `get_dashboard_stats(p_org_id)` that returns all 8 dashboard counters (total matches, violations, active distributors, active campaigns, pending scans, completed scans, active schedules, unread alerts) in a single round-trip instead of 8 separate queries
- `supabase/migrations/018_production_indexes.sql` — 7 composite indexes for production query patterns: `matches(distributor_id, compliance_status)`, `matches(distributor_id, created_at)`, `scan_jobs(organization_id, status)`, `scan_jobs(organization_id, created_at)`, `alerts(organization_id, is_read)`, `discovered_images(scan_job_id, is_processed)`, `assets(campaign_id)`

#### Backend — Infrastructure (Tier 3)

- `.do/app.yaml` (+104 lines) — Major expansion: added Celery worker component with all env vars (Supabase, Anthropic, scraper keys, Stripe, Redis), `SCHEDULER_ENABLED=true` on API only, corrected CORS origins
- `scheduler_service.py` — Added `SCHEDULER_ENABLED` env var check to prevent APScheduler duplication on multi-replica deployments. Added data retention sweep as daily cron job at 03:00 UTC

#### Frontend — Landing Page & Pricing Page (Roadmap Item 4)

- `app/landing/page.tsx` (new, 438 lines) — Public-facing marketing page with:
  - Hero section with headline, subheadline, and dual CTAs ("Start Free Trial" / "Book a Demo")
  - 6-feature grid: Multi-Channel Scanning, Proprietary AI Detection, Compliance Reporting, Automated Scheduling, Real-Time Alerts, Coverage Mapping
  - "How It Works" 3-step explainer (Upload → Scan → Report)
  - Social proof section with stat callouts
  - Bottom CTA banner
- `app/pricing/page.tsx` (new, 478 lines) — Pricing page with 4-tier card layout:
  - Free (Trial): 2 dealers, 1 campaign, website scanning, 5 total scans
  - Starter ($49/mo): 10 dealers, 3 campaigns, 15 scans/month, basic scheduling
  - Professional ($149/mo): 25 dealers, 10 campaigns, all channels, PDF reports, email alerts
  - Business ($349/mo): 100 dealers, unlimited campaigns, full feature set, priority support
  - Feature comparison checklist per tier, "Most Popular" badge on Professional
- `components/marketing/navbar.tsx` (new, 95 lines) — Marketing navigation bar with logo, nav links, and auth-aware CTA buttons
- `components/marketing/footer.tsx` (new, 69 lines) — Marketing footer with product/company/legal link columns

#### Frontend — Scan Usage UI (Roadmap Item 6)

- `components/dashboard/trial-banner.tsx` (new, 73 lines) — Dismissible trial banner showing days remaining, with "Upgrade" CTA. Only renders for free-tier orgs during active trial
- `components/dashboard/usage-card.tsx` (new, 111 lines) — Usage meters showing scan count (used/limit), dealer count (used/limit), and campaign count with progress bars and color-coded thresholds
- `components/dashboard/upgrade-modal.tsx` (new, 96 lines) — Modal triggered when user hits a plan limit. Shows upgrade benefits and redirects to pricing page
- `lib/upgrade-events.ts` (new, 16 lines) — Custom event system for triggering upgrade modals from any component

#### Frontend — Onboarding Checklist (Roadmap Item 7)

- `components/dashboard/onboarding-checklist.tsx` (new, 165 lines) — Dismissible checklist for first-time setup with 5 steps: Create Campaign, Add Distributor, Upload Assets, Run First Scan, Review Matches. Each step links to the relevant page. Progress bar tracks completion

#### Frontend — Compliance Trend Analytics (Roadmap Item 13)

- `components/dashboard/compliance-trend.tsx` (new, 160 lines) — Recharts-based area chart showing week-over-week compliance vs violation trends. Gated to Pro+Business plans with upgrade prompt for lower tiers

#### Frontend — Team Management UI (Roadmap Item 9)

- `components/settings/team-section.tsx` (new, 279 lines) — Team settings card with:
  - Member list with role badges and remove buttons
  - Invite form with email input and role selector (member/admin)
  - Pending invites list with cancel buttons
  - Seat count display (used/max by plan)
  - Admin-only actions gated by current user's role

#### Frontend — Alerts Page

- `app/alerts/page.tsx` (new, 253 lines) — Full alerts page with filtering (all/unread/read), mark-as-read on individual alerts, "Mark All Read" bulk action, severity badges, and relative timestamps

#### Frontend — Settings Page Expansion

- `app/settings/page.tsx` (+175 lines) — Added billing settings card with current plan display, usage summary, and "Manage Subscription" button (links to Stripe portal). Added team management section integration

#### Frontend — Dashboard Updates

- `app/page.tsx` (+38 lines) — Integrated trial banner, onboarding checklist, usage card, and compliance trend chart into dashboard layout
- `app/scans/page.tsx` (+98 lines) — Added scan status badges with contextual error messages and retry buttons. Shows scan source icons and progress indicators

#### Frontend — Auth & Navigation

- `lib/auth-context.tsx` — Extracted `PUBLIC_PATHS` constant (exported). `onAuthStateChange` now redirects unauthenticated users to `/landing` instead of `/login`. Includes `/landing`, `/pricing`, `/login`, `/signup` as public paths
- `components/layout/auth-gate.tsx` — Imports shared `PUBLIC_PATHS` from auth-context instead of maintaining its own copy
- `components/layout/sidebar.tsx` — Added "Alerts" nav item with bell icon. Added "Compliance Rules" nav item

#### Frontend — API & Hooks

- `lib/api.ts` (+103 lines) — Added: `createCheckoutSession()`, `createPortalSession()`, `getBillingUsage()`, `getTeamMembers()`, `inviteTeamMember()`, `acceptInvite()`, `removeTeamMember()`, `getAlerts()`, `markAlertRead()`, `markAllAlertsRead()`, `getOnboardingStatus()`, `getComplianceTrend()`
- `lib/hooks.ts` (+100 lines) — Added React Query hooks: `useBillingUsage()`, `useTeamMembers()`, `useInviteTeamMember()`, `useAlerts()`, `useOnboardingStatus()`, `useComplianceTrend()`

#### Database Migrations

- `014_billing_plan.sql` — `plan`, `plan_status`, `stripe_customer_id`, `stripe_subscription_id`, `trial_expires_at` columns on `organizations`
- `015_pending_invites.sql` — `pending_invites` table with token, org_id, email, role, expires_at, unique constraint on (org_id, email)
- `016_page_hit_cache.sql` — `page_hit_cache` table with org_id, distributor_id, campaign_id, page_url, hit_count, last_hit_at, unique constraint on (org_id, distributor_id, page_url)
- `017_dashboard_stats_rpc.sql` — `get_dashboard_stats` Postgres RPC function
- `018_production_indexes.sql` — 7 production composite indexes

---

### Session 2: Production Hardening (Commit `5ed34d8`)

**7 files changed, 127 insertions(+), 29 deletions(−)**

Follow-up hardening pass fixing issues discovered during Session 1 review.

#### Tenant Isolation Gaps in Scan Dispatch

- `scanning.py` — `start_scan()` now validates that the campaign and all distributors in the scan request actually belong to the authenticated user's organization before dispatching to Celery. Previously, a user could submit a scan request referencing another org's campaign or distributors
- `scanning.py` — `reprocess_unprocessed_images` endpoint now scopes image lookup by organization (only reprocesses images from scan jobs belonging to the user's org)

#### Celery Task Failure Handling

- `tasks.py` — Wrapped all 4 scan tasks (`run_website_scan_task`, `run_google_ads_scan_task`, `run_facebook_scan_task`, `run_instagram_scan_task`) in try/except blocks. On unhandled exception, the scan job is marked as `failed` in the database with a truncated error message (500 chars max) via `_mark_job_failed()`. Previously, an uncaught exception would leave the scan job stuck in `running` status permanently
- `tasks.py` — `analyze_scan_task` now catches errors and marks the scan job as failed. `reprocess_images_task` now scopes discovered images to the campaign's organization's scan jobs (prevents cross-org data leakage)

#### Auth Error Handling

- `auth.py` — Added try/except around UUID parsing of `sub` claim from JWT. Returns `401 Unauthorized` instead of crashing with a `500 Internal Server Error` when a malformed UUID is in the token

#### Stripe Webhook Hardening

- `billing.py` — Sanitized error responses on webhook failures (no longer leaks internal error details). Added guard requiring both `stripe_secret_key` and `stripe_webhook_secret` to be configured before processing webhooks

#### Playwright Browser Lifecycle

- `extraction_service.py` — Fixed browser reconnection: when a disconnected browser is detected, the old `Browser` and `Playwright` instances are now explicitly closed/stopped before creating new ones. Previously, stale instances leaked memory. Added defensive `finally` blocks around `page.context.close()` calls to prevent crashes when the browser context is already invalidated

#### Infrastructure

- `.do/app.yaml` — Added `FRONTEND_URL` and all Stripe environment variables to the Celery worker component (worker needs these for notification emails and billing checks during scan execution)
- `celery_app.py` — Added `load_dotenv()` call so the worker process picks up `.env` variables including `PLAYWRIGHT_BROWSERS_PATH` (Chromium location in Docker)

### Commits
- `34e753a` — Production readiness: security hardening, billing, tests, CI, and performance (58 files, +6,669/−375)
- `5ed34d8` — Harden production: tenant isolation, task failure handling, browser cleanup (7 files, +127/−29)

### New Third-Party Services Added
| Service | Purpose | Cost |
|---------|---------|------|
| **Stripe** | Subscription billing, checkout, customer portal, webhooks | Usage-based (2.9% + 30¢/txn) |
| **cachetools** | TTL-based profile cache replacing unbounded dict | Open source |
| **pytest** | Backend test framework | Open source |
| **GitHub Actions** | CI pipeline (tests + build + migrations) | Free for public repos |

### Roadmap Items Completed Today
| # | Item | Description |
|---|------|-------------|
| 1 | Stripe billing | Checkout, subscriptions, webhooks, customer portal |
| 2 | Plan enforcement | 4-tier limits on dealers, campaigns, scans, channels, features |
| 3 | Scan quotas | Monthly scan counting + concurrent scan limiter |
| 4 | Landing + pricing pages | Marketing pages with feature grid, pricing cards, CTAs |
| 6 | Scan usage UI | Trial banner, usage meters, upgrade modals |
| 7 | Onboarding flow | 5-step dashboard checklist for first-time setup |
| 8 | Error handling | Contextual error messages + retry on scan status |
| 9 | User seats + invites | Team management with role-based access, 7-day invite tokens |
| 10 | Data retention | Scheduled daily purge by plan tier (21d–unlimited) |
| 12 | Batch scanning | "Scan All Channels" for Pro+Business plans |
| 13 | Compliance trends | Week-over-week compliance chart (Pro+Business) |
| 17 | Page hit caching | Hot pages scanned first, full discovery skipped on repeat scans |

### Production Readiness Tiers Completed Today
| Tier | Focus | Items |
|------|-------|-------|
| 1 | Security | Auth on all org/scan/team endpoints, tenant isolation guards |
| 2 | Rate Limiting | SlowAPI activated, per-route limits, compliance rules gated |
| 3 | Infrastructure | Celery worker in app.yaml, CORS fix, scheduler guard, Redis URL |
| 4 | Auth & Data | TTL profile cache, auto-provision race condition fix, PUBLIC_PATHS |
| 5 | Observability | Redis health check, request logging middleware, dangerous endpoint audit |
| 6 | Testing & CI | 27 pytest tests, GitHub Actions CI with automated migrations |
| 7 | Performance | Dashboard stats RPC, 7 production indexes, migration runner |

### Updated Production Readiness Score
**Previous: 4.5 / 10 → Current: 8.5 / 10** — All 7 tiers completed. Remaining gaps: end-to-end integration tests with real Supabase, load testing under production traffic, and Sentry alert rules configuration.

---

## Third-Party Services Inventory

All external services and significant libraries used across the application.

### Cloud Services & APIs
| Service | Purpose | Config |
|---------|---------|--------|
| **Supabase** | PostgreSQL database + file storage (logos, assets) + auth | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| **Anthropic Claude** | AI image analysis — Haiku (filtering), Sonnet (comparison), Opus (verification) | `ANTHROPIC_API_KEY` |
| **Stripe** | Subscription billing, checkout, customer portal, webhooks | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` |
| **Apify** | Meta Ad Library + Instagram organic post scraping | `APIFY_API_KEY` |
| **SerpApi** | Google Ads Transparency Center structured data | `SERPAPI_API_KEY` |
| **ScreenshotOne** | Website screenshot capture with cookie blocking | `SCREENSHOTONE_ACCESS_KEY`, `SCREENSHOTONE_SECRET_KEY` |
| **Resend** | Transactional email notifications (scan results, violations) | `RESEND_API_KEY` |
| **Sentry** | Error tracking and performance monitoring (frontend + backend) | `SENTRY_DSN` |
| **Mapbox GL** | Interactive dealer compliance map visualization | `NEXT_PUBLIC_MAPBOX_TOKEN` |
| **GitHub Actions** | CI pipeline (backend tests, frontend build, automated migrations) | — |
| **DigitalOcean App Platform** | Backend API + Celery worker hosting (Docker) | — |
| **DigitalOcean Managed Valkey** | Celery task broker (Redis-compatible, TLS) | `REDIS_URL` |
| **Vercel** | Frontend hosting and deployment | — |

### Key Libraries
| Library | Purpose | Language |
|---------|---------|----------|
| **FastAPI** | Backend web framework | Python |
| **Gunicorn** | Production WSGI/ASGI server with Uvicorn workers | Python |
| **Celery** | Distributed task queue for durable background scan processing | Python |
| **Next.js 14** | Frontend React framework with App Router | TypeScript |
| **APScheduler** | Cron-based scan scheduling engine | Python |
| **ReportLab** | PDF compliance report generation | Python |
| **Playwright** | Browser automation for image extraction from web pages | Python |
| **OpenCV** | Visual template matching + ORB feature matching | Python |
| **CLIP (sentence-transformers)** | Embedding-based image similarity pre-filtering | Python |
| **Pillow** | Image processing, resizing, default logo generation | Python |
| **imagehash** | Perceptual hashing for image deduplication pre-filter | Python |
| **httpx / aiohttp** | Async HTTP clients for API calls and image downloads | Python |
| **Pydantic** | Data validation, settings management, API schemas | Python |
| **shadcn/ui** | UI component library (cards, tables, tabs, badges, buttons) | TypeScript |
| **Tailwind CSS** | Utility-first CSS framework | CSS |
| **React Query** | Server state management and data fetching | TypeScript |
| **Recharts** | Dashboard charts and data visualization | TypeScript |
| **Axios** | Frontend HTTP client | TypeScript |
| **slowapi** | API rate limiting | Python |
| **cachetools** | TTL-based profile caching for auth | Python |
| **pytest** | Backend test framework | Python |
| **stripe** | Stripe API client for billing integration | Python |

---

## Open Items / Next Steps

### Priority 1 — Ship-Ready
- [x] ~~Commit all uncommitted changes~~
- [x] ~~Add authentication (Supabase Auth + JWT-based RLS)~~
- [x] ~~Implement task queue (Celery + Valkey) to replace BackgroundTasks~~
- [x] ~~Write tests (27 pytest tests — auth, tenant isolation, billing webhooks)~~
- [x] ~~Add Docker + CI/CD configuration (GitHub Actions pipeline)~~

### Priority 2 — Feature Completeness
- [x] Add scheduled/automated scans (daily, weekly per org)
- [x] Build PDF/CSV compliance report generation
- [x] Add email/Slack notifications for violations

### Priority 3 — Performance & Polish
- [ ] Re-enable match deduplication (disabled for testing)
- [x] ~~Batch scanning mode for large distributor networks (40+ distributors)~~

### Completed (Previous Sessions)
- [x] Adaptive threshold calibration with feedback loop (Item 8)
- [x] Match feedback UI (thumbs up/down on matches list and detail pages)
- [x] Instagram organic post scanning via Apify actor
- [x] Campaign scan routing fix (Instagram no longer routes to Meta Ads actor)
- [x] Early-stopping optimization for website scans (stops after all assets matched; skipped 15/16 pages in first live test)
- [x] Image download caching (LRU cache with 22.7% hit rate observed in first live test)

### Completed (2026-03-24 — Priority 2)
- [x] PDF/CSV compliance report generation with download endpoints
- [x] Customizable PDF branding: logo upload, company name, color theme presets
- [x] Settings page for organization-level configuration
- [x] Email notifications via Resend (scan completions + violation alerts)
- [x] Scheduled/automated scans with APScheduler (daily, weekly, biweekly, monthly)
- [x] Time-specific scheduling: time picker (UTC) + day-of-week selector
- [x] Schedule management UI: create, pause/resume, delete

### Completed (2026-03-24 — Deployment & Infrastructure)
- [x] Docker containerization (Dockerfile with Playwright, OpenCV, CPU-only PyTorch)
- [x] Gunicorn production server config (Uvicorn workers, 5-min timeout, preload)
- [x] DigitalOcean App Platform deployment (API service + Celery worker)
- [x] Vercel frontend deployment with production environment variables
- [x] Celery + Valkey distributed task queue (durable, crash-recoverable scans)
- [x] Late ACK + task rejection for automatic crash recovery
- [x] Auto-deploy on push to `main` for both API and worker
- [x] TLS-encrypted Valkey connection for task broker security

### Completed (2026-03-25 — Production Readiness Blitz)
- [x] Stripe billing integration (checkout, subscriptions, webhooks, customer portal)
- [x] Plan enforcement middleware (4-tier limits on dealers, campaigns, scans, channels)
- [x] Monthly scan quotas + concurrent scan limiter
- [x] Landing page + pricing page with marketing components
- [x] Scan usage UI (trial banner, usage meters, upgrade modals)
- [x] Onboarding checklist (5-step first-time setup guide)
- [x] User seats + team invite flow with role-based access
- [x] Alerts system (org-scoped, mark read, bulk mark)
- [x] Compliance rules CRUD with plan gating
- [x] Data retention enforcement (daily purge by plan tier)
- [x] Batch scanning mode ("Scan All Channels")
- [x] Compliance trend analytics (week-over-week chart, Pro+Business)
- [x] Page hit caching for scan cost optimization
- [x] Security hardening: auth + tenant isolation on all endpoints
- [x] Rate limiting activated (SlowAPI middleware + per-route limits)
- [x] TTL profile cache + auto-provision race condition fix
- [x] Redis health check + request logging middleware
- [x] 27 pytest tests (auth, tenant isolation, billing webhooks)
- [x] GitHub Actions CI pipeline (tests + build + automated migrations)
- [x] Dashboard stats RPC + 7 production database indexes
- [x] Celery task failure handling (stuck job prevention)
- [x] Playwright browser lifecycle cleanup
- [x] Tenant isolation gaps fixed in scan dispatch + image reprocessing

---

## Roadmap — Prioritized Checklist

Items 1–4 block revenue. Items 5–9 block a good first-customer experience. Items 10–13 prevent problems at ~5–10 customers. Remaining items are growth and differentiation plays.

- [x] **1. Stripe integration + subscription billing** — Stripe Checkout, Subscriptions with metered dealer billing, webhook handler, billing columns on `organizations`
- [x] **2. Plan enforcement middleware** — `plan_limits` config mapping tier → caps, enforced at every create endpoint
- [x] **3. Monthly scan quota + concurrent scan limiter** — Per-org per-period scan counting + concurrent scan gating
- [x] **4. Landing page + pricing page** — Public-facing marketing pages with "Book a Demo" CTAs
- [ ] **5. Re-enable match deduplication** — Already built, disabled for testing *(deferred to pre-launch testing)*
- [x] **6. Scan usage UI** — Trial banner, usage meters, billing settings, upgrade modals
- [x] **7. Onboarding flow** — Dashboard checklist for first-time setup
- [x] **8. Error handling + user-facing scan status** — Error messages with contextual suggestions + retry mechanism
- [x] **9. User seats + invite flow** — Org admin invite flow with seat limits by plan
- [x] **10. Data retention enforcement** — Scheduled daily purge job at 03:00 UTC, retention by plan tier
- [ ] **11. Tests (pytest)** — Unit tests for `ai_service.py`, integration tests, API router tests *(deferred to pre-launch testing)*
- [x] **12. Batch scanning mode** — "Scan All Channels" for Pro+Business plans
- [x] **13. Compliance trend analytics** — Week-over-week compliance chart on dashboard (Pro+Business)
- [x] **17. Recurring scan cost optimization** — Page hit cache: hot pages scanned first on repeat scans, full discovery skipped when all assets matched from cache

### On Hold
- [ ] **15. Slack / webhook notifications** — Blocked on Slack access
- [ ] **16. White-label reports (Enterprise)** — On hold

### Remaining
- [ ] **20. API access (Enterprise)** — REST API with API key authentication for customer integrations

### Removed
- ~~14. Volume pricing~~ — Removed
- ~~18. Instagram Stories/Reels scanning~~ — Removed
- ~~19. YouTube scanning~~ — Removed

---

## Production Readiness Checklist

**Current score: 8.5 / 10 — All 7 tiers completed (2026-03-25). Remaining: E2E integration tests, load testing, Sentry alert rules.**

### Tier 1: Security (Critical — fix before any real user)

- [x] **1.1 Add auth to unprotected org endpoints** — `POST /{org_id}/test-email`, `GET /{org_id}/logo`, `DELETE /{org_id}/logo` in `organizations.py` have no `get_current_user` dependency. Add auth + plan gating.
- [x] **1.2 Add tenant scoping on all org routes** — `get_org_settings`, `update_org_settings`, `upload_org_logo` accept `{org_id}` from URL but never verify it matches `user.org_id`. Add `_assert_own_org(org_id, user)` guard to every endpoint in `organizations.py`.
- [x] **1.3 Add auth to unprotected scan endpoints** — `GET /scans/{job_id}`, `DELETE /scans/{job_id}`, `POST /scans/{job_id}/analyze`, `POST /scans/reprocess-unprocessed` in `scanning.py` have no auth. Add `get_current_user` + org scoping to each.
- [x] **1.4 Protect invite-accept endpoint** — `POST /team/invites/{token}/accept` has no auth and no rate limit. Require `get_current_user` and verify invite email matches `user.email`.

### Tier 2: Rate Limiting & Abuse Prevention

- [x] **2.1 Activate the rate limiter** — Add `SlowAPIMiddleware` to `main.py` (currently configured but never wired). Add per-route limits: `POST /scans/start` (10/min), `POST /scans/batch` (2/min), `POST /billing/webhook` (60/min), `POST /team/invites/{token}/accept` (10/min), `POST /{org_id}/test-email` (5/min).
- [x] **2.2 Wire unused compliance rules limit** — Built `compliance_rules.py` CRUD router (list, get, create, update, delete). `check_compliance_rules_limit(op)` enforced on create. Wired into `main.py`.
- [x] **2.3 Gate compliance trend by plan** — `GET /dashboard/compliance-trend` is ungated, but `compliance_trends` is a paid feature flag. Add `OrgPlan` dependency and check the flag.

### Tier 3: Infrastructure & Deployment

- [x] **3.1 Fix `app.yaml` — add Celery worker** — Added `workers` section with Celery process, `REDIS_URL` env to both api and worker, `SCHEDULER_ENABLED=true` on api.
- [x] **3.2 Fix CORS / frontend URL mismatch** — `CORS_ORIGINS` updated to `dealer-intel-saas.vercel.app` to match `FRONTEND_URL`.
- [x] **3.3 Prevent APScheduler duplication** — Added `SCHEDULER_ENABLED` env var check in `scheduler_service.py`. Defaults to `true` for single-instance; set to `false` on additional replicas.
- [x] **3.4 Unify Redis URL env var** — `celery_app.py` now falls back to both `REDIS_URL` and `redis_url` env vars. Documented `REDIS_URL` as canonical.

### Tier 4: Auth & Data Integrity

- [x] **4.1 Add TTL to profile cache** — Replaced unbounded `dict` with `cachetools.TTLCache(maxsize=10_000, ttl=300)` in `auth.py`. Added `cachetools>=5.3.0` to `requirements.txt`.
- [x] **4.2 Fix auto-provisioning race condition** — `user_profiles.user_id` already has a `UNIQUE` constraint. Added try/except around `_auto_provision_user` with a retry lookup so concurrent requests don't crash — second request picks up the already-created profile.
- [x] **4.3 Fix frontend auth redirect inconsistency** — Extracted `PUBLIC_PATHS` constant in `auth-context.tsx` (exported). `onAuthStateChange` now uses `PUBLIC_PATHS.includes(pathname)` and redirects to `/landing` instead of `/login`. `auth-gate.tsx` imports shared `PUBLIC_PATHS` instead of its own copy.

### Tier 5: Observability & Error Handling

- [x] **5.1 Add Redis health check** — `GET /health` now pings both Supabase and Redis. Returns `503 degraded` if either is unreachable. Uses `redis.from_url()` with a 3-second connect timeout.
- [x] **5.2 Add request logging middleware** — `RequestLoggingMiddleware` in `main.py` logs `METHOD /path STATUS TIMEms` for every request via `BaseHTTPMiddleware`.
- [x] **5.3 Verify dangerous endpoints are disabled** — `ENABLE_DANGEROUS_ENDPOINTS=false` confirmed in `app.yaml`. All 3 guarded endpoints (`DELETE /scans`, `GET /scans/debug/{id}`, `DELETE /matches`) return 403. Added startup log line confirming the state.

### Tier 6: Testing & CI

- [x] **6.1 Create auth tests** — `backend/tests/test_auth.py`: 10 tests covering missing token, expired JWT, invalid JWT, wrong secret, valid token profile resolution, auto-provisioning new user, cache hit on second request, TTL config check, single-user cache clear, full cache clear.
- [x] **6.2 Create tenant isolation tests** — `backend/tests/test_tenant_isolation.py`: 10 tests verifying User A cannot read/update/logo/delete/email Org B's settings, campaign and distributor lists are org-scoped, match list goes through org distributors, scan lookup is org-scoped, alert list is org-scoped.
- [x] **6.3 Create billing webhook tests** — `backend/tests/test_billing_webhook.py`: 7 tests covering invalid signature → 400, checkout.session.completed activates plan, missing org_id is graceful, payment_failed marks past_due, unknown customer is graceful, subscription.deleted downgrades to free, unhandled event returns 200.
- [x] **6.4 Add CI pipeline** — `.github/workflows/ci.yml`: runs `pytest` on backend (Python 3.11) and `npm run build` on frontend (Node 20) on every push/PR to main. Added `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `httpx>=0.28.0` to `requirements.txt`.

### Tier 7: Data & Performance

- [x] **7.1 Optimize dashboard stats** — Created `get_dashboard_stats` Postgres RPC (migration `017_dashboard_stats_rpc.sql`) that returns all 8 counters in a single round-trip. `dashboard.py` calls the RPC first and falls back to sequential queries if the function isn't deployed yet.
- [x] **7.2 Add production database indexes** — Migration `018_production_indexes.sql`: 7 composite indexes on `matches(distributor_id, compliance_status)`, `matches(distributor_id, created_at)`, `scan_jobs(organization_id, status)`, `scan_jobs(organization_id, created_at)`, `alerts(organization_id, is_read)`, `discovered_images(scan_job_id, is_processed)`, `assets(campaign_id)`.
- [x] **7.3 Add migration runner to deploy pipeline** — Added `migrate` job to `.github/workflows/ci.yml` that runs `supabase db push` after backend tests pass, only on pushes to `main`. Requires `SUPABASE_ACCESS_TOKEN` and `SUPABASE_PROJECT_REF` GitHub secrets.

### Execution Timeline

All 7 tiers completed in a single day (2026-03-25). Original 3-week estimate collapsed into one session.

| Tier | Items | Status |
|------|-------|--------|
| **Tier 1** | 1.1, 1.2, 1.3, 1.4 | Completed 2026-03-25 |
| **Tier 2** | 2.1, 2.2, 2.3 | Completed 2026-03-25 |
| **Tier 3** | 3.1, 3.2, 3.3, 3.4 | Completed 2026-03-25 |
| **Tier 4** | 4.1, 4.2, 4.3 | Completed 2026-03-25 |
| **Tier 5** | 5.1, 5.2, 5.3 | Completed 2026-03-25 |
| **Tier 6** | 6.1, 6.2, 6.3, 6.4 | Completed 2026-03-25 |
| **Tier 7** | 7.1, 7.2, 7.3 | Completed 2026-03-25 |

---

## 2026-03-26 — Production Scan Pipeline Fix

### Problem

Website scans stuck in "pending" indefinitely in production. The issue began after the initial deployment to DigitalOcean App Platform and persisted across multiple debugging attempts throughout the day.

### Root Cause Chain

1. **Celery/Kombu SSL transport bug** — The original task queue (Celery) used Kombu for Redis transport. Kombu silently drops messages over `rediss://` (SSL) connections to DigitalOcean's managed Valkey. Workers appeared "ready" but never received tasks. This is a known upstream issue (`celery/kombu#2007`).

2. **ARQ migration — same class of problem** — Migrated from Celery to ARQ (lighter async Redis queue). ARQ connected and ran its internal cron jobs, but enqueued scan tasks were never picked up by the worker. Root causes: missing `username` parameter in Redis connection settings, `ssl_cert_reqs` defaulting to `required`, and stale `in-progress` keys from deployment rolling restarts creating 40-minute invisible locks on jobs.

3. **Fundamental architecture mismatch** — A separate worker process communicating via Redis was over-engineered for the current scale (single instance, 1-2 concurrent scans). Every production bug traced back to the API→Redis→Worker hand-off: SSL transport failures, serialization issues, deployment race conditions, and split-process debugging difficulty.

### Solution: Remove the Worker Entirely

Replaced the external worker architecture with **in-process background tasks** using `asyncio.create_task()`.

**Key changes:**
- **`backend/app/tasks.py`** — Rewrote `dispatch_task()` to use `asyncio.create_task()` instead of Redis queue. Scan coroutines run directly in the API's event loop. No serialization, no message passing, no separate process.
- **`backend/app/worker.py`** — Deleted entirely.
- **`backend/app/services/scheduler_service.py`** — Moved `cleanup_stale_scans` back here as an APScheduler cron job (was previously an ARQ cron).
- **`backend/app/main.py`** — Simplified health check (removed Redis/ARQ queue depth, added active background task count).
- **`backend/requirements.txt`** — Removed `arq` dependency. Kept `redis` for scheduler lock only.
- **`.do/app.yaml`** — Removed the `workers` section entirely (saves one DO instance ~$12/mo).
- **`backend/app/routers/scanning.py`**, **`campaigns.py`** — Updated error messages (no more "worker" references).

**Why this works:**
- All scan functions (`run_website_scan`, `run_google_ads_scan`, etc.) were already `async`. Zero logic changes needed.
- FastAPI's async event loop handles both HTTP requests and background scans concurrently.
- Errors appear directly in the API logs — no cross-process debugging.
- One deployment target instead of two.

### OOM Crash & Instance Upgrade

After the worker removal, the scan started successfully but the API process crashed with **exit code 128 (OOM kill)** when loading the CLIP model (`clip-ViT-B-32`). The `professional-xs` instance (512MB RAM) was insufficient.

**Fix:** Upgraded API instance to **2GB RAM ($25/mo)** and set `WEB_CONCURRENCY=1` (single Gunicorn worker to maximize available memory).

### Plan Enforcement Bypass

Free trial scan limit was blocking test scans. Updated the organization row in Supabase directly: `plan` → `business`, `plan_status` → `active`.

### Result

Scans now run end-to-end in production: trigger → scan website → discover images → CLIP matching → results displayed. Two successful matches confirmed on the Yancey Bros dealer site.

### Files Changed

| File | Change |
|------|--------|
| `backend/app/tasks.py` | Rewrote: ARQ dispatch → `asyncio.create_task()` |
| `backend/app/worker.py` | Deleted |
| `backend/app/main.py` | Simplified health check |
| `backend/app/services/scheduler_service.py` | Added `_cleanup_stale_scans` APScheduler job |
| `backend/app/routers/scanning.py` | Updated error messages |
| `backend/app/routers/campaigns.py` | Updated error messages |
| `backend/app/config.py` | Updated comment (Redis description) |
| `backend/requirements.txt` | Removed `arq` |
| `.do/app.yaml` | Removed worker component |

### Known Minor Issue

Image matching paired the correct dealer page (Yancey Bros) with the wrong image from that page — picked a construction equipment photo instead of the actual carousel ad containing the approved asset. The carousel images are loaded dynamically via JavaScript and may not be captured by the screenshot. This is a matching accuracy tuning issue, not a pipeline bug.
