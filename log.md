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

## Third-Party Services Inventory

All external services and significant libraries used across the application.

### Cloud Services & APIs
| Service | Purpose | Config |
|---------|---------|--------|
| **Supabase** | PostgreSQL database + file storage (logos, assets) | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| **Anthropic Claude** | AI image analysis — Haiku (filtering), Sonnet (comparison), Opus (verification) | `ANTHROPIC_API_KEY` |
| **Apify** | Meta Ad Library + Instagram organic post scraping | `APIFY_API_KEY` |
| **SerpApi** | Google Ads Transparency Center structured data | `SERPAPI_API_KEY` |
| **ScreenshotOne** | Website screenshot capture with cookie blocking | `SCREENSHOTONE_ACCESS_KEY`, `SCREENSHOTONE_SECRET_KEY` |
| **Resend** | Transactional email notifications (scan results, violations) | `RESEND_API_KEY` |
| **Sentry** | Error tracking and performance monitoring (frontend + backend) | `SENTRY_DSN` |
| **Mapbox GL** | Interactive dealer compliance map visualization | `NEXT_PUBLIC_MAPBOX_TOKEN` |
| **Vercel** | Frontend hosting and deployment | — |

### Key Libraries
| Library | Purpose | Language |
|---------|---------|----------|
| **FastAPI** | Backend web framework | Python |
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

---

## Current State — Uncommitted Changes Summary

### New Files (18)
| File | Purpose |
|------|---------|
| `backend/app/logging_config.py` | Structured JSON/dev logging |
| `backend/app/services/apify_instagram_service.py` | Instagram organic post scraper |
| `backend/app/services/apify_meta_service.py` | Meta Ad Library scraper |
| `backend/app/services/cv_matching.py` | OpenCV visual matching |
| `backend/app/services/embedding_service.py` | CLIP embedding pre-filter |
| `backend/app/services/extraction_service.py` | Playwright image extraction |
| `backend/app/services/page_discovery.py` | Dealer site page discovery |
| `backend/app/services/screenshot_service.py` | ScreenshotOne integration |
| `backend/app/services/serpapi_service.py` | Google Ads via SerpApi |
| `frontend/app/error.tsx` | Global error boundary |
| `frontend/app/global-error.tsx` | Root error boundary |
| `frontend/app/not-found.tsx` | Custom 404 page |
| `frontend/sentry.client.config.ts` | Client Sentry config |
| `frontend/sentry.edge.config.ts` | Edge Sentry config |
| `frontend/sentry.server.config.ts` | Server Sentry config |
| `frontend/package-lock.json` | NPM lockfile |
| `frontend/tsconfig.tsbuildinfo` | TS build cache |
| `run-all-ports.sh` | One-command dev startup |

### Modified Files (23)
| File | Change Summary |
|------|---------------|
| `README.md` | Updated for new architecture |
| `backend/app/config.py` | +ScreenshotOne, SerpApi, Apify, Sentry, CLIP, Playwright, page discovery settings |
| `backend/app/database.py` | Connection pooling and error handling |
| `backend/app/main.py` | +Sentry, rate limiting, structured logging, JSON errors |
| `backend/app/routers/campaigns.py` | +Instagram scan routing, campaign scan source separation |
| `backend/app/routers/dashboard.py` | Dashboard endpoint updates |
| `backend/app/routers/distributors.py` | Distributor endpoint updates |
| `backend/app/routers/matches.py` | +Feedback endpoints, adaptive threshold recommendations |
| `backend/app/routers/scanning.py` | +Instagram scan routing, refactored for new extraction/screenshot services |
| `backend/app/services/ai_service.py` | Tiered models, CLIP integration, hash pre-filter, adaptive threshold calls |
| `backend/check_scans.py` | Updated scan inspection utility |
| `backend/requirements.txt` | +opencv, sentence-transformers, playwright, slowapi, sentry-sdk |
| `frontend/app/campaigns/page.tsx` | +Scan source descriptions, UI fixes |
| `frontend/app/distributors/page.tsx` | UI fixes |
| `frontend/app/globals.css` | Additional styles |
| `frontend/app/layout.tsx` | +Sentry integration |
| `frontend/app/page.tsx` | Dashboard layout improvements |
| `frontend/components/dashboard/DealerMap.tsx` | Major map rewrite |
| `frontend/components/dashboard/recent-matches.tsx` | Minor fix |
| `frontend/lib/api.ts` | +Feedback & threshold API functions |
| `frontend/next-env.d.ts` | Type update |
| `frontend/next.config.js` | +Security headers, Sentry webpack, CSP |
| `frontend/package.json` | +@sentry/nextjs |

### Deleted Files (1)
| File | Reason |
|------|--------|
| `backend/app/services/apify_service.py` | Replaced by serpapi + apify_meta + screenshot services |

---

## Open Items / Next Steps

### Priority 1 — Ship-Ready
- [ ] Commit all uncommitted changes
- [ ] Add authentication (Supabase Auth + JWT-based RLS)
- [ ] Implement task queue (Celery + Redis) to replace BackgroundTasks
- [ ] Write tests (pytest with mocked AI/Apify calls)
- [ ] Add Docker + CI/CD configuration

### Priority 2 — Feature Completeness
- [x] Add scheduled/automated scans (daily, weekly per org)
- [x] Build PDF/CSV compliance report generation
- [x] Add email/Slack notifications for violations

### Priority 3 — Performance & Polish
- [ ] Re-enable match deduplication (disabled for testing)
- [ ] Instagram Stories/Reels scanning support
- [ ] Batch scanning mode for large distributor networks (40+ distributors)

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
