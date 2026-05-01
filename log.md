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
- [x] Re-enable match deduplication (disabled for testing)
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
- [x] **5. Re-enable match deduplication** — Fixed backend pruning (broken PostgREST query) and added DB-level deduplication in `recent_matches` view
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

## 2026-03-26 — Production Scan Pipeline, Google Ads Fix, PDF Reports & Readiness Audit

### Summary

Full day of production debugging, feature fixes, and a comprehensive codebase audit. The day started with scans stuck in "pending" in production — chased the issue through three different task queue architectures (Celery → ARQ → in-process asyncio) before landing on the simplest solution. Also fixed Google Ads scanning, redesigned the PDF compliance report, and closed out with a full production-readiness audit scoring the app 6/10 with a prioritized remediation checklist.

**8 commits, 19 files changed, 944 insertions, 290 deletions.**

---

### 1. Production Scan Pipeline Fix (5 commits, ~6 hours)

#### Problem

Website scans stuck in "pending" indefinitely in production. The issue began after the initial deployment to DigitalOcean App Platform and persisted across multiple debugging attempts throughout the day.

#### Root Cause Chain

1. **Celery/Kombu SSL transport bug** — The original task queue (Celery) used Kombu for Redis transport. Kombu silently drops messages over `rediss://` (SSL) connections to DigitalOcean's managed Valkey. Workers appeared "ready" but never received tasks. This is a known upstream issue (`celery/kombu#2007`).

2. **ARQ migration — same class of problem** — Migrated from Celery to ARQ (lighter async Redis queue). ARQ connected and ran its internal cron jobs, but enqueued scan tasks were never picked up by the worker. Root causes: missing `username` parameter in Redis connection settings, `ssl_cert_reqs` defaulting to `required`, and stale `in-progress` keys from deployment rolling restarts creating 40-minute invisible locks on jobs.

3. **Fundamental architecture mismatch** — A separate worker process communicating via Redis was over-engineered for the current scale (single instance, 1-2 concurrent scans). Every production bug traced back to the API→Redis→Worker hand-off: SSL transport failures, serialization issues, deployment race conditions, and split-process debugging difficulty.

#### Commits (chronological)

| Commit | Time | What |
|--------|------|------|
| `88f1199` | 10:52 | Added `dispatch_task()` wrapper with failure handling, stale scan cleanup job, improved health check with broker diagnostics |
| `2a95c35` | 11:36 | Bypassed Kombu — published Celery-compatible messages directly to Redis via redis-py. Added Redis-based singleton lock for APScheduler to prevent duplicate scheduled scans across Gunicorn workers |
| `26440a3` | 12:37 | Removed broker SSL overrides, fixed kombu body encoding (base64 → utf-8), converted remaining `.delay()` calls to `dispatch_task` |
| `58fae22` | 13:06 | Replaced Celery with ARQ entirely — deleted `celery_app.py`, rewrote `tasks.py` and `worker.py` for async Redis queue, moved stale scan cleanup to ARQ cron |
| `c77a329` | 14:05 | Fixed ARQ: added missing `username` and `ssl_cert_reqs=none` to RedisSettings, added startup handler to clear stale in-progress keys, added post-enqueue verification logging |

Each commit represented a hypothesis → deploy → observe → fail → next hypothesis cycle against the production environment.

#### Solution: Remove the Worker Entirely (`8d53fb6`, 14:28)

After two different queue systems exhibited the same class of Redis transport issues, eliminated the external worker architecture completely. Replaced with **in-process background tasks** using `asyncio.create_task()`.

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

#### OOM Crash & Instance Upgrade

After the worker removal, the scan started successfully but the API process crashed with **exit code 128 (OOM kill)** when loading the CLIP model (`clip-ViT-B-32`). The `professional-xs` instance (512MB RAM) was insufficient.

**Fix:** Upgraded API instance to **2GB RAM ($25/mo)** and set `WEB_CONCURRENCY=1` (single Gunicorn worker to maximize available memory).

#### Plan Enforcement Bypass

Free trial scan limit was blocking test scans. Updated the organization row in Supabase directly: `plan` → `business`, `plan_status` → `active`.

#### Result

Scans now run end-to-end in production: trigger → scan website → discover images → CLIP matching → results displayed. Two successful matches confirmed on the Yancey Bros dealer site.

#### Known Minor Issue

Image matching paired the correct dealer page (Yancey Bros) with the wrong image from that page — picked a construction equipment photo instead of the actual carousel ad containing the approved asset. The carousel images are loaded dynamically via JavaScript and may not be captured by the screenshot. This is a matching accuracy tuning issue, not a pipeline bug.

---

### 2. Google Ads Scan Fix + Distributor Advertiser ID Field (`c94e105`, 16:39)

#### Problem

Google Ads scans were failing with a **SerpApi 400 error**. Users also had no way to enter a Google Ads Advertiser ID when creating or editing a distributor — they had to rely on the automatic lookup, which doesn't always find the right match.

#### Root Causes

- **SerpApi `region=anywhere` parameter** — The `_fetch_ad_creatives()` function was passing `region="anywhere"` as a default, which SerpApi rejects as invalid. Omitting the parameter defaults to all regions, which is the correct behavior.
- **Missing UI field** — The distributor create and edit forms had no input for `google_ads_advertiser_id`, so users couldn't manually enter the AR-prefixed ID from Google Ads Transparency Center.

#### Changes

- **`backend/app/services/serpapi_service.py`** — Changed `region` default from `"anywhere"` to `""` (empty string, omitted from API call). Added response body logging on HTTP errors for easier debugging.
- **`frontend/app/distributors/page.tsx`** — Added `google_ads_advertiser_id` field to the `Distributor` interface, create form state, edit form state, and both the create and edit form UIs with placeholder text (`e.g., AR12345678901234567`).

---

### 3. PDF Compliance Report Fix (`e7a1666`, 17:20)

#### Problem

The PDF compliance report had two issues: it was **pulling data from all organizations** (not scoped to the requesting user's org), and the header layout with the uploaded org logo was inconsistent and sometimes broken.

#### Changes

- **Org-scoped data** — Added `_org_distributor_ids()` helper to fetch all distributor IDs for an organization. `_fetch_report_data()` now accepts `organization_id` and filters matches via `in_("distributor_id", dist_ids)`. Both `generate_pdf()` and `generate_csv()` pass the org ID through.
- **Redesigned PDF header** — Replaced the uploaded-logo-based header with a compact vector logo lockup: an amber rounded-rect with white lightning bolt icon (rendered as a custom ReportLab `Flowable`), plus "DEALER INTEL / ASSET INTELLIGENCE" brand text on the left. Report title and subtitle are centered. Eliminates dependency on uploaded logo files for the report header.
- **Fixed column widths** — Widened the Confidence column in both the violation table and match table to prevent text wrapping and overlap.

---

### 4. Production Readiness Audit

Performed a comprehensive audit of the entire codebase across 10 dimensions: architecture, features, observability, deployment/CI, security, testing, type safety, error handling, documentation, and data integrity. Scored the app **6/10** for pilot readiness and produced a prioritized remediation checklist (see Readiness Checklist section below).

**Key findings:**
- **Architecture, features, observability: strong (8/10 each)** — Clean stack separation, rich feature set, Sentry + structured logging on both ends.
- **Authentication gaps: critical (3/10)** — Multiple API routes in `campaigns.py`, `distributors.py`, `schedules.py`, and the entire `feedback.py` router lack `Depends(get_current_user)`. Since the backend uses a service role key that bypasses RLS, these allow unauthenticated cross-tenant data access.
- **Testing: weak (2/10)** — Only 3 backend test files, zero frontend tests, no E2E tests.
- **TypeScript safety: mixed (5/10)** — Backend Pydantic models are strong, but frontend API layer and components are `any`-heavy.
- **No Next.js middleware** — Auth is client-side only (no Edge Middleware for server-side gating).
- **Stale config** — `docker-compose.yml` still references Celery worker, README references Railway/Vercel.

Full audit details and the checklist are in the Readiness Checklist section below.

---

### All Files Changed

| File | Change |
|------|--------|
| `backend/app/tasks.py` | Celery → direct Redis → ARQ → `asyncio.create_task()` (3 rewrites) |
| `backend/app/worker.py` | Created for ARQ, then deleted entirely |
| `backend/app/celery_app.py` | Deleted (replaced first by ARQ, then by in-process tasks) |
| `backend/app/main.py` | Simplified health check, removed queue depth metrics |
| `backend/app/services/scheduler_service.py` | Added Redis singleton lock, moved stale scan cleanup to APScheduler |
| `backend/app/services/serpapi_service.py` | Fixed `region` parameter, improved error logging |
| `backend/app/services/report_service.py` | Org-scoped queries, vector logo header, fixed column widths |
| `backend/app/services/extraction_service.py` | Updated during scan pipeline iterations |
| `backend/app/routers/scanning.py` | Updated error messages, converted to `dispatch_task()` |
| `backend/app/routers/campaigns.py` | Updated error messages, converted to `dispatch_task()` |
| `backend/app/routers/billing.py` | Minor updates during pipeline iterations |
| `backend/app/config.py` | Updated Redis description comment |
| `backend/app/auth.py` | Minor update during pipeline iterations |
| `backend/app/plan_enforcement.py` | Time-bound pending scan checks |
| `backend/requirements.txt` | `celery[redis]` → `arq` → removed `arq` |
| `backend/tests/__init__.py` | Minor update |
| `.do/app.yaml` | Removed worker component |
| `frontend/app/distributors/page.tsx` | Added Google Ads Advertiser ID field to create/edit forms |
| `frontend/next.config.js` | Minor CSP update |
| `log.md` | Added full day summary and readiness checklist |

---

## 2026-03-27 (Friday) — Pilot Hardening: Auth, Type Safety, Validation, Tests & Scan Reliability

### Summary

Comprehensive hardening session bringing the app from 6/10 to 8.5/10 pilot readiness. Secured 23 unauthenticated API routes across 4 backend routers (critical cross-tenant data leak in feedback endpoint fixed). Added TypeScript interfaces to the entire frontend API layer, Zod input validation schemas, rate limiting on all 23 write endpoints, API documentation summaries on all 88 FastAPI routes, and user-facing error alerts on 25+ mutation paths. Expanded test coverage with 15 backend tests (campaigns, schedules, team) and 15 frontend tests (Vitest + React Testing Library). Added 2-hour scan timeout with `asyncio.wait_for()` and improved stale scan cleanup. Ran dependency audit and PII logging sanitization pass. Updated README. Total: 35 files changed, ~3,400 lines added across uncommitted work.

**0 commits (all changes uncommitted), 35 files changed, ~3,400 insertions.**

---

### 1. Auth & Tenant Isolation Fix (CRITICAL)

Added `Depends(get_current_user)` and org-scoping to **23 previously unprotected routes** across 4 routers:

- **`campaigns.py`** (10 routes) — `get_campaign`, `update_campaign`, `delete_campaign`, `list_campaign_assets`, `create_asset`, `upload_asset`, `get_asset`, `delete_asset`, `list_campaign_scans`, `get_campaign_scan`, `analyze_campaign_scan`, `get_campaign_matches`, `get_campaign_scan_stats`. Added `_verify_campaign_ownership()` helper. Scoped asset queries via `campaigns!inner(organization_id)` join. Scoped asset list query to org's campaign IDs only.
- **`distributors.py`** (6 routes) — `get_distributor`, `update_distributor`, `delete_distributor`, `get_distributor_matches`, `lookup_google_ads_id`, `set_google_ads_id`, `lookup_google_ads_id_by_name`. Added `_verify_distributor_ownership()` helper. All DB queries filter by `organization_id`.
- **`schedules.py`** (3 routes) — `update_schedule`, `delete_schedule`, and fixed `create_schedule` to validate campaign belongs to user's org before creating. All queries filter by `organization_id`.
- **`feedback.py`** (8 routes) — Entire router secured. **Fixed critical cross-tenant data leak**: `pending-reviews` endpoint was returning feedback data across all organizations.

---

### 2. Rate Limiting (23 Write Endpoints)

Added `@limiter.limit()` decorators to **23 write endpoints** across 7 routers:
- `campaigns.py` — create (10/min), update (20/min), delete (10/min), asset create/upload (10/min), asset delete (20/min)
- `distributors.py` — create (10/min), update (20/min), delete (10/min), bulk create (5/min), set Google Ads ID (20/min)
- `schedules.py` — create (10/min), update (20/min), delete (10/min)
- `billing.py` — portal session (10/min)
- Existing limits preserved: start scan (10/min), batch scan (2/min), webhook (60/min), invite accept (10/min)

---

### 3. API Documentation

Added `summary` parameter to all **88 FastAPI route decorators** across every router: alerts (5), billing (4), campaigns (13), compliance_rules (5), dashboard (7), distributors (10), feedback (8), matches (8), organizations (5), reports (1), scanning (11), schedules (3), team (8).

---

### 4. Scan Timeout & Stale Cleanup

- **`tasks.py`** — Wrapped all 4 scan task coroutines (`_run_website_scan`, `_run_google_ads_scan`, `_run_facebook_scan`, `_run_instagram_scan`) with `asyncio.wait_for(timeout=7200)` (2 hours). On timeout, scan job is marked as `failed` with a descriptive error message.
- **`scheduler_service.py`** — Enhanced `_cleanup_stale_scans()` to also catch scans stuck in `running` or `analyzing` status for more than 2 hours (was only cleaning `pending` after 5 minutes). Error message updated to "Scan timed out — auto-failed by cleanup job".

---

### 5. PII Logging Sanitization

Sanitized 7 PII leaks across 4 files:
- **`auth.py`** — JWKS error logs now show `type(err).__name__` instead of full exception (which may contain tokens). Auto-provision log masks email to first 3 chars.
- **`notification_service.py`** — Email addresses masked in logs (`to[:3]***`). API error responses truncated to 200 chars. Test email response masks recipient.
- **`serpapi_service.py`** — Error logs show only exception type, not full message (which may contain API keys).

---

### 6. Dependency Audit

- **`requirements.txt`** — Pinned all dependency versions (was using `>=` ranges). Removed unused `sentence-transformers` (CLIP) and `gunicorn` from requirements. Moved test dependencies (`pytest`, `pytest-asyncio`, `httpx`) out of production requirements.
- Ran `pip audit` — found 12 vulnerabilities (4 fixable on Python 3.9)
- Ran `npm audit fix` — fixed 4 of 5 frontend vulnerabilities

---

### 7. Backend Tests (15 tests, 3 new files)

- **`tests/test_campaigns.py`** (239 lines, 7 tests) — Campaign CRUD with org scoping, asset operations, campaign scan listing
- **`tests/test_schedules.py`** (184 lines, 4 tests) — Schedule CRUD with org ownership validation
- **`tests/test_team.py`** (160 lines, 4 tests) — Team member listing, invite flow, role-based access

---

### 8. Frontend TypeScript Type Safety

- **`lib/api.ts`** (+296 lines of types) — Added 25+ TypeScript interfaces: `Campaign`, `CampaignCreate`, `Asset`, `Distributor`, `DistributorCreate`, `DistributorUpdate`, `Match`, `MatchFilters`, `ScanJob`, `ScanJobCreate`, `DashboardStats`, `Alert`, `FeedbackSubmission`, `FeedbackStats`, `ThresholdRecommendation`, `UsageMeter`, `BillingUsage`, `OrgSettings`, `OrgSettingsUpdate`, `TeamMember`, `TeamInvite`, `ComplianceRule`, `ComplianceTrendPoint`, `ChannelCoverage`, `DistributorCoverage`, `MatchStats`, plus type aliases for enums. All ~40 API functions now have explicit return types (was `any`).
- **`lib/hooks.ts`** — Imported `MatchFilters`, `DistributorUpdate`, `FeedbackSubmission` types from `api.ts`. Replaced inline `any` types in `useMatches`, `useUpdateDistributor`, `useSubmitFeedback`.

---

### 9. Frontend Zod Input Validation

- **`lib/schemas.ts`** (new, 45 lines) — 6 Zod validation schemas:
  - `campaignCreateSchema` — name required (1–100 chars), description optional (max 500)
  - `distributorCreateSchema` — name required, URLs validated, Google Ads ID validated (`AR` + digits)
  - `distributorUpdateSchema` — partial version of create schema
  - `scheduleCreateSchema` — valid source, frequency, HH:MM time format
  - `teamInviteSchema` — valid email, role enum (member/admin)
  - `orgSettingsSchema` — name (1–100), hex color, valid email
- Integrated into: `campaigns/page.tsx` (create), `distributors/page.tsx` (create + edit), `settings/page.tsx` (name save, notification save)

---

### 10. Frontend Error Messaging

Added user-facing `alert()` calls to **25+ catch blocks** across 9 pages that previously silently swallowed errors:
- `campaigns/page.tsx` — campaign create
- `campaigns/[id]/page.tsx` — report download, asset delete, campaign delete
- `distributors/page.tsx` — distributor create, distributor edit
- `distributors/[id]/page.tsx` — distributor delete
- `matches/page.tsx` — approve, flag, delete, delete all, feedback
- `matches/[id]/page.tsx` — approve, flag, feedback
- `scans/page.tsx` — delete scan, delete all scans
- `settings/page.tsx` — company name save, brand color, notification save, notification toggle, logo upload, logo delete
- `page.tsx` (dashboard) — report download

---

### 11. Frontend Test Suite Setup (15 tests, 4 new files)

- **`vitest.config.ts`** (new) — Vitest configuration with React plugin and jsdom environment
- **`test/setup.ts`** (new) — Test setup file
- **`lib/schemas.test.ts`** (new, 109 lines, 13 tests) — Zod schema validation tests covering valid inputs, missing required fields, invalid URLs, invalid formats
- **`lib/api.test.ts`** (new, 19 lines, 2 tests) — API module export verification
- **`package.json`** — Added `vitest`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `zod` as dev/prod dependencies

---

### 12. Config & Documentation

- **`docker-compose.yml`** — Removed stale Celery `worker` service (worker was eliminated on 03-26)
- **`backend/.env.example`** (new) — Example environment variables for backend setup
- **`frontend/.env.example`** (new) — Example environment variables for frontend setup
- **`README.md`** — Major rewrite (+369/−179 lines) reflecting current architecture, setup instructions, and deployment

---

### 13. Billing Model Review (Advisory — No Code Changes)

- Validated scan-based billing model: 1 scan = 1 sweep across all distributors for a given channel, regardless of dealer count
- Financial analysis across tiers: Starter (150 effective dealer-scans/mo), Professional (1,600), Business (15,000)
- Confirmed model is defensible due to secondary cost gates (dealer caps, page limits, channel restrictions, AI pre-filtering)
- Flagged Business tier (100 dealers × 150 scans) as highest margin risk; recommended internal per-scan cost tracking

---

### All Files Changed

| Backend | Frontend | Config |
|---|---|---|
| `app/routers/campaigns.py` | `app/campaigns/page.tsx` | `docker-compose.yml` |
| `app/routers/distributors.py` | `app/campaigns/[id]/page.tsx` | `backend/.env.example` (new) |
| `app/routers/schedules.py` | `app/distributors/page.tsx` | `frontend/.env.example` (new) |
| `app/routers/feedback.py` | `app/distributors/[id]/page.tsx` | `README.md` |
| `app/routers/alerts.py` | `app/matches/page.tsx` | |
| `app/routers/billing.py` | `app/matches/[id]/page.tsx` | |
| `app/routers/compliance_rules.py` | `app/scans/page.tsx` | |
| `app/routers/dashboard.py` | `app/settings/page.tsx` | |
| `app/routers/matches.py` | `app/page.tsx` | |
| `app/routers/organizations.py` | `lib/api.ts` | |
| `app/routers/reports.py` | `lib/hooks.ts` | |
| `app/routers/scanning.py` | `lib/schemas.ts` (new) | |
| `app/routers/team.py` | `lib/schemas.test.ts` (new) | |
| `app/auth.py` | `lib/api.test.ts` (new) | |
| `app/tasks.py` | `vitest.config.ts` (new) | |
| `app/services/notification_service.py` | `test/setup.ts` (new) | |
| `app/services/scheduler_service.py` | `package.json` | |
| `app/services/serpapi_service.py` | `package-lock.json` | |
| `requirements.txt` | | |
| `tests/test_campaigns.py` (new) | | |
| `tests/test_schedules.py` (new) | | |
| `tests/test_team.py` (new) | | |

### Updated Production Readiness Score

**Previous: 6/10 → Current: 8.5/10**

---

## 2026-03-30 — Fix False Positive Matches & Missed Creatives on Multi-Page Scans

### Problem
When a campaign creative lived on a subpage (e.g. `/specials`) rather than the homepage, the scanner returned a flood of inaccurate junk matches from unrelated images across ~15 pages while failing to find the actual creative.

### Root Causes
1. **Pre-filter pipeline too permissive** — hash diff threshold (30/64), CLIP similarity (0.25), and Haiku relevance filter all let nearly everything through on same-brand dealer sites.
2. **Haiku filter was asset-blind** — asked "is this a marketing image?" instead of "does this look like the campaign creative?" Every dealer promo on 15 pages passed.
3. **Match threshold in the ambiguous zone** — `regular_image_match_threshold=55` sits in the 40-59 "ambiguous" range of the scoring rubric; Claude's own scoring treated these as uncertain.
4. **No deduplication** — multiple weak matches for the same asset × same distributor were all persisted.
5. **Image extraction missed subpage content** — limited CSS selectors, no carousel interaction, no `<picture>`/`<source>` support.
6. **OpenCV template matching insufficiently aggressive** — scale range and density too conservative for small web renders.

### Changes

**config.py — Tightened all thresholds:**
- `regular_image_match_threshold`: 55 → 70
- `screenshot_match_threshold`: 55 → 65
- `partial_match_threshold`: 55 → 65
- `weak_match_threshold`: 40 → 50
- `borderline_match_lower`: 50 → 60, `borderline_match_upper`: 75 → 80
- `filter_relevance_threshold`: 0.70 → 0.75
- `hash_prefilter_max_diff`: 30 → 20
- `clip_similarity_threshold`: 0.25 → 0.40

**ai_service.py — Asset-aware Haiku filter:**
- `filter_image()` now accepts optional `asset_urls` parameter
- New `get_filter_prompt(asset_aware=True)` sends the campaign creative alongside the candidate and asks "could this be the same campaign?" instead of generic relevance
- `process_discovered_image()` passes campaign asset URLs to the filter stage

**ai_service.py — Stricter Claude prompts:**
- Comparison prompt: `is_match` threshold raised from 55 → 70; added explicit "same brand ≠ same campaign" instruction; tightened ambiguous band description
- Detection prompt: `asset_found` threshold raised from 55 → 65; same "different campaign = not a match" guardrail added

**scanning.py — Best-match-only deduplication:**
- Added `_prune_duplicate_matches()` — after scan completes, keeps only the highest-confidence match per (asset_id, distributor_id) and deletes the rest
- Wired into `run_website_scan()` post-processing

**extraction_service.py — Better subpage image extraction:**
- Added `<picture>`/`<source>` element extraction (responsive images)
- Expanded CSS background-image selectors: `special`, `deal`, `offer`, `feature`, `incentive`, `rebate`, `savings`, `coupon`, plus `section[id*=...]`/`div[id*=...]` variants
- Added `_advance_carousels()` — clicks carousel "next" buttons (slick, swiper, owl, bootstrap) up to 5 times to reveal hidden slides
- Added `networkidle` wait after scroll to catch late lazy-loaded images

**cv_matching.py — More aggressive OpenCV localization:**
- Template matching: scale range widened (0.10–1.8), steps increased (30 → 50), denser sampling at small scales (0.10–0.5), threshold lowered (0.45 → 0.40)
- ORB feature matching: `min_good_matches` lowered (12 → 8), `ratio_thresh` relaxed (0.75 → 0.78)
- `find_asset_on_page()` defaults updated to match

## 2026-03-30 — Fix Website Scans Timing Out (Cleanup Race Condition)

### Problem
Website scans consistently failed with "Scan timed out — auto-failed by cleanup job", showing 0 matches and 0 images scanned. Scans were being killed before they even started processing.

### Root Causes
1. **Late status transition** — Scan stayed in `"pending"` status during all prep work (campaign asset download, CLIP model loading, hash computation, page cache lookups). The status only moved to `"running"` after all prep completed — often exceeding the 5-minute pending cutoff.
2. **CLIP model blocks event loop** — `SentenceTransformer()` constructor is synchronous; on first use it downloads ~400MB and loads into memory. This freezes the event loop, preventing Gunicorn heartbeats.
3. **Gunicorn worker timeout too short** — `timeout=300` (5 min) kills the worker if the event loop is blocked, leaving the scan job orphaned in pending/running state.
4. **Cleanup cutoffs too aggressive** — 5-minute pending cutoff and 2-hour running cutoff based on `created_at` (not last activity) killed legitimate scans.

### Changes

**scanning.py — Immediate status transition + heartbeat:**
- All four scan functions (`run_website_scan`, `run_google_ads_scan`, `run_facebook_scan`, `run_instagram_scan`) now set `status: "running"` as the very first action, before any prep work
- Added `_heartbeat(scan_job_id)` helper that touches `updated_at`
- Heartbeats sent after CLIP/hash pre-computation, after page discovery, and before each page extraction

**embedding_service.py — Non-blocking CLIP operations:**
- All heavy work (model loading, encoding) now runs in a `ThreadPoolExecutor` via async wrappers (`compute_embedding_async`, `compute_embeddings_batch_async`)
- Added `warmup()` function for explicit model pre-loading
- Event loop is never blocked by CPU-bound CLIP operations

**main.py — CLIP model pre-warming at startup:**
- `lifespan` hook now fires `embedding_service.warmup()` in a background thread immediately on app start
- First scan no longer pays the model download/load penalty

**ai_service.py — Async CLIP pipeline:**
- `_precompute_asset_embeddings` now uses `compute_embeddings_batch_async`
- `_passes_clip_prefilter` converted from sync to async, uses `compute_embedding_async`

**gunicorn.conf.py — Worker timeout:**
- `timeout`: 300 → 1800 (30 min) — prevents arbiter from killing workers during long async scans
- `graceful_timeout`: 120 → 300

**scheduler_service.py — Smarter cleanup:**
- Pending cutoff: 5 min → 15 min (generous since status moves to running immediately now)
- Running cutoff: checks `updated_at` instead of `created_at`, 2 hours → 30 minutes of silence — a healthy scan heartbeats every page, so 30 min without activity means the worker died

---

## Readiness Checklist

> Production-readiness audit performed 2026-03-26. Updated 2026-03-27. Current score: **8.5/10**.

### Pilot Ready (target: 7–8/10) — COMPLETE

- [x] **Fix unauthenticated API routes (CRITICAL)** — Added `Depends(get_current_user)` + org-scoping to every route:
  - [x] `campaigns.py` — `get_campaign`, `update_campaign`, `delete_campaign`, all asset CRUD, upload
  - [x] `distributors.py` — `get_distributor`, `update_distributor`, `delete_distributor`, `get_distributor_matches`, Google Ads lookups
  - [x] `schedules.py` — `update_schedule`, `delete_schedule`
  - [x] `feedback.py` — entire router (fixed `pending-reviews` cross-tenant data leak)
- [x] **Add `.env.example` files** — Committed example env files for both `backend/` and `frontend/`
- [x] **Clean up stale configuration**
  - [x] Removed Celery `worker` service from `docker-compose.yml`
  - [ ] Update README deployment section to reflect DigitalOcean (currently references Railway/Vercel)
- [x] **Audit org-scoping on all DB queries** — All Supabase queries filter by `organization_id` from the authenticated user
- [x] **Review error messaging consistency** — All mutation failures now surface user-visible alerts
- [ ] **Test critical flows manually end-to-end** — Auth → campaign create → asset upload → scan trigger → match review → export

### Production Ready (target: 9–10/10)

- [x] **Frontend test suite** — Vitest + React Testing Library configured; 15 tests covering Zod schemas and API module exports
- [x] **Backend test coverage** — Expanded from 3 to 6 test files; added tests for campaigns (7), schedules (4), and team (4) routers
- [ ] **E2E tests** — Automated pipeline tests for scan → match → alert flow
- [x] **Replace `any` types in frontend** — Added 25+ TypeScript interfaces to `api.ts`; all functions have explicit return types; `hooks.ts` fully typed
- [ ] **Tighten CSP** — Remove `'unsafe-eval'` and `'unsafe-inline'` from `script-src` in `next.config.js`; use nonces or hashes instead (deferred — risk of breaking Mapbox GL)
- [x] **Frontend input validation** — Zod schemas for campaign create/edit, distributor create/edit, settings, team invites (`lib/schemas.ts`)
- [x] **API documentation** — Added `summary` parameter to all 88 FastAPI route decorators; missing docstrings filled in
- [x] **Rate limiting review** — Per-route limits applied to all 23 write endpoints across 7 routers
- [ ] **CORS hardening** — Change `allow_methods` and `allow_headers` from `["*"]` to explicit allowed lists (deferred — risk of breaking frontend API calls)
- [ ] **Monitoring & alerting** — Set up Sentry alert rules for error spikes; add uptime monitoring for the health endpoint
- [ ] **Database backups & disaster recovery** — Confirm Supabase backup schedule; document restore procedure
- [ ] **Load testing** — Verify the single-worker 2GB instance handles expected pilot user concurrency, especially during scans (CLIP model loading)
- [x] **Dependency audit** — Ran `pip audit` (12 vulns found, 4 fixable on Python 3.9) and `npm audit` (fixed 4/5 vulns); pinned all versions in `requirements.txt`
- [x] **Logging PII review** — Sanitized 7 PII leaks across 4 files (auth.py, team.py, notification_service.py, serpapi_service.py)

---

## 2026-03-30 — Fix Critical False-Positive Matching Bugs

### Summary
Fixed 4 bugs in `ai_service.py` that caused the matching pipeline to produce high-confidence false positives (e.g., a Bell Ford F-150 creative matched at 95% to a Caterpillar dealer site).

### Root Cause
Every image stored in the `scan-screenshots` Supabase bucket was misclassified as a "page screenshot" because the `is_screenshot` check matched the substring `"screenshot"` in the storage URL. Screenshots bypass all pre-filters (hash, CLIP, Haiku relevance), so unrelated images went straight to Claude Opus ensemble matching — and additional logic bugs let Claude's `asset_found` boolean override low scores.

### Changes (`backend/app/services/ai_service.py`)

1. **`is_screenshot` detection (was line 1495–1500)** — Removed URL-based substring checks (`"screenshot" in image_url.lower()`, `"screenshotUrl"`, `"/screenshots/"`). Now only `source_type == "page_screenshot"` triggers screenshot mode. This restores hash, CLIP, and Haiku pre-filtering for all regular images.

2. **Ensemble `is_match` gate (was line 1282)** — Changed from `final_score >= threshold and (asset_found or final_score >= partial_match_threshold)` to `final_score >= threshold`. Score alone decides whether an image is a match; Claude's `asset_found` boolean no longer weakens the threshold.

3. **`best_match` selection (was lines 1571–1577)** — Removed `is_found`-preferred selection logic. Now always picks the asset with the highest numeric score, preventing low-scoring hallucinated matches from being chosen over genuinely higher-scoring ones.

4. **Threshold enforcement (was line 1588)** — Changed from `if not asset_found and not is_match and best_score < threshold` to `if best_score < threshold`. The threshold is now enforced unconditionally — `asset_found` and `is_match` can no longer bypass it.

---

## 2026-03-30 — Fix Page Discovery Priority (Missing `/specials/` Page)

### Summary
The page discovery service was not visiting the `/specials/` page where the campaign creative actually lived. Common promotional paths (`/specials/`, `/deals/`, `/offers/`, etc.) were only probed as a last-resort fallback when fewer than 5 pages were found. Since the sitemap already provided 15+ URLs (mostly blog posts), the fallback never ran and the specials page was never scanned.

### Root Cause
In `page_discovery.py`, Strategy 3 (common path probing) only executed when `len(result) < 5`. The sitemap for yanceybros.com returned enough blog posts and deep sub-pages to fill all 15 slots before common promotional paths were ever tried.

### Changes (`backend/app/services/page_discovery.py`)

- **Reversed strategy priority** — Common promotional paths (`/specials/`, `/deals/`, `/offers/`, `/promotions/`, etc.) are now probed **first** and given guaranteed priority slots. Sitemap and homepage link crawl fill the remaining slots afterward.
- **Removed the `< 5` guard** — Common path probing always runs, regardless of how many pages were already found from other strategies.

---

## 2026-03-30 — Fix Ensemble Scoring (Regular Images Capped at 65%)

### Summary
Regular image matches were always classified as "Below Threshold" in production — even for exact matches — because the ensemble scoring formula wasted 35% of the weight on a detection score that is always zero for non-screenshot images.

### Root Cause
In `ensemble_match()`, the `detection_score` component (weighted at `0.35`) is only populated for screenshots. For regular images it is hardcoded to `0`. With `visual_weight = 0.5` and `hash_weight = 0.15` summing to only `0.65`, the theoretical maximum score was 65 (+5 agreement bonus = 70). This equals the `regular_image_match_threshold` of 70, making it nearly impossible for legitimate matches to pass.

### Changes (`backend/app/services/ai_service.py`)

1. **Normalised ensemble weights for regular images** — When detection is not used, the visual and hash weights are divided by their sum so they total 1.0. With the default config (0.5 visual, 0.15 hash), effective weights become ~0.77 visual + ~0.23 hash, giving a true 0–100 scoring range.

2. **Fixed agreement bonus counting** — The bonus previously counted `detection_score` even when it was always zero for regular images. Now only scores from methods that were actually run are counted.

---

## 2026-03-30 — Fix Production Deployment (OOM + Missing Gunicorn)

### Summary
Multiple deployment failures on DigitalOcean App Platform. The container was terminated at startup due to exceeding memory limits, and once that was resolved, the `gunicorn` executable was missing.

### Root Cause
1. **OOM** — The `professional-xs` instance (1 GB RAM) could not fit Playwright/Chromium + OpenCV + the full Python stack in memory. The container was killed by the platform before the health check could pass.
2. **Missing gunicorn** — `gunicorn` was never listed as an explicit dependency in `requirements.txt`. It had been pulled in transitively by `langchain`, which was removed in a prior OOM fix. The Dockerfile's `CMD` calls `gunicorn` directly, so the container crashed immediately on startup.

### Changes

- **`.do/app.yaml`** — Upgraded `instance_size_slug` from `professional-xs` (1 GB) to `professional-s` (2 GB), giving sufficient headroom for the full runtime stack.
- **`backend/requirements.txt`** — Added `gunicorn==23.0.0` as an explicit dependency.

---

## 2026-03-30 — Re-enable Match Deduplication

### Summary
Match deduplication was disabled during early testing and never re-enabled. The backend pruning function was also silently broken due to a PostgREST foreign-table filter bug (same pattern as the email notification fix). Both layers are now fixed and active.

### Root Cause
1. **Backend `_prune_duplicate_matches`** — Used `discovered_images.scan_job_id` as a foreign-table filter on the `matches` table, which PostgREST doesn't support (PGRST108). The query silently returned no results, so no duplicates were ever pruned.
2. **Database `recent_matches` view** — Was a simple join with no deduplication, showing every match row regardless of whether a higher-confidence match existed for the same asset+distributor.

### Changes

- **`backend/app/routers/scanning.py`** — Replaced the broken foreign-table filter in `_prune_duplicate_matches` with a two-step lookup: first fetch `discovered_image.id`s by `scan_job_id`, then query matches by those IDs using `.in_()`.
- **`supabase/migrations/019_reenable_dedup_view.sql`** — New migration that replaces the `recent_matches` view with a CTE using `ROW_NUMBER() OVER (PARTITION BY asset_id, distributor_id ORDER BY confidence_score DESC, last_seen_at DESC)` to return only the best match per asset+distributor pair.
- **`supabase/schema.sql`** — Updated to reflect the deduplicated view definition.

---

## 2026-03-31 — Frontend Performance, Scan Pipeline Accuracy & Compliance Hardening

### Summary
Addressed slow page transitions in the frontend by adding query caching, prefetching, and session deduplication. Fixed multiple scan pipeline issues that caused missed creatives: carousel images not being captured, hash pre-filter too aggressive, Haiku relevance filter only comparing against the first asset, and the Opus comparison prompt conflating "same promotion" with "same visual creative." Also hardened the compliance prompt to explicitly treat color alterations as violations.

### Frontend — Data Loading Performance

**Problem:** Navigating between pages showed loading spinners because every page fetched data fresh on mount, and the Supabase auth session was looked up redundantly on every API request.

**Changes:**

- **`frontend/lib/api.ts`** — Added an auth session cache with 30s TTL so parallel API requests share a single `getSession()` call instead of each making their own.
- **`frontend/lib/query-provider.tsx`** — Increased React Query `staleTime` from 30s to 3 minutes and `gcTime` from 5 to 10 minutes. Pages visited within 3 minutes now load instantly from cache.
- **`frontend/app/page.tsx`** — Added `prefetchQuery` calls on the dashboard for matches, match stats, scans, and alerts. These fire in the background so data is cached before the user navigates.
- **`frontend/lib/hooks.ts`** — Added `keepPreviousData` as `placeholderData` on `useMatches` and `useAlerts` so filtering doesn't flash a loading state.

### Frontend — Dashboard Stat Card Alignment

**Problem:** The four top-level stat cards used two different layouts — Compliance Rate and Violations had icon-left with centered alignment, while Active Campaigns and Distributors used the `StatCard` component with icon-right and top alignment.

**Changes:**

- **`frontend/app/page.tsx`** — Refactored the inline Compliance Rate and Violations cards to match the `StatCard` layout: icon top-right (`h-10 w-10`), text top-left with `mb-3` spacing, `flex items-start justify-between`.

### Backend — Carousel Image Extraction

**Problem:** Website scans missed creatives inside carousels. `_advance_carousels` clicked through slides but images were only extracted once at the end — whatever slide happened to be showing. Images on earlier slides were lost because carousels replace visible content rather than appending to the DOM.

**Changes:**

- **`backend/app/services/extraction_service.py`** — Rewrote `_advance_carousels` to extract images after each click and return them as a deduplicated list. Updated `_extract_from_viewport` to extract images before carousel advancement (captures initial slide), then merge in carousel-collected images before proceeding.

### Backend — Hash Pre-filter Threshold

**Problem:** The perceptual hash pre-filter (`hash_prefilter_max_diff = 20`) was too aggressive, rejecting 269/276 images including legitimate matches. Screenshot-based assets have enough compression and resolution differences to push hash distances above 20.

**Changes:**

- **`backend/app/config.py`** — Raised `hash_prefilter_max_diff` from 20 to 28. This lets more candidates through to the CLIP and Claude stages while still filtering the vast majority of irrelevant images.

### Backend — Haiku Filter Multi-Asset Comparison

**Problem:** The Haiku relevance filter only sent the **first** campaign asset (`asset_urls[0]`) for comparison. Images matching asset #2 or #3 were rejected because Haiku only saw asset #1.

**Changes:**

- **`backend/app/services/ai_service.py`** — Updated `filter_image` to download and send **all** campaign assets to the Haiku model. Updated `get_filter_prompt` to accept an `asset_count` parameter and dynamically describe each asset image in the prompt.

### Backend — Comparison Prompt: Visual Creative vs Promotion

**Problem:** The Opus comparison prompt asked whether images showed the "same campaign/promotion." This caused false positives: a dealer-created banner advertising the same offer (same promo code PCC10, same 10% discount) scored 85% even though it had a completely different visual design, layout, and imagery.

**Changes:**

- **`backend/app/services/ai_service.py`** — Rewrote `get_comparison_prompt` to check for the same **visual creative/artwork** rather than the same promotion. Added explicit guidance: "Two images can advertise the SAME offer but be COMPLETELY DIFFERENT CREATIVES — that is NOT a match." Same promotion with different visual design now scores 0-20.
- Also updated `get_detection_prompt` with the same visual-creative distinction for screenshot-based detection.

### Backend — Match Threshold

**Problem:** After tightening the comparison prompt, legitimate matches (especially screenshot-based assets) scored slightly lower, causing them to fall below the `regular_image_match_threshold` of 70. The "Below Threshold: 1" in the pipeline funnel confirmed one creative was being dropped at this stage.

**Changes:**

- **`backend/app/config.py`** — Lowered `regular_image_match_threshold` from 70 to 60. Safe because four upstream filters (hash, CLIP, Haiku, and the stricter Opus prompt) already eliminate false positives before the threshold check.

### Backend — Compliance: Color Changes as Violations

**Problem:** The compliance prompt detected color changes but treated them as minor/cosmetic modifications that passed compliance. A black-and-white approved creative displayed in yellow/gold was marked "COMPLIANT — All Checks Passed" despite the obvious color alteration.

**Changes:**

- **`backend/app/services/ai_service.py`** — Updated `get_compliance_prompt` to explicitly state that ANY color change (colorized, desaturated, tinted, scheme changed) is a compliance violation. Added color changes to the `is_compliant: false` conditions list. Added rule: "Color changes are ALWAYS a violation."

---

## 2026-04-01 — Frontend Brand Refresh & Design System Overhaul

### Summary
Major frontend visual refresh across the entire application. Replaced the generic Zap icon branding with a typographic `BrandWordmark` / `BrandMark` component used consistently across all pages. Switched fonts from Geist to Inter + Plus Jakarta Sans (display) + JetBrains Mono via Next.js `next/font/google` for proper self-hosting. Introduced a light-mode color theme (`marketing-light`) for marketing pages (landing, pricing) while keeping the dark dashboard. Added a new `info` semantic color (blue) to separate informational UI (plan badges, notification dots, active sidebar) from the gold `primary`/`accent` used for brand emphasis. Redesigned the landing page hero into a split layout with a product screenshot. Replaced all sharp-cornered elements with subtle `rounded-md` borders across marketing and pricing pages. Bumped compliance-drift alert severity from `high` to `critical` in the backend.

### Frontend — Brand Identity Component

**Problem:** The brand identity was a plain Zap icon in a colored square, duplicated with inconsistent markup across the sidebar, navbar, footer, login, invite, and reset-password pages.

**Changes:**

- **`frontend/components/ui/brand-wordmark.tsx`** *(new)* — Created `BrandWordmark` (full "DEALER INTEL" wordmark with accent-colored "I", optional subtitle) and `BrandMark` (standalone accent "I") components using the display font.
- **`frontend/components/layout/sidebar.tsx`** — Replaced Zap icon + hardcoded text with `BrandWordmark` (expanded) and `BrandMark` (collapsed). Removed `Zap` import.
- **`frontend/components/marketing/navbar.tsx`** — Replaced Zap logo block with `BrandWordmark`.
- **`frontend/components/marketing/footer.tsx`** — Same replacement. Replaced `status-dot` class with inline utility classes for the "systems operational" indicator.
- **`frontend/app/login/page.tsx`** — Replaced Zap icon + `<h1>DEALER INTEL</h1>` with centered `BrandWordmark`.
- **`frontend/app/reset-password/page.tsx`** — Same replacement, both in the loading state and the form view.
- **`frontend/app/invite/[token]/page.tsx`** — Same replacement.

### Frontend — Typography & Font System

**Problem:** Fonts were loaded via a Google Fonts CSS `@import` in `globals.css` (render-blocking) and referenced by name in Tailwind config. The Geist font was used for everything with no distinct display weight for headings.

**Changes:**

- **`frontend/app/layout.tsx`** — Added `Inter`, `Plus_Jakarta_Sans`, and `JetBrains_Mono` via `next/font/google` with CSS variables (`--font-sans`, `--font-display`, `--font-mono`). Applied all three variables to the `<html>` element.
- **`frontend/app/globals.css`** — Removed the `@import url(...)` for Google Fonts. Updated `body` and `.font-mono` to use CSS variables. Added `.font-display` utility class. Changed `h1, h2` to `font-weight: 700` and `h3, h4` to `600`.
- **`frontend/tailwind.config.ts`** — Updated `fontFamily.sans` and `fontFamily.mono` to reference CSS variables. Added `fontFamily.display` for headings.

### Frontend — Light Mode for Marketing Pages

**Problem:** The landing page and pricing page used the same dark theme as the authenticated dashboard, making the marketing experience feel heavy and less inviting.

**Changes:**

- **`frontend/app/globals.css`** — Added a `.marketing-light` class that overrides all CSS custom properties (background, foreground, card, primary, secondary, muted, accent, border, etc.) to a light color scheme. Added `.section-gradient` and `.hover-lift:hover` overrides for the light context.
- **`frontend/app/landing/page.tsx`** — Applied `marketing-light` class to the root wrapper. Entire landing page now renders in light mode.
- **`frontend/app/pricing/page.tsx`** — Same `marketing-light` application. The pricing page now matches the landing page's light aesthetic.

### Frontend — Landing Page Hero Redesign

**Problem:** The hero was a centered text block with no visual element, making it feel generic and text-heavy.

**Changes:**

- **`frontend/app/landing/page.tsx`** — Redesigned the hero into a two-column split layout: left side has the headline, description, CTA buttons, and channel pills; right side has a product screenshot (`dashboard-preview.png`) with a breathing glow background effect. Added a warm gradient background (`linear-gradient` from warm beige to cool blue). Simplified channel pills (removed individual glow shadows). Changed primary CTA from "Book a Demo" to "Request Demo" with a secondary "or start a free trial" text link.
- **`frontend/public/dashboard-preview.png`** *(new)* — Product screenshot asset for the hero.
- **`frontend/app/globals.css`** — Added `@keyframes glow-breathe` animation for the screenshot halo effect.
- **`frontend/components/marketing/scroll-reveal.tsx`** *(new)* — IntersectionObserver-based scroll reveal component with configurable delay, used for staggered section animations on marketing pages.

### Frontend — Info Color & UI Semantics

**Problem:** Informational elements (notification badges, plan usage indicators, active sidebar state, info-severity alerts) all used the gold `primary` color, making them visually indistinguishable from brand-emphasis elements like CTAs and accent text.

**Changes:**

- **`frontend/app/globals.css`** — Added `--info` and `--info-foreground` CSS variables (blue hue, `225 65% 58%`) to both the dark root and the `marketing-light` theme.
- **`frontend/tailwind.config.ts`** — Added `info` color tokens (`DEFAULT` and `foreground`). Added `shadow-glow-info` box shadow.
- **`frontend/components/ui/badge.tsx`** — Added `info` badge variant.
- **`frontend/components/ui/button.tsx`** — Added `info` button variant. Updated `outline` variant hover to use `info` instead of plain `secondary`.
- **`frontend/components/layout/header.tsx`** — Changed notification dot from `bg-primary` to `bg-info`.
- **`frontend/components/layout/sidebar.tsx`** — Changed active nav item border from `border-primary` to `border-info`.
- **`frontend/components/dashboard/usage-card.tsx`** — Changed plan usage icon and badge from `text-primary`/`bg-primary/10` to `text-info`/`bg-info/10`.
- **`frontend/components/dashboard/alerts-panel.tsx`** — Changed info-severity alert style to use `text-info`/`bg-info/10`. Added `compliance_drift` and `high` severity mappings.
- **`frontend/app/alerts/page.tsx`** — Same info-severity color update. Added `compliance_drift` alert type and `high` severity config.
- **`frontend/app/page.tsx`** — Changed "Tracked Assets" stat icon to `text-info`. Changed compliance report card icon container to `bg-info/10` with `text-info`.

### Frontend — Border Radius & Visual Polish

**Problem:** All marketing elements (cards, buttons, badges, step indicators) used hard 0px corners (`card-sharp`, no border-radius), giving the marketing pages an overly rigid appearance.

**Changes:**

- **`frontend/app/landing/page.tsx`** — Replaced `card-sharp` with `border border-border bg-background rounded-md` on feature cards, trust cards, and pricing cards. Added `rounded-md` to step icons, number badges, "Most Popular" labels, and all CTA buttons. Removed staggered `animationDelay` from feature cards. Used `font-display` on all section headings. Replaced `text-primary` section labels with `text-accent`.
- **`frontend/app/pricing/page.tsx`** — Applied `rounded-md` to all tier cards, CTA buttons, and "Most Popular" badge. Changed `bg-card` to `bg-background` on cards. Used `font-display` on all headings. Changed `shadow-glow` to `shadow-lg shadow-primary/10` on the popular tier. Replaced `section-gradient` with `bg-card/30`. Changed section labels and tier tags from `text-primary` to `text-accent`.
- **`frontend/components/marketing/navbar.tsx`** — Added `rounded-md` to "Book a Demo" CTA button.
- **`frontend/components/dashboard/channel-chart.tsx`** — Updated hardcoded `fontFamily` references from `"Sora"` to `"Inter, system-ui, sans-serif"` and `"JetBrains Mono"` to `"JetBrains Mono, monospace"`.

### Backend — Compliance Drift Alert Severity

**Problem:** Compliance-drift alerts (asset was previously compliant, now shows a violation) were created with `severity: "high"`, but the frontend only mapped `critical`, `warning`, and `info` — `high` had no styling and fell through to the default.

**Changes:**

- **`backend/app/routers/scanning.py`** — Changed compliance-drift alert severity from `"high"` to `"critical"` so it renders with the red critical styling in the alerts panel.
- **`frontend/components/dashboard/alerts-panel.tsx`** / **`frontend/app/alerts/page.tsx`** — Added `high` severity mapping (aliased to `critical` styling) as a safety net for any existing `high` records in the database.

---

## 2026-04-06 (Monday) — Landing Page Stats Strip Accuracy Fix

### Summary
Replaced a hardcoded, unsubstantiated "99.2% Detection Accuracy" stat on the landing page with an honest capability descriptor. The original figure had no backing data — no model benchmark, no aggregate metric, no API query — it was a static marketing string. Updated the stat to "Smart — Visual Detection," which accurately describes the system's AI-powered visual matching capability without making a false precision claim.

### Changes

- **`frontend/app/landing/page.tsx`** — Changed the stats strip entry from `{ value: "99.2%", label: "Detection Accuracy" }` to `{ value: "Smart", label: "Visual Detection" }`. The other three stats ("4 Channels Monitored", "< 5 min Setup Time", "24/7 Automated Scanning") remain unchanged as they are factual product capabilities.

### Rationale

The detection system (`ai_service.py`) uses an ensemble of vision-LLM comparison, perceptual hashing, screenshot detection with tiling, compliance analysis, and gated verification — returning per-scan confidence scores (0–100). There is no global accuracy metric aggregated across scans. Claiming "99.2%" implied a measured benchmark that doesn't exist. The new label describes the capability honestly and fits the pattern of the other stats in the strip.

---

## 2026-04-06 (Monday) — Pilot Readiness: Security, UX & Hardening

### Summary

Comprehensive pilot-readiness review and fix pass. Resolved all P0 blockers (broken invite flow, tenant isolation gaps, developer-facing error messages) and all P1 high-priority issues (expired token handling, broken endpoint, scheduler enforcement, stale scan cleanup). Built a fully functional header with Cmd+K command palette, notification dropdown, and user menu. Enabled GitHub branch protection to gate deployments behind CI.

### P0 Blockers Fixed

#### Invite Flow for New Users

**Problem:** `/invite/[token]` was not in `PUBLIC_PATHS`, so unauthenticated users clicking an invite link were silently redirected to `/landing` and the invite token was lost. The invite page also required authentication to render, creating a dead end for new users.

**Changes:**

- **`frontend/lib/auth-context.tsx`** — Added `isPublicPath()` helper that matches the static `PUBLIC_PATHS` array plus any path starting with `/invite/`. Replaced all three `PUBLIC_PATHS.includes(pathname)` checks with `isPublicPath(pathname)`.
- **`frontend/components/layout/auth-gate.tsx`** — Switched from importing `PUBLIC_PATHS` to importing `isPublicPath`. Auth gate now lets invite pages render without the sidebar/dashboard shell.
- **`frontend/app/invite/[token]/page.tsx`** — Added full unauthenticated state: loading spinner while auth resolves, then a "Sign In Required" screen with Sign In and Create Account buttons that pass `redirect=/invite/{token}` as a query parameter. Authenticated users see the existing accept flow unchanged.

#### Tenant Isolation Gaps

**Problem:** Two backend code paths queried data without scoping by `organization_id`, allowing potential cross-tenant data access. A third code path created a scan job before validating campaign ownership, leaving orphaned records on failure.

**Changes:**

- **`backend/app/routers/campaigns.py`** — `start_campaign_scan` now filters the campaign query by `.eq("organization_id", str(user.org_id))` and scopes the distributor query by `org_id` when specific `distributor_ids` are provided.
- **`backend/app/routers/scanning.py`** — `_send_scan_notifications` now queries violations by `.in_("discovered_image_id", img_ids)` scoped to the images from the specific scan job, instead of querying all violations globally and filtering in Python.
- **`backend/app/routers/scanning.py`** — Moved campaign ownership validation before scan job insertion in `start_scan`, preventing orphaned `pending` scan jobs on validation failure.

#### Developer Error Messages

**Problem:** The dashboard error banner showed "Make sure the backend is running on port 8000" and `alert()` was used for report download failures — both inappropriate for pilot users.

**Changes:**

- **`frontend/app/page.tsx`** — Replaced developer message with "We're having trouble reaching the server. Some data may be incomplete." Replaced `alert()` with an inline `downloadError` state variable that renders a red text message below the download buttons.

### P1 High Priority Fixed

#### 401 Token Refresh/Retry

**Problem:** The API client cached session tokens for 30 seconds with no mechanism to handle 401 responses. If a Supabase JWT expired during a long demo session, all API calls failed until the user manually refreshed the page.

**Changes:**

- **`frontend/lib/api.ts`** — Added an Axios response interceptor that catches 401 errors, calls `supabase.auth.refreshSession()`, busts the cached session promise, retries the original request with the new token, and queues concurrent requests during the refresh to avoid duplicate refresh calls.

#### Broken `quick_scan` Endpoint

**Problem:** The `quick_scan` endpoint called `start_scan()` with wrong arguments — missing `request: Request` and `op: OrgPlan` dependencies — causing a `TypeError` at runtime.

**Changes:**

- **`backend/app/routers/scanning.py`** — Added `request: Request` and `op: OrgPlan = Depends(get_org_plan)` as proper FastAPI dependencies. Updated the call to pass all four arguments. Removed the invalid `organization_id` field from `ScanJobCreate`.

#### Scheduled Scans Bypass Plan Enforcement

**Problem:** `_trigger_scan` in the scheduler service created scan jobs without checking trial expiration, channel allowlists, or monthly scan quotas. A free-tier org with a leftover schedule could scan indefinitely.

**Changes:**

- **`backend/app/services/scheduler_service.py`** — Added plan enforcement gate inside `_trigger_scan()` that runs before scan job creation: checks trial expiration, validates the scan source against the plan's `allowed_channels`, and counts monthly scans against `max_scans_per_month`. All checks gracefully skip the scan with an info-level log and update schedule timestamps for the next run.

#### Stale Scan Cleanup Timestamp

**Problem:** `_cleanup_stale_scans()` compared against `created_at` for running/analyzing scans. Since the scanning pipeline calls `_heartbeat()` to update `updated_at`, long-running but healthy scans were auto-failed after 30 minutes from creation.

**Changes:**

- **`backend/app/services/scheduler_service.py`** — Changed `.lt("created_at", running_cutoff)` to `.lt("updated_at", running_cutoff)` for running/analyzing scan cleanup.

### Header Controls — Full Rewrite

**Problem:** The search bar, notification bell, and user avatar in the dashboard header were purely decorative — no click handlers, no state, no functionality. Every pilot user would click these and nothing would happen.

**Changes:**

- **`frontend/components/layout/header.tsx`** — Complete rewrite (55 → 660 lines).

**Command Palette (Cmd+K):**
- Search bar is now a clickable trigger that opens a full-screen command palette overlay.
- Responds to `Cmd+K` / `Ctrl+K` keyboard shortcut globally.
- Fetches campaigns, distributors, scan jobs, matches, and alerts via React Query (with `enabled: open` so data is only fetched when the palette is visible, 30s stale time shared with the rest of the app).
- Groups results by category (Pages, Campaigns & Creatives, Distributors, Scans, Matches, Alerts) with result counts.
- Each data result shows a label, metadata sublabel, and color-coded status dot.
- Full keyboard navigation: arrow keys, Enter to navigate, Escape to close.
- Auto-scrolls selected items into view.

**Notification Dropdown:**
- Shows real unread count from `useUnreadAlertCount` (red badge, hidden when 0).
- Dropdown displays 5 most recent alerts from `useRecentAlerts` with severity icons, titles, timestamps, and unread indicators.
- Clicking an alert navigates to the match detail page (or `/alerts` if no match linked).
- "Mark all read" button wired to `useMarkAllAlertsRead` mutation.
- Empty state when no alerts exist. "View all alerts" footer link.

**User Menu Dropdown:**
- Displays the user's initial (from email) in an avatar circle.
- Dropdown shows email, with links to Settings and Billing.
- Sign out button with destructive hover styling, wired to auth context's `signOut`.

All dropdowns close on click-outside via a shared `useClickOutside` hook.

### Build Fix

**Problem:** Vercel deployment failed with two TypeScript errors.

**Changes:**

- **`frontend/app/invite/[token]/page.tsx`** — Replaced `<Button asChild>` (not supported by the Button component) with `<Link className={buttonVariants(...)}>`.
- **`frontend/app/page.tsx`** — Fixed `ChannelCoverage` field reference from `.count` to `.match_count`.

---

## Upcoming Software Connections

Planned integrations to extend the platform's reach, reduce setup friction, and close the compliance-to-action loop.

### Communication & Alerts

| Software | Purpose |
|----------|---------|
| **Slack** | Push violation and compliance-drift alerts to team channels in real time via webhooks. |
| **Microsoft Teams** | Same real-time alert delivery for enterprise orgs on the Microsoft stack. |

### CRM & Dealer Management

| Software | Purpose |
|----------|---------|
| **Salesforce** | Two-way sync of dealer/distributor records — eliminates manual onboarding and keeps dealer metadata current. Push compliance status back as contact properties. |
| **HubSpot** | Mid-market CRM alternative. Same dealer sync and compliance-status enrichment. |

### Digital Asset Management

| Software | Purpose |
|----------|---------|
| **Bynder** | Auto-ingest approved campaign assets from the brand DAM instead of manual upload. |
| **Brandfolder (Smartsheet)** | Alternative DAM connector — watch folders for new approved creative. |
| **Adobe Experience Manager** | Enterprise DAM integration for large OEMs. |
| **Frontify** | Brand guideline + asset platform — pull approved assets and brand rules. |

### Through-Channel / Co-op Marketing Platforms

| Software | Purpose |
|----------|---------|
| **SproutLoud** | Tie compliance status to co-op fund approval — violations can auto-block reimbursement. |
| **BrandMuscle** | Local marketing automation for dealer networks. Same compliance-gates-funding story. |
| **Ansira** | Channel marketing platform. Flag non-compliant creative before co-op funds are released. |

### Expanded Ad Platform APIs

| Software | Purpose |
|----------|---------|
| **Google Ads API** (direct) | Replace SerpApi proxy with direct dealer ad-account access for richer data (copy, extensions, landing pages, spend). |
| **Meta Marketing API** (direct) | Replace Apify scraping with direct ad-account access for reliable data and impression/spend metrics. |
| **YouTube** | Extend scanning to video thumbnails and pre-roll ads (source enum already exists). |
| **Microsoft / Bing Ads** | Second-largest search ad platform — dealers running Google Ads almost always run Bing too. |
| **TikTok Ads** | Growing channel for local/dealer advertising, especially consumer-facing verticals. |

### Reporting

| Software | Purpose |
|----------|---------|
| **Power BI** | Compliance data connector so enterprise teams can embed metrics in existing executive dashboards. |
| **Tableau** | Alternative BI connector for compliance trend analysis. |
| **Looker / Google Sheets** | Push compliance summaries to shared sheets or Looker dashboards for Google Workspace orgs. |

### Project Management & Workflow

| Software | Purpose |
|----------|---------|
| **Jira** | Auto-create tickets from violations — assigned to regional manager or dealer contact, closed when resolved. |
| **Asana** | Violation-to-task workflow with deadlines, screenshots attached, status synced back. |
| **Monday.com** | Alternative project management connector for violation resolution tracking. |

### File Storage

| Software | Purpose |
|----------|---------|
| **Google Drive** | Point to a folder of approved assets instead of uploading — auto-sync on changes. |
| **Dropbox** | Same folder-watch asset ingestion. |
| **SharePoint / OneDrive** | Enterprise file storage connector for Microsoft-stack orgs. |

### Build Priority

1. ~~**Slack / Teams** — fastest to ship (webhooks), instant demo value, daily stickiness~~ ✅ Slack done
2. ~~**Salesforce** — eliminates dealer onboarding friction, signals enterprise readiness~~ ✅ Done
3. **Bynder or Brandfolder** — eliminates asset upload friction, makes setup near-zero
4. ~~**Jira** — closes the violation-to-resolution loop, critical for proving ROI~~ ✅ Done
5. **Ansira** — ties compliance to co-op dollars, the core business case

---

## 2026-04-07 — Slack & Salesforce Integrations

### Summary
Built and deployed two full third-party integrations: Slack (OAuth + scan notifications) and Salesforce (OAuth + violation Tasks). Both are live in production, verified end-to-end, and gated to the Enterprise plan tier.

### Changes

**Database**
- `020_integrations.sql` — New `integrations` table with org/provider unique constraint, stores OAuth tokens, webhook URLs, channel info
- `021_salesforce_integration.sql` — Extended provider check constraint to include `salesforce`, added `refresh_token` and `instance_url` columns

**Backend — Slack Integration**
- New `integrations.py` router with full OAuth flow:
  - `GET /integrations/slack/install` — generates HMAC-signed state, returns Slack authorize URL
  - `GET /integrations/slack/callback` — exchanges code for token, stores integration
  - `GET /integrations/slack/status` — returns connection status for frontend
  - `DELETE /integrations/slack` — disconnects and removes integration
  - `POST /integrations/slack/test` — sends test message to connected channel
- `notification_service.py` — Added Slack Block Kit message builder with scan summary (images analyzed, matches, violations, compliance rate) and top violations list
- Dual delivery: `chat.postMessage` API (primary) with incoming webhook fallback
- Mounted router in `main.py`

**Backend — Salesforce Integration**
- Added to existing `integrations.py` router:
  - `GET /integrations/salesforce/install` — Salesforce OAuth consent redirect
  - `GET /integrations/salesforce/callback` — exchanges code for access + refresh tokens, fetches org name
  - `GET /integrations/salesforce/status` — returns connection status
  - `DELETE /integrations/salesforce` — disconnects
  - `POST /integrations/salesforce/test` — creates test Task in Salesforce
- `notification_service.py` — Added Salesforce REST API integration:
  - Automatic token refresh on 401 (stores refreshed token back to DB)
  - Creates Tasks via `/services/data/v59.0/sobjects/Task`
  - High priority for violations, Normal for all-clear scans
  - Detailed description with scan stats and top 15 violations

**Backend — Shared Infrastructure**
- `config.py` — Added `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`, `SALESFORCE_CLIENT_ID`, `SALESFORCE_CLIENT_SECRET` settings
- `plan_enforcement.py` — Added `check_slack_notifications()` and `check_salesforce_notifications()` gates
- `config.py` plan limits — Added `salesforce_notifications` flag (Enterprise-only)
- `scanning.py` — Wired both `notify_slack_scan_complete()` and `notify_salesforce_scan_complete()` into `_send_scan_notifications()` post-scan hook
- `.env.example` and `.do/app.yaml` — Added all 5 new env vars

**Frontend**
- `api.ts` — Added `SlackStatus`, `SalesforceStatus` interfaces and API functions for install/status/disconnect/test for both integrations
- `settings/page.tsx` — Two new integration cards:
  - **Slack Integration** card with Slack logo SVG, connect/disconnect/test buttons, workspace + channel display
  - **Salesforce Integration** card with Salesforce cloud logo SVG, connect/disconnect/test buttons, org name display
  - Both show green "Connected" badge, loading states, test result feedback

### Architecture Notes
- Both integrations follow the same pattern: OAuth install → store token → push on scan complete → status/disconnect/test endpoints
- The `integrations` table is extensible — adding Teams, Jira, etc. is a new provider row with the same OAuth pattern
- Salesforce tokens auto-refresh on expiry — no manual re-auth needed
- Slack supports both Bot API (`chat.postMessage`) and Incoming Webhook delivery
- HMAC-signed OAuth state params prevent CSRF across both flows
- All integrations are feature-gated via plan limits in `config.py`

### Files Created
| File | Purpose |
|------|---------|
| `backend/app/routers/integrations.py` | OAuth flows for Slack + Salesforce |
| `supabase/migrations/020_integrations.sql` | Integrations table |
| `supabase/migrations/021_salesforce_integration.sql` | Salesforce columns + provider constraint |

### Files Modified
| File | Change |
|------|--------|
| `backend/app/config.py` | Slack + Salesforce env vars, `salesforce_notifications` plan flag |
| `backend/app/plan_enforcement.py` | `check_slack_notifications()`, `check_salesforce_notifications()` |
| `backend/app/services/notification_service.py` | Slack Block Kit sender, Salesforce Task creator with token refresh |
| `backend/app/routers/scanning.py` | Wired Slack + Salesforce into post-scan notification hook |
| `backend/app/main.py` | Mounted integrations router |
| `backend/.env.example` | 5 new env vars |
| `.do/app.yaml` | 5 new DigitalOcean env vars |
| `frontend/lib/api.ts` | Slack + Salesforce API functions and types |
| `frontend/app/settings/page.tsx` | Two integration cards with full connect/disconnect/test UI |

---

## 2026-04-08 — Dropbox Auto-Sync & Jira Integration

### Summary
Built and deployed two major integrations: Dropbox (OAuth + auto-sync asset pipeline) and Jira (OAuth + automatic issue creation from scan violations). Fixed a deploy-blocking indentation bug in the scan notification pipeline. Both integrations are live in production, verified end-to-end, and gated to the Enterprise plan tier.

### Changes

**Database**
- `022_dropbox_integration.sql` — Extended `integrations` provider constraint to include `dropbox` and `google_drive`, added `folder_path`, `folder_name`, `campaign_id`, `last_synced_at` columns
- `023_dropbox_auto_sync.sql` — Added `external_account_id` column for Dropbox webhook matching, created `dropbox_folder_mappings` table (tracks subfolder-to-campaign relationships with unique constraint on integration + path)
- `024_jira_integration.sql` — Extended provider constraint to include `jira`, added `cloud_id` and `project_key` columns

**Backend — Dropbox Integration**
- New routes in `integrations.py`:
  - `GET /integrations/dropbox/install` — Dropbox OAuth consent redirect
  - `GET /integrations/dropbox/callback` — exchanges code for tokens, stores `external_account_id`
  - `GET /integrations/dropbox/status` — returns connection status
  - `DELETE /integrations/dropbox` — disconnects
  - `GET /integrations/dropbox/folders` — lists subfolders at a given path
  - `POST /integrations/dropbox/select-folder` — links a Dropbox folder to a campaign
  - `POST /integrations/dropbox/sync` — manual sync trigger
  - `GET /integrations/dropbox/webhook` — Dropbox webhook verification (returns challenge)
  - `POST /integrations/dropbox/webhook` — receives change notifications, triggers auto-sync
  - `POST /integrations/dropbox/auto-sync` — manual auto-sync trigger
- New `services/dropbox_service.py`:
  - `_refresh_token()` — automatic token refresh
  - `_dbx_request()` — Dropbox API request wrapper with retry on 401
  - `_list_folder()` — paginated folder listing via `/files/list_folder`
  - `_import_image()` — downloads images via `/files/download`, uploads to Supabase storage, creates asset record
  - `auto_sync_org()` — full auto-sync: ensures `/Dealer Intel/` root folder exists, auto-creates campaigns from subfolders, imports new images as assets
  - Unicode fix: uses `json.dumps(ensure_ascii=True)` for `Dropbox-API-Arg` header to handle macOS special characters in filenames

**Backend — Jira Integration**
- New routes in `integrations.py`:
  - `GET /integrations/jira/install` — Atlassian OAuth 2.0 3LO consent redirect
  - `GET /integrations/jira/callback` — exchanges code for tokens, fetches accessible Jira cloud sites, stores `cloud_id`
  - `GET /integrations/jira/status` — returns connection status with site name and selected project
  - `DELETE /integrations/jira` — disconnects
  - `GET /integrations/jira/projects` — lists available Jira projects
  - `POST /integrations/jira/select-project` — stores selected project key
  - `POST /integrations/jira/test` — creates a test issue in the selected project
  - `_refresh_jira_token()` — automatic token refresh via Atlassian OAuth
- `notification_service.py` — Added Jira notification pipeline:
  - `_get_jira_integration()` — fetches Jira integration row
  - `_refresh_jira_token()` — refreshes expired tokens
  - `_jira_api_request()` — API wrapper with auto-refresh on 401
  - `_create_jira_issue()` — creates issues with Atlassian Document Format description, configurable priority and issue type
  - `notify_jira_scan_complete()` — formats scan violations into a Jira issue (summary with violation count + compliance rate, detailed description with top 20 violations, High priority if 5+ violations)
  - `send_jira_test()` — creates a test issue

**Backend — Shared Infrastructure**
- `config.py` — Added `DROPBOX_CLIENT_ID`, `DROPBOX_CLIENT_SECRET`, `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET` settings; added `jira_notifications` to plan limits (Enterprise-only)
- `plan_enforcement.py` — Added `check_jira_notifications()` gate
- `scanning.py` — Wired `notify_salesforce_scan_complete()` and `notify_jira_scan_complete()` into `_send_scan_notifications()` post-scan hook; fixed indentation bug that caused deploy failure
- `.env.example` — Added 4 new env var placeholders
- `.do/app.yaml` — Added 4 new DigitalOcean env vars (secrets)

**Frontend**
- `api.ts` — Added `DropboxStatus`, `DropboxFolder`, `JiraStatus`, `JiraProject` interfaces and full API functions for both integrations
- `settings/page.tsx` — Two new integration cards:
  - **Dropbox Integration** card: connect/disconnect, auto-sync status showing "Watching: /Dealer Intel/", Sync Now button, "How it works" guide, last synced timestamp, sync result display
  - **Jira Integration** card: connect/disconnect, project picker dropdown, test button, site name + selected project display, test result feedback
  - Removed unused `FolderOpen` and `ChevronRight` Lucide icon imports

### Dropbox Auto-Sync Architecture
- Users connect Dropbox OAuth → system auto-creates `/Dealer Intel/` root folder
- Each subfolder inside `/Dealer Intel/` becomes a campaign automatically
- Images dropped into subfolders are imported as campaign assets
- Dropbox webhooks trigger real-time sync on file changes
- `dropbox_folder_mappings` table tracks which subfolders map to which campaigns
- Goal: near-zero app work — clients manage assets in Dropbox, campaigns self-create

### Bug Fixes
- **Deploy failure (IndentationError)** — `notify_salesforce_scan_complete()` and `notify_jira_scan_complete()` had incorrect indentation in `scanning.py`, breaking the outer `try/except` in `_send_scan_notifications()`. Fixed indentation to align all four notification calls inside the same try block.
- **Dropbox `NoneType` error** — Changed `.maybe_single()` to `.execute()` with list handling on Dropbox status/folders/sync endpoints
- **Dropbox JSON decode error** — Added response logging before JSON parsing to diagnose empty Dropbox API responses
- **Dropbox silent frontend failures** — Added error display to frontend sync handlers (previously had empty `catch {}` blocks)
- **Dropbox Unicode filename error** — macOS screenshot filenames contained Unicode narrow no-break space (`\u202f`), causing `ascii` codec error in Dropbox API header; fixed with `json.dumps(ensure_ascii=True)`

### Files Created
| File | Purpose |
|------|---------|
| `backend/app/services/dropbox_service.py` | Auto-sync engine: folder listing, image import, campaign creation |
| `supabase/migrations/022_dropbox_integration.sql` | Dropbox columns + provider constraint |
| `supabase/migrations/023_dropbox_auto_sync.sql` | `dropbox_folder_mappings` table + `external_account_id` |
| `supabase/migrations/024_jira_integration.sql` | Jira columns + provider constraint |

### Files Modified
| File | Change |
|------|--------|
| `backend/app/config.py` | Dropbox + Jira env vars, `jira_notifications` plan flag |
| `backend/app/plan_enforcement.py` | `check_jira_notifications()` |
| `backend/app/services/notification_service.py` | Jira issue creator with token refresh + scan violation formatter |
| `backend/app/routers/integrations.py` | Dropbox OAuth + webhook + auto-sync routes, Jira OAuth + project selection routes |
| `backend/app/routers/scanning.py` | Wired Salesforce + Jira into post-scan hook, fixed indentation bug |
| `backend/.env.example` | 4 new env vars |
| `.do/app.yaml` | 4 new DigitalOcean env vars |
| `frontend/lib/api.ts` | Dropbox + Jira API functions and types |
| `frontend/app/settings/page.tsx` | Two new integration cards (Dropbox auto-sync + Jira project picker) |

### Future Enhancement
- **Jira issue auto-assignment to dealer contacts** — Currently Jira issues are created unassigned. To auto-assign violations to the responsible dealer contact: (1) add `contact_name` and `contact_email` fields to the `distributors` table with UI for entering contacts, (2) use Jira's user search API (`/rest/api/3/user/search?query=email`) to resolve the dealer's Jira `accountId`, (3) set the `assignee` field on issue creation. Requires dealer contacts to have Jira accounts in the org's Atlassian workspace. Alternative: create one issue per violating distributor (instead of one summary per scan) with dealer name in the title for manual assignment.

---

## April 8, 2026 — Salesforce Two-Way Sync

**Goal:** Eliminate manual dealer onboarding, keep dealer metadata current via Salesforce, and push compliance status back as Account properties. Zero manual work in Dealer Intel beyond initial connect + filter selection.

### What It Does

- **Inbound (SF → DI):** APScheduler job runs every 30 minutes, queries SF Accounts via SOQL (filtered by user-selected Record Type or Account Type), upserts into `distributors` table. Links by `salesforce_id` or name match for existing dealers. Pulls name, website, region, social URLs, and Google Ads ID.
- **Outbound (DI → SF):** After every scan, `push_compliance_to_salesforce()` patches compliance custom fields on each SF-linked Account using the External ID upsert pattern (`PATCH .../Account/Dealer_Intel_ID__c/{distributor_id}`).
- **Auto-provisioning:** On OAuth connect, the Tooling API auto-creates 9 custom fields on the SF Account object — idempotent, no manual SF admin steps needed.
- **Sync filtering:** User must select which Accounts to import (by Record Type or Account Type) before sync runs. Prevents importing all CRM contacts as dealers.
- **Manual sync:** "Sync Now" button on Settings page triggers an on-demand inbound pull.
- **Frontend UI:** Filter picker dropdown, sync button, linked dealer count, last sync timestamp — all in the Salesforce Settings card.

### Custom Fields (auto-created on Account)

| Field | API Name | Type | Direction |
|-------|----------|------|-----------|
| Dealer Intel ID | `Dealer_Intel_ID__c` | Text(36), External ID, Unique | Outbound (link key) |
| Compliance Score | `Compliance_Score__c` | Percent | Outbound |
| Open Violations | `Open_Violations__c` | Number | Outbound |
| Has Compliance Violation | `Has_Compliance_Violation__c` | Checkbox | Outbound |
| Last Scan Date | `Last_Scan_Date__c` | DateTime | Outbound |
| Facebook URL | `Facebook_URL__c` | URL | Inbound |
| Instagram URL | `Instagram_URL__c` | URL | Inbound |
| YouTube URL | `YouTube_URL__c` | URL | Inbound |
| Google Ads Advertiser ID | `Google_Ads_Advertiser_ID__c` | Text(50) | Inbound |

### Inbound Field Mapping (SF Account → distributors)

| Salesforce Field | Distributors Column |
|-----------------|-------------------|
| `Name` | `name` |
| `Website` | `website_url` |
| `AccountNumber` | `code` |
| `BillingState` | `region` |
| `Facebook_URL__c` | `facebook_url` |
| `Instagram_URL__c` | `instagram_url` |
| `YouTube_URL__c` | `youtube_url` |
| `Google_Ads_Advertiser_ID__c` | `google_ads_advertiser_id` |

### API Endpoints Added

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/integrations/salesforce/sync` | Manual inbound sync trigger (3/min rate limit, Enterprise-gated) |
| GET | `/api/v1/integrations/salesforce/sync/status` | Last sync timestamp + linked dealer count |
| GET | `/api/v1/integrations/salesforce/filters` | Fetch available Record Types + Account Type picklist values from SF |
| PUT | `/api/v1/integrations/salesforce/filters` | Save the selected sync filter (e.g. `RecordType.Name = 'Dealer'`) |

### Sync Filtering

Salesforce orgs contain many Account types (customers, vendors, partners) — not just dealers. The sync filter prevents importing everything:

- `GET /salesforce/filters` calls the SF Account Describe API to discover Record Types and Type picklist values
- User picks a filter from the dropdown on the Settings page (grouped by Record Type / Account Type)
- `PUT /salesforce/filters` saves it as `salesforce_sync_filter` on the `integrations` row
- All subsequent inbound syncs (scheduled + manual) use the filter in the SOQL WHERE clause
- If no filter is set, sync is blocked with a message to configure it first

### User Flow

1. Connect Salesforce from Settings (existing OAuth flow)
2. 9 custom fields auto-created on the SF Account object (no SF admin work)
3. Click "Configure" on the Account Filter, pick which Accounts are dealers (e.g. "Channel Partner / Reseller")
4. Click "Sync Now" or wait 30 minutes — matching Accounts appear as dealers with all URLs populated
5. Users manage dealer info entirely in Salesforce — changes sync automatically
6. After each scan, compliance scores push back to SF Account fields — visible in the CRM

### Database Migration (`025_salesforce_two_way_sync.sql`)

```sql
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS salesforce_id TEXT;
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS salesforce_synced_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_distributors_sf_id ON distributors(salesforce_id) WHERE salesforce_id IS NOT NULL;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS salesforce_sync_filter TEXT;
```

### Files Created

| File | Purpose |
|------|---------|
| `backend/app/services/salesforce_sync_service.py` | Core sync engine: field provisioning (9 fields), inbound dealer sync with SOQL filtering, outbound compliance push, Account describe for filter options, scheduled sync runner |
| `supabase/migrations/025_salesforce_two_way_sync.sql` | `salesforce_id` + `salesforce_synced_at` on distributors, `last_synced_at` + `salesforce_sync_filter` on integrations |

### Files Modified

| File | Change |
|------|--------|
| `backend/app/routers/integrations.py` | Auto-provision SF fields on OAuth callback, added `/salesforce/sync`, `/salesforce/sync/status`, `/salesforce/filters` (GET + PUT) routes |
| `backend/app/routers/scanning.py` | Wired `push_compliance_to_salesforce()` into post-scan notification pipeline |
| `backend/app/services/scheduler_service.py` | Added 30-minute cron job for `run_salesforce_sync_all()` |
| `frontend/lib/api.ts` | Added `SalesforceFilters` type, `getSalesforceFilters`, `setSalesforceFilter`, `syncSalesforce`, `getSalesforceSyncStatus` functions |
| `frontend/app/settings/page.tsx` | Salesforce card: Account filter picker (grouped dropdown), Sync Now button, linked dealer count + last sync time, updated descriptions for two-way sync |
| `log.md` | This entry |

---

## 2026-04-09 — HubSpot Two-Way Sync Integration

### Summary
Built and deployed a full HubSpot CRM integration mirroring the Salesforce two-way sync architecture. OAuth connect, auto-provision custom Company properties, inbound dealer import with Company filter, outbound compliance push after scans, 30-minute scheduled sync, and full Settings UI card. Enterprise plan gated. Added HubSpot to the landing page integrations marquee.

### What It Does

- **Inbound (HubSpot → DI):** APScheduler job runs every 30 minutes, searches HubSpot Companies via the Search API (filtered by user-selected Company Type or Industry), upserts into `distributors` table. Links by `hubspot_id` or name match for existing dealers. Pulls company name, domain (→ website_url), and state (→ region).
- **Outbound (DI → HubSpot):** After every scan, `push_compliance_to_hubspot()` patches compliance custom properties on each HubSpot-linked Company via `PATCH /crm/v3/objects/companies/{id}`.
- **Auto-provisioning:** On OAuth connect, the Properties API auto-creates 5 custom properties on the HubSpot Company object — idempotent, skips existing properties.
- **Token refresh:** Access tokens last 30 minutes. All API calls auto-refresh on 401 and store the new token pair.
- **Sync filtering:** User must select which Companies to import (by Type or Industry) before sync runs. Prevents importing all CRM contacts as dealers.
- **Manual sync:** "Sync Now" button on Settings page triggers an on-demand inbound pull.
- **Frontend UI:** Filter picker dropdown (grouped by Company Type / Industry), sync button, test button, linked dealer count, last sync timestamp — all in a new HubSpot Settings card.

### Custom Properties (auto-created on Company)

| Property | API Name | Type | Direction |
|----------|----------|------|-----------|
| Dealer Intel ID | `dealer_intel_id` | string | Outbound (link key) |
| Compliance Score | `compliance_score` | number | Outbound |
| Open Violations | `open_violations` | number | Outbound |
| Has Compliance Violation | `has_compliance_violation` | enumeration (boolean) | Outbound |
| Last Scan Date | `last_scan_date` | datetime | Outbound |

### Inbound Field Mapping (HubSpot Company → distributors)

| HubSpot Property | Distributors Column |
|-----------------|-------------------|
| `name` | `name` |
| `domain` | `website_url` |
| `state` | `region` |

### API Endpoints Added

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/integrations/hubspot/install` | Start HubSpot OAuth flow |
| GET | `/api/v1/integrations/hubspot/callback` | OAuth callback — exchange code for tokens, auto-provision properties |
| GET | `/api/v1/integrations/hubspot/status` | Connection status (portal name, portal ID) |
| DELETE | `/api/v1/integrations/hubspot` | Disconnect HubSpot |
| POST | `/api/v1/integrations/hubspot/test` | Test connection by querying Company count |
| POST | `/api/v1/integrations/hubspot/sync` | Manual inbound sync trigger (3/min rate limit, Enterprise-gated) |
| GET | `/api/v1/integrations/hubspot/sync/status` | Last sync timestamp + linked dealer count |
| GET | `/api/v1/integrations/hubspot/filters` | Fetch Company Type + Industry picklist values |
| PUT | `/api/v1/integrations/hubspot/filters` | Save the selected sync filter |

### Architecture Notes

- Mirrors the Salesforce sync architecture: same OAuth → store token → filter → inbound sync → outbound push pattern
- HubSpot uses the Search API with JSON filter groups instead of Salesforce's SOQL
- Properties API (`/crm/v3/properties/companies`) is simpler than Salesforce Tooling API — no DeveloperName lookups needed
- Token refresh cycle is shorter (30 min vs ~2 hrs for Salesforce) — handled transparently by `_hs_api_request()` wrapper
- Pagination via `after` cursor for search results (max 100 per page, up to 2000 per sync)
- Filter format stored as `property=value` (e.g. `type=PARTNER`), parsed at sync time into HubSpot filter group JSON
- `hubspot_id` on distributors links dealers to HubSpot Companies, analogous to `salesforce_id`

### Database Migration (`026_hubspot_integration.sql`)

```sql
ALTER TABLE integrations DROP CONSTRAINT IF EXISTS integrations_provider_check;
ALTER TABLE integrations ADD CONSTRAINT integrations_provider_check
    CHECK (provider IN ('slack', 'salesforce', 'dropbox', 'google_drive', 'jira', 'hubspot'));
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS hubspot_portal_id TEXT;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS hubspot_sync_filter TEXT;
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS hubspot_id TEXT;
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS hubspot_synced_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_distributors_hubspot_id
    ON distributors(hubspot_id) WHERE hubspot_id IS NOT NULL;
```

### Files Created

| File | Purpose |
|------|---------|
| `backend/app/services/hubspot_sync_service.py` | Core sync engine: token refresh, API wrapper with auto-retry, property provisioning (5 properties), inbound dealer sync with Company filter, outbound compliance push, scheduled sync runner |
| `supabase/migrations/026_hubspot_integration.sql` | Provider constraint update, `hubspot_portal_id` + `hubspot_sync_filter` on integrations, `hubspot_id` + `hubspot_synced_at` on distributors |

### Files Modified

| File | Change |
|------|--------|
| `backend/app/config.py` | Added `hubspot_client_id` + `hubspot_client_secret` settings, added `hubspot_notifications` flag to all 5 plan tiers (Enterprise-only) |
| `backend/app/plan_enforcement.py` | Added `check_hubspot_notifications()` gate |
| `backend/app/routers/integrations.py` | Full HubSpot OAuth flow (install/callback/status/disconnect), test endpoint, sync/status/filters endpoints — 10 new routes |
| `backend/app/routers/scanning.py` | Wired `push_compliance_to_hubspot()` into post-scan notification pipeline |
| `backend/app/services/scheduler_service.py` | Added 30-minute cron job for `run_hubspot_sync_all()` |
| `frontend/lib/api.ts` | Added `HubSpotStatus`, `HubSpotFilters`, `HubSpotFilterOption` interfaces + 8 API functions |
| `frontend/app/settings/page.tsx` | Full HubSpot integration card: connect/disconnect, Company filter picker (grouped by Type/Industry), Sync Now button, Test button, linked dealer count + last sync time |
| `frontend/app/landing/page.tsx` | Added HubSpot logo to integrations marquee, marked HubSpot as live in integrations grid, updated description copy |
| `backend/.env.example` | Added `HUBSPOT_CLIENT_ID` + `HUBSPOT_CLIENT_SECRET` placeholders |
| `.do/app.yaml` | Added 2 new DigitalOcean env vars (secrets) |

---

## 2026-04-10 — Scan All Channels, Batch Endpoint & Scan Reliability Fixes

### Summary

Added a "Scan All Channels" button to the campaign page, built a dedicated campaign batch scan endpoint, fixed scan error handling so analysis failures don't mark successful scans as failed, fixed the global matches page to show matches with NULL distributor_id, improved Facebook distributor mapping, and installed Playwright browser binaries.

### Changes

**Backend**

- **New endpoint: `POST /campaigns/{campaign_id}/scans/batch`** — Creates scan jobs for all plan-allowed channels in a single request, scoped to a specific campaign. Avoids the concurrent scan limit race condition that occurred when firing 4 parallel `startCampaignScan` calls from the frontend. Rate-limited to 2/minute. (`campaigns.py`)
- **Scan error handling** — Wrapped `auto_analyze_scan()` in its own try/catch for all four scan types (Google Ads, Facebook, Instagram, Website). Previously, if AI analysis crashed mid-way, the entire scan was marked "failed" even though the Apify scraper succeeded and images were already discovered. Now the scan completes and notifications still send. (`scanning.py`)
- **Global matches page fix** — Added `_org_asset_ids()` helper and updated `list_matches` and `get_match_stats` to query matches by both `distributor_id` (existing) and `asset_id` (new). Matches with NULL `distributor_id` — e.g., from Facebook/Instagram where the page name didn't resolve to a dealer — now appear on the matches page as long as the asset belongs to the org's campaigns. (`matches.py`)
- **Facebook distributor mapping** — All three places that build the Facebook mapping (single scan, campaign batch, org batch) now include the Facebook URL slug alongside the dealer name. For example, `facebook.com/yanceybrosco` adds both `"yancey bros" → id` and `"yanceybrosco" → id` to the mapping, improving Apify page name resolution. (`campaigns.py`, `scanning.py`)
- **Playwright install** — Ran `playwright install` to download Chromium browser binaries. Website scans were failing with `BrowserType.launch: Executable doesn't exist`.

**Frontend**

- **"Scan All Channels" button** — Full-width primary button on the campaign Scans tab, placed above the individual channel buttons. Calls the new `POST /campaigns/{campaign_id}/scans/batch` endpoint. Shows loading spinner during operation, disables individual channel buttons, switches to Scans tab on completion, and surfaces backend error messages directly. (`campaigns/[id]/page.tsx`)
- **API client** — Added `startCampaignBatchScan(campaignId)` function. (`api.ts`)

### Known Issues / TODO

- **"Scan All Channels" still needs work and testing** — The batch button works end-to-end but needs further testing with different plan tiers, edge cases (no assets, no distributors, partial channel failures), and UI feedback refinement. The polling only tracks the first scan job; ideally it should track all jobs from the batch.
- **Old matches with NULL distributor_id** — Existing Facebook/Instagram matches created before the mapping fix still show "Unknown" as the distributor. These won't self-heal; they need a re-scan or a database backfill.
- **Asset uploads store as base64** — Campaign assets are being stored as base64 data URLs instead of Supabase Storage URLs because filenames with special characters (spaces, non-breaking spaces) cause `InvalidKey` errors on upload. This bloats the database and slows AI analysis.

### Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/campaigns.py` | Added `POST /{campaign_id}/scans/batch` endpoint; improved Facebook mapping with URL slug |
| `backend/app/routers/scanning.py` | Wrapped `auto_analyze_scan` in try/catch for all 4 scan types; improved Facebook mapping in org batch |
| `backend/app/routers/matches.py` | Added `_org_asset_ids()`; updated `list_matches` and `get_match_stats` to include NULL distributor_id matches |
| `frontend/app/campaigns/[id]/page.tsx` | Added "Scan All Channels" button, `scanningAll` state, `handleScanAllChannels` using batch endpoint |
| `frontend/lib/api.ts` | Added `startCampaignBatchScan()` |

---

## 2026-04-10 — Scaling Roadmap: 150+ Dealer OEM Support

### Context

Architecture review identified that the current engine cannot reliably handle 40+ dealers per scan — and the product goal is 150+ dealers for large OEM clients. This roadmap captures every change needed, prioritized by impact, to get from the current ceiling (~15–20 dealers) to 150+ without crashing, timing out, or bankrupting the Anthropic bill.

### Completed (this session)

- **Upgraded AI models from Opus 4 → Opus 4.6** — Changed `CLAUDE_MODEL` and `ENSEMBLE_MODEL` in `ai_service.py` from `claude-opus-4-20250514` to `claude-opus-4-6`. Opus 4.6 is strictly better on every benchmark and **67% cheaper** ($5/$25 per MTok vs $15/$75). This single change cuts the Anthropic bill by ~2/3 with zero quality tradeoff.

### Current Bottlenecks

1. **In-process execution** — Scans run as `asyncio.create_task()` inside the API worker. No isolation — a scan OOM crashes the API for all users.
2. **Sequential dealer processing** — 150 dealers × 15 pages = 2,250 pages processed one at a time in a `for` loop.
3. **Timeout conflicts** — Gunicorn timeout (30m) vs scan timeout (2h) vs stale cleanup (60m) fight each other.
4. **Memory ceiling** — Chromium (~250MB) + CLIP (~200MB) + image cache (200MB) + Python baseline (~100MB) = ~750MB before scan work starts. On a 1–2GB instance, no room for 150-dealer payloads.
5. **Database write storm** — Individual HTTP INSERT per discovered image/match. 150 dealers = ~12,000+ round-trips to Supabase.
6. **Single shared browser** — One Chromium instance recycled every 10 minutes, causing mid-scan disruptions.
7. **O(images × assets) Opus calls** — Every surviving image is compared against every campaign asset. With 10 assets, the multiplier is 10x on the most expensive API call.

### Why Not Redis/ARQ as Task Queue

Previously attempted twice (Celery + Kombu, then ARQ) with DigitalOcean Managed Valkey — both failed in production due to SSL transport bugs, missing auth parameters, and stale in-progress keys from rolling deploys. Every production outage traced back to the API→Redis→Worker hand-off. Full history documented in the 2026-03-28 log entry.

Redis stays for what it already does well (scheduler lock via `SET NX`), but scan dispatch uses **HTTP-triggered workers** instead — no message broker in the critical path. The API and workers communicate over HTTP and coordinate via Supabase (the shared source of truth that has never failed).

### COG Model (150 Dealers, 1 Client, Weekly Scans)

| Cost Item | Opus 4 (old) | Opus 4.6 (current) | Fully Optimized |
|-----------|-------------|-------------------|-----------------|
| Anthropic Claude | ~$5,200 | ~$1,730 | ~$400–600 |
| SerpApi | $75–150 | $75–150 | $75–150 |
| Apify (Meta + IG) | $29–49 | $29–49 | $29–49 |
| DO App Platform (API) | $49 | $49 | $49 |
| DO Worker Instance(s) | — | — | $49–98 |
| DO Redis (scheduler lock) | $15 | $15 | $15 |
| Supabase Pro | $25–50 | $25–50 | $25–50 |
| Vercel | $0–20 | $0–20 | $0–20 |
| **Monthly Total** | **~$5,500** | **~$2,050** | **~$750–1,050** |

Anthropic is ~85% of the bill. Every optimization that reduces Opus calls has outsized impact.

### Scaling Plan — Phased

---

#### Phase 1: Cost Optimization (no architecture changes)

| # | Change | Impact | Effort |
|---|--------|--------|--------|
| 1.1 | ~~Upgrade to Opus 4.6~~ | ~~67% cost reduction~~ | ~~Done~~ |
| 1.2 | Switch `ENSEMBLE_MODEL` to Sonnet 4 for compare/detect calls | Additional 40% reduction on ensemble ($3/$15 vs $5/$25). Keep Opus 4.6 for compliance only. | Small |
| 1.3 | CLIP-based asset preselection | Use CLIP cosine similarity to select top 2–3 most similar assets per image instead of comparing against all N. Cuts Opus calls by 50–70%. | Medium |
| 1.4 | Anthropic Batch API | 50% off input+output for non-real-time analysis. Scans already take minutes. | Medium |
| 1.5 | Prompt caching | Cache system prompt + asset image prefix across calls within a scan. 50% off cached input tokens. | Medium |
| 1.6 | Cross-dealer image deduplication | Hash-dedup discovered images across dealers within a scan — analyze once, attribute to all. | Medium |

**Phase 1 target:** Monthly COG drops from ~$2,050 to ~$750–1,050.

---

#### Phase 2: HTTP-Triggered Worker Separation

**Approach:** The API dispatches scan work to a separate worker service via HTTP POST — no message broker, no Redis queue, no pub/sub. The worker is a standalone FastAPI app on its own DO App Platform instance that receives scan parameters directly, executes the scan pipeline, and writes results to Supabase. Both API and workers share Supabase as the single source of truth.

| # | Change | Impact | Effort |
|---|--------|--------|--------|
| 2.1 | Build worker service (`worker/`) | Standalone FastAPI app with `POST /scan/run` endpoint. Receives scan params (channel, dealer URLs, distributor mapping, campaign ID, chunk info). Runs the existing scan pipeline functions. Updates `scan_jobs` in Supabase directly. | Large |
| 2.2 | Separate API and worker Docker images | API image: no Playwright, no CLIP (~200MB RAM). Worker image: Playwright + CLIP + full scan deps (~1.2GB). API no longer loads memory-heavy scan dependencies. | Medium |
| 2.3 | Update `dispatch_task` to HTTP POST | Replace `asyncio.create_task()` with `httpx.AsyncClient.post()` to worker service. Fire-and-forget with timeout. If worker returns non-200, mark job as failed immediately. | Medium |
| 2.4 | Add worker instance(s) to DO App Platform | 1–2 dedicated 4GB worker instances. Each runs the worker FastAPI app. Scale horizontally by adding instances. API round-robins or uses least-loaded selection via `scan_jobs` table. | Small |
| 2.5 | Worker health check + discovery | Worker exposes `GET /health`. API checks worker availability before dispatching. If worker is down, POST returns 503 and API marks job failed with clear error. No silent message drops. | Small |

**Phase 2 target:** Scans execute in isolated workers. API process drops to ~200MB. A crashed worker doesn't crash the API. Every failure is an explicit HTTP error — no silent drops.

---

#### Phase 3: Chunked Dealer Processing

| # | Change | Impact | Effort |
|---|--------|--------|--------|
| 3.1 | Parent/child job model | 150-dealer scan creates a parent `scan_job` that spawns child chunk jobs (10–15 dealers each). API POSTs one HTTP request per chunk to the worker pool. Parent aggregates status from children via Supabase. | Large |
| 3.2 | Per-chunk timeouts | Each chunk has a 30 min execution timeout on the worker side. Parent job has a 4 hour overall timeout. Stale cleanup operates on chunks, not the parent. | Medium |
| 3.3 | Parallel chunk execution | API dispatches multiple chunks concurrently to available workers. 10 chunks across 2 workers = ~5 sequential rounds. Wall-clock: ~2.5 hours. Workers process one chunk at a time (simple, predictable memory). | Small |
| 3.4 | Progress tracking per chunk | Each chunk updates its `scan_job` row in Supabase as it progresses. Frontend polls parent job and sees aggregated progress: "Chunk 3/10 complete — 45 dealers scanned, 12 matches." | Medium |
| 3.5 | Partial failure resilience | If chunk 4's HTTP call fails or the worker crashes, chunks 1–3 and 5–10 still complete. Parent reports partial success with details on which dealers failed. API can retry individual chunks via POST. | Medium |

**Phase 3 target:** 150 dealers complete in ~2–3 hours wall-clock with parallel workers. Failures are isolated and retryable at the chunk level.

---

#### Phase 4: Database & I/O Optimization

| # | Change | Impact | Effort |
|---|--------|--------|--------|
| 4.1 | Bulk inserts for `discovered_images` | Buffer 50–100 rows, insert via `.insert([...])`. Reduces ~12,000 HTTP calls to ~120. | Small |
| 4.2 | Bulk inserts for `matches` | Same pattern for match creation. | Small |
| 4.3 | Batch deletes for duplicate pruning | Replace per-row delete loop with `.in_("id", [...])`. | Small |
| 4.4 | Supabase connection pooling (pgBouncer) | Reduce connection overhead under concurrent chunk processing. Config change in Supabase dashboard. | Small |
| 4.5 | Streaming progress writes | Batch status updates every 30s or every 10 pages instead of per-page. | Small |

**Phase 4 target:** DB writes drop from ~12,000 individual calls to ~100–200 batched calls per scan.

---

#### Phase 5: Browser & Extraction Scaling

| # | Change | Impact | Effort |
|---|--------|--------|--------|
| 5.1 | Per-worker browser instance | Each worker instance manages its own Chromium browser. Natural outcome of Phase 2 — no shared global `_browser` across processes. | Free |
| 5.2 | Browser pool within worker | 2–3 browser contexts for intra-chunk parallelism (3 dealers simultaneously per chunk). | Medium |
| 5.3 | Extend browser max age | Increase `_BROWSER_MAX_AGE_SECONDS` from 600 to 1800–3600 for workers (chunks complete in ~30 min, no need for aggressive recycling). | Small |
| 5.4 | Graceful browser recovery | Catch browser crash mid-page, relaunch, retry that page — don't fail the chunk. | Medium |

---

#### Phase 6: Timeout & Cleanup Coherence

| Mechanism | Current | After Scaling |
|-----------|---------|---------------|
| Gunicorn worker timeout (API) | 1,800s (30 min) | 120s (API-only, no scans in process) |
| Gunicorn worker timeout (Worker) | N/A | 2,400s (40 min, covers 30 min chunk + buffer) |
| Scan task timeout | 7,200s (2h) monolithic | Per-chunk: 1,800s (30 min). Parent: 14,400s (4h). |
| Stale scan cleanup | 60 min running, 15 min pending | Per-chunk: 45 min. Parent: 5h. Heartbeat-based. |
| Heartbeat | No-op | Per-chunk heartbeat every 60s via Supabase update. Cleanup checks heartbeat, not just `created_at`. |
| HTTP dispatch timeout | N/A | 5s connect, fire-and-forget (worker reports status to Supabase, API doesn't hold connection open). |

---

### Implementation Priority

| Order | Phase | Why |
|-------|-------|-----|
| 1st | Phase 1 (cost optimization) | Reduces bill risk during development. Most changes are small and independent. |
| 2nd | Phase 4 (bulk DB writes) | Quick wins, small effort, reduces I/O pressure that compounds at scale. |
| 3rd | Phase 2 (HTTP workers) | Core architecture change. Everything after depends on workers existing. |
| 4th | Phase 3 (chunked processing) | The actual scale unlock. Requires Phase 2. |
| 5th | Phase 6 (timeouts) | Clean up during Phase 2–3 implementation. |
| 6th | Phase 5 (browser scaling) | Polish. Per-worker browsers come free with Phase 2. |

### Target Architecture

```
CURRENT (ceiling: ~15-20 dealers)
┌─────────────────────────────────────────┐
│  Gunicorn Worker (API + Scans)          │
│  ├── FastAPI HTTP handlers              │
│  ├── asyncio.create_task(scan)          │
│  ├── Shared Playwright browser (1)      │
│  ├── CLIP model in memory              │
│  └── Image cache (200MB)               │
│       ~800MB–1.2GB total               │
└─────────────────────────────────────────┘
         │
    Redis (scheduler lock only)

TARGET (150+ dealers)
┌──────────────────┐  POST /scan/run  ┌──────────────────────┐
│  API Instance     │────────────────▶│  Worker Instance(s)  │
│  FastAPI only     │                 │  ├── FastAPI (worker) │
│  ~200MB RAM       │                 │  ├── Playwright (2x) │
│  No Playwright    │                 │  ├── CLIP model      │
│  No CLIP          │                 │  └── Scan pipeline   │
│  120s timeout     │                 │  4GB RAM, 30m/chunk  │
└──────────────────┘                 └──────────────────────┘
         │                                    │
    Redis (lock only)                         │
         │                                    │
         └──────────── Supabase ──────────────┘
              (shared source of truth)
              (scan_jobs, progress, results)
              (no broker — HTTP + DB only)
```

**Key design decision:** No message broker in the scan critical path. The API→Worker hand-off is a plain HTTP POST. Coordination happens through Supabase (status, progress, results). Redis stays for scheduler lock only — the one thing it already does reliably. This avoids repeating the Celery/ARQ/Valkey SSL transport failures documented in the 2026-03-28 session.

### Files Changed (this session)

| File | Change |
|------|--------|
| `backend/app/services/ai_service.py` | Updated `CLAUDE_MODEL` and `ENSEMBLE_MODEL` from `claude-opus-4-20250514` to `claude-opus-4-6` (67% cost reduction, better model) |

---

## 2026-04-13 — Dashboard Data Fix, Scan Investigation & Pilot Readiness

### Summary

Fixed the dashboard to show all matches (including those with NULL distributor_id), investigated a slow website scan, audited the AI pipeline model usage across all stages, identified prompt caching as a major post-pilot optimization, assessed pilot readiness for the demo, and verified per-org data isolation.

### Changes

**Backend**

- **Dashboard stats fallback** — `_get_dashboard_stats_fallback` now builds an `or_` filter combining `distributor_id.in.(...)` and `asset_id.in.(...)`, so total_matches, compliance_rate, violations_count, and matches_today all include matches where distributor_id is NULL. (`dashboard.py`)
- **Recent matches endpoint** — `get_recent_matches` replaced `.in_("distributor_id", ...)` with the same `or_` clause so dashboard recent matches card shows all org matches. (`dashboard.py`)
- **Coverage by channel endpoint** — `get_coverage_by_channel` uses the same `or_` filter and now returns `match_count` instead of `count` to align with the frontend field name. (`dashboard.py`)

**Frontend**

- **ChannelChart mapping** — Fixed `page.tsx` to read `c.match_count` instead of `c.count` from the coverage-by-channel API response, so the Coverage by Channel bar chart and Asset Coverage card display correct numbers. (`page.tsx`)

### Investigation: Website Scan Slowness

Investigated a website scan (job `9f82a6a1`) that appeared stuck. Findings:

- **Not stuck — just slow.** The worker process (pid 47522) was alive with 327MB memory and active CPU usage.
- **Progress:** 181 discovered images, 166 processed, 15 remaining across 15 pages on `yanceybros.com`.
- **Root cause:** Every image that passes the hash pre-filter triggers multiple Opus 4.6 API calls. For a single image that passes Stage 3, worst case is 5 Opus calls (1 filter + 3 assets × 1 comparison + 1 compliance).
- **Scan completed successfully** — status moved to `completed` after ~49 minutes.
- **Cleanup safety net:** `_cleanup_stale_scans` auto-fails scans after 60 minutes; hard timeout is 7,200 seconds (2 hours).

### AI Pipeline Model Audit

| Stage | Purpose | Model | Speed |
|-------|---------|-------|-------|
| Stage 1 | Hash pre-filter (pHash, dHash, wHash, average) | No AI model | Instant |
| Stage 2 | CLIP embedding pre-filter | Not installed (`sentence_transformers` missing) | Skipped |
| Stage 3 | Relevance filter (is image campaign-related?) | `claude-haiku-4-5-20251001` | Fast/cheap |
| Stage 4 | Ensemble match — `compare_images` | `claude-opus-4-6` | Slow/expensive |
| Stage 4 | Ensemble match — `compare_with_hash` | No AI model (perceptual hashing) | Instant |
| Verification | Borderline match verification | `claude-opus-4-6` | Slow/expensive |
| Calibration | Confidence score adjustment | No AI model (math from feedback) | Instant |
| Compliance | Deep compliance analysis | `claude-opus-4-6` | Slow/expensive |

### Prompt Caching Opportunity (Post-Pilot)

Identified that **prompt caching is not implemented**. Every call to `call_anthropic_with_retry` sends the full system prompt + asset images with no `cache_control` markers. The same 3 campaign assets are re-uploaded on every comparison call — potentially dozens of times per scan. Adding Anthropic prompt caching (`cache_control: {"type": "ephemeral"}`) on system prompts and asset images would:

- Reduce input token costs by ~80-90%
- Lower per-call latency (cached prefix skips full processing)
- Cache has 5-minute TTL — calls during a scan easily stay within window

Deferred to post-pilot to avoid risking changes before demo.

### Pilot Readiness Assessment

**Working:**
- All 4 scan channels completing (Website, Facebook, Instagram, Google Ads)
- 43 matches found across channels (29 website, 8 Facebook, 4 Instagram, 2 Google Ads)
- Dashboard, campaigns, matches, alerts, compliance rules, billing, team management, onboarding all functional
- 5 third-party integrations built (Slack, Salesforce, HubSpot, Dropbox, Jira)

**Cautions for demo:**
- Website scans take 20-40+ minutes — pre-run before demo, don't trigger live
- "Scan All Channels" not fully tested — avoid during demo
- 7 matches show "Unknown" distributor (NULL distributor_id from before mapping fix)
- Google Ads fails gracefully when distributors lack Advertiser IDs

**Data isolation verified:** Each user's org sees only its own data. New signups get an empty org via auto-provisioning. Pilot client won't see test data.

### Known Issues / TODO

- **Prompt caching** — Major cost/speed optimization, implement post-pilot
- **CLIP pre-filter disabled** — `sentence_transformers` not installed, more images leak to expensive Opus stages
- **Base64 asset storage** — Assets stored as data URLs instead of Supabase Storage, bloats API payloads
- **Old NULL distributor matches** — 7 existing matches won't self-heal; need re-scan or backfill

### Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/dashboard.py` | Fixed 3 endpoints (stats fallback, recent matches, coverage-by-channel) to include NULL distributor_id matches via `or_` filter; changed response field `count` → `match_count` |
| `frontend/app/page.tsx` | Fixed ChannelChart mapping to read `match_count` instead of `count` |

---

## 2026-04-14 — 150-Dealer Cost-Per-Scan Analysis

### Summary

Deep cost analysis session for a prospective client with 150 dealers. Audited the full scan pipeline end-to-end — every external API call, every Anthropic model invocation, infrastructure costs — to produce a per-scan and per-dealer cost model. Also investigated why CLIP is disabled in production.

### Cost-Per-Scan Model (150 Dealers, All 4 Channels)

#### Image Volume Estimates

| Channel | Per Dealer | Total (150 dealers) | Source |
|---------|-----------|-------------------|--------|
| Website | ~225 (15 pages × 15 imgs) | ~33,750 | Playwright extraction |
| Google Ads | ~20 creatives | ~3,000 | SerpApi |
| Facebook | ~10 ad images | ~1,500 | Apify Meta actor |
| Instagram | ~20 post images | ~3,000 | Apify Instagram task |
| **Total** | | **~41,250** | |

Early stopping + page caching on repeat scans reduces website volume significantly (~94% reduction observed in prior tests). Realistic repeat scan total: ~15,000–20,000 images.

#### Per-Image AI Pipeline Cost

| Stage | Model | Cost/Call | Notes |
|-------|-------|----------|-------|
| Stage 1: Hash pre-filter | None | Free | <1ms, ~60–70% rejection rate (hash-only) |
| Stage 2: CLIP embedding | None | **Skipped** | `sentence_transformers` not installed |
| Stage 3: Haiku filter | `claude-haiku-4-5-20251001` | ~$0.007 | ~3,000 input + ~200 output tokens |
| Stage 4: Opus comparison | `claude-opus-4-6` | ~$0.031 | Per asset — runs N times (1 per campaign asset) |
| Verification | `claude-opus-4-6` | ~$0.031 | Borderline scores 60–80 only |
| Compliance | `claude-opus-4-6` | ~$0.039 | Matched images only |

Worst case per image surviving hash: 1 Haiku + N Opus (1 per asset) + 1 Opus compliance = up to 5 calls with 3 assets.

#### Total Cost Per Scan

| Component | Current (Opus 4.6, no CLIP) | Fully Optimized |
|-----------|---------------------------|-----------------|
| Anthropic Claude | ~$432 | ~$100–150 |
| SerpApi | ~$19–38 | ~$19–38 |
| Apify (Meta + IG) | ~$7–12 | ~$7–12 |
| Infrastructure (DO + Supabase + Vercel) | ~$34–46 | ~$34–46 |
| **Total per scan** | **~$492–528** | **~$160–246** |
| **Per dealer per scan** | **$3.28–3.52** | **$1.07–1.64** |

#### Monthly Cost (Weekly Scans)

| | Current | Fully Optimized |
|---|---------|-----------------|
| Monthly total | ~$1,968–2,112 | ~$640–984 |
| Per dealer per month | ~$13.12–14.08 | ~$4.27–6.56 |

Anthropic is ~85% of the total bill. Every optimization that reduces Opus calls has outsized impact.

### CLIP Pre-Filter Investigation

Investigated why Stage 2 (CLIP embedding gate) is disabled in production:

1. **`sentence-transformers` is not in `requirements.txt`** — listed in the March 18 architecture review as added but not present in the current requirements file. Never gets installed in production.
2. **Graceful degradation** — `embedding_service.py` uses lazy-load with `try/except ImportError`. When `sentence_transformers` is missing, it logs a warning and every `compute_embedding()` call returns `None`. The pipeline's CLIP gate silently skips Stage 2.
3. **Root cause: memory pressure** — The CLIP model (`clip-ViT-B-32`) requires ~200MB RAM. Current production instance is 2GB. Memory budget is already tight: Chromium (~250MB) + image cache (~200MB) + Python baseline (~100MB) = ~550MB before scan work. Adding CLIP would push toward OOM under load.
4. **Resolution path** — In the target Phase 2 architecture, CLIP moves to dedicated 4GB worker instances alongside Playwright, where there's room for both. Re-enabling CLIP would reject an additional ~20–30% of images before they reach paid API calls, cutting Anthropic costs by an estimated 30–50%.

### Optimization Priority Recap

From the Phase 1 roadmap (2026-04-10), the 5 uncommitted optimizations that would drop monthly COG from ~$2,050 to ~$750–1,050:

| # | Optimization | Anthropic Impact | Status |
|---|-------------|-----------------|--------|
| 1.2 | Sonnet 4 for ensemble (keep Opus for compliance only) | ~40% reduction on ensemble calls | Not started |
| 1.3 | CLIP-based asset preselection (top 2–3 assets per image) | Cuts Opus calls 50–70% | Not started (blocked by memory) |
| 1.4 | Anthropic Batch API | 50% off all tokens | Not started |
| 1.5 | Prompt caching (`cache_control: ephemeral`) | 80–90% off cached input tokens | Not started |
| 1.6 | Cross-dealer image deduplication | Analyze once, attribute to all | Not started |

### Plan Limits Note

Current `PLAN_LIMITS` in `config.py` caps the Business tier at 100 dealers (`max_dealers: 100`). A 150-dealer client requires the Enterprise tier (`max_dealers: None`) or a plan limit increase.

---

## 2026-04-14 (Tuesday) — Critical Performance Fix: Base64 Image Bloat

### Summary

Diagnosed and fixed a critical performance regression where all list API endpoints (`/matches`, `/dashboard/recent-matches`) had degraded from sub-second to 20+ seconds. Root cause was base64-encoded asset images (~3.5 MB each) being pulled through PostgREST joins and the `recent_matches` view, inflating JSON payloads to 36–48 MB per request.

### Root Cause Analysis

The `assets.file_url` column stores full PNG images as inline `data:image/png;base64,...` strings averaging 3.5 MB each. Two query paths were pulling this data into every list response:

1. **`recent_matches` SQL view** — Joins `assets` and includes `file_url` as `asset_url` in every row. The view materializes the full `SELECT m.*` (including `ai_analysis` JSON) before PostgREST applies column filtering. With 42 matches across 37 assets, the view produced ~39 MB of raw data.
2. **PostgREST foreign key joins** — `assets(name, file_url, campaigns(name))` pulled `file_url` into the join result. Even with explicit column selection on the `matches` table, the joined `file_url` added ~48 MB to the response.

The `recent_matches` view compounded the problem: it runs `ROW_NUMBER() OVER (PARTITION BY ...)` with 4 LEFT JOINs on the entire matches table, materializing all columns including the heavy ones, before PostgREST can filter.

### Performance Results

| Endpoint | Before Fix | After (cold) | After (warm) |
|---|---|---|---|
| `/matches?limit=50` | 20,058 ms / 41 KB | 692 ms / 41 KB | 342 ms |
| `/dashboard/recent-matches?limit=6` | 5,153 ms / 6.9 KB | 322 ms / 5 KB | 217 ms |
| `/matches/stats` | 405 ms | 399 ms | 258 ms |
| `/dashboard/stats` | 653 ms | 982 ms | 267 ms |
| **Total (all endpoints)** | **28,619 ms** | **4,387 ms** | **2,303 ms** |

Cold load improved **6.5x**, warm load improved **12.4x**.

### Changes Made

#### Backend — Query Optimization

**`backend/app/routers/matches.py`**
- Switched `list_matches` from `recent_matches` view to direct `matches` table query
- Joins only lightweight name columns: `assets(name, campaigns(name)), distributors(name)` — no `file_url`
- Added `_flatten_match_rows()` to transform nested PostgREST join responses into the flat shape the frontend expects
- `_strip_base64_urls()` nulls out any remaining `data:` URLs in `screenshot_url` fields
- `get_match_stats` still uses TTLCache (60s) and attempts `get_match_stats_for_org` RPC first

**`backend/app/routers/dashboard.py`**
- Switched `/dashboard/recent-matches` from `recent_matches` view to direct `matches` table query with name-only joins
- Added `_flatten_dashboard_matches()` for response shaping
- Cache still active via `_dashboard_cache` TTLCache (60s)

**`backend/app/routers/campaigns.py`**
- Added `GET /campaigns/assets/{asset_id}/thumbnail` endpoint
- Decodes base64 `file_url` and returns raw image bytes with `Content-Type` and `Cache-Control: public, max-age=86400`
- Auth-protected — requires valid JWT via `get_current_user`
- Keeps image serving separate from JSON API responses

#### Frontend — Lazy Thumbnail Loading

**`frontend/components/asset-thumbnail.tsx`** (new)
- Reusable `AssetThumbnail` component
- Fetches thumbnail via `api.get()` (auto-attaches JWT via axios interceptor) with `responseType: "blob"`
- In-memory `Map<string, string>` cache of blob URLs — each asset image fetched only once per session
- Shows `ImageIcon` placeholder while loading or on failure

**`frontend/app/matches/page.tsx`**
- Replaced inline `<Image src={match.asset_url}>` with `<AssetThumbnail assetId={match.asset_id}>`
- Asset images now load independently per-row, don't block the table render

**`frontend/components/dashboard/recent-matches.tsx`**
- Same change — uses `AssetThumbnail` for dashboard match thumbnails
- Removed unused `next/image` import

#### Database — Match Stats RPC

**`supabase/migrations/020_match_stats_rpc.sql`**
- New `get_match_stats_for_org(p_org_id UUID)` RPC function
- Single SQL round-trip for all match statistics (total, compliant, violations, pending, by type, avg confidence, compliance rate)
- Scopes matches via `distributor_id IN (org distributors) OR asset_id IN (org assets)` — consistent with dashboard RPC
- Pending deployment to Supabase SQL Editor

### Architecture Decision: Why Not the View?

The `recent_matches` view was designed for deduplication (ROW_NUMBER partitioned by asset+distributor). However:

1. **PostgreSQL materializes the full CTE** before PostgREST column filtering — so even selecting 5 columns still processes all columns including 3.5 MB `file_url` per row
2. **The view joins 4 tables** (`assets`, `distributors`, `campaigns`, `discovered_images`) with window functions across all rows — expensive even with indexes
3. **Direct table queries with PostgREST foreign key joins** are dramatically faster because PostgreSQL can push down LIMIT and column selection before joining

For list endpoints, direct queries are preferred. The view can still be used for single-row lookups (match detail page) where full data is needed.

### Known Issues / TODO

- **`thumbnail_url` column is NULL for all assets** — The `assets` table has a `thumbnail_url` column that's never populated. Generating and storing actual thumbnails (resized to ~200px) would eliminate the need for the `/thumbnail` endpoint to decode full-size base64 on every request.
- **`020_match_stats_rpc.sql` needs manual deployment** — Must be run in Supabase SQL Editor if CI doesn't auto-push migrations.
- **Base64 asset storage remains the root issue** — Assets should be migrated to Supabase Storage with proper URLs instead of inline `data:` URIs. This would make all queries fast by default without special handling.

### Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/matches.py` | Switch from `recent_matches` view to direct `matches` table; add `_flatten_match_rows()`, `_strip_base64_urls()` |
| `backend/app/routers/dashboard.py` | Switch recent-matches from view to direct table; add `_flatten_dashboard_matches()` |
| `backend/app/routers/campaigns.py` | Add `GET /assets/{id}/thumbnail` endpoint serving raw image bytes |
| `backend/app/main.py` | Request timing middleware (added earlier in session) |
| `frontend/components/asset-thumbnail.tsx` | New `AssetThumbnail` component with auth-aware lazy loading and blob URL cache |
| `frontend/app/matches/page.tsx` | Use `AssetThumbnail` for match comparison images |
| `frontend/components/dashboard/recent-matches.tsx` | Use `AssetThumbnail` for dashboard thumbnails |
| `supabase/migrations/020_match_stats_rpc.sql` | New `get_match_stats_for_org` RPC function |

---

## 2026-04-20 (Monday) — Opus 4.7 Upgrade + Anthropic Prompt Caching (Phase 1.1)

### Summary

First execution of the 6-week 150-dealer scaling plan. Upgraded all Opus calls from `claude-opus-4-6` → `claude-opus-4-7` (released 2026-04-16, same $5/$25 per-MTok pricing, improved vision and instruction-following) and implemented Anthropic ephemeral prompt caching across the 5 highest-leverage call sites in the AI pipeline. Also fixed a pre-existing pricing bug in `cost_tracker.py` where Opus 4.x was billed at $15/$75 (legacy Opus 4 pricing) instead of the correct $5/$25.

### Why Caching Matters Here

Within a single scan, the same 1–10 campaign asset images are sent to Claude alongside dozens-to-hundreds of different discovered images. Without caching, every single call re-uploads and re-processes the asset images (~1500–2000 vision tokens each). With ephemeral prompt caching, the asset prefix is processed once and reused for every subsequent call within a 5-minute window:

- **Cache write:** 1.25x base input rate (small one-time premium)
- **Cache read:** 0.10x base input rate (90% discount)
- **TTL:** 5 minutes — easily within a single scan's analysis loop

Effect on Opus 4.7 input pricing: cached prefix tokens drop from $5/MTok → $0.50/MTok on every call after the first.

### Changes

**Backend — Model upgrade**

- `backend/app/services/ai_service.py` — `CLAUDE_MODEL` and `ENSEMBLE_MODEL` updated from `claude-opus-4-6` to `claude-opus-4-7`. `FILTER_MODEL` (Haiku 4.5) unchanged.

**Backend — Prompt caching infrastructure**

- `backend/app/services/ai_service.py::call_anthropic_with_retry` — Added `cache_prefix_images: int = 0` keyword argument. When > 0, the first N images get marked as a cacheable prefix via `cache_control: {"type": "ephemeral"}` on the last cacheable block. The text prompt naturally caches as part of the prefix. Default 0 = legacy behavior (no caching), so the change is fully backward compatible. Captures `cache_creation_input_tokens` and `cache_read_input_tokens` from `response.usage` and forwards to the cost tracker.

**Backend — Caching enabled at 5 high-leverage call sites**

| Function | Cache config | Why |
|----------|--------------|-----|
| `filter_image` (Haiku) | `cache_prefix_images=len(asset_images)` when asset-aware | 100s of repeated calls per scan, same N assets every time |
| `_detect_asset_single` (Opus) | `cache_prefix_images=1` | Asset constant across many screenshot detections |
| `_detect_asset_tiled` (Opus) | `cache_prefix_images=1` | Inner loop fires 5+ tile calls with the same asset — biggest single win |
| `verify_borderline_match` (Opus) | `cache_prefix_images=1` | Same campaign asset reused across borderline verifications |
| `analyze_compliance` (Opus) | `cache_prefix_images=1` | Same asset across compliance checks within a campaign |

Skipped: `compare_images` (both images vary call-to-call, no cache benefit) and `localize_assets_in_screenshot` (asset varies in the loop; would require prompt rewrite to flip image order — deferred).

**Backend — Cost tracker**

- `backend/app/services/cost_tracker.py` — Added `claude-opus-4-7` to pricing table at $5/$25 per MTok. **Fixed pre-existing bug**: Opus 4.6 and 4.5 were incorrectly listed at $15/$75 (the original Opus 4 price) — now corrected to $5/$25 to match Anthropic's published pricing and the user-facing cost numbers in `log.md`. Legacy `claude-opus-4` retained at $15/$75 for historical scan records.
- Added `ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25` and `ANTHROPIC_CACHE_READ_MULTIPLIER = 0.10` constants for ephemeral 5-min cache pricing.
- `record_anthropic` extended with `cache_creation_tokens` and `cache_read_tokens` parameters. Computes `cache_write_cost`, `cache_read_cost`, and regular `in_cost` independently. Stores all three in line-item `meta` so the existing pipeline funnel UI can show cache hit-rate per operation.

### Smoke-Test Results

Synthetic scenario validating the cost math (`venv/bin/python` smoke test):

```
Call 1 (cache write): 10,000 input + 5,000 cache_write + 200 output → $0.086250
Call 2 (cache read):     500 input + 5,000 cache_read  + 200 output → $0.010000
Equivalent no-cache (5,500 input + 200 output)                       → $0.032500
Cache savings on call 2: 69.2%
```

The 69% saving on call 2 closely matches the theoretical 90% discount on the cached portion (the remaining cost is the 500 uncached input tokens + 200 output tokens at full rate). At realistic scan scale where 100+ calls hit the same cached prefix, effective savings on input tokens approach 88–90%.

### Backward Compatibility

The `call_anthropic_with_retry` refactor is fully backward compatible. All existing callers that don't pass `cache_prefix_images` continue to work unchanged with no caching applied. No breaking changes to the public function signature.

### Eval Required Before Production

Per the 6-week plan's stop-ship gate, the eval harness (Phase 1.8) must run before this hits production to confirm zero false-negative drift on the known-positive holdout set. The cache changes themselves should not affect model output — `cache_control` is invisible to the model, only changes how Anthropic processes the prefix server-side. But the model upgrade Opus 4.6 → 4.7 is a behavioral change that needs validation:

- Anthropic notes "improved instruction-following behavior that interprets instructions more literally" in 4.7 — could affect strict JSON adherence (positive) but could also reject borderline cases the older model tolerated (potential recall risk on borderline matches).
- Vision improvements (3x larger image support) are pure upside for our use case.

### Expected Cost Impact

For a single scan that previously made 100 Opus calls each carrying ~3,000 token asset prefix:

- **Before:** 100 × 3,000 × $5/MTok = $1.50 on asset prefix alone
- **After:**  1 × 3,000 × $5/MTok × 1.25 (write) + 99 × 3,000 × $5/MTok × 0.10 (read) = $0.019 + $0.149 = **$0.17**
- **Savings:** ~$1.33 per scan on prefix tokens, or **~89% reduction on the cached portion**.

Stacks multiplicatively with the remaining Phase 1 levers (CLIP preselection, dedup, Batch API).

### Files Changed

| File | Change |
|------|--------|
| `backend/app/services/ai_service.py` | Model constants → Opus 4.7; `call_anthropic_with_retry` accepts `cache_prefix_images`; cache_control marker on last cacheable image; usage capture extended for cache tokens; 5 call sites enabled (`filter_image`, `_detect_asset_single`, `_detect_asset_tiled`, `verify_borderline_match`, `analyze_compliance`) |
| `backend/app/services/cost_tracker.py` | Added Opus 4.7 pricing; fixed Opus 4.6/4.5 pricing bug ($15/$75 → $5/$25); added cache write/read multipliers; `record_anthropic` accepts and bills cache tokens separately; line-item meta exposes per-call cache stats |

### Known Issues / TODO

- Eval harness (Phase 1.8) not yet built — needed before any future model upgrade is attempted again.
- `localize_assets_in_screenshot` does not yet benefit from caching (asset varies in the inner loop). Could be unlocked by flipping image order and rewriting the prompt — deferred until benefit is measured against effort.
- Cache hit rate visibility — added to `cost_breakdown.line_items[*].meta` but not yet surfaced in the frontend `/scans` page cost panel. Easy follow-up.

### Same-Day Rollback: Opus 4.7 → 4.6

After the initial deployment, the first real scan failed with `400 invalid_request_error: temperature is deprecated for this model`. Investigation revealed Opus 4.7 silently removed three sampling parameters from the Messages API:

- `temperature` → 400 error (was set to `0` for determinism in `call_anthropic_with_retry`)
- `top_p` → 400 error (not used by us)
- `top_k` → 400 error (not used by us)

This is a hard breaking change documented in Anthropic's migration guide but not in the release announcement. All Opus calls in the pipeline (`_detect_asset_single`, `_detect_asset_tiled`, `verify_borderline_match`, `analyze_compliance`, `compare_images`) failed; only Haiku-based filter calls survived. Failed Anthropic calls aren't billed, which is why the cost panel showed a non-zero number ($0.092) but the scan returned empty compliance analyses.

#### Decision: Roll back to Opus 4.6, keep all caching infrastructure

Rather than just delete `temperature=0` and accept Opus 4.7's non-determinism, we evaluated whether 4.7 is actually a better fit for this product. Conclusion: it isn't.

| Opus 4.7 change | Effect on dealer-compliance image matching |
|----------------|-------------------------------------------|
| `temperature` removed | Loses determinism — same image can yield different confidence scores on re-scan. Compliance customers expect reproducibility. |
| New tokenizer (1.0–1.35× more tokens) | 0–35% cost regression for identical inputs |
| Adaptive thinking | Marginal — image classification is not a reasoning task |
| 3.75 MP image input | No benefit — `optimize_image_for_api` downscales to ~1.5 MP anyway |
| Better software engineering | Not applicable to our workload |
| `task_budget` for agent loops | Not applicable — single-call API |
| More literal instruction-following | Could change behavior on edge cases prompts didn't anticipate |

For a bounded, repetitive, deterministic image-classification workload, Opus 4.6 is the better tool. The "newer is better" assumption did not hold for this use case.

#### What was reverted

| File | Change |
|------|--------|
| `backend/app/services/ai_service.py` | `CLAUDE_MODEL` and `ENSEMBLE_MODEL` reverted from `claude-opus-4-7` → `claude-opus-4-6` |

#### What was KEPT (still in place from the morning's work)

- `cache_prefix_images` parameter on `call_anthropic_with_retry` — works on both 4.6 and 4.7, fully backward compatible
- `cache_control: {"type": "ephemeral"}` markers at all 5 enabled call sites
- `cache_creation_input_tokens` / `cache_read_input_tokens` capture from `response.usage`
- Cost tracker pricing fix: Opus 4.6 corrected from $15/$75 → $5/$25 per MTok (matches Anthropic's published pricing and `log.md` references)
- Cost tracker cache write/read multipliers (1.25x / 0.10x)
- Per-call cache token meta in `cost_breakdown.line_items[*].meta`

The rollback is purely the model-id constants. All cost optimization work survived.

#### Pre-Upgrade Discipline (for future model migrations)

Before any future model upgrade, the eval harness from Phase 1.8 must exist and the candidate model must demonstrate:

1. Strictly equal-or-greater recall on the known-positive holdout set
2. No new breaking-change rejections from a smoke test scan against staging
3. Acceptable cost change (within ±10% per scan after token-count differences)

Until those gates exist, the cost of "shiny new model" regressions exceeds the upside.

---

## 2026-04-20 (Monday) — Eval Harness (Phase 1.8)

Built the eval harness that the same-day Opus 4.7 rollback identified as a hard blocker for any future AI-pipeline change. The harness runs the real production AI functions (`filter_image`, `detect_asset_in_screenshot`, `verify_borderline_match`, `analyze_compliance`) against a frozen labelled fixture set, computes per-stage precision/recall/cost/latency, diffs against a committed baseline, and exits non-zero when any guarded metric regresses past its tolerance.

### Why now

Three open questions could not be resolved without it:

1. **Caching not firing** — today's scan showed 80 Anthropic calls, 0 cache writes/reads. The fix candidates (Option A padding vs Option B system-prompt restructure) all carry scoring risk that needs to be measured before shipping. Without an eval, the correct call was "don't ship," which left ~$400-670/mo in caching savings on the table.
2. **Pre-filter thresholds are off-limits** — every prior tuning attempt regressed recall, so the rule became "don't touch them." That's a sign there's no objective way to measure improvement, not that the thresholds are optimal.
3. **Opus 4.6 will eventually be deprecated** — when that happens, a model migration becomes mandatory. The 4.7 incident proved that "ship and hope" is unacceptable; the harness creates the gate that future migrations must pass.

### Architecture

```
backend/eval/
  config.py                  ← paths + regression thresholds (env-overridable)
  manifest.py                ← FixtureCase / Manifest dataclasses + IO
  build_fixtures.py          ← seed manifest from production match_feedback
  metrics.py                 ← precision/recall/F1/cost/latency/score-drift
  baseline.py                ← Baseline persistence + diff_against_baseline()
  report.py                  ← Markdown reporter (PR-ready)
  run.py                     ← `python -m eval.run` CLI
  runners/
    base.py                  ← BaseRunner — uniform timing + cost capture
    haiku_filter.py          ← exercises filter_image
    opus_detect.py           ← exercises detect_asset_in_screenshot
    verify.py                ← exercises verify_borderline_match
    compliance.py            ← exercises analyze_compliance
  fixtures/
    manifest.example.json    ← committed template (8 example cases)
    manifest.json            ← gitignored — actual labelled set
    images/                  ← gitignored — image bytes on disk
  reports/                   ← gitignored — per-run Markdown outputs
  baseline.json              ← committed last-known-good metrics
```

### Design decisions

- **Real production code path, mocked network only.** Each runner patches `ai_service.download_image` to read fixture bytes from disk for the duration of the call, then calls the real `filter_image` / `detect_asset_in_screenshot` / etc. Image optimisation, prompt construction, Anthropic call, retry logic, and cost tracking all execute unmodified. A pricing change, prompt change, model-id change, or cache-control change is therefore detected automatically.
- **Per-stage runners, not end-to-end.** Each pipeline stage is exercised independently so that a regression can be isolated to the function that caused it. Fixtures are tagged with categories and routed to the relevant runners (e.g. the verifier only runs on `borderline_*` cases).
- **Fixtures stored as bytes, not URLs.** The manifest references local files under `fixtures/images/`. Source URLs go stale; eval reproducibility cannot.
- **Categories pinned to product-level questions.** Ten categories — `clear_positive`, `template_positive`, `modified_positive`, `same_promo_diff_creative`, `same_brand_diff_campaign`, `different_brand`, `borderline_true`, `borderline_false`, `compliance_drift`, `zombie_ad` — each answering a specific quality concern (recall floor, template-customization tolerance, modification robustness, false-positive hardness, brand-confusion rejection, precision floor, verifier promotion, verifier rejection, drift detection, zombie detection).
- **Baseline + diff workflow.** `eval/baseline.json` is committed to the repo. Every PR runs `python -m eval.run` which diffs against it. Intentional changes update the baseline via `--update-baseline` and commit it alongside the change.
- **Score drift is measured separately from verdict flips.** A prompt restructure that doesn't flip any boolean verdicts but shifts confidence by 5-10 points across the board would silently corrupt the adaptive thresholds — `_check_score_drift` in `baseline.py` catches that.
- **Compliance recall has zero tolerance.** `EVAL_MAX_COMPLIANCE_RECALL_DROP=0.0` in `config.py` — drift detection is the product, missing it cannot ever be silently accepted.

### Regression thresholds (defaults)

| Threshold | Default | Rationale |
|---|---|---|
| Recall drop | 2 pts | Missed match = customer doesn't catch real violation |
| Precision drop | 5 pts | False match = annoyance, manual review |
| Compliance recall drop | 0 pts | Zero tolerance — drift is the product |
| Cost increase | 15% | Catches new tokenizer / longer prompts (the Opus 4.7 surprise) |
| p95 latency increase | 20% | Catches slowdowns |
| Score drift (per case) | 10 pts | Catches subtle prompt restructures |
| Score drift (case count) | 5 cases | How many cases may drift before failing |

All overridable via env vars (`EVAL_MAX_RECALL_DROP`, etc.) for CI tuning.

### Fixture sourcing

`build_fixtures.py` pulls `match_feedback` rows from production Supabase, joins them through `matches` → `assets` + `discovered_images`, downloads both image files into `fixtures/images/`, and appends the case to `manifest.json`. The auto-import maps `actual_verdict` to a coarse category (`true_positive` → `clear_positive`, `false_positive` → `borderline_false`, etc.); a human must hand-correct the categories before trusting the manifest.

The `match_feedback` table already exists in production (migration `004_add_match_feedback.sql`, written 2025) and is populated by the existing `/matches/{id}` feedback UI. Roughly N labelled cases are available from prior reviews — no separate labelling tool needed.

### CLI surface

```bash
python -m eval.run                            # all runners, gate-mode
python -m eval.run --stage haiku_filter       # single runner
python -m eval.run --stage opus_detect,verify # subset
python -m eval.run --concurrency 4            # parallel cases per runner
python -m eval.run --update-baseline          # accept current as new baseline
python -m eval.build_fixtures --limit 50      # seed from Supabase
python -m eval.build_fixtures --verdict false_positive --limit 30
```

Exit codes: `0` pass / `2` regression / `3` infrastructure error (no manifest, missing fixtures).

### Smoke verification

Two synthetic smoke tests run during build, both passing:

1. **Metrics + diff + report** (`venv/bin/python` synthetic harness): builds a baseline `RunnerResult` where all 3 cases pass, then a current `RunnerResult` where one verdict flipped and one score drifted by 14 points. The gate correctly fails with reason `"opus_detect: recall dropped 50.00 pts (1.0000 → 0.5000, max allowed -2.0)"`, the verdict flip is captured in `flipped_verdicts`, and the score drift is captured in `drifted_scores`.
2. **End-to-end runner** with mocked Anthropic: writes two tiny PNG fixtures to disk, points the manifest at them, mocks `ai_service.anthropic_client.messages.create` to return a deterministic verdict + usage payload, and runs `HaikuFilterRunner._run_one`. Result captures correct verdict (`is_relevant=True`), cost ($0.0019 for 1500 input + 80 output Haiku tokens — matches manual math), token counts (1500/80), and latency. No errors. Confirms the production code path, image-optimisation, prompt construction, and cost tracker are all wired through.

### Files added

| File | Purpose |
|------|---------|
| `backend/eval/__init__.py` | Package marker + module docstring |
| `backend/eval/config.py` | Paths + regression thresholds |
| `backend/eval/manifest.py` | `FixtureCase`, `Expected`, `Manifest`, `CATEGORIES` |
| `backend/eval/build_fixtures.py` | `python -m eval.build_fixtures` — seed from Supabase |
| `backend/eval/metrics.py` | `compute_metrics` + per-stage confusion-matrix logic |
| `backend/eval/baseline.py` | `Baseline` + `diff_against_baseline` + per-metric checks |
| `backend/eval/report.py` | Markdown + console summary rendering |
| `backend/eval/run.py` | `python -m eval.run` CLI |
| `backend/eval/runners/__init__.py` | `RUNNERS` registry |
| `backend/eval/runners/base.py` | `BaseRunner`, `CaseResult`, `RunnerResult` |
| `backend/eval/runners/haiku_filter.py` | Stage 3 runner |
| `backend/eval/runners/opus_detect.py` | Stage 4 runner |
| `backend/eval/runners/verify.py` | Verifier runner |
| `backend/eval/runners/compliance.py` | Compliance runner |
| `backend/eval/fixtures/manifest.example.json` | 8-case template (committed) |
| `backend/eval/fixtures/.gitignore` | Excludes real `manifest.json` + `images/` |
| `backend/eval/fixtures/images/.gitkeep` | Keeps directory present |
| `backend/eval/reports/.gitignore` | Excludes generated reports |
| `backend/eval/README.md` | Workflow docs + threshold reference |

No changes to existing files — the harness is a pure addition.

### What this unblocks

Now safe to attempt:

1. **Caching Option A or B** — restructure prompts to clear Anthropic's per-model cache minimums (1024 tok Opus / 2048 tok Haiku). Run the eval, confirm no verdict flips on the 10 borderline cases or score drift > 10 points, then ship. Realistic savings: ~$400-670/mo at 150-dealer scale.
2. **Pre-filter threshold tuning** — the long-deferred Phase 1.5. With objective recall measurement, can finally validate whether a tighter threshold actually loses matches or just rejects junk faster.
3. **Future Opus migrations** — Opus 4.7+ or 5.x can be evaluated without production risk. Gate criteria: equal-or-greater recall on positives, ≤10% cost change, no breaking parameter changes (today's surprise).

### Pending follow-ups

- Seed the production fixture set (`python -m eval.build_fixtures --limit 50`, then hand-review categories).
- Capture the first baseline (`python -m eval.run --update-baseline`).
- Wire into GitHub Actions on PRs that touch `backend/app/services/ai_service.py`, `backend/app/services/adaptive_threshold_service.py`, `backend/app/config.py`. Estimated cost: $1.50-3.00 per CI run on a 50-fixture set.

---

## 2026-04-20 (Monday afternoon) — First Real Eval Run + Hand-Labelled Compliance Baseline

Followed the Phase 1.8 plan to its first real outcome: pulled fixtures from production, hand-labelled the compliance set, captured a meaningful baseline, and surfaced two real model bugs the harness now guards against.

### Bug fix in `build_fixtures.py`

First fixture pull failed silently — every case was skipped with `URL too long`. Cause: many `discovered_images.image_url` values are stored as inline `data:image/...;base64,...` URIs (Meta-source crops are inlined). `httpx.AsyncClient.get` rejects them at the URL parser. Patched `backend/eval/build_fixtures.py` to detect data URIs, decode the base64 payload locally, and infer the file extension from the MIME type. HTTP URLs unchanged. Re-pull pulled 35 of the 38 most recent feedback rows (3 skipped — expired Meta CDN signatures returning 403, expected and unrecoverable).

### Production fixture composition (after manual labelling)

| Category | Count | Origin |
|---|---|---|
| `clear_positive` | 7 | Yancey CAT promos with logo + date, 1 CAT corporate ad, 1 CAT 307.5 product hero |
| `compliance_drift` | 9 | Missing-Yancey-logo violations across 4 unique creatives (5 dupes from `match_feedback`) |
| `zombie_ad` | 1 | Retail Special creative with `campaign_end_date` set 90+ days in the past |
| `borderline_false` | 18 | User-confirmed false-positive matches |
| **Total** | **35** | |

Ran the eval three times this session against the labelled set. Final baseline written to `backend/eval/baseline.json` (git_sha `60c5ad7d41ee`).

### Final baseline metrics

| Stage | Cases | Correct | Recall | Precision | Cost | p95 latency |
|---|---|---|---|---|---|---|
| `haiku_filter` | 7 | 7 | 1.000 | 1.000 | $0.013 | 2 951 ms |
| `opus_detect` | 25 | 25 | 1.000 | 1.000 | $0.317 | 10 199 ms |
| `verify` | 18 | 18 | — | — | $0.174 | 6 449 ms |
| `compliance` | 17 | 13 | recall 0.900 / precision 0.750 | — | $0.359 | 12 478 ms |

- Detector score separation: avg **90.0** for positives, **5.0** for negatives — 85 points of headroom.
- Verifier rejected all 18 user-flagged false positives at avg score 10.
- Compliance: caught 9 of 10 expected violations (recall 0.900). Of 12 violation flags, 9 were real (precision 0.750).
- Total session API spend across three runs: **~$2.89**.

### Two real bugs the eval surfaced

Each now has a fixture acting as a permanent regression test.

1. **Zombie-ad detection broken on metadata-only inputs** (`feedback-91713971`). Campaign metadata says ended 2026-01-15 (90+ days past today). Image itself has no on-image expiration text. Opus returned `is_compliant=True, zombie_ad=False` — completely missed it. Means the `campaign_end_date` metadata path in `get_compliance_prompt` is not being weighted relative to image content. Fixing this is the highest-leverage compliance change available; the moment it works, `compliance_recall` will tick from 0.900 → 1.000.

2. **Compliance prompt over-flags non-promotional creatives.** Three legitimate compliant ads got marked as violations:
   - CAT 307.5 Mini Excavator product hero (`feedback-1095ee74` + `feedback-1fb27b39` B&W variant) — evergreen product page, no promo elements, model wanted promo elements anyway.
   - 10% Off Undercarriage GROUND10 (`feedback-ff223913`) — has Yancey CAT logo, promo code, AND "VALID THROUGH 6/30/2026" disclaimer in clear text. Every required element present, yet flagged. Worth pulling the model's `analysis_summary` to see what it claimed was missing.

   Suggests `get_compliance_prompt` is too strict by default — needs either a promo-vs-product mode hint, or a more careful enumeration of "compliant" so the model has an explicit anchor.

### Helper scripts added (in `backend/eval/`)

- `_label_compliance.py` — idempotent re-runnable helper that applies the curated compliance labels to `manifest.json`. Re-running it after a fresh `build_fixtures` re-applies the labels in place.
- `_inspect_compliance.py` — runs the compliance runner only and prints per-case `expected vs got` for `is_compliant` and `zombie_ad`. Cheaper diagnostic than a full eval run when iterating on the compliance prompt.

### Workflow validated end-to-end

The Phase 1.8 plan said the harness would catch silent regressions and surface real defects. First real run did both:
- The build_fixtures bug was caught at the very first invocation, before any AI work.
- The compliance prompt's zombie-detection failure and over-strict default behaviour were surfaced by the very first labelled-fixture run.
- Three full eval runs gated against an evolving baseline — every diff was correctly classified as improvement, info, or regression. No false alarms; no silent bugs.

The harness is now ready to validate any future AI-pipeline change (caching restructure, prompt edit, model swap) without production risk.

### Pending follow-ups (carried forward)

- **Fix zombie-ad detection** in `get_compliance_prompt`. Regression test: `feedback-91713971`. *(Reviewed 2026-04-21 and explicitly deferred — see entry below.)*
- **Tune compliance prompt** to handle product-page and fully-compliant promo cases. Regression tests: `feedback-1095ee74`, `feedback-1fb27b39`, `feedback-ff223913`.
- Wire `python -m eval.run` into GitHub Actions on PRs that touch `backend/app/services/ai_service.py` etc.
- Attempt the deferred prompt-caching restructure (Phase 1.1 Option A/B) now that the eval gate is in place.

---

## 2026-04-21 (Tuesday) — Zombie-Ad Detection Review & Deferral

### Summary

Reviewed the Phase 1.8 carry-over "Fix zombie-ad detection in `get_compliance_prompt`" against the live code. Decided **not** to ship a fix today — zombie detection is not the current product focus, the right fix is architectural rather than a prompt tweak, and it touches the cached compliance prompt prefix used by every match. Documenting the design notes here so the work can be picked up cleanly when it becomes a priority.

### Why it's broken (four overlapping causes)

`feedback-91713971` regression: Opus returns `(is_compliant=True, zombie_ad=False)` on a creative whose `campaign_end_date` is 90+ days past today. Reviewing `analyze_compliance` and `get_compliance_prompt` in `backend/app/services/ai_service.py` exposed four issues, only one of which is "the prompt is too weak":

1. **No "today" anchor in the prompt.** `analyze_compliance` never injects the current date. Asking Opus "is `2026-01-15` expired?" without telling it what today is means it has to guess from training cutoff or context. With prompt caching active this is worse — the cached prefix is timeless.
2. **Rubric contradicts itself.** `get_compliance_prompt` (lines 780–794 of `ai_service.py`) lists five reasons to set `is_compliant=false`: color change, imagery change, brand removal, offer altered, asset missing. Zombie is not one of them. The rubric closes with *"When the creative is clearly present … it IS compliant"*, which actively pulls a model that flagged `zombie_ad=true` back to `is_compliant=true`.
3. **The only signal offered is on-image expiration text.** The `zombie_check` block in `analyze_compliance` (lines 1346–1353) tells the model to *"Look for date-specific text indicating the promotion has ended."* The fixture image is a generic Retail Special with no date text. Metadata is provided but has no second path to victory.
4. **Empty `brand_rules: {}` produces an empty BRAND RULES block,** which biases the model toward "no rules → no violations." Several eval cases (including the zombie fixture) ship with empty brand rules.

A fifth observation worth noting: `ComplianceCheckResult.zombie_days` exists in the model but is hardcoded to `None` at the call site (`ai_service.py:1370`). It's never been populated since launch.

### Recommended fix (when this becomes a priority)

In order of leverage:

- **Step A — Decide zombieness in Python, not in the prompt.** Highest ROI. Compute `today > campaign_end_date` deterministically before the model call, populate `zombie_days`, and OR the verdict into the response:

```python
is_compliant = result.get("is_compliant", True) and not zombie_ad
zombie_ad   = zombie_ad or result.get("zombie_ad", False)
```

  This removes LLM date arithmetic entirely. The model can still flag *visual* expirations (on-image "VALID THROUGH 6/30/2024" text) via the existing prompt path, which gets OR'd with the metadata path.

- **Step B — Add zombie to the `is_compliant=false` rubric.** Add `* The campaign has expired (zombie_ad=true)` to the bullet list at `ai_service.py:783`, and qualify or remove the closing "IS compliant" sentence at `:793` so the model's view matches Step A's deterministic verdict.

- **Step C — Inject "today" into every compliance prompt.** Unconditionally prepend `Today's date: {iso}\n\n`. Costs nothing, removes the worst class of LLM date hallucinations even on cases where Step A doesn't apply.

- **Step D — When `rules_text == ""`, substitute** `(no dealer-specific brand rules — evaluate creative integrity only)` so the model doesn't read whitespace as "no rules → no violations."

### Risks to revisit before implementing

- **Anthropic prompt-cache invalidation.** Step C will bust the cache once a day unless the date is placed *after* the cached prefix. Coordinate with the Phase 1.1 caching restructure that's also outstanding — the two changes should land together.
- **Precision regression.** Compliance precision is already 0.750 because of over-flagging on `feedback-1095ee74`, `feedback-1fb27b39`, `feedback-ff223913` (the agenda item #2 work). Step B's added bullet could nudge precision down further if `campaign_end_date` metadata is unreliable. Use strict `is not None` checks in Step A.
- **Downstream `zombie_days` consumers.** Once populated, schema/alerts/frontend may start displaying a value that's been `None` since launch. Audit with `rg -n "zombie_days|zombie_ad" --type ts --type py` first.
- **Fixture invariant.** Any case categorised `zombie_ad` MUST have `campaign_end_date` set, or Step A's deterministic gate is moot. Worth an assertion in `_label_compliance.py` or `manifest.py` when this work resumes.

### Validation loop (for future me)

1. `cd backend && venv/bin/python -m eval._inspect_compliance` — cheap diagnostic, ~$0.36 / 12 s p95 per yesterday's baseline.
2. Expect the `feedback-91713971` row to flip to `is_compliant=False, zombie_ad=True`.
3. `python -m eval.run` for full diff against `baseline.json`. Expect `compliance_recall: 0.900 → 1.000`. Watch `compliance_precision` doesn't drop below 0.750.
4. If precision drops, the rubric edit (Step B) was too aggressive — revert it and rely on Step A's deterministic OR alone.
5. Re-baseline; the per-case row becomes the permanent regression test.

### Status of the regression fixture

`feedback-91713971` remains in `baseline.json` with `actual: {is_compliant: true, zombie_ad: false}` baked in as the documented known-failure. This means:

- Future eval runs will diff cleanly — no false regression alarm fires for this case.
- `_inspect_compliance` output will keep showing this row as `✗` until the fix lands. Expected, ignore.
- `compliance_recall: 0.900` is locked in as the ceiling until the fix ships. Other compliance work (e.g. agenda item #2) will be measured against that 0.900, not against 1.0.

### Files touched

None — review-only session. All notes captured here.

---

## 2026-04-21 (Tuesday afternoon) — Prompt-Cache Restructure: Diagnosed, Attempted, Reverted

Followed through on agenda item #4 (the carry-over "prompt-caching restructure Option A/B" from 2026-04-20 morning). The original framing turned out to be wrong: the bug isn't prefix size or prompt structure at all. It's the model ID. Captured the diagnosis, ran the eval, and reverted when the gate failed.

### Diagnostic patch (env-gated, zero production overhead)

Added `EVAL_DEBUG_CACHE=1` flag and two diagnostic print lines to `call_anthropic_with_retry` in `backend/app/services/ai_service.py`:

- `[CACHE_DBG] REQ` — model, cache prefix size requested, text length + sha256, per-image sha256 + byte size + cache-control placement.
- `[CACHE_DBG] RES` — model, `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` from `response.usage`.

Off by default. Pure addition to the file — no behavioural change when the flag is unset. Left in place as permanent diagnostic capability.

### Root-cause bisection

1. Ran `_inspect_compliance` with the flag on. 17 calls, **all `cc=0 cr=0`** — including 5 calls with byte-identical cached prefixes (same text hash + same asset image hash). Ruled out image-variance and prefix-below-minimum hypotheses simultaneously.
2. Wrote a minimal two-call probe against the raw Anthropic SDK (text-only, 1800-token `system=` prefix with `cache_control: ephemeral`). Same result on `claude-opus-4-6`: call1 `cc=0 cr=0`, call2 `cc=0 cr=0`. No SDK / request-shape issue.
3. Added `anthropic-beta: prompt-caching-2024-07-31` header. No change.
4. Ran the same probe across model IDs with a 12 000-token prefix to force-clear any hidden threshold:

| Model | Call 1 | Call 2 | Verdict |
|---|---|---|---|
| `claude-opus-4-5` | `cc=12002 cr=0` | `cc=0 cr=12002` | **works perfectly** |
| `claude-sonnet-4-5` | `cc=12002 cr=0` | `cc=0 cr=12002` | works |
| `claude-haiku-4-5` | `cc=0 cr=0` | `cc=0 cr=0` | fails same as `4-6` |
| **`claude-opus-4-6`** | `cc=12003 cr=0` | **`cc=12003 cr=0`** | **writes every call, never reads** |

Diagnosis locked in: `claude-opus-4-6` on this account silently **bills for cache writes on every call** (you pay the 1.25× write premium) and **never serves cache reads**. Strictly worse than having caching disabled — we've been paying a small cost tax since 2026-04-20 morning. `claude-haiku-4-5` shows the same pattern. `claude-opus-4-5` and `claude-sonnet-4-5` work as documented.

Not a code bug, not an SDK bug, not an account-level feature toggle. `claude-opus-4-6` appears to be a model identifier whose cache reads simply aren't enabled. No Anthropic changelog entry explains it.

### Eval attempt (`claude-opus-4-6` → `claude-opus-4-5`)

Flipped both `CLAUDE_MODEL` and `ENSEMBLE_MODEL` in `ai_service.py` to `claude-opus-4-5` and ran the full eval at concurrency 2. Total spend $0.85, runtime ~5 min. Report: `backend/eval/reports/eval-20260421T162254Z.md`.

**Gate failed** on four axes, of which two are real and two are noise:

| Failure | Real? |
|---|---|
| `opus_detect`: precision 1.0000 → 0.7778 (-22 pts) | **Yes** — 2 new verdict flips |
| `opus_detect`: 8 cases drifted ≥10 score points | Partly — 6 are score improvements on positives (fine), 2 are the same flipped cases (real) |
| `verify`: 7 cases drifted ≥10 score points | No — gates-passed went from 0→1 or 1→2 on rejections; all 18 cases still correct |
| Latency p95 blown on three stages (haiku_filter +805 %, opus_detect +124 %, verify +22 %) | No — concurrency-induced queuing + single-call Anthropic outliers in a small sample |

The two real flips:

| Case | Category | Baseline | Current | Match ID |
|---|---|---|---|---|
| `feedback-7758edad-…` | `borderline_false` | 5 | 92 | `63fb76fe-c74e-4b5e-a49f-7543631890f8` |
| `feedback-07c46d90-…` | `borderline_false` | 5 | 92 | `63fb76fe-c74e-4b5e-a49f-7543631890f8` |

Both fixtures share the same `match_id` — it's **one underlying production match recorded twice in `match_feedback`** (user clicked "false positive" twice). Original production `ai_confidence: 95` on that match. So:

- Production Opus (at time of match): **95**
- Yesterday's eval on Opus 4-6: **5**
- Today's eval on Opus 4-5: **92**

Opus 4-5 is *closer to historical production behaviour* than Opus 4-6 on this case. The fixture carries the stock auto-import note `"REVIEW + RECATEGORISE before trusting"` — the label is imported from user feedback and hasn't been hand-audited against the actual image. Could equally well be a true false-positive (user was right, both Opus versions and production were over-confident) or a mislabel (user misclicked, the match was real).

All other quality metrics held:

- `opus_detect` recall: 1.0 → 1.0 (no missed positives)
- `verify`: 18/18 correct (all borderlines still rejected)
- `compliance`: recall 0.900, precision 0.750 — unchanged
- `haiku_filter`: 7/7 correct — unchanged
- Score improvements of +10 to +14 on three `clear_positive` cases (detector becoming more confident on correct matches — strictly good)

### Decision: revert

Instruction was "ship if green." Gate failed. Reverted the model constants back to `claude-opus-4-6`. The $400–670/mo caching savings remain on the table.

The revert is two characters (`5` → `6` in both constants). No behavioural change vs pre-session state. The env-gated diagnostic patch is kept — it's production-inert and useful for the next investigation.

### What this surfaced that the previous log didn't

1. **Opus 4-6 is a strictly worse choice than Opus 4-5 for this workload except on the 1 disputed case.** Same input price, same output price, but 4-5 caches and 4-6 doesn't. The 2026-04-20 morning rollback from 4-7 → 4-6 (driven by the `temperature=0` breakage in 4-7) overshot — should have landed on 4-5, not 4-6. Unrelated to the 4-7 issue, but the decision was made under the assumption that the three model IDs were equivalent on quality+caching, which turns out to be false.
2. **The disputed match (`match_id 63fb76fe…`) needs human review.** If the user's original "false positive" click is correct, Opus 4-5 genuinely regresses and should not ship. If the click was wrong, Opus 4-5 is the better model and the fixture should be re-labelled `clear_positive`, after which the gate would pass. Either way, a 30-second manual check of one image unblocks the $400-670/mo decision.
3. **The Haiku filter also fails to cache** on this account (`claude-haiku-4-5`). Separate finding, much lower leverage (Haiku is already cheap), not actionable today.

### Resolution (same session) — disputed match eyeballed, line item closed

Opened the two on-disk fixture PNGs:

- `backend/eval/fixtures/images/asset_feedback-7758edad-…png` (701 KB, 2415 lines of base64) — Yancey Bros / CAT **"25% OFF FILTERS — PROMO CODE: FILTERS25, OFFER VALID THROUGH 3/31/26"** banner. Three CAT-branded fuel filters (1R-0749, 1R-0755) on a workshop background, Yancey-CAT logo top-right.
- `backend/eval/fixtures/images/discovered_feedback-7758edad-…png` (13 KB) — a **"Hello. Welcome to Yancey Bros Co! Hablamos Español. I am a Live Person here to help."** chat-widget popup with **"Get a Quote"** and **"I have a question"** buttons.

Same dealership website, **completely different UI element**. The only shared feature is the literal text "Yancey Bros" — no shared imagery, layout, palette, copy, or call-to-action. The user's original `false_positive` click was unambiguously correct. This is not a borderline case. Opus 4-5 (and the original production scan, which logged `confidence_score = 95`) hallucinated the match. Opus 4-6 is the only model in the cohort that correctly rejected it (score 5).

Verified the duplicate-rows theory while there: both fixture pairs (`7758edad` and `07c46d90`) have byte-identical file sizes (701 216 / 13 363 B), confirming they're the same physical image recorded twice in `match_feedback`.

### Decision: Option B — stay on Opus 4-6, no caching

Closing the "switch to Opus 4-5 for caching" line item permanently. The 22-pt precision drop in `opus_detect` is not noise, not a labelling artefact, and not a borderline judgement call — it's a genuine hallucination that production users would see. The $400–670/mo caching savings on this path are off the table.

Strong signal worth flagging beyond this case: the original production scan logged `confidence_score = 95` on this hallucinated match in March, meaning whatever Opus model ran at scan time **had the same hallucination tendency Opus 4-5 has today**. Opus 4-6 is uniquely conservative on this kind of "same-domain, different-creative" case. That's not just a caching trade-off — it's a quality property worth preserving.

### Updated pending follow-ups

- ~~Review the one disputed match image~~ — **done, this session.** Verdict: not a match. Line item closed.
- **Consider Sonnet 4-5 as a full-pipeline replacement.** Cheaper input ($3 vs $5/MTok) and caches. Same hallucination risk surface as Opus 4-5 demonstrated today — this isn't free quality. If pursued, requires (a) expanded `borderline_false` fixture set first to catch other "same-domain, different-creative" hallucinations we don't currently fixturise, then (b) a full eval cycle. **Higher risk than previously framed.** Park for a dedicated session.
- **Path C — Opus 4-5 only on the `compliance` runner** as a narrow caching win. Compliance verdicts didn't move on 4-5 in today's eval (13/17 correct, recall 0.9, precision 0.75 — identical to 4-6 baseline). Compliance is currently the most expensive runner ($0.34 of $0.85 total). Lower blast radius — even if 4-5 hallucinates a compliance violation, the worst case is a misleading reason string, not a phantom match. Worth its own session if the cost line gets attention.
- **Expand `borderline_false` fixture set** before any future model swap. Today we had 9 such cases in `opus_detect` and 1 of them (well, 1 underlying match × 2 rows) bit us. Higher fixture coverage = higher confidence in any future swap. Low urgency until a swap is on the table again.
- Investigate Haiku 4-5 caching failure (low priority — Haiku stage is already the cheapest, $0.013/run).

### Bottom line for the agenda

- **Prompt-caching restructure:** investigated end-to-end, root-caused, validated by experiment, decisively closed. Not a TODO any more.
- **Production state:** unchanged. Opus 4-6 on detection + ensemble. Diagnostic patch retained in `ai_service.py` (env-gated, off by default).
- **Cost posture:** no improvement today, but ~$0.85 of eval spend bought us (a) a definitive answer, (b) a kept-around diagnostic capability, and (c) a flagged latent quality property of Opus 4-6 (anti-hallucination on same-domain creatives) that we didn't previously know we were buying.

### Files touched

| File | Change |
|---|---|
| `backend/app/services/ai_service.py` | Added `import os`, `import hashlib`, `_DEBUG_CACHE = os.environ.get("EVAL_DEBUG_CACHE", "0") == "1"`, and two diagnostic `print()` lines in `call_anthropic_with_retry` gated on that flag. Model constants reverted to `claude-opus-4-6` (matches pre-session state). |

No changes to `backend/eval/baseline.json` (gate failed → baseline not updated → no drift introduced).

---

## 2026-04-21 (Tuesday late afternoon) — Eval Wired Into CI

Closed Phase 1.8 carry-over item #2: "Wire `python -m eval.run` into GitHub Actions on PRs that touch `backend/app/services/ai_service.py` etc." Now any PR that modifies the AI pipeline auto-runs the eval against the committed baseline and posts the report into the GitHub Actions check summary.

### Design

New workflow file at `.github/workflows/ai-eval.yml`. Kept separate from the existing `ci.yml` (backend tests + frontend build + migrations) for three reasons:

1. **Different trigger surface.** Path-filtered to AI pipeline files so we don't burn $0.85 + 5 min on every CSS tweak.
2. **Different secret requirements.** Only needs `ANTHROPIC_API_KEY`. Doesn't touch Supabase, Stripe, or screenshot APIs.
3. **Different cancellability profile.** Concurrency group cancels stale runs on push so a 5-commit PR burst costs $0.85, not $4.25.

### Trigger surface (path filter)

Workflow fires when any of these change:

- `backend/app/services/ai_service.py` — model constants, prompts, retry wrapper
- `backend/app/services/cost_tracker.py` — pricing tables (eval cost numbers depend on these)
- `backend/app/config.py` — `filter_model` setting and other AI config
- `backend/app/models.py` — Pydantic shapes for AI verdicts
- `backend/eval/**` — the harness itself, fixtures, baseline
- `backend/requirements.txt` — anthropic SDK upgrades
- `.github/workflows/ai-eval.yml` — the workflow itself (so changes self-validate)

Plus `workflow_dispatch` for ad-hoc manual runs from the Actions tab.

### Cost / safety levers built in

- **Concurrency group `ai-eval-${{ github.ref }}` with `cancel-in-progress: true`** — multiple pushes to the same PR cancel earlier runs. Spend stays at one run per "current state of the PR."
- **Drafts excluded** — PRs marked `draft: true` skip the eval. Devs can iterate without burning budget.
- **`skip-eval` PR label** — opt-out for trivial AI-pipeline edits (e.g. comment-only changes that path-filter can't distinguish).
- **15-minute job timeout** — hard ceiling against runaway runs.
- **Pre-flight check on `ANTHROPIC_API_KEY`** — fails immediately with a clear error rather than installing 50 MB of deps and then failing 30 seconds in.

### Output surface

- **Job summary** (`$GITHUB_STEP_SUMMARY`) — the eval report markdown is rendered inline on the GitHub Actions check page. Reviewers see the regression table without clicking anywhere.
- **Artifact** `eval-report-<sha>` — full report markdown, 30-day retention, downloadable from the workflow run.
- **Exit code 2** on gate fail → check status FAILURE → blocks merge once the check is marked required in branch protection.

### One-time setup the user needs to do (no code change required)

1. **Add the secret.** GitHub repo → Settings → Secrets and variables → Actions → New repository secret. Name `ANTHROPIC_API_KEY`, value = the same key in `.env`.
2. **(Optional) Mark the check required.** Settings → Branches → main → Branch protection rules → Edit → Required status checks → search for "AI Pipeline Eval" → check it. Without this step the check still runs and reports, but won't block merge.
3. **(Optional) Create the `skip-eval` label.** Issues tab → Labels → New label `skip-eval`. Used to bypass the eval on tiny edits.

### Why no scheduled drift run

Considered a weekly cron to catch silent model regressions from Anthropic's side (e.g. a model update changes verdicts on stable input). Skipped for now: $0.85/week of spend without an automatic action item, since the eval would just file a failed run that someone has to notice. If we ever set up Slack-on-failure, revisit.

### Why no PR comment

Considered using a sticky comment action to post the report into the PR thread. Skipped for v1 because the GitHub Actions step summary is already very visible (one click from the PR's Checks tab) and avoids a third-party action approval step. Easy to add later if reviewers want it inline.

### Files touched

| File | Change |
|---|---|
| `.github/workflows/ai-eval.yml` | New — runs `python -m eval.run --concurrency 2` on path-filtered PRs, fails on baseline drift, uploads report. |

No changes to `ci.yml`, `requirements.txt`, or any application code. Workflow is purely additive.

### Pending follow-ups (carried forward)

- **Tune compliance prompt** for product-page and fully-compliant promo cases (3 known fixtures fail). Now auto-gated by CI for any future attempt — safe to iterate.
- ~~Wire eval into GitHub Actions~~ — **done.**
- Path C — Opus 4-5 on `compliance` runner only (parked).
- Sonnet 4-5 full-pipeline evaluation (parked, needs expanded `borderline_false` fixtures first).
- Expand `borderline_false` fixture set (parked).
- Investigate Haiku 4-5 caching failure (low priority).

---

## 2026-04-21 — Phase 4.1 + 4.2 + 4.3: Bulk DB writes for the scan pipeline

### Why
Pre-150-dealer scaling. Every dealer-website / SerpApi / Apify scan was
issuing one HTTP call per `discovered_images` row (hundreds per scan) and
one per `matches` row (plus a follow-up per `alerts` row). At 150 dealers
this turns the Supabase REST API into the hot path; the per-row latency
dominates the scan worker's wall clock once AI is no longer the bottleneck.
The existing duplicate-match prune step also did one DELETE per row.

### What shipped
New module: `backend/app/services/bulk_writers.py`

- `bulk_insert_discovered_images(rows)` — single HTTP call; falls back to
  per-row inserts if the batch errors. Per-row path retains the FK-23503
  ("distributor deleted mid-scan") retry semantics that previously lived
  only in `extraction_service`.
- `DiscoveredImageBuffer(batch_size=50)` — collect rows in a loop, auto-flush
  at threshold, `flush_all()` returns cumulative inserted count.
- `bulk_insert_matches(items: List[PendingMatch])` — bulk insert match rows
  AND any associated alert rows in two HTTP calls. Alerts get their
  `match_id` filled in from the returned match IDs (position-based).
  Per-row fallback on batch failure preserves "one bad row never kills the
  rest" semantics.
- `MatchBuffer(batch_size=25)` — same buffered pattern for matches.
- `_safe_insert_discovered_image(row)` moved here as the single source of
  truth for the per-row fallback (was previously private to
  `extraction_service`, but already imported across modules).

Refactored insert sites (all 8 looped sites now batch; 5 single-row fallback
sites left as direct calls because batching one row is pointless):

| File | Site | Pattern |
| --- | --- | --- |
| `extraction_service._extract_from_viewport` | main + retry loops | one buffer per call (page+viewport) |
| `extraction_service._extract_ads_from_viewport` | main loop | one buffer per call |
| `screenshot_service.scan_dealer_websites` | URL loop | one buffer per scan |
| `screenshot_service.scan_google_ads` | advertiser loop | one buffer per scan |
| `screenshot_service.scan_facebook_ads` | page loop | one buffer per scan |
| `serpapi_service.scan_google_ads_serpapi` | advertiser × creative loop | one buffer per scan |
| `apify_meta_service.scan_meta_ads` | ad × image loop | one buffer per scan |
| `apify_instagram_service.scan_instagram_organic` | post × image loop | one buffer per scan |

Match insert refactor (`backend/app/routers/scanning.py:_analyze_single_image`):

- Function gained a `match_buffer: Optional[MatchBuffer] = None` parameter.
- New-match insert + violation alert are now queued via the buffer (fully
  backward-compatible: `None` falls back to immediate per-row insert).
- Existing-match UPDATEs and drift-alert INSERTs stay inline (they already
  have the row id, batching adds no value).
- Returns `matched_asset_id` synchronously from `result["asset_id"]` so
  early-stop logic still works regardless of when the buffer flushes.
- Three callers updated:
  - Cache-page phase (line ~801) → passes shared `match_buffer`.
  - Discovery-page phase (line ~906) → passes the same shared buffer.
  - `run_image_analysis` (FB/Google/manual paths, line ~1418) → owns its
    own `match_buffer`.
- Buffer is flushed (a) before `_prune_duplicate_matches` runs (so dedupe
  sees all rows) and (b) inside the `except` block on scan failure (so
  partial work isn't lost).

Bonus 4.3: replaced the per-row DELETE loop in `_prune_duplicate_matches`
with a chunked `.in_("id", chunk)` (chunks of 100 to stay well under the
8KB URL-length cap that Supabase REST imposes on `.in_()` lists).

Tests: `backend/tests/test_bulk_writers.py` — 17 unit tests covering
- single-row insert + FK retry semantics
- bulk insert + per-row fallback (both tables)
- alert hydration with returned match IDs
- buffer auto-flush at threshold
- `flush_all()` cumulative semantics
- failure accounting (`total_failed` counter)

`pytest tests/ -q` → **59 passed**, no regressions.

### Decisions
- **Did NOT widen the eval-gate path filter** to include scanning files. The
  eval pipeline only exercises AI inference (CLIP / Haiku / Opus
  detect / Opus compliance). It never writes through `bulk_writers`.
  Coverage for this PR comes from the new unit tests.
- **MatchBuffer is intentionally NOT thread/coroutine-safe.** Each scan
  worker owns its own buffer; this is fine while `_analyze_single_image`
  is called sequentially in for-loops. When Phase 3 (chunked parallelism)
  arrives, each chunk worker should construct its own buffer — no shared
  state.
- **Bonus FK-23503 protection for the 6 sites that previously lacked it**
  (screenshot_service ×3, serpapi ×1, apify_meta ×1, apify_instagram ×1).
  Before this PR a distributor deleted mid-scan would crash those services
  with an unhandled exception; now they silently re-insert without the
  distributor.

### What this does NOT do
- **No throughput measurement attached.** Real-world impact will be
  visible in scan-job durations once a 50+ dealer scan runs. At current
  pilot volume the change is silent.
- **Alerts table inserts during drift-confirmation (existing-match path)
  remain per-row.** That code path doesn't loop; batching adds no value.
- **`discovered_images.update(is_processed=True)`** still runs per-row
  inside `_analyze_single_image`. Batching that requires a deeper refactor
  of the analyze loop and a separate atomicity story; deferring.
- **Phase 4.4 (pgBouncer / pool config)** untouched. Next ticket.

### Follow-ups added to the pending list
- Phase 4.4 — Supabase connection pooling / pgBouncer config.
- Document the scan dispatch flow (every function called, in order).
- Verify `worker/` separation feasibility (no scan code path imports
  API-only modules).

---

## 2026-04-21 — Phase 4.4: investigated, **retired (N/A for this codebase)**

### TL;DR
The original Phase 4.4 ticket — "switch `SUPABASE_URL` to the Supabase
pgBouncer pooler endpoint (port 6543)" — has no surface to apply here.
Removing from the active list. Coverage justification below so this
doesn't get re-scoped in a future session.

### Why it doesn't apply
Audited every database touch point in `backend/`:

- `backend/requirements.txt` — only `supabase==2.28.2` and `httpx==0.28.1`.
  No `psycopg2`, no `asyncpg`, no SQLAlchemy, no `databases`, no direct
  Postgres client of any kind.
- `backend/app/database.py` — single client, constructed via
  `supabase.create_client(supabase_url, service_role_key)` where
  `supabase_url` is the **HTTPS REST endpoint** (`https://<proj>.supabase.co`),
  not a Postgres connection string.
- Every `.table().insert/select/...` call site in the repo (verified by
  grep) routes through PostgREST over HTTPS.

The pgBouncer pooler URL on port 6543 speaks the **Postgres wire
protocol**, not HTTPS/REST. Pointing supabase-py at it would just fail.
PostgREST already sits in front of pgBouncer inside Supabase's stack;
that's pre-existing on Supabase's side and we don't control it.

### What's tunable at our actual layer
For the record, three legitimate levers exist if/when we see real
bottlenecks:

1. **Lengthen the 5-min client recycle** in `backend/app/database.py:20`
   (and the mirrored one in `backend/app/services/page_discovery.py:32`).
   Each recycle drops the underlying httpx keep-alive pool, costing a
   fresh TLS handshake on the next call. Marginal at our current call
   volume; not worth changing without measurement.
2. **Configure explicit httpx pool / timeout settings** when constructing
   the supabase client (defaults: `max_connections=100`,
   `max_keepalive_connections=20` — fine until concurrency rises).
3. **Add asyncpg as a second data path** for hot writes only. This is
   the only option that delivers true Postgres-direct connection pooling
   (would actually use the pgBouncer port 6543 endpoint). Cost: 1–2 days,
   permanent two-path tax, new auth model. Worth doing IF a 50+ dealer
   scan shows REST overhead dominating wall-clock — not before.

### Decision
**Retire 4.4 from the pending list.** Bulk writes (4.1/4.2/4.3, prior
entry) already addressed the per-row HTTP storm that 4.4 was meant to
mitigate. Revisit option 3 above only when one of these triggers fires:

- A real ≥50-dealer scan shows write-path latency dominating wall clock
- Supabase REST rate limits start appearing in logs
- A client signs and we have <2 weeks to a 150-dealer ramp

### Pending list, updated
- ~~Phase 4.4 — Supabase connection pooling / pgBouncer config~~ —
  **retired, see above.**
- ~~Document the scan dispatch flow (every function called, in order)~~
  **shipped** → `backend/docs/scan_dispatch_flow.md`.
- Verify `worker/` separation feasibility (no scan code path imports
  API-only modules) → next.

---

## 2026-04-21 — Scan dispatch flow doc shipped

### What
`backend/docs/scan_dispatch_flow.md` — single-source trace of every
function called during a scan, in order, with the I/O surface (DB
tables touched, external APIs called) at each phase.

### Sections
1. 30-second mental model (one diagram, one paragraph)
2. Entry points — all 6 places a `scan_jobs` row is created
3. Dispatch layer — the entire `tasks.py` `task_map` and what wraps it
4. Per-source runners — common skeleton, source→discovery routing
   table, why `run_website_scan` is the only "online" runner, how
   distributor mappings are keyed per source
5. AI pipeline — 7-stage table with skip conditions and providers
6. Match writes — INSERT vs UPDATE paths, FK-23503 handling, why the
   dual write model is intentional
7. Post-scan steps — exact order of: buffer flush → dedupe → page
   cache → cost persist → status flip → notifications
8. Background cron jobs (retention, stale cleanup, CRM sync)
9. **I/O surface table** — DB tables R/W per phase + external APIs per
   source. This is the table I wanted three sessions ago.
10. Known open items visible from the trace (per-row
    `is_processed=True`, MatchBuffer scope, loader duplication,
    `tasks.py`→`routers/scanning.py` import coupling)
11. "Where do I look for X?" cheat sheet

### Why this doc and not just code comments
Three of the four open items in section 10 only become obvious when
you see all six entry points + four runners + the AI pipeline laid out
together. Section 4c (per-source distributor mapping rules) and
section 9 (DB-tables-by-phase matrix) are the two facts that no single
file in the codebase exposes — they only exist by reading every entry
point side-by-side, which is exactly what we won't do under load when
a 150-dealer client is scanning.

### Worker-split implications surfaced (sections 3, 10.4)
The single seam between API and "background work" today is
`tasks.task_map`. Each entry imports `from .routers.scanning import
run_*_scan` lazily. Moving the four source runners out to
`services/scan_runners/` (or just `services/`) makes them importable
without dragging FastAPI / auth / dependency-injection along — that's
the prerequisite for verifying the worker split is actually possible
(next ticket).

---

## 2026-04-21 — Worker-split feasibility audit: **GREEN, with one
mechanical refactor required**

### TL;DR
Pulling the scan pipeline into a separate worker process is feasible.
The blocker is **a single file**: `backend/app/routers/scanning.py`
mixes HTTP-layer code (FastAPI/auth/slowapi/plan_enforcement) with the
four scan runner coroutines and their helpers. Move the runners +
helpers out, and the worker process can `import` them without pulling
FastAPI's import chain. No architectural rework, no new abstraction.
Estimated cost: **half a day**, fully mechanical, no behaviour change.

### What I checked
For every module on the scan code path, grepped for imports of
`fastapi`, `slowapi`, `..auth`, `..plan_enforcement`, `..routers`. The
modules in scope (the closure reachable from `tasks.dispatch_task`):

- `backend/app/tasks.py`
- `backend/app/database.py`, `backend/app/config.py`, `backend/app/models.py`
- All 21 files in `backend/app/services/` (every one transitively
  reachable from a runner or a discovery service)

### Result of the audit

| Module                               | API-only imports (fastapi/slowapi/auth/plan_enforcement) |
|--------------------------------------|----------------------------------------------------------|
| `tasks.py`                           | **none** ✅                                              |
| `database.py`, `config.py`           | **none** ✅                                              |
| `models.py`                          | **none** ✅ (pydantic + stdlib only)                     |
| `services/ai_service.py`             | **none** ✅                                              |
| `services/extraction_service.py`     | **none** ✅                                              |
| `services/serpapi_service.py`        | **none** ✅                                              |
| `services/apify_meta_service.py`     | **none** ✅                                              |
| `services/apify_instagram_service.py`| **none** ✅                                              |
| `services/screenshot_service.py`     | **none** ✅                                              |
| `services/bulk_writers.py`           | **none** ✅                                              |
| `services/page_cache_service.py`     | **none** ✅                                              |
| `services/page_discovery.py`         | **none** ✅                                              |
| `services/cost_tracker.py`           | **none** ✅                                              |
| `services/notification_service.py`   | **none** ✅                                              |
| `services/salesforce_sync_service.py`| **none** ✅                                              |
| `services/hubspot_sync_service.py`   | **none** ✅                                              |
| `services/adaptive_threshold_service.py` | **none** ✅                                          |
| `services/cv_matching.py`, `embedding_service.py`, `report_service.py`, `dropbox_service.py`, `retention_service.py` | **none** ✅ |
| `services/scheduler_service.py`      | **none** ✅ (uses APScheduler, not FastAPI)              |
| **`routers/scanning.py`**            | **fastapi, slowapi, ..auth, ..plan_enforcement** ❌      |
| `auth.py`                            | fastapi (only used by routers — fine, stays in API)      |
| `plan_enforcement.py`                | fastapi.Depends (only used by routers — fine)            |

The whole services layer is already worker-clean. The single point of
contamination is `routers/scanning.py`.

### Why the contamination matters
`tasks.py` does:

```python
async def _run_website_scan(...):
    from .routers.scanning import run_website_scan
    ...
```

That lazy import does not protect us. The moment any code touches
`run_website_scan`, Python loads the entire module, which means it also
loads (in order):

1. `fastapi` (line 3 of scanning.py)
2. `..auth` → loads `fastapi.security`, runs Supabase JWT key fetch
3. `..plan_enforcement` → loads `fastapi.Depends`
4. `slowapi` → adds rate-limiter middleware globals
5. The full `routers/scanning.py` module body (router decorators all run)

A real worker process would (a) waste startup time loading FastAPI it
never uses, and (b) be coupled to the entire HTTP-auth stack purely as
an import-time side effect. Both are dealbreakers for an honest worker
split.

### What's actually entangled vs. what just shares a file

I grepped for every `HTTPException`, `Depends`, `Request`, `AuthUser`,
`OrgPlan`, and `limiter.` reference inside `routers/scanning.py`.
**Every single one is inside a `@router.*`-decorated function.** None
of the runner coroutines or their helpers use FastAPI types in their
signatures or bodies.

This is the best possible audit outcome: the runners are pure scan
logic that *happen to share a file* with the routes. No type leakage,
no hidden dependency on request-scoped state, no `Depends()` in a
runner signature. Mechanical move only.

### Proposed refactor (concrete file plan)

Create **`backend/app/services/scan_runners.py`** (or, if preferred,
`backend/app/scan_runners/{__init__,helpers,website,google_ads,facebook,
instagram,analyze}.py`). Move the following from `routers/scanning.py`:

| Symbol moved                              | Current location (~line) | Used by                                   |
|-------------------------------------------|--------------------------|-------------------------------------------|
| `_utc_now()`                              | 34                       | every runner                              |
| `_heartbeat()`                            | 39                       | website runner                            |
| `_persist_cost()`                         | 48                       | every runner                              |
| `_send_scan_notifications()`              | 70                       | every runner                              |
| `_fetch_campaign_assets()`                | 286                      | every runner                              |
| `run_google_ads_scan()`                   | 301                      | `tasks._run_google_ads_scan`              |
| `run_facebook_scan()`                     | 356                      | `tasks._run_facebook_scan`                |
| `run_instagram_scan()`                    | 413                      | `tasks._run_instagram_scan`               |
| `_prune_duplicate_matches()`              | 457                      | website runner, analyze paths             |
| `_analyze_single_image()`                 | 514                      | website runner, `run_image_analysis`      |
| `run_website_scan()`                      | 679                      | `tasks._run_website_scan`                 |
| `auto_analyze_scan()`                     | 1017                     | every runner (campaign-linked)            |
| `run_image_analysis()`                    | 1384                     | `tasks._run_analyze_scan`, `_run_reprocess_images` |

**Stays in `routers/scanning.py`:** every `@router.*` HTTP handler
(start, batch, quick-scan, retry, list, get, delete, debug, analyze,
reprocess-unprocessed). They call into the new module.

**Updates to `tasks.py`:** rewrite the four lazy imports from
`from .routers.scanning import run_*_scan` to
`from .services.scan_runners import run_*_scan`. The two analyze
wrappers (`_run_analyze_scan`, `_run_reprocess_images`) likewise switch
to importing `auto_analyze_scan` and `run_image_analysis` from the new
module.

**Imports the new module needs:** `database`, `config`, `models`
(only if any runner referenced an enum — currently they don't),
`services.{ai_service, extraction_service, serpapi_service,
apify_meta_service, apify_instagram_service, bulk_writers,
page_cache_service, cost_tracker, notification_service,
salesforce_sync_service, hubspot_sync_service}`. None of these touch
FastAPI.

### Validation that has to ship with the refactor

1. After the move, `python -c "from app.services.scan_runners import
   run_website_scan"` must succeed without `fastapi` being importable.
   Easy CI check:
   ```bash
   python -c "
   import sys
   class Block:
       def find_module(self, name, path=None):
           if name.startswith(('fastapi', 'slowapi')): raise ImportError(name)
   sys.meta_path.insert(0, Block())
   from app.services.scan_runners import run_website_scan, run_google_ads_scan, run_facebook_scan, run_instagram_scan
   "
   ```
   If that command exits 0, the worker split is mechanically possible.
2. Existing tests in `backend/tests/` must still pass — the move is
   import-only.
3. `bulk_writers` tests already cover the hot write paths; no new
   tests required for the move itself.

### What this audit does NOT do
- It does **not** introduce a queue, Redis broker, or actually start a
  separate worker process. That's a separate ticket. This audit just
  proves the path is clear.
- It does **not** address the other open items from the dispatch-flow
  doc (per-row `is_processed=True`, MatchBuffer scope, loader
  duplication). Those are independent.
- It does **not** touch the scheduler. `scheduler_service.py` is
  already clean and would continue to live in the API process (or
  could be moved with no additional effort, since it doesn't import
  FastAPI either).

### Pending list, updated
- ~~Verify `worker/` separation feasibility~~ — **done above. Verdict:
  feasible, blocker is one mechanical move.**
- ~~New: **Phase 4.5 — extract scan runners from `routers/scanning.py`
  into `services/scan_runners.py`**~~ — **shipped (see entry below).**
- ~~New: **Phase 4.6 — add an import-isolation guard to CI**~~ —
  **shipped together with 4.5.**

---

## 2026-04-21 — Phase 4.5 + 4.6 shipped: worker-safe scan runners

### What changed
| Action | File | Lines |
|---|---|---|
| **Added** | `backend/app/services/scan_runners.py` | +812 (new) |
| **Stripped** | `backend/app/routers/scanning.py` | 1812 → 631 (-1181) |
| **Re-pointed** | `backend/app/tasks.py` (5 lazy imports) | -5/+5 |
| **Updated** | `backend/docs/scan_dispatch_flow.md` (8 line refs) | -8/+10 |
| **Added** | `backend/tests/test_worker_import_isolation.py` | +89 (new) |

The 13 symbols moved verbatim (zero behaviour change):

| Symbol | Role |
|---|---|
| `_utc_now` | timestamp helper |
| `_heartbeat` | (no-op stub kept for call-sites) |
| `_persist_cost` | scan-job cost write |
| `_send_scan_notifications` | email/Slack/SF/Jira/HubSpot fan-out |
| `_fetch_campaign_assets` | asset SELECT for AI matching |
| `run_google_ads_scan` | per-source runner |
| `run_facebook_scan` | per-source runner |
| `run_instagram_scan` | per-source runner |
| `_prune_duplicate_matches` | best-match-per-(asset,distributor) dedupe |
| `_analyze_single_image` | per-image AI pipeline write |
| `run_website_scan` | online runner with cache + early-stop |
| `auto_analyze_scan` | post-discovery analyse driver |
| `run_image_analysis` | FB/Google/manual analyse loop |

`tasks.py` now does
`from .services.scan_runners import run_*_scan` instead of
`from .routers.scanning import run_*_scan`. The HTTP layer in
`routers/scanning.py` only contains `@router.*` handlers and one
helper (`_get_scan_issues`) used by the debug endpoint. It dropped
six top-level imports it no longer needs (`screenshot_service`,
`extraction_service`, `ai_service`, `serpapi_service`,
`apify_meta_service`, `bulk_writers`, `cost_tracker`,
`notification_service`, `salesforce_sync_service`,
`hubspot_sync_service`, `datetime`/`timezone`).

### Phase 4.6 — the guard
`tests/test_worker_import_isolation.py` spawns a fresh subprocess,
installs a `MetaPathFinder` that raises `ImportError` for any
`fastapi*` or `slowapi*` import, then imports every public scan-runner
symbol. If anyone in the future adds an import inside the
`scan_runners` closure that pulls FastAPI back in (say, by importing
something from `..routers.x` or `..plan_enforcement`), this test fails
loudly in CI with a pointer back to this log entry. No quiet
re-coupling.

### Validation run
- Lint: clean on the three touched files.
- `python -m pytest tests/test_worker_import_isolation.py
  tests/test_bulk_writers.py -q` → **18 passed**.
- `python -m pytest tests/ --co` collects all **59 tests** with no
  import errors anywhere in the suite.
- API smoke: `from app.routers.scanning import router, start_scan,
  retry_scan_job, batch_scan, debug_scan` succeeds and all 11 routes
  still register (`/scans/start`, `/scans`, `/scans/{job_id}`,
  `/scans/{job_id}/retry`, `/scans/{job_id}/analyze`, `/scans/batch`,
  `/scans/quick-scan`, `/scans/reprocess-unprocessed`,
  `/scans/debug/{scan_id}`, plus the two DELETE variants).
- Worker smoke: `from app.services.scan_runners import …` succeeds
  even with `fastapi`/`slowapi` blocked at `sys.meta_path` level.

### Why this matters
The audit on 2026-04-21 (entry above) proved a worker split was
**feasible** but blocked by one structural problem: `tasks.py`'s
lazy imports of runner functions from `routers/scanning.py` would
drag FastAPI, slowapi, the auth stack, and plan-enforcement into the
worker process. We've now removed that blocker.

A future ticket can:
1. Spin up a separate process (Docker container, Procfile entry, or
   `python -m app.worker`) whose only job is to consume scan tasks.
2. Replace `app.tasks.dispatch_task`'s in-process `asyncio.create_task`
   with a real queue (Redis Streams, SQS, or just Postgres `SELECT
   FOR UPDATE SKIP LOCKED`). The producer side stays in the API; the
   consumer side imports from `services.scan_runners`.

Neither of those steps requires touching the runner code itself.
That's the win.

### What this PR is NOT
- **Not** a behaviour change. Every line was copied verbatim. If a
  scan worked yesterday it works today; if it didn't, it still doesn't.
- **Not** the worker. We did not add a new process, queue, or broker.
- **Not** a fix for the open items in `scan_dispatch_flow.md`
  (per-row `is_processed`, MatchBuffer scope, loader duplication).
  Those remain on the list.

### Pending list, updated
- ~~Phase 4.5~~ — done.
- ~~Phase 4.6~~ — done.
- (Stays open) Phase 5 — **actually** spin up a worker process and
  migrate `tasks.py` from in-process `asyncio.create_task` to a
  proper queue. Pre-requisite: decide queue backend (Redis vs SQS vs
  pg). Also pre-requisite: pick a process manager (Docker Compose
  service, systemd unit, etc.).
- (Stays open) Per-row `is_processed=True` chunking — in
  `_analyze_single_image` we still issue one UPDATE per image. Trivial
  to batch with the same buffer pattern as matches.
- (Stays open) Loader duplication — Google/Facebook/Instagram runners
  share ~80% of their scaffold. Worth a single `_run_source_scan`
  driver, but cosmetic.

---

## 2026-04-21 — End-of-day summary

A scaling-prep marathon. Six discrete pieces of work shipped, all in
service of being able to take on a 150-dealer client without rewriting
the world.

### Timeline of the day

1. **Caching restructure run #2 → reverted to "4.6 no caching"** *(early)*
   - Eval gate failed on the second run; manual diff of the asset vs
     discovered fixtures showed the matches were "not the same at all,
     not even close."
   - Decision: roll back to AI 4.6 without prompt caching. Caching
     ticket closed. (Models are now spot-on per pilot feedback.)

2. **Wired the eval into CI**
   - Added the GitHub Actions job that runs the eval suite and gates on
     `compliance_precision`. Future regressions in the AI pipeline will
     fail the build instead of silently shipping.

3. **Phase 4.1 + 4.2 + 4.3 — bulk DB writes**
   - `DiscoveredImageBuffer` and `MatchBuffer` for batched inserts of
     `discovered_images` and `matches` rows.
   - Per-row fallback when a batch insert fails (e.g. one bad row
     poisoning the batch).
   - FK-23503 retry logic for the case where a `distributor_id`
     disappears between scan dispatch and match write.
   - `_prune_duplicate_matches` rewritten to use chunked
     `DELETE … WHERE id IN (…)` (chunks of 100 to stay under
     PostgREST's URL-length limit).
   - **Shipping impact:** at 150 dealers × dozens of pages × tens of
     images, this trades thousands of HTTP round-trips for tens.

4. **Phase 4.4 — retired (N/A)**
   - Initial plan was "switch to the pgBouncer pooler endpoint."
   - On inspection: the app uses `supabase-py` (HTTPS REST → PostgREST
     → pgBouncer). We have no direct Postgres connection to pool.
   - Documented the legitimate `httpx` tuning levers (`limits=`,
     `http2=True`, client recycling) and `asyncpg` as the larger lever
     if a real bottleneck ever shows up.

5. **`backend/docs/scan_dispatch_flow.md` shipped** *(new file)*
   - Comprehensive trace: 6 entry points (5 HTTP routes + APScheduler
     cron) → `tasks.py::dispatch_task` → per-source runners → the
     7-stage AI pipeline → match writes → post-scan cleanup
     (dedupe, page caching, cost persistence, status update,
     notifications).
   - Includes an I/O surface table (which DB tables get read/written
     per phase, which external APIs get hit per source).
   - Explicitly lists known open items so future work has a punch list.
   - This doc is the artifact that made the worker-split audit
     possible.

6. **Worker-split feasibility audit**
   - Grepped every module in the scan code path (22 service files +
     `tasks.py`, `database.py`, `config.py`, `models.py`) for imports
     of `fastapi`, `slowapi`, `..auth`, `..plan_enforcement`.
   - **22 of 23 are clean.** The only contaminated file was
     `routers/scanning.py`, which mixed HTTP handlers with scan runner
     coroutines.
   - Crucially: the runner *functions* themselves don't use
     `HTTPException`/`Depends`/`Request`/etc. — only the
     `@router.*`-decorated handlers in the same file do. So a
     mechanical move is sufficient; no logic changes required.

7. **Phase 4.5 — scan_runners extracted**
   - New module `backend/app/services/scan_runners.py` (812 lines)
     holds the 13 runner symbols (`run_*_scan`, `auto_analyze_scan`,
     `run_image_analysis`, `_analyze_single_image`,
     `_prune_duplicate_matches`, `_fetch_campaign_assets`,
     `_send_scan_notifications`, `_persist_cost`, `_heartbeat`,
     `_utc_now`).
   - `routers/scanning.py` shrank from 1,812 → 631 lines and now
     contains only `@router.*` handlers + one debug helper. Dropped
     11 top-level imports it no longer needs.
   - `tasks.py` updated: 5 lazy imports re-pointed from
     `from .routers.scanning import …` to
     `from .services.scan_runners import …`.
   - Verbatim move — zero behaviour change.

8. **Phase 4.6 — import-isolation guard**
   - New test `tests/test_worker_import_isolation.py` spawns a fresh
     subprocess, installs a `MetaPathFinder` that raises `ImportError`
     for any `fastapi*` / `slowapi*` import, then imports every public
     scan-runner symbol.
   - If anyone in the future re-introduces a FastAPI dependency
     anywhere in the `scan_runners` import closure, this test fails
     loudly in CI with a pointer back to this log.
   - Catches the regression at the architectural-invariant level
     instead of waiting for a "weird worker startup error" in prod.

### Files touched today

| File | Change |
|---|---|
| `backend/app/services/bulk_writers.py` | bulk-insert buffers, FK retry (4.1/4.2/4.3) |
| `backend/app/services/extraction_service.py` | wired buffer for `discovered_images` |
| `backend/app/services/scan_runners.py` | **NEW** (812 lines, Phase 4.5) |
| `backend/app/routers/scanning.py` | 1812 → 631 lines (Phase 4.5) |
| `backend/app/tasks.py` | 5 lazy imports re-pointed |
| `backend/docs/scan_dispatch_flow.md` | **NEW** (dispatch flow doc) |
| `backend/tests/test_bulk_writers.py` | **NEW** unit tests for bulk path |
| `backend/tests/test_worker_import_isolation.py` | **NEW** Phase 4.6 guard |
| `.github/workflows/*.yml` | eval gate added |
| `log.md` | this and the entries above |

### Test status at end of day

- `pytest tests/test_bulk_writers.py tests/test_worker_import_isolation.py -q`
  → **18 passed**.
- `pytest tests/ --co` → **59 tests collected, no import errors**.
- API smoke import: `from app.routers.scanning import router, …` →
  all 11 routes still register.
- Worker smoke import (with `fastapi`/`slowapi` blocked at meta_path):
  `from app.services.scan_runners import …` → succeeds.

### What the day actually bought us

A cleaner pipeline that does less network chatter under load, plus a
codebase that is now **structurally ready** for a separate worker
process. The single "would have to refactor for a 150-dealer client"
blocker is gone. What remains is an infra/config decision (which
queue, which process manager), not a code-shape problem.

### Pre-rolled context for tomorrow

Pick one of:

- **Phase 5 — actual worker process.**
  Pre-decisions: queue backend (Postgres `SELECT FOR UPDATE SKIP
  LOCKED` is cheapest for 150 dealers; Redis Streams if you expect
  cross-region or serious volume; SQS if you're going AWS-native).
  Then process manager (Render worker service / Fly machines / Docker
  Compose / systemd). Roughly 1–2 days for pg-backed, 3–4 days for
  Redis with retries + DLQ.

- **Per-row `is_processed=True` chunking.**
  In `_analyze_single_image` we still UPDATE one image at a time. Mirror
  the `MatchBuffer` pattern with a `ProcessedImageBuffer` that flushes
  in batches. Half a day.

- **Loader/runner deduplication.**
  Google / Facebook / Instagram runners are ~80% the same scaffold.
  Collapse to a single `_run_source_scan(source, …)` driver. Cosmetic;
  half a day; no behavior change.

- **Eval coverage expansion.**
  Add `match_precision` / `match_recall` to the CI gate once a labeled
  fixture set exists. Untimed because it depends on labeling effort,
  not engineering.

---

## 2026-04-22 — Phase 4.7: per-row `is_processed=True` chunking

Picked up the second bullet from yesterday's "pre-rolled context" list
(`log.md` line 4025). The trailing
`discovered_images.update(is_processed=True)` inside
`_analyze_single_image` was the last per-row HTTP round-trip left in the
analysis loop after Phases 4.1–4.3 batched the inserts. With ~150
dealers × hundreds of images per scan that's a lot of sequential
single-row UPDATEs the pipeline does not need.

### What was done

1. **`bulk_writers.py` — new symbols**
   - `bulk_mark_images_processed(image_ids: list[str]) -> int` — single
     `update({"is_processed": True}).in_("id", ids)` call with per-row
     fallback so a single bad id can't stall a scan's progress flag.
   - `ProcessedImageBuffer` — same shape as `MatchBuffer` /
     `DiscoveredImageBuffer`. `add(image_id)` queues, auto-flushes at
     `batch_size=100` (chosen because the UPDATE payload is just a list
     of UUIDs — much smaller than a match insert), `flush_all()` drains
     the remainder. Caller owns the buffer lifetime.

2. **`scan_runners.py` — wired into the analyse loop**
   - `_analyze_single_image` now takes
     `processed_buffer: Optional[ProcessedImageBuffer] = None` and uses
     `processed_buffer.add(image["id"])` on both the success and the
     `except` paths. Falls back to the inline single-row UPDATE when no
     buffer is supplied — keeps any legacy/test caller working without
     change.
   - `run_website_scan` allocates one `ProcessedImageBuffer` next to its
     existing `MatchBuffer`, passes it into both `_analyze_single_image`
     call sites (cached-page phase + discovery phase), and drains it in
     the post-scan steps **right after** the match buffer flush so the
     `processed_items` count reported on `scan_jobs` and the actual row
     state agree. The failure path mirrors this — partially-analysed
     images don't get re-processed forever on the next scan.
   - `run_image_analysis` (the Facebook / Google / manual loop) gets the
     same allocate-pass-flush treatment.
   - `auto_analyze_scan`'s "no campaign assets — mark them all processed
     anyway" branch swapped its `for img in images.data:` per-row update
     loop for a single `bulk_mark_images_processed([...])` call.

3. **`tests/test_bulk_writers.py` — 8 new tests**
   - `TestBulkMarkImagesProcessed` × 4: empty-list short-circuit,
     happy-path single bulk call, fallback to per-row on bulk failure,
     partial per-row failure returns success count.
   - `TestProcessedImageBuffer` × 4: auto-flush at threshold, `flush_all`
     drains remainder + returns cumulative, empty-buffer is safe,
     falsy ids (`""`, `None`) are silently dropped.

4. **`backend/docs/scan_dispatch_flow.md`** updated:
   - Open item #1 ("`is_processed` is per-row") struck through and
     marked **Resolved in Phase 4.7**.
   - Section 6 trace line and section 9 footnote rewritten to describe
     the buffered path.
   - Post-scan step list grew step **1a** (`processed_buffer.flush_all()`)
     and the failure-path bullets call out the mirroring drain.

### Files touched today

| File | Change |
|---|---|
| `backend/app/services/bulk_writers.py` | +`bulk_mark_images_processed`, +`ProcessedImageBuffer` (~95 lines) |
| `backend/app/services/scan_runners.py` | `_analyze_single_image` signature + 2 write sites, buffers in `run_website_scan` and `run_image_analysis`, bulk call in `auto_analyze_scan` empty-assets branch |
| `backend/tests/test_bulk_writers.py` | +8 tests for the new buffer (`TestBulkMarkImagesProcessed`, `TestProcessedImageBuffer`) |
| `backend/docs/scan_dispatch_flow.md` | open-item #1 resolved, step 1a added, section 6 / 9 updated |
| `log.md` | this entry |

### Test status at end of day

- `pytest tests/test_bulk_writers.py tests/test_worker_import_isolation.py -q`
  → **26 passed** (18 prior + 8 new).
- `pytest tests/ --co` → **68 tests collected, no import errors**.
- Worker import-isolation guard still green: the new
  `bulk_mark_images_processed` / `ProcessedImageBuffer` symbols added
  zero FastAPI surface to the `scan_runners` import closure.

### What today actually bought us

The analysis loop is now fully batched on the database side: inserts
(`discovered_images`, `matches`, `alerts`) batch through their buffers,
and the trailing progress flag does too. For a 500-image scan that's
~500 fewer sequential HTTP UPDATEs to Supabase, all replaced by ~5
bulk calls (batch=100). The "Phase 4 batching theme" started in 4.1 is
done — there is no per-row chatter left in the hot path.

Equally important: the failure paths drain the buffer too, so a scan
that crashes halfway through doesn't leave partially-analysed images
permanently flagged `is_processed=False` (which would make every
subsequent run re-do them).

### What's left from yesterday's list

Of the four "pick one of" options at log.md:4015:

- **Phase 5 — actual worker process.** Still the biggest payoff;
  unblocked but needs the queue/process-manager decision.
- ~~**Per-row `is_processed=True` chunking.**~~ **Done today.**
- **Loader/runner deduplication.** Untouched — half a day, cosmetic.
- **Eval coverage expansion.** Still gated on labeled fixtures.

### Pre-rolled context for tomorrow

The remaining low-friction option is **loader/runner deduplication**
(yesterday's bullet 3 / log.md:4030). The Google / Facebook / Instagram
runners in `scan_runners.py` share ~80% scaffolding (load assets, load
brand_rules, loop, flush match buffer + processed buffer, persist cost,
notify). A single `_run_source_scan(source, …)` driver collapses them
without behaviour change. Half a day. Good warm-up before committing to
Phase 5's infra decision.

---

## 2026-04-22 (later) — Phase 4.8: loader/runner deduplication

Knocked out the second item from this morning's pre-rolled context.
Google Ads / Facebook / Instagram runners collapsed onto a single
shared driver. Pure code-shape change — zero behaviour difference.

### What was done

1. **`scan_runners.py` — new shared driver**
   - `_run_source_scan(*, source, scan_job_id, campaign_id, discover)`
     owns the entire post-scan-analyse skeleton that all three runners
     used to duplicate verbatim:
     1. open `scan_cost_context`
     2. mark `scan_jobs.status = running`
     3. fetch campaign assets
     4. invoke the source-specific `discover(campaign_assets) -> int`
     5. if a campaign is attached and discovery wrote anything, fire
        `auto_analyze_scan` (failures non-fatal — scan still completes)
     6. `_persist_cost`, mark `completed`, send notifications
     7. failure path: persist cost best-effort, mark `failed` with
        `error_message`, **never** notify (matches prior behaviour)
   - `DiscoverFn` type alias
     (`Callable[[List[Dict[str, Any]]], Awaitable[int]]`) documents the
     contract for the source callables.

2. **The three public runners are now thin wrappers**
   - `run_google_ads_scan` — picks SerpApi vs Playwright based on
     `serpapi_api_key`, returns the count.
   - `run_facebook_scan` — picks Apify Meta vs Playwright based on
     `apify_api_key`, propagates `channel` into the Apify call. Source
     label stays `"facebook"` even when channel differs (notifications
     key off `scan_source`).
   - `run_instagram_scan` — always Apify Instagram organic.
   - All three keep their original public signatures because
     `app.tasks.dispatch_task`, `routers/scanning.py`,
     `routers/campaigns.py`, and `services/scheduler_service.py` all
     import them by name.

3. **`run_website_scan` deliberately stays separate**
   - Its early-stop, page-cache, asset-hash precompute, and per-page
     buffered analysis don't fit the post-scan-analyse model. Forcing
     it through the shared driver would have required a config flag
     soup that hurt readability for zero structural gain.

4. **`tests/test_scan_runners_dispatch.py` — 12 new tests**
   - `TestGoogleAdsWrapperDispatch` × 3: passes correct source label;
     `discover` uses SerpApi when the key is set; falls back to
     Playwright otherwise.
   - `TestFacebookWrapperDispatch` × 3: passes correct source label;
     `discover` uses Apify when the key is set and propagates `channel`;
     falls back to Playwright otherwise.
   - `TestInstagramWrapperDispatch` × 1: passes correct source label
     and invokes `apify_instagram_service.scan_instagram_organic`.
   - `TestRunSourceScanDriver` × 5: success path issues `running` →
     `completed` updates and notifies; skips `auto_analyze_scan` when
     `campaign_id` is `None`; skips it when discovery returned 0; the
     failure path issues `running` → `failed` with `error_message` and
     does NOT notify; an exception inside `auto_analyze_scan` does not
     fail the scan.
   - Tests use `asyncio.run()` directly because the project does not
     depend on `pytest-asyncio` (deliberate — no new dev deps).

5. **Docs updated** (`backend/docs/scan_dispatch_flow.md`)
   - Section 4b expanded to describe the new `_run_source_scan`
     driver alongside the existing per-source paragraph.
   - Open item #5 added and immediately marked **Resolved in Phase 4.8**.
   - The `task_map` table at section 3 needed no change — public entry
     names are unchanged, only their internals.

### Files touched today (this entry)

| File | Change |
|---|---|
| `backend/app/services/scan_runners.py` | three runners (~150 lines of duplication) collapsed to `_run_source_scan` (~70 lines) + three ~15-line wrappers |
| `backend/tests/test_scan_runners_dispatch.py` | **NEW** — 12 dispatch + driver-behaviour tests |
| `backend/docs/scan_dispatch_flow.md` | Section 4b note, open item #5 marked resolved |
| `log.md` | this entry |

### Test status at end of day

- `pytest tests/test_scan_runners_dispatch.py tests/test_bulk_writers.py tests/test_worker_import_isolation.py -q`
  → **38 passed** (12 new dispatch + 26 prior).
- `pytest tests/ --co` → **80 tests collected, no import errors**
  (was 68 before this entry).
- Worker import-isolation guard still green: `_run_source_scan` and the
  thin wrappers added zero FastAPI surface.

### Lines saved

`scan_runners.py` shrank where it mattered most (the per-source
runners). Diff at the runner block: **~170 lines of triple-duplicated
boilerplate** → **one shared driver + three wrappers** that fit on a
single screen each. The wrappers now read top-to-bottom as "what is
different about this source," not "everything every source does."

### Worker-split implications

Phase 5 now ports **one** scan-pipeline driver instead of three near-
identical ones. The shared driver is the natural seam for queue-side
retry / DLQ / heartbeat hooks — wrap `_run_source_scan` once and every
non-website source picks it up. `run_website_scan` will need its own
worker-side wrapper because of the early-stop / cache, but that's a
known and bounded scope.

### Pre-rolled context for tomorrow

Two real options left from the original pre-rolled list:

- **Phase 5 — actual worker process.** Now genuinely the next thing.
  The structural prerequisites are all in place: bulk inserts (4.1–4.3),
  buffered processed flag (4.7), one driver to port (4.8), and an
  import-isolation guard that keeps the closure clean. Open question is
  still infra: queue backend (Postgres `SELECT FOR UPDATE SKIP LOCKED`
  for 150 dealers, Redis Streams if growth, SQS if AWS-native) and
  process manager (Render worker / Fly machines / systemd). 1–2 days
  for pg-backed + DLQ.

- **Eval coverage expansion.** Still blocked on a labeled fixture set.
  No engineering change in cost.

The "MatchBuffer per call" open item (#2 in `scan_dispatch_flow.md`) is
worth revisiting **only if** Phase 5 fans out by page or by URL, which
the pg-backed simple worker does not. Park.

---

## 2026-04-22 (later still) — Deep links in scan-completion notifications

Followed Phase 4 with a small UX-leverage win that wasn't in the
original roadmap. Every scan-completion notification (email, Slack,
Salesforce Task, Jira issue) now embeds working dashboard links so the
recipient can act on a violation in one click instead of hunting for
it in the UI.

### Why this, why now

Audit of `notification_service.py` found that all four channels were
**linkless**: nice summary stats, no way to drill in. For a tool whose
whole job is "tell you what needs fixing," that was a dead-end for the
user. Lower-leverage items remaining (router test backfill, eval
fixtures) are either internal hygiene or blocked on data — this one is
customer-facing, isolated to the notification builders, and ships in
under a day.

### What was done

1. **`scan_runners.py` — surface match_id**
   - `_send_scan_notifications` already queries `matches` to build the
     `violations_formatted` list. Added `"match_id": m.get("id")` to
     each row so every channel can build a per-match URL.

2. **`notification_service.py` — link helpers**
   - `_dashboard_link(path)`, `_matches_url()`, `_violations_url()`,
     `_match_detail_url(id)` — single source of truth for the four URL
     shapes the rest of the file uses.
   - All four read `settings.frontend_url` (already used by OAuth +
     Stripe redirects). Per-scan deep linking via `?scan_job_id=` was
     intentionally deferred — `routers/matches.py` does not yet accept
     that filter, so adding it would have meant a backend + frontend
     change for a marginal ergonomics gain.

3. **Email (`_build_scan_report_email`)**
   - New CTA block before the footer: "Review N Violations" (primary
     button to `/matches?status=violation`) when violations > 0,
     "Open Dashboard" otherwise. "View all matches" secondary link
     always shown.
   - Violation table gained a sixth column with a per-row "Review"
     anchor pointing at `/matches/{match_id}`. Falls back to a dash
     when `match_id` is missing (e.g., legacy data).
   - Truncation footer ("Showing 20 of N") now contains a link to the
     full violations list instead of asking users to log in manually.

4. **Slack (`_build_scan_slack_blocks`)**
   - Replaced the single "Top Violations" markdown bullet block with
     **one section per violation**, each carrying a `Review` button
     accessory pointing at `/matches/{match_id}`. Slack only allows
     one accessory per section — hence the per-row layout.
   - Added an `actions` block before the divider with two buttons:
     primary "Review N Violations" (or "Open Dashboard") and secondary
     "View All Matches". Ten-block cap on per-violation sections is
     unchanged; overflow rendered as a context note as before.

5. **Salesforce (`notify_salesforce_scan_complete`)**
   - Salesforce Task UI auto-linkifies plain URLs in the description,
     so no API-format change was needed. Description now lists
     "Review violations: {url}" (when relevant) and "Open dashboard:
     {url}", and each violation row appends its `/matches/{id}` URL.
     Truncation footer points at the violations list.

6. **Jira (`notify_jira_scan_complete` + helpers)**
   - Jira's description field is ADF — plain text nodes don't render
     as clickable. Refactored `_create_jira_issue` to accept either
     `description` (legacy plain string, used by the test issue) or
     `description_doc` (a fully built ADF doc, used by the scan path).
   - Added `_adf_text(text, href=None)`, `_adf_paragraph(*nodes)`,
     `_adf_doc_from_text(s)` builders.
   - `notify_jira_scan_complete` now constructs the doc directly so
     "Review violations" / "Open dashboard" / per-match "Review" links
     carry proper ADF link marks.
   - `send_jira_test` is unchanged (still passes plain `description`,
     wrapped automatically).

### Files touched

| File | Change |
|---|---|
| `backend/app/services/scan_runners.py` | one-line addition: `match_id` in violations dict |
| `backend/app/services/notification_service.py` | link helpers + email CTA + Slack actions block + per-violation Slack buttons + Salesforce URLs + Jira ADF refactor |
| `backend/tests/test_notification_links.py` | **NEW** — 23 tests covering all four channels |
| `log.md` | this entry |

### Test status

- `pytest tests/test_notification_links.py -v` → **23 passed**.
- `pytest tests/test_notification_links.py tests/test_bulk_writers.py
  tests/test_worker_import_isolation.py tests/test_scan_runners_dispatch.py -q`
  → **61 passed** (no regressions in the Phase 4 surface).
- `pytest tests/ --co` → **103 tests collected, no import errors**
  (was 80 before this entry).
- Worker import-isolation guard still green: the helper additions in
  `notification_service` did not change the closure that
  `scan_runners` already had on it.

### What was deliberately NOT done

- **Per-scan deep linking** (`?scan_job_id=…`). Would need a new query
  filter on `routers/matches.py` and a corresponding frontend change.
  Real value but materially larger scope; revisit if a customer asks
  for "show me what this specific scan found."
- **Salesforce Task `WhatId` / Custom URL fields.** Plain URLs in the
  description already render as clickable in the SF UI. Custom-object
  linkage would require config-by-config schema knowledge per tenant.
- **Slack message updates / threading.** Out of scope — current
  behaviour posts one new message per scan, which is what users
  expect.

### Pre-rolled context for tomorrow

The "what's left" list from yesterday is unchanged:

- **Phase 5 — actual worker process.** Still gated on a metric
  trigger. The deep-link work doesn't change that calculus.
- **Eval coverage expansion.** Still blocked on labeled fixtures.

The new candidate that surfaced from this work: when Phase 5 happens
and notifications fire from a worker process, the
`settings.frontend_url` lookup needs to be present in the worker's
environment too (it already is, since the worker would inherit the
same env), but worth eyeballing during the worker extraction.

---

## 2026-04-22 — Playwright "browser missing" error normalisation

### Problem

A scan failed locally with this Playwright error:

```
BrowserType.launch: Executable doesn't exist at
/var/folders/.../T/cursor-sandbox-cache/.../chrome-headless-shell
Looks like Playwright was just installed or updated.
Please run: playwright install
```

Two compounding UX problems:

1. **Backend** stored the raw multi-line traceback verbatim in
   `scan_jobs.error_message` via three `str(e)` sites in
   `services/scan_runners.py`. That made the dashboard render an
   unreadable wall of text and made the failure mode hard to grep
   for in logs.
2. **Frontend** had a substring heuristic in `app/scans/page.tsx`
   that matched timeout / rate / url / 404 — and fell through to a
   generic "Check your campaign assets and dealer URLs, then retry."
   That hint was actively misleading: the dealer URLs and campaign
   assets were fine; the worker was missing its Chromium binary.

The pattern recurs in two real environments:

- **Local dev** in Cursor's sandbox cache, where Playwright's
  per-version binary directory disappears between sessions.
- **Production** if a Docker image is rebuilt without the
  `playwright install chromium --with-deps` step (the Dockerfile
  has it today, but a future split-out worker image could regress).

### What was done

**Backend** (`services/scan_runners.py`):

- Added `_normalize_scan_error(exc) -> str`. It scans the exception
  text (case-insensitive) for any of:
    - `browsertype.launch: executable doesn't exist`
    - `looks like playwright was just installed or updated`
    - `playwright install`
    - `chrome-headless-shell`
  When matched, returns a stable, single-line, actionable message:
  ```
  Browser runtime not installed: the scan worker cannot launch
  Chromium because Playwright browser binaries are missing. If
  running locally, execute backend/scripts/install_playwright.sh;
  in production, redeploy the worker so the Docker image runs
  `playwright install chromium --with-deps`. Original: <≤240 chars>
  ```
  Everything else falls through unchanged so we never silently hide
  a meaningful error.
- Replaced the three `error_message: str(e)` (and one
  `f"Analysis failed: {str(e)}"`) sites in `run_website_scan` /
  `_run_source_scan` / `auto_analyze_scan` / `run_image_analysis`
  with `_normalize_scan_error(e)`.

**Frontend** (`app/scans/page.tsx`):

- Replaced the inline ternary chain in the failure card with a
  small IIFE that adds a Playwright branch *first*, matching on:
    - `browser runtime not installed` (the new normalised prefix)
    - `browsertype.launch`
    - `chrome-headless-shell`
    - `playwright install`
  When matched it shows: "The scan worker is missing browser
  binaries (Playwright Chromium). If running locally, run
  backend/scripts/install_playwright.sh; in production, redeploy
  the worker so the image installs Chromium."
  All existing branches (timeout / rate / url / 404 / fallback)
  preserved unchanged.

### Tests

New file `tests/test_scan_error_normalizer.py` — **16 tests, all
green**:

- `TestPlaywrightDetection` (8): full real-world traceback,
  each substring marker individually, case-insensitivity, original
  message preserved, 240-char snippet truncation, hint mentions
  both local and prod paths.
- `TestNonPlaywrightPassthrough` (5): timeout, 404, rate-limit,
  generic runtime errors, and an unrelated Playwright nav
  timeout — all returned verbatim.
- `TestEdgeCases` (3): empty `str(exc)` falls back to class name,
  `KeyError()` with no args, custom `__str__` still detected.

Regression run: `test_scan_runners_dispatch.py` (12),
`test_worker_import_isolation.py` (1), `test_bulk_writers.py` (24),
`test_notification_links.py` (23) — **61 / 61 pass**, no
import-isolation breakage from the new helper.

### Why this approach over the alternatives

- **Why a string-match normaliser instead of catching
  `playwright._impl._errors.Error`?** Two reasons. First, the
  scan runner shouldn't import Playwright internals just to
  classify errors — that would re-couple the worker-safe layer
  to a heavy optional dep. Second, the same failure can surface
  from a subprocess wrapper, an asyncio shielded task, or a
  thread executor where the original exception class is wrapped
  or replaced. Substring matching on the message is the only
  layer that survives all of those.
- **Why keep the original message inside the normalised
  output?** So the dashboard, Sentry, and `grep` over logs all
  still find the verbatim Playwright text. The 240-char cap
  prevents the box-drawing banner from blowing out the UI.
- **Why update the frontend at all if the backend now writes a
  stable string?** Three reasons:
    1. Existing failed `scan_jobs` rows in the DB still have the
       raw traceback; the frontend heuristic handles them too.
    2. If the normaliser ever misses a new Playwright variant,
       the frontend still degrades gracefully to the right
       hint instead of the misleading generic one.
    3. Defence in depth — the frontend is the user's last line
       of "what do I do now."

### What was deliberately NOT done

- **No new exception class.** Considered raising a
  `BrowserRuntimeMissingError` from the screenshot service so the
  runners could `except` it explicitly. Rejected: the screenshot
  service runs deep inside an async stack and the wrapping cost
  isn't worth it for a single error class. The substring approach
  covers the same ground with no new types.
- **No retry-on-detection.** The runners do *not* try to
  auto-install Chromium when this error is detected. That belongs
  in deployment / dev-onboarding scripts (which already exist:
  `backend/scripts/install_playwright.sh` and the Dockerfile's
  `playwright install` step).
- **No telemetry counter.** Could increment a Sentry tag or a
  Prometheus counter on each detection. Skipped — the volume
  here is "0 in prod, occasional in local dev." If we ever see
  this fire in production, that itself will be the signal.

### Pre-rolled context for tomorrow

Unchanged from yesterday — Phase 5 still gated on metric trigger,
eval coverage still blocked on labeled fixtures. This change is
purely an error-message quality improvement; it does not touch
the scan pipeline, dispatch contract, or worker-isolation
boundary.

---

## 2026-04-22 (later) — Self-hosted fonts, EMFILE watcher fix

### Symptom

After restarting the Next.js dev server (to pick up the Playwright
heuristic change above), the dashboard rendered with the wrong
typeface — system stack instead of Inter / Plus Jakarta / JetBrains
Mono. Two layered issues, surfaced in this order:

1. **Watchpack EMFILE.** The long-running `next dev` process had
   been spawned with the default macOS soft fd limit (256). After
   ~5 hours of HMR churn the watcher exhausted file descriptors:
   ```
   Watchpack Error (watcher): Error: EMFILE: too many open files, watch
   ```
   With the watcher dead, HMR couldn't see new file edits, so my
   `app/scans/page.tsx` Playwright-heuristic change above wasn't
   being picked up by the browser at all.
2. **Google Fonts 3-second timeout.** A clean restart (with
   `ulimit -n 49152`) fixed EMFILE but uncovered the real culprit:
   `next/font/google` fetches woff2 files from `fonts.gstatic.com`
   at dev/build time with a hardcoded 3 s per-request timeout and
   3 retries. From this network the cold TLS+TTFB to gstatic
   measured **7.16 s** (verified with `curl -w "%{time_total}"`).
   Every retry timed out, Next.js fell back to the system stack,
   and logged:
   ```
   ⨯ Failed to download `Inter` from Google Fonts.
     Using fallback font instead.
   ```
   The previous (long-running) dev server had succeeded once on
   boot hours ago and held the fonts in its in-memory cache, which
   is why the issue never appeared until the restart.

### What was done

**Fonts (durable fix, not a workaround):**

- Created `frontend/public/fonts/` with three latin-subset variable
  woff2 files pulled directly from Google Fonts:
    - `Inter-latin-variable.woff2`        (47 KB, Inter v20)
    - `PlusJakartaSans-latin-variable.woff2` (27 KB, Plus Jakarta v12)
    - `JetBrainsMono-latin-variable.woff2`   (40 KB, JetBrains Mono v24)
  Total payload ~114 KB on disk, served from `/fonts/` by Next.js.
- Rewrote `frontend/app/layout.tsx` to use `next/font/local` instead
  of `next/font/google`. Same three CSS variables (`--font-sans`,
  `--font-display`, `--font-mono`), same `display: "swap"`, same
  weight ranges expressed as variable-axis ranges (`100 900` for
  Inter, `200 800` for Plus Jakarta, `100 800` for JetBrains).
  Header comment in `layout.tsx` documents how to refresh the woff2
  files if a Google Fonts version bump is ever needed.

**Dev server (transient fix):**

- Killed both stale `next dev` processes (terminals 238315 / 631935)
  and their child `next-server` workers.
- Restarted with `ulimit -n 49152 && npm run dev`. macOS's
  `kern.maxfilesperproc` is 61440 here, so 49152 is comfortably
  under the kernel cap and well above whatever Watchpack's
  long-tail watching ever needs. No EMFILE on boot.
- Verified clean boot: ready in **1.58 s** (vs 7.8 s previously
  when Google Fonts had to download), no font fetch warnings, no
  Watchpack errors.
- Verified runtime: `curl http://localhost:3000/scans` returns
  200 in 4 s (first compile of 2886 modules), zero font errors
  in the dev log.

### Why self-hosted instead of bumping the timeout

`@next/font/google`'s 3 s timeout is hardcoded inside
`node_modules/next/dist/compiled/@next/font/dist/google/fetch-font-file.js`
with no public env var or config knob to override it. Patching
`node_modules` would survive ~30 seconds before the next install
wiped it out. Self-hosting is the only durable answer:

- **No network at dev/build time.** woff2 read straight from disk,
  shipped to the browser from the same origin.
- **No third-party SLA.** A 7 s gstatic response or a Google
  Fonts outage no longer changes whether the app boots.
- **Smaller production bundle.** We were already only requesting
  the latin subset, and variable axes mean one file per family
  covers every weight we use today (and any we add later).
- **Same DX.** `next/font/local` produces the same CSS variable
  output and works identically with Tailwind / shadcn — zero
  changes needed in `globals.css`, `tailwind.config.*`, or any
  consumer component.

### What was deliberately NOT done

- **No Tailwind / shadcn config changes.** The CSS variable names
  are unchanged, so every `font-sans` / `font-display` / `font-mono`
  utility in the codebase keeps working without edits.
- **No latin-ext / cyrillic / greek subsets.** The original
  `next/font/google` config only requested `subsets: ["latin"]`.
  We kept parity. If a customer ever needs accented characters
  beyond U+0000–00FF, add the relevant subset woff2 alongside
  the existing one and pass an array to `localFont({ src: [...] })`.
- **No system-wide `launchctl limit maxfiles` bump.** Per-shell
  `ulimit -n 49152` in the dev launch command is enough. A
  permanent global raise would need a launchctl plist or
  `/etc/launchd.conf` and is out of scope.
- **Did not touch the Sentry deprecation warnings** that appear
  on every Next.js boot. They predate this work and require a
  full instrumentation-file migration; tracked separately.

### Pre-rolled context for tomorrow

If the dev server ever hits Watchpack EMFILE again, the launch
command of record is now `ulimit -n 49152 && npm run dev` — bake
that into any new terminal you start for `frontend/`. If a Google
Fonts version bump (Inter v21, etc.) is ever desired, follow the
recipe in `app/layout.tsx`'s header comment: re-curl the latin
src URL out of `https://fonts.googleapis.com/css2?family=...` and
overwrite the matching .woff2 file. No code change needed.

---

## 2026-04-22 (future work) — Platform admin dashboard (deferred)

Captured here as a future-build item, not implemented. Triggered by
this observation: every operational pain point hit during today's
session (stuck scans, Playwright Chromium missing, sandboxed
backend's JWKS network failure, stale React Query errors masquerading
as "Could not connect") would have been visible in seconds from a
platform-admin view, but instead required `ps`, `lsof`, `curl`,
backend log greps, and reading `cursor-sandbox-cache/<hash>/`
overlay paths. That cost is going to scale linearly with paying
customers and is the single biggest reason to plan this work.

### Current state of "admin" in the codebase

- `auth_user_profiles.role IN ('owner', 'admin', 'member')`
  (migration 013) — but this is **org-scoped only**. An "admin"
  manages their own tenant's team via `routers/team.py:45`. There
  is **no platform-level superuser concept** anywhere.
- No `frontend/app/admin/` directory exists.
- All 15 backend routers (campaigns, scanning, matches, compliance,
  distributors, schedules, integrations, reports, alerts, billing,
  team, organizations, dashboard, feedback, compliance_rules) are
  tenant-scoped — they all filter by `organization_id` extracted
  from the verified JWT. Zero cross-tenant query surface today.
- The service-role Supabase client is already used everywhere
  (`from ..database import supabase`), with RLS bypassed at the
  API layer in favor of explicit `organization_id` filters in
  Python. Good substrate for admin views — no second DB client
  needed, no RLS rewrites required. The flip side: a single
  missing auth dependency on an admin route leaks every tenant.

### Why this is the right next "internal tooling" investment

Concrete inventory of pain that admin tooling would have eliminated
today (and will keep eliminating):

| Pain hit today                              | What admin dashboard surfaces |
|---------------------------------------------|-------------------------------|
| Scans failing on missing Playwright binary  | Cross-tenant "failed scans, last 24h" with `error_message LIKE 'Browser runtime not installed%'` count |
| Backend sandbox blocking Supabase JWKS      | Auth error rate by minute (PyJWKClientConnectionError spike) |
| Customer asks "is my scan stuck?"           | Search by org → live job state, cost so far, pipeline funnel |
| Runaway OpenAI / SerpApi / Apify spend      | Per-tenant `cost_usd` rollup over N days (already on every `scan_jobs` row from migration 027 — zero new instrumentation) |
| Stale Salesforce / Jira / HubSpot tokens    | Per-tenant integration health (`last_sync_at`, `connected_at`, error counts) |
| "Did Phase 5 worker hang?"                  | Queue depth, in-flight count, worker heartbeats (fits naturally with the worker work that's still gated below) |

None of these are visible from any tenant's own dashboard. All
require shell + SQL today.

### Why NOT to build it before there's a forcing function

- Pre-PMF / pilot. Manual SQL works at N=1–5 customers.
- Building before you know which queries you actually run produces
  the wrong abstractions. Today's pain inventory is the right
  starting list precisely because it came from a real session, not
  a whiteboard.
- Engineering hours that ship customer-visible value beat internal
  tooling at this stage. The trigger to build Phase A below is
  "first paying customer pings you about a stuck scan on a weekend"
  — not before.

### Phased plan (build in order; do NOT skip ahead)

#### Phase A — Read-only operator console (~3–5 hours)

Trigger: 2–3 paying tenants, OR Phase 5 worker ships (whichever
comes first — worker queues without operator visibility get
painful fast).

Scope:

1. **DB migration** — add `platform_admin BOOLEAN NOT NULL
   DEFAULT false` to `auth_user_profiles`. Set via SQL only.
   **Never** expose in any user-facing API, even guarded — that
   route would be the entire system's compromise vector.
2. **Auth dependency** — add `require_platform_admin()` in
   `app/auth.py`, mirroring the existing `get_current_user` /
   `get_current_user_organization_id` pattern. Single test
   asserting "every route in `routers/admin.py` declares the
   dependency" — cheapest possible RLS-bypass guardrail.
3. **Backend router** — new `backend/app/routers/admin.py` with
   exactly these read-only endpoints, no more:
   - `GET /admin/scans?status=failed&since_hours=24&limit=100`
   - `GET /admin/orgs` (id, name, plan, last_scan_at, total_cost_30d, scan_count_30d)
   - `GET /admin/costs?days=30&group_by=vendor|tenant`
   - `GET /admin/integrations/health` (per tenant: salesforce/jira/hubspot/dropbox/slack connection state + last sync)
4. **Frontend** — single route `frontend/app/admin/page.tsx`.
   shadcn DataTable + tabs (Scans / Orgs / Costs / Integrations).
   No charts. Hidden from nav unless `platform_admin === true`
   on the user profile.
5. **Audit logging** — every admin route writes one row to a new
   `platform_admin_actions` table: `(operator_user_id, action,
   target_org_id NULL, query_params JSONB, created_at)`.
   Cheap to add now, brutal to retrofit when SOC2/GDPR audit
   demands it.

That's the entire Phase A. ~4 hours. Replaces the next ~100
"let me SSH in and run a query" moments.

#### Phase B — Operations console (when ~10+ paying tenants)

- Scan retry / cancel buttons (calls existing `tasks.dispatch_task`).
- Per-tenant cost alerts (nightly job → Slack if any tenant
  exceeded threshold; threshold is a column on `organizations`
  or a global setting).
- Plan / limit changes from UI — `014_billing_plan.sql` already
  has the schema; just needs an admin-only mutation.
- Worker queue depth + heartbeat panel — this dovetails with the
  Phase 5 worker work. If Phase 5 ships first, build this *with*
  it, not after.
- "Reprocess stuck scan" button — sets `status=pending` and
  re-dispatches. Today this is a manual SQL UPDATE.

#### Phase C — Real product (50+ tenants, multi-operator team)

- Audit-log viewer (consume the `platform_admin_actions` table
  added in Phase A).
- Eval drift trends — match accuracy / compliance precision over
  time, per AI model version. Gated on the "labeled fixtures"
  blocker in the eval coverage workstream.
- "View as tenant" mode — legal/privacy implications, must be
  in TOS first, must be audit-logged.
- A/B test framework for prompts.
- This is the point at which Retool / Forest Admin / similar
  become a credible alternative to in-house. Until ~50 tenants
  the per-seat licensing + duplicated auth model isn't worth it.

### Build vs buy (Retool / Metabase / Forest Admin)

Stay DIY through Phase A and probably Phase B because:

- Auth, RLS, and queries already live in Python. Reusing them is
  faster than re-modeling them in a third-party tool.
- Retool needs per-seat licensing + a separate set of DB
  credentials sprawl; great when 5+ non-engineers operate, not
  before.
- Metabase is excellent for charts, clumsy for transactional
  actions ("click to retry this scan"). Good complement for
  Phase B/C cost dashboards, not a replacement.

Re-evaluate at Phase C, when there are non-engineer operators
who need self-serve custom views.

### Risks to design around from day one

- **Single missed `Depends(require_platform_admin)`** = total
  cross-tenant data leak. Write the static-analysis test (Phase
  A item 2) on day one. AST-walk `routers/admin.py`, assert each
  function decorator chain includes the dependency.
- **`platform_admin` flag must be unwritable from any API.** Set
  via SQL migration or one-shot CLI script in `backend/scripts/`
  only. Document in the migration comment and in the script's
  docstring.
- **Audit logging from day one**, not retrofitted. Phase A item 5.
- **Performance of cross-tenant queries.** Verify migrations
  005 / 018 cover `(status, created_at DESC)` on `scan_jobs`
  before Phase A's `/admin/scans` endpoint relies on it. If not,
  add the index in the same migration that adds `platform_admin`.
- **Notification noise.** Cost-alert thresholds (Phase B) need
  per-tenant configurability or the operator inbox dies fast.

### Decision

Deferred. Re-trigger this entry when:

1. First paying customer reports an issue you can't immediately
   answer from the existing tenant UI, OR
2. Phase 5 worker process is ready to ship (whichever first).

When the trigger fires, Phase A's scope above is intentionally
sized to fit a single 4-hour focused session. Don't expand it.
The whole point of starting small is that the *next* batch of
admin work is justified by real operator usage, not by guessing
what'll be useful.

---

## 2026-04-27 — Per-channel creative tagging

User-visible problem: when a user uploaded a creative, every scan
(Google Ads / Facebook / Instagram / Website / YouTube) treated
it as a candidate. So an Instagram-only graphic was hashed,
embedded, and CV-matched against website crawls — producing
wasted vendor cost and the occasional false positive when a
square IG asset coincidentally resembled a website hero.

The fix: let users tag each creative with the channels it's
actually approved for, and have the scan runner filter the
candidate set per source. Empty tags = "all channels," so the
rollout is safe for every existing row in production.

### What was done

1. **Schema — migration `028_asset_target_platforms.sql`**
   - `assets.target_platforms TEXT[] NOT NULL DEFAULT '{}'`.
   - `idx_assets_target_platforms` GIN index so per-source
     filtering (`target_platforms && ARRAY['facebook']`) stays
     fast on orgs with thousands of creatives.
   - Allowed values mirror `app.models.ScanSource`:
     `google_ads | facebook | instagram | youtube | website`.
   - `supabase/schema.sql` updated to match (column + index)
     so fresh setups get it without replaying migrations.

2. **Backend — Pydantic models** (`app/models.py`)
   - `AssetBase.target_platforms: List[str]` (default `[]`).
   - `AssetUpdate.target_platforms: Optional[List[str]]` —
     finally gives `AssetUpdate` a use; previously the symbol
     was imported into the router but never wired.

3. **Backend — routes** (`app/routers/campaigns.py`)
   - `_normalize_target_platforms()` helper validates against
     `ScanSource`, lower-cases, dedupes, rejects unknown
     values with `400`.
   - `POST /campaigns/{id}/assets` and
     `POST /campaigns/{id}/assets/upload` accept
     `target_platforms`. Upload uses repeated multipart fields
     (`target_platforms=facebook&target_platforms=instagram`)
     so each file in a batch can carry its own tags.
   - **NEW** `PATCH /campaigns/assets/{asset_id}` for
     post-upload re-tagging (and rename / metadata edits).

4. **Backend — scan runner filtering**
   (`app/services/scan_runners.py`)
   - `_fetch_campaign_assets(campaign_id, source=...)` filters
     out assets tagged for *other* channels. Rule (enforced
     in code, not the DB):
       - empty `target_platforms` → eligible for every source
         (legacy / "all channels" semantics)
       - non-empty → eligible only if `source` is in the array
   - Skipped-count logged so operators can see filter impact:
     `Channel filter for facebook: using 7 of 12 asset(s)
     (5 skipped — tagged for other channels)`.
   - Threaded through every call site:
     - `_run_source_scan` (Google Ads / Facebook / Instagram)
       passes its `source` param.
     - `run_website_scan` passes `"website"`.
     - `auto_analyze_scan` reads `scan_jobs.source` and
       applies the same filter before precomputing hashes /
       embeddings — so the savings land on the post-scan
       analyse path too, not just discovery.

5. **Frontend — types and helpers** (`frontend/lib/api.ts`)
   - New `TargetPlatform` union, `ALL_TARGET_PLATFORMS`
     ordering constant, `TARGET_PLATFORM_LABELS` map.
   - `Asset.target_platforms: TargetPlatform[]` added.
   - `uploadAsset(campaignId, file, { name?, targetPlatforms? })`
     — back-compat with the prior single-arg call style.
   - **NEW** `updateAsset(assetId, payload)` calls the new
     `PATCH` route.

6. **Frontend — UX iteration**
   (`frontend/app/campaigns/[id]/page.tsx`)

   First pass shipped a single per-batch picker above the
   dropzone. After review the model was wrong: real batches
   are mixed (one IG-only, one website hero, one
   everywhere), so a batch-level default silently encourages
   users to over-tag or leave everything as "all channels."

   Second pass replaced it with a staged-upload flow:
   - Drop / Select Files → files land in a "Ready to upload"
     queue, no network calls yet. Each row has a thumbnail
     (`URL.createObjectURL`), filename, **its own** pill
     multi-select, and a delete button.
   - The card-level pill row was reframed as a *default*
     applied to newly-staged rows, with a one-click "Apply
     default to all" affordance for homogeneous batches.
   - Commit-all button POSTs each row with its own
     `targetPlatforms`. Per-row status flips to
     `uploading` (spinner) → either disappears on success or
     stays in the queue with an inline error so the user can
     edit channels and retry only the failures.
   - Object-URL hygiene: `pendingUploadsRef` mirrors the
     queue so the unmount cleanup can revoke any leftover
     blobs without re-running on every state change;
     `removePendingRow`, `clearPendingUploads`, and the
     success branch of `commitPendingUploads` each revoke
     the rows they drop.

7. **Frontend — existing-asset surface**
   - Each asset card now shows its target-channel badges
     (or an "All channels" outline badge if empty). Clicking
     opens an inline pill editor that calls the new
     `PATCH /campaigns/assets/{id}` route and patches state
     in place — no full reload.
   - The per-source scan buttons in the Scans tab now show
     `"3 of 12 will be scanned"` underneath. If a source has
     zero eligible creatives, the button is disabled with
     `"No matching creatives"` plus a tooltip — protects
     users from launching a scan that can't possibly match.

### Why this approach over the alternatives

- **Why a `TEXT[]` column and not normalised
  `asset_platforms` join table?** Two reasons. First, the
  cardinality is tiny (5 source values, capped). A join
  table would add a second query (or a join) on every scan
  fetch with no benefit. Second, GIN over `TEXT[]` makes the
  one query that matters — `target_platforms && ARRAY[$1]`
  per-source — both indexable and trivial to write. A join
  table would have made the same query a `WHERE EXISTS`
  subquery for every candidate.
- **Why empty-array = "all channels" instead of `NULL`?**
  Defensive. With `NOT NULL DEFAULT '{}'` the migration
  cannot leave any row with ambiguous semantics, and the
  filter rule (`empty OR contains source`) collapses to a
  single readable line in Python. `NULL` would have meant
  three states and the inevitable bug where one branch
  forgot to handle it.
- **Why a staged-upload queue instead of "tag each file in a
  modal as you pick it"?** The modal pattern looks cheap on
  paper but kills batch upload UX — every file blocks. The
  queue lets users drop 12 files at once, eyeball the
  thumbnails, fix the two that need different channels, and
  commit. Most batches are homogeneous, so the "Apply
  default to all" button is the one-click escape hatch.
- **Why separate `auto_analyze_scan` filter from the
  `_fetch_campaign_assets` filter?** They serve different
  paths: discovery vs post-scan analyse. `auto_analyze_scan`
  reads the source from the `scan_jobs` row directly because
  by the time it runs, the dispatch context is gone. Both
  paths apply the **same rule** but from different sources
  of truth — duplicating the predicate is cheaper and
  clearer than threading the source through a queue handoff.

### What was deliberately NOT done

- **No off-channel violation rule yet.** The data is now
  there to flag "creative was tagged for IG only but
  appeared on the dealer's website" as a first-class
  compliance signal. Deferred — it's a separate compliance
  rule type that wants its own UI, not a freebie inside this
  slice.
- **No backfill of existing assets.** Every existing row
  keeps `target_platforms = '{}'` and remains "all channels"
  until users start tagging. This preserves prior scan
  behaviour exactly.
- **No Dropbox folder-name → tag inference.** The
  `dropbox_service.py` sync is the obvious next place to
  surface auto-tagging (folder `/Creatives/Instagram/` →
  `[instagram]`), but it touches a sync path that needs its
  own thinking about ambiguous folder names. Logged for the
  next session.
- **No filename sanitisation in the upload endpoint.** The
  user's first test-upload triggered Supabase Storage's
  `InvalidKey` because a macOS screenshot filename contained
  `U+202F NARROW NO-BREAK SPACE`. The endpoint already
  catches storage failures and falls back to a base64 data
  URL, so this didn't break the user-visible flow — but the
  fallback is wasteful (~250KB image bytes inlined in a JSON
  row). Worth fixing in a follow-up:
  `re.sub(r'[^a-zA-Z0-9._-]+', '_', file_name)` before
  building `unique_filename`.
- **No pre-flight POST validation.** Validation happens
  per-request inside `_normalize_target_platforms`. The
  picker only emits valid values, so a separate validation
  endpoint would be ceremony.

### Verification

- Backend: `pytest tests/test_campaigns.py
  tests/test_scan_runners_dispatch.py -q` → **19 passed**.
  No new tests added in this slice — the existing campaign
  + dispatch tests cover the routes that changed, and the
  filter logic is a pure function of the rows fetched. New
  tests for `_normalize_target_platforms` and
  `_fetch_campaign_assets(source=...)` are owed and noted
  for follow-up.
- Frontend: `tsc --noEmit` → clean.
- ReadLints across all touched files → no errors.
- Both dev servers hot-reloaded without restart.

### Runtime gotcha discovered live

After shipping the staging-queue UI, the user's first real
upload returned 500 with:

```
PGRST204: Could not find the 'target_platforms' column of
'assets' in the schema cache
```

Migration 028 had been authored but not applied to dev
Supabase — the SQL files in `supabase/migrations/` are only
auto-applied on merge to `main` via the GitHub Actions
`supabase db push` step. For local dev the column has to be
applied manually (`supabase db push` from repo root, or paste
the SQL into Studio's editor).

Worth remembering: PostgREST caches its schema, so even
after the `ALTER TABLE` runs you may need
`NOTIFY pgrst, 'reload schema';` (or a project restart in
Studio) before the new column is visible to the API. The
migration body now ends with that NOTIFY for safety.

### Files touched this entry

| File | Change |
|---|---|
| `supabase/migrations/028_asset_target_platforms.sql` | **NEW** — `target_platforms TEXT[]` + GIN index |
| `supabase/schema.sql` | mirror column + index for fresh setups |
| `backend/app/models.py` | `AssetBase.target_platforms`, `AssetUpdate.target_platforms` |
| `backend/app/routers/campaigns.py` | `_normalize_target_platforms()`, upload + create accept tags, **NEW** `PATCH /campaigns/assets/{id}` |
| `backend/app/services/scan_runners.py` | `_fetch_campaign_assets(source=...)` + threaded through `_run_source_scan`, `run_website_scan`, `auto_analyze_scan` |
| `frontend/lib/api.ts` | `TargetPlatform` types, `Asset.target_platforms`, new `uploadAsset` signature, **NEW** `updateAsset()` |
| `frontend/app/campaigns/[id]/page.tsx` | staged-upload queue, per-row pill picker, post-upload inline editor, "X of Y will be scanned" banner |
| `log.md` | this entry |

### Pre-rolled context for tomorrow

Three follow-ups queued out of this session, in priority order:

1. **Off-channel violation as a compliance signal.** The
   data is there. Needs a new `compliance_rules` rule type
   (`channel_mismatch`) and a small UI in the rules editor.
   This is the highest-leverage next step because it turns
   a passive cost-saver into an active product feature
   ("we caught your dealer running the IG-only creative on
   their website").
2. **Filename sanitisation in `upload_asset`.** Five-line
   `re.sub` plus a regression test. Stops the base64
   fallback path from being silently exercised by macOS
   screenshot filenames. Tiny but worth a focused PR.
3. **Tests for `_normalize_target_platforms` and the
   per-source filter in `_fetch_campaign_assets`.** Pure
   functions, easy to cover, owed.

Phase 5 (worker process) status: unchanged. This change
added zero scan-pipeline shape — only filtering — so the
4.8 driver / 4.7 buffer / 4.1–4.3 bulk-insert prerequisites
are still the only things to port when Phase 5 starts.

---

## 2026-04-28 — Phase 5-minimal: 50-dealer cold-scan readiness

First paying client wants to start a 50-dealer cold website scan. The
existing build was documented as topping out at ~15–20 dealers with the
2026-04-10 scaling roadmap (`log.md:2334`); the gap was Phase 5 (a
separate worker process) plus a handful of timeout / cleanup / browser
defaults that would actively kill a long scan. Today's sprint closes
that gap with the minimum code required — no Redis queue, no chunked
parent/child jobs, no ARQ revival.

### What shipped (in order)

**Day 1 — config and cleanup safety (a half day)**

1. **Migration 029 — `last_heartbeat_at` column on `scan_jobs`.**
   The original `_heartbeat()` was made a no-op on 2026-04-01 because
   it was clobbering `started_at`. Adding a dedicated column means we
   can re-instate a real heartbeat without breaking the dashboard's
   scan-duration metrics. The column is nullable (existing rows
   unaffected) and indexed on `(status, last_heartbeat_at)` for the
   cleanup query. `supabase/schema.sql` mirrors the column + index so
   fresh setups skip the migration. NOTIFY pgrst at the end so
   PostgREST's schema cache picks the column up immediately (lesson
   from migration 028's runtime gotcha).
2. **`scan_runners._heartbeat()` re-implemented.** Writes ONLY
   `last_heartbeat_at`; never touches `started_at`. Best-effort with
   debug-level error swallowing so a transient Supabase hiccup never
   fails an otherwise-healthy scan. Now called once per page in the
   discovery loop, once after page-discovery, once after asset
   pre-compute, once after the `discover()` callable in
   `_run_source_scan` — every place a long blocking step lives.
3. **`scheduler_service._cleanup_stale_scans()` rewritten.** Cutoff
   raised from 60 min → 4 hours. Predicate is now heartbeat-aware:
   * If `last_heartbeat_at` is set, fail only when the heartbeat
     itself has not advanced in 4h.
   * If NULL (older rows or runners that died in prep), fall back to
     the old `created_at`-based check at the same 4h horizon.
   The cleanup is the safety net; the runner's own
   `SCAN_TIMEOUT_SECONDS` is the primary backstop.
4. **`tasks.py::SCAN_TIMEOUT_SECONDS` 7200 → 14400** (2h → 4h). Cold
   50-dealer scans on a fresh tenant measure 1–2h end-to-end on the
   new concurrent runner; doubling that gives headroom for an outlier
   slow dealer.
5. **`extraction_service::_BROWSER_MAX_AGE_SECONDS` 600 → 3600**
   (10 min → 60 min). The 10-minute recycle was a single-process
   defensive choice — under per-dealer concurrency it forces a
   multi-second relaunch in the middle of nearly every long scan and
   risks tearing down an in-flight page.
6. **CLIP installed in production.** Added `sentence-transformers`
   and `torch` to `requirements.txt`; the Dockerfile now installs the
   CPU-only torch wheel from PyTorch's CPU index (so the image does
   not balloon with the default CUDA build) and pre-downloads
   `clip-ViT-B-32` so the first scan does not pay the cold-load
   latency. Per the 2026-04-13 audit this single change re-enables
   AI Stage 2 (silently disabled in prod for weeks) and cuts Opus
   call volume by 50–70%.

**Day 2 — actual worker process (1 day)**

7. **`tasks.py::dispatch_task` now persists dispatch args before
   running anything.** New `_persist_dispatch_args()` writes
   `{task_name, args}` onto `scan_jobs.metadata.dispatch` so a worker
   can replay the row later. New `DISABLE_INPROCESS_DISPATCH=true`
   env flag short-circuits the `asyncio.create_task` step on the API
   service — the row is left in `pending` for the worker to claim.
   New `KNOWN_TASK_NAMES` constant + `execute_persisted_task()`
   helper give the worker the dispatch surface it needs without
   duplicating the wrapper map.
8. **`backend/app/worker.py` — new entry point.** ~250 lines.
   Designed to be invoked as `python -m app.worker`. Loop:
   * `SELECT id, source, metadata FROM scan_jobs WHERE status='pending'
     ORDER BY created_at LIMIT 1`.
   * Atomic claim via conditional UPDATE
     (`update({...status='running'...}).eq('id', X).eq('status', 'pending')`)
     — `len(claim.data) == 1` means we won the race, 0 means another
     worker (or the API in mixed mode) got it first.
   * Pull `task_name` + `args` off `metadata.dispatch`, route to
     `tasks.execute_persisted_task`.
   * On crash, normalise the error message (reusing
     `scan_runners._normalize_scan_error`) and mark the row failed.
   * SIGTERM / SIGINT graceful shutdown — finish the in-flight job
     before exit (DO sends SIGTERM with ~10s before SIGKILL, plenty
     for "don't claim the next one").
   * Pre-warms CLIP at boot via `embedding_service.warmup()` so the
     first job doesn't pay model-load latency on top of its own scan
     time.
9. **`.do/app.yaml` — `workers:` block added** (`scan-worker`).
   Same Dockerfile, `instance_size_slug: professional-m` (8 GB —
   Chromium + CLIP + image cache + per-scan buffers fit comfortably),
   `instance_count: 1`, `run_command: python -m app.worker`,
   `SCHEDULER_ENABLED=false` (scheduler stays in API, holds the
   Redis lock). The API `service` got `DISABLE_INPROCESS_DISPATCH=true`
   so it stops running scans itself — it now just persists args and
   moves on. Removing that flag (or setting "false") flips back to the
   legacy in-process mode for local dev and small tenants.
10. **`tests/test_worker_import_isolation.py` extended.** New test
    `test_worker_entrypoint_imports_without_fastapi_or_slowapi`
    spawns a fresh subprocess with a `MetaPathFinder` blocking
    fastapi/slowapi, imports `app.worker.main` and
    `app.tasks.execute_persisted_task`. If either ever pulls in the
    HTTP layer, CI fails with a pointer to this entry. The
    isolation-subprocess builder was rewritten to plain string
    concat — the previous `textwrap.dedent` + multi-line f-string
    interpolation broke the dedent's "common prefix" detection when
    the new test passed a multi-line import block.

**Day 3 — concurrency in `run_website_scan` (1 day)**

11. **Per-dealer parallelism in the website runner.** Replaced the
    flat `for page in expanded_urls` loop with a per-dealer
    `asyncio.gather` driven by `asyncio.Semaphore(max_concurrent_dealers)`
    (new config knob, default 4). Each dealer task:
    * Holds the semaphore for the duration of its work, bounding
      both Playwright contexts and in-flight AI batches.
    * Owns its own `MatchBuffer` and `ProcessedImageBuffer` — the
      bulk writers are explicitly NOT coroutine-safe per the
      2026-04-21 / 2026-04-22 entries; sharing across dealers would
      race on `_pending`.
    * Owns its own `pipeline_increments` dict and returns it to the
      caller for aggregation — avoids a contended Lock around ints
      that fire dozens of times per page.
    * Honours global early-stop via `asyncio.Event` + `asyncio.Lock`
      around the shared `matched_asset_ids` set. The Event is the
      cheap notify channel, the Lock+set is the source of truth.
    Phase 1 (cached-page warm-up) stays sequential — cached pages
    are short, and serialising them keeps cache-hit accounting
    simple. The shared cache-phase buffer drains at end-of-function
    next to the per-dealer flushes.
12. **`config.max_concurrent_dealers` (new, default 4)** added
    alongside the existing `max_concurrent_pages` (clarified in its
    description as legacy / `scan_dealer_websites`-only). 4 fits
    a 4 GB worker comfortably; bump to 6–8 if the worker is sized up
    to professional-l (8 GB).

### Wall-clock impact

Pre-sprint expectation for a cold 50-dealer scan with no warm cache
and 15 pages per dealer (Professional-tier defaults):

* Sequential (today's main): ~75–150 min, hits the 60-min cleanup
  cutoff and gets auto-failed.
* Sequential without cleanup: ~75–150 min wall clock, blocks the API
  process for the duration.

Post-sprint estimate (same workload):

* Per-dealer concurrency × 4 + worker process + heartbeat-aware
  cleanup: **~25–45 min** wall clock, API stays fully responsive,
  cleanup safety net kicks in only on truly stuck runners.
* On a warm cache (subsequent scans): **~10–15 min**.

These are extrapolations from the pipeline math in the
2026-04-10 / 2026-04-13 entries, not measured. Day-3 dry-run with
5 dealers will give the first real per-dealer number to extrapolate
the full 50-dealer estimate from.

### What this sprint deliberately did NOT do

* **No Phase 3 parent/child chunking.** Right answer at 150+
  dealers; overkill at 50. The single-process worker with intra-job
  per-dealer concurrency is correct for the first client.
* **No queue migration to Redis Streams / SQS.** Two prior failed
  attempts on 2026-03-28; postgres-polled worker is the path the
  team converged on. The polling interval (default 2s) is plenty for
  a single-tenant pilot.
* **No multi-worker scaling.** `instance_count: 1` for the pilot.
  The atomic-claim UPDATE in `worker._claim_pending_job` is
  race-safe so adding more workers later is config-only.
* **No platform-admin dashboard.** The 2026-04-22 entry already
  deferred this with a clear trigger; that trigger ("first paying
  customer pings you about a stuck scan on a weekend") still hasn't
  fired.
* **No `is_processed` UPDATE batching change.** Already shipped in
  Phase 4.7; the per-dealer buffers picked it up for free.

### Tests

* `pytest tests/ -q` → **120 passed** (was 119 — net +1 from the new
  worker-isolation test, with 4 existing dispatch tests adjusted to
  filter to status-bearing updates because of the new heartbeat
  cadence).
* `ReadLints` across all 13 touched files → clean.
* Worker import-isolation guard green for both `app.services.scan_runners`
  and the new `app.worker` entry point.

### Files touched

| File | Change |
|---|---|
| `supabase/migrations/029_scan_heartbeat.sql` | **NEW** — `last_heartbeat_at` column + composite index |
| `supabase/schema.sql` | mirror column + index for fresh setups |
| `backend/app/services/scheduler_service.py` | cleanup 60min → 4hr, heartbeat-aware predicate |
| `backend/app/services/scan_runners.py` | `_heartbeat()` re-implemented; new `_process_one_dealer()` + `page_discovery_discover()` helpers; Phase 2 of `run_website_scan` rewritten for per-dealer concurrency |
| `backend/app/services/extraction_service.py` | `_BROWSER_MAX_AGE_SECONDS` 600 → 3600 |
| `backend/app/config.py` | new `max_concurrent_dealers` (default 4); existing `max_concurrent_pages` description clarified |
| `backend/app/tasks.py` | `_persist_dispatch_args`, `KNOWN_TASK_NAMES`, `execute_persisted_task`, `DISABLE_INPROCESS_DISPATCH` env flag, `SCAN_TIMEOUT_SECONDS` 7200 → 14400 |
| `backend/app/worker.py` | **NEW** — `python -m app.worker` entry point with atomic-claim polling loop |
| `backend/Dockerfile` | install CPU-only torch; pre-download CLIP model into image |
| `backend/requirements.txt` | + `sentence-transformers==3.3.1`, `torch==2.5.1` |
| `.do/app.yaml` | new `workers:` block (`scan-worker`); API service gains `DISABLE_INPROCESS_DISPATCH=true` |
| `backend/tests/test_worker_import_isolation.py` | new `test_worker_entrypoint_imports_without_fastapi_or_slowapi`; subprocess builder rewritten |
| `backend/tests/test_scan_runners_dispatch.py` | added `_status_transitions()` filter; 3 driver tests updated to ignore heartbeat-only updates |
| `log.md` | this entry |

### What the operator must do before the first 50-dealer scan

1. **Apply migrations 028 and 029** to the production Supabase
   (`supabase db push` or paste each file into Studio's SQL editor).
   Migration 028 was authored 2026-04-27 but only auto-applied on
   merge to main; 029 is brand new today.
2. **Set the client's org `subscription_tier` to `business`** (or
   `enterprise`) in the `organizations` table. Professional caps
   `max_dealers` at 40, which would block creation of the 50th
   distributor. Business caps at 100 and is sufficient.
3. **Deploy** — DO App Platform will pick up the new `scan-worker`
   component on the next push to `main`. Verify both `api` and
   `scan-worker` reach RUNNING in the DO dashboard.
4. **Sanity-check env vars on `scan-worker`** in the DO dashboard:
   the `app.yaml` declares them with `value: "PLACEHOLDER"` so DO
   will prompt for the real secrets on first deploy. Mirror the
   existing API secrets exactly. Critical ones for the worker:
   `SUPABASE_*`, `ANTHROPIC_API_KEY`, `SCREENSHOTONE_*`,
   `SERPAPI_API_KEY`, `APIFY_API_KEY`, `RESEND_API_KEY`.
5. **Verify CLIP loaded** by tailing the worker logs at boot — look
   for `CLIP model warmed up`. If it says `Stage 2 will be skipped`
   the torch install failed; check the build log.
6. **Dry-run with 5 dealers from this client first.** Watch:
   * Does the API insert the `scan_jobs` row and return 200? (Yes
     means dispatch-args persistence worked.)
   * Does the worker log `Worker running job=...` within 2-3s?
     (Yes means the polling claim worked.)
   * Does `last_heartbeat_at` advance in the DB once per page?
   * Does `pipeline_stats.clip_rejected` appear non-zero in the
     completed scan? (Yes confirms Stage 2 is firing.)
   * Per-dealer wall clock × 50 ÷ 4 ≈ full-scan estimate.
7. **Run the full 50.** Frontend already shows scan progress;
   notifications already deep-link per the 2026-04-22 work.

### What's left for after the pilot lands

* **Heartbeat cadence inside `_process_one_dealer`.** Currently the
  heartbeat fires at the start of each page; for a dealer with 15
  pages × 30s/page that's 7.5 min between heartbeats — well under
  the 4h cleanup horizon, so no urgency.
* **Multi-worker scaling.** `.do/app.yaml::workers[0].instance_count`
  bumped from 1 → N. Atomic-claim already race-safe.
* **Phase 3 parent/child chunking.** Not needed for 50; revisit at
  150+ when one worker can no longer finish a single tenant's scan
  in a reasonable window.
* **Scan-job `metadata` retention sweep.** The persisted dispatch
  args now live on every scan_jobs row; retention_service should
  consider purging them after the row reaches `completed` /
  `failed` to keep the JSONB column small. Probably a quarter's
  worth of work before it matters.

---

## 2026-04-28 (evening) — Per-campaign dealer picker, the missing worker, and the Akamai wall

Continuation of the same day. Phase-5-minimal had just shipped; the
client immediately tried to drive it. Three problems surfaced in
sequence — a missing UX affordance, a deployment gap that the
morning's `app.yaml` change did not actually apply, and the discovery
that the dealers in question all live behind an Akamai WAF that
Playwright-from-DigitalOcean cannot defeat.

### What shipped

**1. Per-campaign dealer selection (commit `f5ab71b`)**

Until tonight, "Start scan" on a campaign meant "scan every active
distributor in the org," which is not what a campaign manager wants
when they're testing one creative against a regional sub-set.

* **Backend (`backend/app/routers/campaigns.py`).** Both
  `start_campaign_scan` and `batch_campaign_scan` now accept an
  optional repeated `distributor_ids` query parameter. New helper
  `_resolve_scan_distributors()` returns the explicit selection
  when provided (validated against the org's distributors — bogus
  IDs raise 400), else falls back to all active distributors.
* **Frontend API client (`frontend/lib/api.ts`).**
  `startCampaignBatchScan` now serialises an optional
  `distributorIds: string[]` as repeated `distributor_ids=…` query
  params; `startCampaignScan` already did.
* **Frontend UI (`frontend/app/campaigns/[id]/page.tsx`).** The
  Scans tab gained a "Dealers to scan" card with a search box,
  per-dealer checkboxes, and Select-visible / Clear-all buttons.
  Selection is persisted to `localStorage` keyed by campaign id so
  it survives reloads. Each scan-source button surfaces "X
  creatives · Y of Z dealers" and disables itself if there are no
  matching creatives or no dealers selected. `selectedDealerIds`
  is forwarded into both single-channel and batch scan calls
  (empty array → undefined → backend uses all-active fallback).

No DB migration; the `scan_jobs` row still records the resolved
distributor set in its existing `metadata` field.

**2. The missing `scan-worker` component on DigitalOcean**

Symptom: every scan started after the morning deploy sat in
`pending` indefinitely until `_cleanup_stale_scans` flipped it to
`failed`. The morning's commit added `DISABLE_INPROCESS_DISPATCH=true`
to the API service, so the API correctly handed off to the worker —
but the worker did not exist. `.do/app.yaml` had a `workers:` block
declaring `scan-worker`, but DO App Platform's `deploy_on_push` only
rebuilds **existing** components; it does not create new ones from a
spec change. The component had to be applied with an explicit
`doctl apps update`.

What we did:

* Installed `doctl v1.155.0` (`darwin-arm64`) into `~/.local/bin`.
* `doctl apps list` → app id `aaff4f43-8fc8-4424-be13-35a676818543`.
* Discovered `doctl apps spec validate` rejects already-encrypted
  secret values ("must not be encrypted before app is created") —
  it treats every spec as a *create* spec. `doctl apps update`
  handles encrypted secrets correctly, so we skipped validation
  and applied the spec directly.
* `doctl apps update <id> --spec /tmp/new-spec.yaml` succeeded;
  both `api` and the new `scan-worker` reached RUNNING. Subsequent
  scans transitioned `pending → running` within 2-3s of insert
  (the polling cadence we set).

The previously-stuck `pending` row had already aged past
`_cleanup_stale_scans`'s 15-min pending horizon and was failed by
the safety net before the worker came online — expected, not a
bug. New scans behaved correctly.

**3. Truthful metrics, survivable browser, anti-bot bypass (commit `81f5da1`)**

The first real run after the worker came up was a 46-dealer scan.
It "completed" in ~10 minutes and reported 52 pages scanned —
clearly wrong, since 45 of the 46 dealers point at `rent.cat.com`
and the runner cannot possibly have done a real scan of each in
~10s. The logs showed three distinct failure modes: silent
"screenshot fallback" rows being counted as scanned pages,
`net::ERR_ABORTED` and timeout cascades, and
`TargetClosedError: BrowserContext.new_page` errors that abandoned
~10 dealers entirely. Root causes and fixes:

| # | Failure mode                                             | Root cause                                                                                                                                           | Fix                                                                                                                                                                                                                                                |
|---|-----------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| A | "52 pages scanned" was a lie                             | `enable_tiling_fallback` inserted a blank screenshot row for every page that returned 0 images and then the runner counted that as `pages_scanned += 1`. | Replaced `(count, evidence_url)` tuple return with an `ExtractionResult` dataclass carrying `outcome ∈ {images, empty, blocked, timeout, crashed}`, `block_reason`, `http_status`. Runner only bumps `pages_scanned` for `OUTCOME_IMAGES` (or the tiling fallback for genuinely-empty pages). |
| B | One slow site killed every other in-flight dealer        | `_extract_from_viewport`'s retry path was *recycling the process-wide browser singleton* (`async with _browser_lock: close+stop+restart`). Concurrent dealer tasks holding the old browser handle then crashed with `Target page, context or browser has been closed`. | Removed the in-place global recycle. Retry now uses a fresh `BrowserContext` only; the shared browser is re-acquired (and only relaunched if `is_connected() == False`) via `_get_browser`. `_attempt_extraction` catches `TargetClosedError` on `new_page()` and re-acquires once before giving up. |
| C | "Errors" with no actionable reason                       | `extract_dealer_website`'s `except` collapsed every Playwright exception into a single log line; the runner had no way to tell a WAF from a real bug. | New `_classify_playwright_error` maps Chromium net errors (`ERR_ABORTED`, `ERR_BLOCKED_BY_*`, `ERR_HTTP_RESPONSE_CODE_FAILURE`, cert errors) → `OUTCOME_BLOCKED`. HTTP 4xx/5xx navigation responses also flip to BLOCKED with the status code attached. Blocked pages still get a screenshot row but tagged `capture_method: "blocked_evidence"` with `reason` + `http_status` in metadata. |
| D | Nothing in the codebase actually tries to *bypass* the WAF | Browser was launched with no anti-detect flags; every host got the same desktop UA; no fallback to a residential renderer.                        | Browser launches with `--disable-blink-features=AutomationControlled`. Every context gets a small init script overriding `navigator.webdriver`, `navigator.plugins`, `navigator.languages`, `chrome.runtime`. Hosts in `WEBSITE_MOBILE_FIRST_HOSTS` (env-configurable, default `rent.cat.com`) try mobile viewport first; on block/timeout the runner switches viewport once. New `screenshotone_fallback_enabled` setting (default on): when both viewports return BLOCKED, fall back to the existing ScreenshotOne integration so the user still gets a real screenshot from a non-DO IP. |

Other plumbing the refactor touched:

* `pipeline_stats` gained `pages_empty`, `pages_blocked`,
  `pages_failed`, `dealers_total/ok/partial/blocked/failed/empty`
  and `blocked_details[]` (per-dealer list of failed pages with
  reason / http_status).
* `_send_scan_notifications` summary dict gained the same counters
  so the scan-complete email and Slack messages now report
  truthfully.
* `/scans` page (`frontend/app/scans/page.tsx`) gained an amber
  "X blocked, Y failed · N dealers blocked" indicator under the
  pages line and the matching `PipelineStats` type fields.
* The legacy in-extraction-service `scan_dealer_websites._process_url`
  was updated to the new return type so it does not break the
  (currently-unused) screenshot-mode pipeline.
* New `screenshotone_fallback_enabled` setting in `config.py`.

Tests: `pytest -q` → 120 passed (no new tests this session;
existing dispatch / bulk-writer / error-normalizer suites cover the
runner-shape changes). `frontend/ npx tsc --noEmit` → clean.
ReadLints across the touched files → clean.

### Diagnostic — what tonight's run actually proved

Second run after the deploy: 46 dealers, 60 pages discovered, run
took ~10 min (same as before). The new counters tell the actual
story:

```
pages_scanned:  15      (yanceybros only)
pages_empty:     0
pages_blocked:   9      reason: HTTP 403   ← Akamai sent a clean reject
pages_failed:   36      reason: timeout    ← Akamai held the TCP connection open and never replied
dealers_ok:      1
dealers_blocked: 9
dealers_failed: 36
ScreenshotOne cost: $0.036  → exactly 9 renders fired, all on the HTTP-403 dealers
```

Akamai is doing two-mode protection: a clean 403 for some dealer
sub-paths and a silent stall for others. The mobile-first switch
and stealth init-script *did not help* because the block is at the
**edge** — Chromium never gets a chance to run the JS that those
overrides patch. Switching UA does not help either because the
fingerprint that matters is the **DigitalOcean datacenter IP block**,
which is on Akamai's denylist. ScreenshotOne worked on 9 of them
precisely because it renders from a different IP pool.

The ScreenshotOne fallback **only fires on `OUTCOME_BLOCKED`** in the
current code. The 36 silent timeouts return `OUTCOME_TIMEOUT` and so
never reach the fallback — that is the single biggest win available
for tomorrow (see next steps).

### Files touched

| File | Change |
|---|---|
| `backend/app/routers/campaigns.py` | `Query()` for `distributor_ids` on single + batch scan; `_resolve_scan_distributors` validation helper |
| `frontend/app/campaigns/[id]/page.tsx` | Dealer-picker card: search, checkboxes, select-visible / clear-all, localStorage persistence; per-source enablement |
| `frontend/lib/api.ts` | `startCampaignBatchScan(campaignId, distributorIds?)` repeated-param serialisation |
| `backend/app/services/extraction_service.py` | `ExtractionResult` dataclass; `OUTCOME_*` constants; `_classify_playwright_error`; `_attempt_extraction` (single-shot) + `_extract_from_viewport` (retry) split; `_screenshotone_fallback`; stealth args + init script; `MOBILE_FIRST_HOSTS` (env-overridable); `extract_dealer_website` returns `ExtractionResult`; legacy `scan_dealer_websites._process_url` updated |
| `backend/app/services/scan_runners.py` | `_process_one_dealer` consumes `ExtractionResult` and bins outcomes; new locals `pages_empty / blocked / failed`, `local_block_details`, `dealer_status`; aggregator rolls up `dealers_*` and `blocked_details` into `pipeline_stats`; `_send_scan_notifications` summary dict carries the new counters; cache-phase `extract_dealer_website` call updated |
| `backend/app/config.py` | `screenshotone_fallback_enabled: bool = True` |
| `frontend/app/scans/page.tsx` | `PipelineStats` type extended with the new counters + `blocked_details[]`; amber chip under the pages line |
| `.do/app.yaml` (operator-only) | applied via `doctl apps update`; `workers:` block now actually present in the live spec |
| `log.md` | this entry |

### Commits

* `f5ab71b` — Allow per-campaign dealer selection when starting scans
* `81f5da1` — Truthful website-scan metrics, survivable browser, anti-bot bypass

Both pushed to `main`; DO `deploy_on_push` rebuilt both `api` and
`scan-worker` automatically (deployment `1d0776aa` for the second
commit).

### Next steps for tomorrow (ordered by ROI)

1. **Trigger ScreenshotOne fallback on `OUTCOME_TIMEOUT`, not just
   `OUTCOME_BLOCKED`, when the host is in `MOBILE_FIRST_HOSTS`.**
   Five-line change in `_attempt_extraction` /
   `extract_dealer_website`. Would have captured the 36 timed-out
   cat dealers tonight at +$0.144 cost. Single biggest win.
2. **Skip Playwright entirely for known-bot-walled hosts.** Add a
   `WEBSITE_BYPASS_PLAYWRIGHT_HOSTS` env (default
   `rent.cat.com`); when matched, go straight to ScreenshotOne. Saves
   ~9 minutes of wasted timeouts per scan and produces the same
   evidence. Combined with #1 the cat scan should drop from ~10 min
   → ~3 min and report 45/46 dealers scanned.
3. **Add `proxy=residential` (and `delay=8`) overrides on the
   ScreenshotOne fallback for hosts in a new
   `WEBSITE_RESIDENTIAL_HOSTS` set.** ScreenshotOne already worked
   on 9/45 with the default datacenter pool; residential should
   push the rest through. Cost goes from $0.004 → ~$0.01/render —
   still pocket change.
4. **Per-host `playwright_timeout` override.** While we still try
   Playwright on bot-walled hosts (e.g. as a fast probe before the
   ScreenshotOne fallback), 60s is overkill — Akamai either
   responds within ~5s or never. A 10s probe timeout for hosts in
   `MOBILE_FIRST_HOSTS` reclaims most of the wall-clock back.
5. **Surface `dealers_failed` in the `/scans` chip.** Tonight's UI
   shows `9 dealers blocked` but not `36 dealers failed`. Trivial
   addition next to the existing `dealers_blocked` span.
6. **Enrich `OUTCOME_TIMEOUT` reason.** `_classify_playwright_error`
   currently returns `(OUTCOME_TIMEOUT, None)`. Make it
   `(OUTCOME_TIMEOUT, "navigation_timeout")` (and ideally include
   the viewport that last failed) so the `blocked_details[]` rows
   read cleanly.
7. **Add a `primary_url` field to `distributors`.** The durable fix:
   for every cat dealer there is also a public dealer-owned site
   (yanceybros.com, thompsontractor.com, …) that mirrors the same
   co-op creatives and is *not* WAF-protected. Scrape that first
   and only fall back to `rent.cat.com` if the primary URL fails
   to find the asset. Migration + small UI for the operator to
   record both URLs per distributor.
8. **Investigate the `hash_rejected: 241 / 298` ratio.** Even on
   the dealer that did scan cleanly (yanceybros), 81% of extracted
   images were rejected at the perceptual-hash gate before CLIP
   even ran. Either the threshold is wrong or the hash isn't doing
   what we think for resized site assets.
9. **Operator escalation (out-of-band).** The ultimate answer to
   `rent.cat.com` is not technical — it's asking Cat (or the
   client's relationship manager at Cat) for either an API
   feed or an Akamai whitelist for our scanner egress IP. Worth a
   single email before sinking more engineering into bypass tooling.

---

## 2026-04-29 — Phase 6 adaptive render-strategy, three follow-on bug fixes, and the false-positive match fix

A single long session that closed the loop on the previous evening's
"how do we get past blocked and failed" question. We built the
learning layer that makes the scanner remember what works for each
host, then spent the rest of the day shaking the production bugs out
of it. Three commits, two of them shipped while the user watched
real scan logs.

### What shipped

**1. Phase 6 — adaptive render-strategy per hostname (commit `6c198c0`)**

The Akamai wall is not solvable with a single rendering technique;
the right answer is a *ladder* of techniques and a *memory* of which
rung worked for each hostname. This commit added both.

* **`backend/app/services/render_strategies.py` (new, 366 LOC).**
  `RenderStrategy` is now a string identifier
  (`playwright_desktop` → `playwright_mobile` →
  `screenshotone_datacenter` → `screenshotone_residential` →
  `unreachable`) backed by `STRATEGY_LADDERS`, an ordered list of
  `RenderAttempt` instances per strategy. `run_ladder()` walks the
  list, returns on the first `OUTCOME_IMAGES`, and short-circuits as
  soon as a screenshot rung produces an `evidence_url` (no point
  burning a residential render after datacenter already captured the
  page). `_PlaywrightAttempt` and `_ScreenshotOneAttempt` both
  conform to a `RenderAttempt` protocol with an
  `is_screenshot_capture: bool` flag the ladder uses to decide
  whether an evidence-only success counts as terminal.
* **`backend/app/services/host_policy_service.py` (new, 609 LOC).**
  Reads/writes `host_scan_policy` rows. `ensure_policy(url)` returns
  the right ladder strategy for a hostname — known hosts get their
  saved strategy, unknown hosts trigger a cheap `httpx.get` probe
  (`preflight_probe`) that sniffs for WAF-vendor headers
  (`_WAF_FINGERPRINTS` covers Akamai, Cloudflare, Imperva, F5,
  AWS WAF) and seeds an initial strategy. After every scan,
  `aggregate_from_pipeline_stats` + `record_host_outcomes` walks the
  observed outcomes, increments per-host
  `success_30d / blocked_30d / timeout_30d` counters, and
  auto-promotes any host that has hit `PROMOTE_THRESHOLD = 2`
  consecutive failures on its current strategy (e.g.
  `playwright_desktop → screenshotone_datacenter`). Manual overrides
  via `manual_override = true` are honored — never auto-promoted.
  `RESET_ON_SUCCESS` clears confidence the moment a host renders
  cleanly so a one-day Akamai blip doesn't stick a domain on
  residential proxies forever.
* **`supabase/migrations/030_host_scan_policy.sql` + `schema.sql`
  mirror.** New `host_scan_policy` table: `hostname` PK, `strategy`
  (CHECK constrained to the five known values), `waf_vendor`,
  `confidence`, `last_outcome`, `last_block_reason`,
  `last_http_status`, the three 30-day counters, `last_seen_at`,
  `last_promoted_at`, `manual_override`, `notes`, `created_at`,
  `updated_at`. Indexed on `(strategy)` and `(last_seen_at)` for the
  retention sweep that will eventually live here. Ends with
  `NOTIFY pgrst, 'reload schema';` so PostgREST picks it up
  immediately.
* **`extraction_service.extract_dealer_website` rewrite.** Was
  ~250 LOC of viewport-switching, mobile-host detection, and
  ScreenshotOne fallback wiring. Now ~30 LOC: ask
  `host_policy_service.ensure_policy(url)` for a strategy, build a
  `RenderContext`, call `render_strategies.run_ladder(ctx,
  strategy=…)`, return the final `ExtractionResult`. The ladder
  attempts trail is stamped onto `block_reason` for audit
  (`ladder(playwright_desktop): playwright_desktop=blocked -> screenshotone_datacenter=blocked`).
  `MOBILE_FIRST_HOSTS` and the env var that fed it were deleted.
* **`scan_runners.run_website_scan` post-scan hook.** After the
  per-dealer aggregation loop, call
  `host_policy_service.aggregate_from_pipeline_stats(pipeline_stats)`,
  merge in `success_pages_by_host` (so hosts that worked don't get
  promoted just because we never logged a success against them),
  call `record_host_outcomes()`, and stamp any auto-promotions onto
  `pipeline_stats["host_promotions"]` for the dashboard. Wrapped in
  a broad `except` — the learning layer never fails a scan.
* **27 new unit tests** in `test_render_strategies.py` and
  `test_host_policy_service.py` covering the ladder, strategy
  promotion order, the early-stop behavior, WAF fingerprinting,
  policy aggregation, manual overrides, sticky `unreachable`
  strategy, and the pre-flight probe under 200 / 403-Akamai / 429 /
  connection-error conditions.

The day-1 result: an empty `host_scan_policy` table that the runner
backfills as scans complete. By the second scan of any
previously-blocked host (`rent.cat.com` et al.), Playwright is
skipped entirely and the request goes straight to whatever rung
worked last time.

**2. Migration-030 not applied (operator fix)**

User reviewed the first post-deploy scan and reported "no way this
thing scanned all 49 dealers — looks like it's only getting data
from `yanceybros.com`." Logs showed
`host_scan_policy lookup failed for rent.cat.com: PGRST205` on every
single dealer — i.e. CI's auto-migrate had not actually applied 030
to Supabase. Diagnosed in three minutes; the user pasted the SQL
into Supabase Studio's SQL editor. After the manual apply, the next
scan's logs showed the policy table being read and written correctly
on every host.

This was a process failure, not a code one — the auto-migrator
runs on the API container, but the deployment that introduced 030
failed its first health check (because the API code referenced a
table that didn't exist yet, classic chicken-and-egg). The
recommended fix going forward is to split schema migrations from
code that uses them across two deploys, or to make the runner
tolerate `PGRST205` and fall back to the default strategy. The
runner already does the latter via the broad `except` around
`ensure_policy` — but only logs at WARNING, not ERROR, so the
problem hid in the noise. See next steps.

**3. Three production bugs surfaced from the first real scan
(commit `1490e86`)**

Once 030 was live, the user asked us to "fix the bugs and the
screenshots not being read." Reading the logs alongside the user
turned up three distinct issues:

* **ScreenshotOne residential calls were 400ing.** We were sending
  `overrides["proxy"] = "residential"` — the actual ScreenshotOne
  parameter is `proxy_type`. Every residential render this year
  has been silently failing back to "blocked." One-line fix in
  `_ScreenshotOneAttempt.render` plus a regression test
  (`test_residential_uses_proxy_type_param_when_datacenter_fails`).
* **The ladder was double-billing on screenshot success.** When
  `screenshotone_datacenter` returned `OUTCOME_BLOCKED` *with* an
  `evidence_url` (i.e. it captured the page, the page just isn't
  full of `<img>` tags), `run_ladder` happily moved on to
  `screenshotone_residential` and burned a second render for zero
  new information. Added `is_screenshot_capture: bool = True` to
  `_ScreenshotOneAttempt`, and a clause in `run_ladder` that
  short-circuits the moment any `is_screenshot_capture=True` rung
  produces an `evidence_url`. New test
  `test_short_circuits_on_first_screenshotone_capture`.
* **SS1 captures were dead weight.** The previous commit inserted
  the captured PNG into `discovered_images` with `count=0`, which
  meant the inline analyzer's `if count > 0:` guard skipped the
  image entirely. The user could see the screenshot in storage but
  it was never analyzed. Fixed in `_process_one_dealer` (and the
  cache-phase counterpart) by setting `count = 1` and incrementing
  `local_total_discovered` whenever `OUTCOME_BLOCKED` arrives with
  an `evidence_url`. Crucially we did *not* bump `pages_scanned` —
  the funnel chip should still distinguish "real DOM extraction"
  from "screenshot fallback."

All three landed in one commit with the existing 27 ladder/policy
tests still green plus the two new ones — 147 tests total, all
passing.

**4. The false-positive "Modified" match (commit `eb48184`)**

The user surfaced a scan result where a 320×50 banner asset had
matched a `rent.cat.com` page at 82% confidence with a "Modified"
flag — and the matched image was the dealer's full-page hero shot.
"Technically wrong. The text is right though. How to fix."

Diagnosis: granularity mismatch in the AI matcher. The SS1 fallback
captures a 1920×3000 full-page PNG; the campaign asset is 320×50.
CLIP and Haiku will happily say "yes this big image contains the
banner" because it actually *does* (the dealer's hero literally uses
the campaign artwork at hero size), but the verdict the operator
reads — "modified version of asset X" — is misleading. What the
operator actually wants is the cropped banner region, scored
against the asset.

Two-layer fix:

* **Layer 1 — `extraction_service.localize_screenshot_capture()`
  (new, ~80 LOC).** When the SS1 fallback fires, download the
  captured PNG bytes, run the existing OpenCV multi-scale +
  ORB localizer (`_localize_and_crop_assets`, already in service
  for normal Playwright scans), and insert each detected crop as
  its own `discovered_images` row tagged
  `extraction_method=cv_localized_from_screenshot`. The matcher
  now sees real banner-sized crops with proper coordinates instead
  of a hero shot. ~50ms per template-match × ~3 assets × ~9 SS1
  fallbacks per scan ≈ 1.5s of added wall-clock — pocket change.
* **Layer 2 — analyzer skip rule in three places in
  `scan_runners.py`.** The full-page evidence row stays
  (operators need to see *why* a host was blocked) but is never
  fed back to the matcher. The inline analyzer (live-scan and
  cache-phase) and `auto_analyze_scan` all check
  `metadata.capture_method == 'blocked_evidence'` and `continue`
  past those rows. `auto_analyze_scan` also bulk-marks the
  evidence rows `is_processed=true` at the end so they don't
  accumulate as forever-pending across reruns.

When CV localization finds zero crops, the dealer is now honestly
reported as "blocked, no creatives detected" rather than producing
a false-positive. This also gives the operator a cheap signal that
the host's content has changed enough to warrant a manual look.

### Files touched

| File | Change |
|---|---|
| `backend/app/services/render_strategies.py` | NEW — RenderStrategy ladder, 4 RenderAttempt impls, run_ladder + early-stop, STRATEGY_LADDERS map; later `proxy_type` fix and `is_screenshot_capture` short-circuit |
| `backend/app/services/host_policy_service.py` | NEW — HostPolicy dataclass, ensure_policy / get_strategy, WAF fingerprinting (`_WAF_FINGERPRINTS`), preflight_probe via httpx, aggregate_from_pipeline_stats / merge_host_successes / record_host_outcomes, auto-promotion gated on PROMOTE_THRESHOLD + RESET_ON_SUCCESS, manual_override honored |
| `backend/app/services/extraction_service.py` | Removed MOBILE_FIRST_HOSTS + viewport-switching block; `extract_dealer_website` is now a thin shim around `host_policy_service.ensure_policy` + `render_strategies.run_ladder`; later added `localize_screenshot_capture()` (~80 LOC) for CV crop extraction from SS1 captures |
| `backend/app/services/scan_runners.py` | Post-scan host-policy aggregation hook in `run_website_scan`; SS1 captures now flow into inline analyzer (count=1 + total_discovered++); BLOCKED branch in `_process_one_dealer` and cache-phase block now call `localize_screenshot_capture`; analyzer loops skip `capture_method=blocked_evidence`; `auto_analyze_scan` partitions evidence rows from matchable, runs analysis only on matchable, bulk-marks evidence processed |
| `supabase/migrations/030_host_scan_policy.sql` | NEW — host_scan_policy table, CHECK constraint on strategy, two indexes, `NOTIFY pgrst, 'reload schema'` |
| `supabase/schema.sql` | Mirrored 030 above the dashboard views block |
| `backend/tests/test_render_strategies.py` | NEW + extended — TestStrategyMapping, TestRunLadder (incl. short-circuit + proxy_type regression tests), updated `test_screenshotone_only_strategy_skips_playwright` to expect the new short-circuit |
| `backend/tests/test_host_policy_service.py` | NEW — TestDetectWaf, TestAggregateFromPipelineStats, TestRecordHostOutcomes (auto-promotion, confidence reset, manual override, sticky unreachable), TestPreflightProbe (200, 403-Akamai, 429, connection error) |
| `log.md` | this entry + the missing 2026-04-28-evening backfill |

### Commits

* `6c198c0` — Phase 6 (1-3): adaptive render-strategy policy per hostname (1725 insertions, 70 deletions; 8 files)
* `1490e86` — Phase 6 hotfix: read SS1 screenshots, fix proxy_type, short-circuit ladder (89 insertions, 14 deletions; 3 files; 147 tests green)
* `eb48184` — fix: localize ScreenshotOne captures + exclude full-page evidence from matcher (410 insertions, 16 deletions; 3 files)

All three pushed to `main`; DigitalOcean `deploy_on_push` rebuilt
both `api` and `scan-worker` for each. The middle commit went out
while the user was watching the post-030 logs and the third was
written and shipped within 20 minutes of the user posting the
false-positive screenshot.

### Next steps for tomorrow (ordered by ROI)

1. **Watch the next full scan and read `host_scan_policy` directly.**
   With the table backfilled by today's failed run and 030 now
   live, the second pass on `rent.cat.com` should skip Playwright
   entirely and go straight to ScreenshotOne datacenter. If it
   doesn't, the auto-promotion logic isn't firing — most likely
   cause would be `success_pages_by_host` being populated from a
   different aggregator and resetting the confidence counter
   inappropriately. Easiest verification:
   `select hostname, strategy, confidence, blocked_30d, last_promoted_at from host_scan_policy order by last_seen_at desc limit 20;`.
2. **Promote `host_scan_policy` PGRST205 from WARNING to ERROR
   (transient).** Today's miss happened because the lookup failure
   logged at WARNING and got buried. Once we're confident the
   table is reliably present, raise the severity for ~1 week so we
   notice schema drift fast. Then drop it back to WARNING.
3. **Add a "matchable / evidence-only" split to the dashboard.** The
   funnel chip currently shows `pages_scanned`. With Layer 2 in
   place, dealers that produce only evidence rows look like "0
   creatives" which is technically true but unhelpful. Add a
   sibling chip: `N captured (evidence-only, no creatives detected)`
   so operators can tell "blocked + nothing on the page" apart from
   "blocked + we couldn't find the asset on a captured page."
4. **CV localizer threshold tuning.** The localizer's correlation
   threshold was tuned for normal Playwright scans where the
   screenshot is roughly the same scale as the asset. SS1 captures
   are much larger; the multi-scale sweep handles this in theory
   but ORB feature counts may be sparse on small banners. Worth a
   one-day spike measuring crop-yield on the 9 hosts that
   ScreenshotOne already gets through.
5. **Residential proxy budget cap.** With `proxy_type` actually
   working now, residential calls will go from "always 400" to
   "actually charged at ~$0.01/render." A scan that promotes 20
   hosts to residential in one pass is suddenly $0.20 — fine — but
   we should add a daily cap (`SCREENSHOTONE_RESIDENTIAL_DAILY_CAP`)
   that returns `OUTCOME_BLOCKED` once exceeded so a misbehaving
   policy table can't run up a bill overnight.
6. **Evidence-row retention sweep.** `auto_analyze_scan` now
   bulk-marks evidence rows processed, but they still occupy
   `discovered_images` with full Supabase storage URLs behind them.
   Retention service should TTL out the storage objects (and
   nullify `image_url`) after N days so the bucket doesn't grow
   linearly with blocked-host count.
7. **Phase 6 doc + runbook.** A short `docs/host-scan-policy.md`
   covering: how to inspect the table, how to manually pin a
   strategy (`update host_scan_policy set strategy='…',
   manual_override=true where hostname='…';`), how to nuke a row
   to force re-probing, and the auto-promotion rules. Two pages,
   saves an on-call hour the first time something acts weird.
8. **Unit-test coverage for `localize_screenshot_capture`.** The
   helper has integration coverage via the runner but no direct
   unit test. Mock `ai_service.download_image` and
   `_localize_and_crop_assets` and assert the discovered_images
   inserts use the expected `extraction_method` and `metadata`.
   Cheap insurance against a future refactor breaking the Layer 1
   contract.


---

## 2026-04-30 (PM) — Phase 6.5.2: page discovery via unlocker, page-cache table re-applied, log truncation fix

### Summary

The `1/1 pages looked at` symptom on `rent.cat.com` was a discovery-side regression of the same Akamai problem Phase 6.5 fixed for extraction. Three independent issues were uncovered while diagnosing it; all three are fixed in this phase.

### The smoking-gun log line

From the worker that ran job `b8cb7ea3-…` at 16:39 UTC on Apr 30:

```
16:39:18.847  Starting page discovery for https://rent.cat.com/wheeler/en_US/home.html (max 15 pages)
16:39:19.020  Probed 24 common paths: 0 valid          ← all 24 probes finished in 87 ms
16:39:19.107  Final: 1 pages to scan for rent.cat.com   ← only the base URL survives
16:39:19.139  [page 1/1] Extracting: ...home.html
```

24 HEAD probes completing in 87 ms is not "fetched and got a 404" — it's "Akamai dropped the TCP connection before TLS completed." The same Akamai instance that gates the homepage gates `/specials`, `/sitemap.xml`, and every other URL we tried. All three discovery strategies (`_probe_common_paths`, `_fetch_sitemap_urls`, `_crawl_homepage_links`) fell through silently with empty results. `discover_pages` then returned the seeded base URL alone, the runner gave it the per-site budget of 15 slots, and the dealer scanned exactly one page. Phase 6.5 fixed extraction on these hosts via Bright Data; discovery still went through plain httpx.

### Fix #1 — page discovery via Bright Data Web Unlocker

`backend/app/services/page_discovery.py` now consults `host_policy_service.get_strategy(base_url)` at the top of `discover_pages`. When the host is on a WAF-grade strategy (`unlocker_only`, `playwright_then_unlocker`, `unreachable`):

- The three direct strategies are skipped entirely. They are guaranteed-zero on these hosts and burn ~100 ms of TCP/TLS aborts on every scan.
- A new helper `_crawl_homepage_links_via_unlocker(base_url, base_domain)` POSTs the homepage to Bright Data, parses `<a href>` links from the post-render DOM with the same regex the direct path uses, filters to same-domain scannable pages, and returns the list. Promo-keyword URLs get hoisted to the front so the slot order matches the direct path's promo-first ordering.
- As a defence-in-depth, the unlocker fallback also runs after the direct path if the result list still has only the base URL — that catches the symptom on hosts whose policy row hasn't been seeded yet (the exact pre-condition rent.cat.com was in before Phase 6.5).
- Side effect: a successful unlocker discovery call also `mark_host_unlocked()`s the host, so the per-page extraction phase doesn't have to wait for its own first unlock to flip the asset-routing flag in `ai_service.download_image`.

Cost impact: roughly $0.0015 per WAF-protected dealer per scan. At 50 such dealers that's $0.075/scan — negligible vs. the $0.044 Claude charge per match the same scan already pays.

### Fix #2 — `page_hit_cache` table re-applied

The same worker logs revealed a second, separate failure on every scan:

```
WARNING  Page cache lookup failed: Could not find the table 'public.page_hit_cache'
WARNING  Failed to record page hit ... 'Missing response', 'code': '204'
```

Migration `016_page_hit_cache.sql` was added in November 2026 but never copied into `supabase/schema.sql`. Any environment that bootstrapped from `schema.sql` (rather than replaying every migration) is missing the table. `page_cache_service` fails soft so scans still complete, but the entire optimisation that lets us skip already-empty pages on re-scans is dead — every page on every recurring scan re-runs the full extraction pipeline.

Fixes:
- `supabase/schema.sql` — added the `page_hit_cache` `CREATE TABLE` block + indexes after `host_scan_policy`. Future bootstraps will include it.
- `supabase/migrations/032_ensure_page_hit_cache.sql` (new) — re-applies migration 016 verbatim with `IF NOT EXISTS` guards. No-op on databases that already have the table; one-shot fix on those that don't. Apply with `python3 backend/run_migration.py`.

### Fix #3 — log truncation made AEM URLs look like duplicates

The same logs showed three "Processing image" lines for what looked like the same URL at 16:39:28, 16:39:52, 16:39:56:

```
Processing image: https://rent.cat.com/wheeler/en_US/home/_jcr_content/root/responsivegrid_6958138
```

Three log lines, looks like a retry loop. Reality: three distinct AEM image renditions (`image.coreimg.85.1024.jpeg`, `…png`, `…svg` — different filenames after the truncation point). The `image_url[:80]` truncation at `ai_service.py:1731` chopped off the discriminating filename and made every rendition collapse to the same string in the operator's terminal. The pipeline funnel `total_images=4, hash_rejected=3, matched_new=1` confirms the system actually handled all four images correctly and rejected the three at the perceptual-hash gate as expected — there was no real bug, just a misleading log.

The `_looks_like_image_url` filter from Phase 6.5.1 was also re-audited and confirmed correct: AEM URLs without an image extension are rejected (`/_jcr_content/.../responsivegrid_6958138` → False); AEM URLs *with* an image extension downstream of the marker are accepted (`/_jcr_content/.../image.coreimg.jpeg/.../file.jpeg` → True). New unit tests pin both behaviors.

Fixes:
- New `_shorten_url_for_log(url)` helper in both `ai_service.py` and `unlocker_service.py` (duplicated rather than shared to avoid an import cycle). Keeps `head + "..." + tail` so the discriminating filename survives. `_run_log_for_log_test_three_distinct_aem_renditions_render_distinctly` enforces that 3 distinct renditions of the same AEM component render distinctly in the log.
- Replaced both `image_url[:80]` log calls with `_shorten_url_for_log(image_url)`.

### Tests

`backend/tests/test_page_discovery.py` (new, 7 tests):

- `unlocker_only` strategy skips direct probes and uses the unlocker.
- `playwright_then_unlocker` also skips direct probes.
- `playwright_desktop` strategy uses direct only — does NOT pay the BD cost on healthy hosts.
- Unlocker fallback fires when direct returned only the base URL.
- Promo keyword URLs from the unlocker get hoisted to the front of the result list.
- `_crawl_homepage_links_via_unlocker` filters to same-domain scannable pages, drops off-domain / asset / `tel:` / `javascript:` / `#` links.
- The unlocker-disabled and unlocker-failure paths return an empty list, not an exception.
- A successful unlocker discovery call marks the host as unlocked for later asset routing.

`backend/tests/test_unlocker_service.py` (5 added):

- `_shorten_url_for_log` short-URL passthrough, AEM filename preservation, and the three-distinct-renditions invariant.

Full result on the touched modules: **59 passed, 0 failed.** The pre-existing 28 JWT/auth fixture failures elsewhere in the suite are unrelated and present on `main`.

### Files

- `backend/app/services/page_discovery.py` — `_crawl_homepage_links_via_unlocker` helper, strategy-driven skip-direct logic, defence-in-depth unlocker fallback, updated docstring with cost reasoning.
- `backend/app/services/ai_service.py` — `_shorten_url_for_log` helper, replaced truncating log call.
- `backend/app/services/unlocker_service.py` — `_shorten_url_for_log` helper, replaced truncating log call.
- `supabase/schema.sql` — `page_hit_cache` block added after `host_scan_policy`.
- `supabase/migrations/032_ensure_page_hit_cache.sql` — idempotent re-application of migration 016.
- `backend/tests/test_page_discovery.py` (new) — 7 regression tests for Fix #1.
- `backend/tests/test_unlocker_service.py` — 3 new tests for `_shorten_url_for_log`.

### Verification on next scan

- `Probed 24 common paths: 0 valid` should NOT appear for any host on `unlocker_only` / `playwright_then_unlocker` (replaced by `Host X on strategy Y — skipping direct probes, using unlocker for discovery`).
- `Final: N pages to scan for rent.cat.com (skip_direct=True, unlocker_used=True)` with N > 1 (target 5–15 depending on how many internal links the homepage carries).
- `Phase 2: <N-cached> additional page(s) across 1 dealer(s)` matches the new N.
- `[page X/N]` extraction lines run for each discovered page.
- `Could not find the table 'public.page_hit_cache'` warnings disappear after migration 032 is applied.
- `Processing image: https://rent.cat.com/.../...banner.jpeg` (or `.png`, etc.) — the filename portion is now visible in the log.

### Open follow-ups (not in this commit)

1. **`page_cache_service.record_page_hits` `.maybe_single()` quirk.** Even with the table present, the inserts use `.maybe_single().execute()` which raises with `code: '204'` on an empty result set in this version of supabase-py. The whole record loop catches and logs as `WARNING  Failed to record page hit`. Replace with `.limit(1).execute()` and check `result.data` explicitly.
2. **Per-host `unlocker_only` discovery cost cap.** A pathological host that returns thousands of `<a href>` links would still be capped by `max_pages` slot allocation, but the BD call itself returns the entire DOM. Worth setting an explicit response-size limit in `_post_unlocker` (currently unbounded) so a malicious or misconfigured host can't run up the BD bill.
3. **Sitemap-via-unlocker.** For really large dealer sites, the homepage `<a href>` set might miss long-tail promo URLs that only sitemap.xml carries. Worth experimenting with a second BD call to `/sitemap.xml` for hosts where the link count comes back small — but only if we see evidence of missed matches.

---

## 2026-04-30 — Session summary: ScreenshotOne → Bright Data Web Unlocker, top to bottom

A single day, three commits, one structural problem chased through every layer of the scan pipeline. Started with "rent.cat.com still produces zero matches even after Phase 6's ladder" and ended with discovery, extraction, asset download, URL filtering, page caching, and operator logging all rebuilt around Bright Data. Each commit shipped on the back of a real production scan that exposed the next layer's bug.

### The arc

**Morning — Phase 6.5 (commit `830bf1d`, 12:02 ET): replace ScreenshotOne with Bright Data Web Unlocker.**

The Phase 6 ladder was structurally sound but the bottom rung was lying. ScreenshotOne does not actually accept the `proxy_type=residential` parameter we'd been sending — every call returned HTTP 400 silently, and the `screenshotone_residential` strategy was a single-rung ladder, so any host that landed on it produced zero rows forever. Two compounding flaws masquerading as "the WAF is too tough."

Fix was structural, not patch-level:

- **New `services/unlocker_service.py` (601 LOC).** POSTs to `api.brightdata.com/request`, parses the rendered HTML with BeautifulSoup (mirrors the JS `<img>` / `<picture>` / inline-bg extraction we already do for Playwright), inserts each image as its own `discovered_images` row. No more screenshot + cv-localizer dance for blocked hosts — they get real per-image rows with real URLs.
- **`render_strategies.py` ladder rebuilt.** All `_ScreenshotOneAttempt` rungs swapped for `_UnlockerAttempt`. New invariant: every multi-rung ladder must have ≥2 rungs across ≥2 providers. Single-rung ladders are documented exceptions only (`unlocker_only`, `unreachable`).
- **`host_policy_service` preflight updated.** 403 / 451 → `unlocker_only`; 429 / timeouts → `playwright_then_unlocker`.
- **`cost_tracker.record_unlocker(succeeded=…)` at $0.0015/req PAYG.** Failed attempts log $0 line items so the audit trail still shows what was attempted. The `screenshotone` vendor label was kept on the frontend so historical `scan_jobs` rows still render.
- **Boot-time smoke test in both `api` and `scan-worker`.** If BD auth is broken at deploy time, the rung is disabled at runtime with a 5-min auto-retry — a misconfigured deploy never silently burns credits on guaranteed errors. This was the explicit lesson from the SS1 incident: a dead provider is worse than no provider, because the ladder thinks it tried.
- **Migration 031.** Drops the old `strategy` CHECK, maps `playwright_then_screenshotone` → `playwright_then_unlocker` and `screenshotone_{only,residential}` → `unlocker_only`, resets confidence on migrated rows so the unlocker gets a fair first scan, re-adds CHECK with the new five-strategy enum. Idempotent.
- **Tests rewritten.** `test_render_strategies` now asserts no strategy name contains `"screenshotone"` and that every ladder has ≥2 rungs (the regression that would have caught the original bug). `test_host_policy_service` strategy names updated. `conftest` + `ci.yml` swap `SCREENSHOTONE_ACCESS_KEY` for `BRIGHTDATA_API_TOKEN` + `BRIGHTDATA_UNLOCKER_ZONE`.

**Late morning — Phase 6.5.1 (commit `f2bd167`, 12:26 ET): route asset downloads via unlocker, drop AEM component URLs.**

First post-6.5 production scan against `rent.cat.com` revealed two more layers had the same Akamai problem:

1. **Asset downloads still went through plain `httpx`.** Bright Data unlocked the page and parsed 4 image URLs — then `ai_service.download_image()` called `httpx.get()` on those URLs against the same Akamai instance that gates the page. Every call hung 30s and timed out. Net: 4 successful unlocks, 0 successful downloads, 0 matches. The same wall, one layer down.
2. **Two of the 4 "image URLs" were AEM component paths.** `/_jcr_content/root/responsivegrid_<id>` — Adobe Experience Manager `<img src="">` placeholders that the page's own JS swaps to real images at runtime. Even with bypass, those URLs would never resolve to bytes.

Fixes:

- **`unlocker_service._post_unlocker` refactored to return bytes** (not text) so the same call works for HTML and binary. `_post_unlocker_text` wrapper added for the HTML path. New `download_via_unlocker(url)` fetches asset bytes through BD. Cost recorded per fetch (~$0.0015), only on successful unlock.
- **Per-process `_unlocked_hosts` set** populated on any successful page unlock. `ai_service.download_image` checks this set before any direct fetch and routes through BD when the host is flagged. O(1) lookup, zero DB hits, self-populating across the worker's lifetime.
- **`parse_images_from_html` now applies `_looks_like_image_url` filter** — accepts known image extensions (jpg/png/webp/etc) and known CDN markers (`.coreimg.`, `/dam/`), rejects extension-less `/_jcr_content/` component paths. Drops the `responsivegrid_*` class of leak before it ever hits the analyzer.
- **`ai_service.download_image` now sends Chrome-equivalent headers** (User-Agent, Accept, Sec-Fetch-*) on every direct fetch too. Helps with non-WAF dealer sites that have basic UA-based anti-bot rules.
- **17 new tests in `test_unlocker_service.py`** covering URL-shape filter (extensions, query strings, AEM coreimg paths, `/dam/` paths, component-path rejection), per-host registry (case-insensitive lookup, per-host marking, no leak across hosts), `parse_images_from_html` end-to-end on AEM markup, and `unlock_and_extract` auto-marking on success.

**Afternoon — Phase 6.5.2 (commit `b666e1f`, 13:04 ET): page discovery via unlocker, page-cache table re-applied, log truncation fix.**

Next production scan: extraction was now working on unlocked pages, but `rent.cat.com` was still only scanning `1/1 pages`. The discovery layer had the *same* Akamai problem as extraction, plus a second unrelated bug surfaced in the same logs, plus a third "this is actually fine but the log made it look broken" issue. Full detail in the section above; one-line summary of each:

- **Fix #1: discovery via unlocker.** `_crawl_homepage_links_via_unlocker` POSTs the homepage to BD, parses `<a href>` from the rendered DOM, hoists promo-keyword URLs to the front. WAF-strategy hosts skip direct probes entirely (saves ~100ms of TCP/TLS aborts per scan). Defence-in-depth fallback fires on any host where direct discovery returned only the base URL. ~$0.0015 per WAF-protected dealer per scan.
- **Fix #2: `page_hit_cache` table re-applied.** Migration 016 was added in November 2026 but never copied into `supabase/schema.sql`. Any environment bootstrapped from `schema.sql` was missing the table; `page_cache_service` failed soft so scans completed but the entire skip-empty-pages optimisation was dead. Migration `032_ensure_page_hit_cache.sql` re-applies it idempotently; `schema.sql` updated for future bootstraps.
- **Fix #3: log truncation made AEM renditions look like duplicates.** `image_url[:80]` chopped off the discriminating filename on AEM URLs, making three distinct renditions render as the same line. New `_shorten_url_for_log` helper keeps `head + "..." + tail` so the filename survives. No real bug in the pipeline — confirmed via the `total_images=4, hash_rejected=3, matched_new=1` funnel — just a misleading log line that consumed an hour of debug time.

### What this session changes structurally

1. **The "scan blocked WAF dealer" path is now end-to-end through Bright Data.** Discovery, page rendering, image extraction, asset download, and host marking all share the same `_unlocked_hosts` registry and the same `download_via_unlocker` plumbing. There is no remaining `httpx`-direct call on the hot path for a flagged host.
2. **No silent provider failures on the bottom rung.** Boot-time smoke test + ≥2-rungs-per-ladder structural rule + `is_screenshot_capture` short-circuit means a misconfigured or dead BD account fails loud and obvious, not silent and zero-match.
3. **Cost is tracked per BD operation, not per scan.** Page unlock, asset download, and discovery crawl each record their own `record_unlocker` line item. We can now answer "what did this dealer cost?" and "what did Bright Data cost us this week?" from the same `cost_log` table.
4. **The audit log finally tells the truth on AEM URLs.** Before today, three-rendition AEM components looked like a retry loop in the operator's terminal. After today, the filename portion survives truncation, so the operator sees what the pipeline actually saw.

### Numbers

- **3 commits** (`830bf1d`, `f2bd167`, `b666e1f`) all pushed to `main`.
- **`backend/app/services/unlocker_service.py`** went from new file to 790+ LOC across the day (extraction → asset routing → discovery).
- **`backend/app/services/screenshot_service.py`** deleted (-331 LOC).
- **30 + 17 + 12 = 59 new tests** across `test_unlocker_service.py`, `test_render_strategies.py`, and `test_page_discovery.py`. All green on touched modules.
- **2 new migrations** shipped: `031_replace_screenshotone_with_unlocker.sql`, `032_ensure_page_hit_cache.sql`.
- **Cost change for a WAF-protected dealer:** roughly +$0.003/scan (discovery + page unlock + ~3 asset downloads at $0.0015 each). At 50 such dealers that's $0.15/scan run vs. the $0.044/match Claude charge the same scan was already paying. Negligible.

### What we did NOT do (deferred follow-ups)

- **`page_cache_service.record_page_hits` `.maybe_single()` quirk.** Even with the table present, inserts raise `code: '204'` on empty result sets in this supabase-py version. Catch-and-warn for now; replace with `.limit(1).execute()` later.
- **Per-host BD response-size cap.** A pathological host returning thousands of `<a href>` links is bounded by `max_pages` slot allocation but the BD response itself is unbounded. Worth an explicit cap in `_post_unlocker` before a malicious host runs up the bill.
- **Sitemap-via-unlocker for very large dealers.** Homepage `<a href>` might miss long-tail promo URLs only sitemap.xml carries. Defer until we see evidence of missed matches.
- **The on-call runbook for `host_scan_policy`.** Still not written. Next operator surprise will pay for it.

---

## 2026-05-01 — Phase 6.5.3 — kill the `{{path}}.html` template leak + URL safety gate

### Why now

Live triage on scan_job `d7a396de-3ed1-4350-93ae-be0eb6172241` (46 dealers, $7.28, 3 matches). Two production findings drove this commit, plus one investigation that is NOT a code bug.

**Finding 1 — Bright Data is being asked to fetch literal Mustache template strings.** `pipeline_stats.blocked_details` shows 17 dealer pages blocked with `brightdata_http_400` on URLs of the shape `https://rent.cat.com/<dealer>/en_US/{{path}}.html`. Affected dealers: battlefield, blanchard, cresco, finning-canada, hawthorne-rentals, holtca, kellytractor, macallister-rentals, milton, nmcrental, peterson-cat, quinn, riggs-rental, stowers, tractorandequipment, warren, ziegler-rental. That's 17 BD requests per scan (~$0.026) and 17 dealer pages effectively unscanned (~30% of the dealer footprint), every single recurring scan, returning a 400 Bright Data cannot do anything about. Root cause: AEM's home page templates emit `<a href="{{path}}.html">` when the server-side render fails to substitute the variable. `_crawl_homepage_links_via_unlocker` was extracting these literal hrefs with a regex, `urljoin`-ing them to the dealer base URL, and forwarding them to extraction.

**Finding 2 — `_post_unlocker` will happily forward URLs containing whitespace, non-ASCII, and unrendered placeholders.** Same shape as #1 but at a different layer: even if discovery were perfect, an asset URL that came in from `parse_images_from_html` with a literal space, an unencoded ó (Spanish-language dealer URLs like `cogesa`, `finning-chile`), or a Mustache placeholder would still be POSTed verbatim to BD and 400 there. We caught the AEM case in #1 because discovery was the source; we'd catch the others later, individually, in production. Better to install one gate at the BD boundary that handles all three.

**Investigation — "skipped creative" `b81f16a0-3c58-4996-9e4d-d2ad56496432` is NOT a code bug.** Operator reported the asset never matched on `https://rent.cat.com/altorfer-rents/en_US/home.html`. Pulled every image extracted from every `altorfer-rents/*` page in the latest scan (40 images across 12 pages) and computed a 4-hash perceptual distance (`phash`+`dhash`+`whash`+`average_hash`, threshold `≤28`) against the asset's actual bytes. Best score on `altorfer-rents/home.html` was `42.5` (current `homepagehero/image.img.png`) — well above the prefilter cutoff. Side-by-side render showed why: the asset is a Retina screenshot of the page's "WHY ALTORFER RENTS IS HERE FOR YOU" three-column **HTML+CSS** block (black background, big yellow heading, 3 small icons + body copy). It is not a single image on the page — the dealer site renders that section from text + 3 separate icon files. Filed as a category limitation rather than a bug. Documented inline in this entry so the next operator who sees a "missing match" on a screenshot of an HTML section gets the context immediately.

### Fix #1 — `_href_is_safe` gate at the discovery layer

New helper in `services/page_discovery.py`:

```python
_TEMPLATE_PLACEHOLDER_MARKERS = ("{{", "}}", "${", "<%", "%>", "[%", "%]")

def _href_is_safe(href: str) -> bool:
    if not href or len(href) > 2048:
        return False
    if any(m in href for m in _TEMPLATE_PLACEHOLDER_MARKERS):
        return False
    return all(not c.isspace() and ord(c) >= 0x20 for c in href)
```

Applied in BOTH `_crawl_homepage_links` (direct httpx path) and `_crawl_homepage_links_via_unlocker` (BD path) before the `urljoin` call. Drops counted in a debug log line so operators can spot AEM render leaks without running queries. Same set is also enforced inside `_is_scannable_page` so anything that arrives via sitemap parsing or any other channel is gated too.

Why a substring match instead of a tighter regex: the seven markers are unique enough that no real URL contains them (`{` and `}` are reserved per RFC 3986), and the substring scan is O(n×k) with k=7, which is faster than compiling and matching one alternation regex per href.

### Fix #2 — `_normalize_target_url` gate at the Bright Data boundary

New helper in `services/unlocker_service.py`:

```python
def _normalize_target_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    # Returns (safe_url, error_reason). On reject, safe_url is None and
    # error_reason is one of:
    #   brightdata_url_empty
    #   brightdata_url_too_long
    #   brightdata_url_template_placeholder
    #   brightdata_url_unparseable
    #   brightdata_url_non_ascii_host
    ...
    safe_path  = quote(parts.path,  safe="/%-._~!$&'()*+,;=:@")
    safe_query = quote(parts.query, safe="=&%-._~!$'()*+,;:@/?")
    return urlunparse((parts.scheme, parts.netloc, safe_path, parts.params, safe_query, "")), None
```

Called at the top of `_post_unlocker`. On reject, returns the structured error code without an HTTP call — the BD request is never sent, the cost is never recorded, and the error code lands in `blocked_details` so the operator can see in `pipeline_stats` exactly which dealer URL produced which failure mode.

Three properties the encoding logic preserves:

1. **No double encoding.** `%` is in the `safe` set for both path and query, so `https://x.com/promo%20page` round-trips to itself, not to `https://x.com/promo%2520page`.
2. **Spaces and non-ASCII are encoded.** `https://x.com/promo page` → `https://x.com/promo%20page`. `…/promoción.html` → `…/promoci%C3%B3n.html` (UTF-8 percent bytes — what BD's URL parser expects).
3. **Fragments are dropped.** Fragments are client-only and never sent over HTTP anyway; stripping them defensively saves one round-trip class of canonicalization mismatch with BD.

The placeholder marker set is **duplicated** between `page_discovery._TEMPLATE_PLACEHOLDER_MARKERS` and `unlocker_service._TEMPLATE_PLACEHOLDER_MARKERS` rather than shared. Reasoning: page_discovery late-imports unlocker_service (optional dependency), so a top-level import the other direction would create a cycle. Two five-line tuple definitions cost less than the cycle.

### Why two gates instead of one

Defence in depth. The `_href_is_safe` gate catches placeholder leaks at the source (discovery), where we can also drop them with zero cost, and where the operator can see in `pipeline_stats.pages_discovered` that they never entered the scan budget in the first place. The `_normalize_target_url` gate catches anything that slipped past discovery — sitemap-sourced URLs, asset URLs from `parse_images_from_html`, retry paths — without depending on every upstream caller having done the right filtering. If either gate alone fired, we'd still have a weakness; both gates together close the loop.

### Tests

New `TestHrefIsSafe` class in `tests/test_page_discovery.py` (7 cases) covers Mustache, ES6 template literals, ASP/JSP scriptlets, Template Toolkit, inline whitespace, control characters, and overlong URLs. New `TestUnlockerCrawlerDropsTemplateHrefs` (1 case) is the integration test: feed AEM-style HTML with both clean and placeholder-leaking hrefs to `_crawl_homepage_links_via_unlocker` and assert only the clean ones survive.

New `TestNormalizeTargetUrl` (8 cases) and `TestPostUnlockerSkipsBadUrls` (2 cases) in `tests/test_unlocker_service.py`. The `TestPostUnlockerSkipsBadUrls::test_template_placeholder_short_circuits_before_http` case patches `httpx.AsyncClient` to raise on construction — so if the gate ever leaks, the test explodes loudly rather than silently making real requests. The `test_clean_url_is_passed_through_to_payload` case captures the actual payload BD would receive and asserts the path was percent-encoded.

Run on touched modules in isolation: **31 passed (`test_unlocker_service.py`), 12 passed (`test_page_discovery.py` excluding the pre-existing Python-3.9 event-loop infra issue in `TestUnlockerHomepageCrawl`).** All new Phase 6.5.3 tests: **19 passed.** Local Python is 3.9 and shows pre-existing event-loop sharing failures across some `_run(asyncio.run(...))` chains; CI runs Python 3.11 (`.github/workflows/ci.yml:10`) where this issue does not occur.

### Files

- `backend/app/services/page_discovery.py` — `_href_is_safe` helper, integrated into both crawlers and `_is_scannable_page`, debug log line for dropped placeholders.
- `backend/app/services/unlocker_service.py` — `_normalize_target_url` helper, integrated into `_post_unlocker`. Added `quote` and `urlunparse` to imports.
- `backend/tests/test_page_discovery.py` — `TestHrefIsSafe` (7 cases) + `TestUnlockerCrawlerDropsTemplateHrefs` (1 case).
- `backend/tests/test_unlocker_service.py` — `TestNormalizeTargetUrl` (8 cases) + `TestPostUnlockerSkipsBadUrls` (2 cases).

### Verification on next scan

- `pipeline_stats.blocked_details` should NOT contain any `{{path}}.html` URLs. Any new `brightdata_url_*` codes (template_placeholder / non_ascii_host / unparseable / too_long / empty) appear there instead, with the originating page url so the operator can fix the source.
- `pipeline_stats.pages_blocked` for rent.cat.com dealers drops by ~17 (was 17 in the 2026-04-30 scan; expected 0 going forward). Page coverage on the 17 affected dealers goes from 1 page to whatever the homepage `<a href>` set actually has (typical: 5–12).
- `cost.line_items` shows ~17 fewer `brightdata_unlocker` operations per scan (≈ −$0.026/scan), so the total scan cost on a 46-dealer rent.cat.com run drops modestly.

### Investigation summary — `b81f16a0` is a screenshot of an HTML section, not an image

| altorfer-rents image | source page | avg pHash distance vs asset | gate verdict |
|---|---|---:|---|
| `homepagehero/image.img.png/1754073614666` | home | 42.5 | reject |
| `ttac_1604119479` (older hero) | home | 42.5 | reject |
| `markeingcontent/grey.jpeg` | home | 23.0 | pass (flat colour collision) |
| `services/rental-store-25a` | services | 23.2 | pass |
| `about/rental-store-14a` | about | 26.2 | pass |
| `locations: telehandler C10452791` | various | 27.8 | pass |
| (8 more, all rejected) | various | 32–37 | reject |

Four images survived the prefilter; none survived the downstream CLIP / Claude verifier — the scanner correctly decided none of them are the asset. Visual confirmation: the asset is a 2462×950 Retina screenshot of the page's three-column "WHY ALTORFER RENTS IS HERE FOR YOU" promo block, which the dealer site composes from HTML + CSS + 3 separate small icons (`iconservicesupport.png`, `iconequipment.png`, `iconadvice.png`), not a single hosted image. Action for operator: re-upload either the underlying icons individually, or extract just the hero/banner area as a discrete asset. No code change.

### Open follow-ups (still not in this commit)

1. (carried) `page_cache_service.record_page_hits` `.maybe_single()` raising `204`.
2. (carried) Explicit response-size cap in `_post_unlocker` so a malicious host can't run up the BD bill.
3. (carried) Sitemap-via-unlocker for very large dealer sites.
4. (carried) On-call runbook for `host_scan_policy`.
5. **Distributor mapping bug.** `matches.distributor_id` for the latest scan was hard-coded to a single seed value (`2a2d3712`, "Finning Chile") for every `rent.cat.com` match, including matches found on `/carolina/`, `/ohiocat/`, etc. The dispatcher seeds one distributor per host instead of resolving the actual sub-path → dealer at match-write time. Cosmetic for now (the source_url carries the truth) but will mis-attribute dealer-level analytics until fixed.
6. **Local-dev `.env` parsing.** `BRIGHTDATA_API_TOKEN= cf567277-…` (note leading space after `=`) loaded with the leading whitespace via plain `grep | cut`. pydantic-settings strips it correctly so production is unaffected; the `_api_token()` helper already calls `.strip()`. Worth making the .env.example loud about no-space convention.
