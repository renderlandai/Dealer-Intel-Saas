# Dealer Intel SaaS

AI-powered campaign asset monitoring for distributor networks. Automatically detect where and how your approved campaign assets appear across dealer and distributor digital channels.

## Features

- **Asset Tracking** — Upload approved campaign assets and track their usage across distributor networks
- **Multi-Channel Scanning** — Scan dealer websites, Google Ads (via SerpApi), Facebook/Meta Ad Library (via Apify), and Instagram
- **AI-Powered Matching** — Multi-stage pipeline: CLIP embeddings for fast semantic pre-filtering, perceptual hashing (pHash/dHash/wHash) for near-duplicate detection, Claude for visual analysis and compliance assessment
- **Modification Detection** — Detect resized, cropped, recolored, or altered versions of assets
- **Compliance Rules** — Define custom compliance rules; AI evaluates matches against them and flags violations (zombie ads, missing brand elements, unauthorized modifications)
- **Scheduled Scans** — APScheduler-based recurring scans (daily/weekly/biweekly/monthly) with Redis-based leader election
- **Billing & Plans** — Stripe integration with tiered plans (Free → Starter → Professional → Business → Enterprise), usage-based extra dealer pricing, checkout and customer portal
- **Team Management** — Multi-seat organizations with email invites and role-based access
- **Alerts & Notifications** — In-app alerts for new matches and violations; email notifications via Resend
- **PDF & CSV Reports** — Branded compliance reports with vector logo, violation tables, and match summaries scoped to the requesting organization
- **Real-Time Dashboard** — Compliance rates, geographic dealer map (Mapbox), channel breakdown charts, compliance trends, and live audit feed
- **Adaptive Thresholds** — Feedback-driven confidence calibration by source type and channel
- **Error Monitoring** — Sentry on frontend (client/server/edge) and backend with structured JSON logging

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Python 3.11, Gunicorn |
| Frontend | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, shadcn/ui |
| Database | Supabase (PostgreSQL) with SQL migrations |
| Auth | Supabase Auth (email/password), JWT verification via JWKS |
| Billing | Stripe (Checkout, Webhooks, Customer Portal) |
| AI | Anthropic Claude (image analysis), CLIP ViT-B-32 (embeddings), perceptual hashing |
| Task Queue | In-process `asyncio.create_task()` (no external worker) |
| Scheduling | APScheduler with Redis singleton lock |
| Email | Resend |
| Monitoring | Sentry, structured JSON logging |
| CI/CD | GitHub Actions (tests, build, auto-migration) |
| Hosting | DigitalOcean App Platform (backend), Vercel (frontend) |

## Prerequisites

- Python 3.11+
- Node.js 20+
- Supabase account (database + auth + storage)
- Anthropic API key (Claude)
- ScreenshotOne account (website capture)
- Redis/Valkey instance (scheduler lock — DigitalOcean managed or local)
- Stripe account (billing — optional for local dev)

## Quick Setup

### 1. Clone and Install

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Mac/Linux
# venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 2. Configure Environment Variables

Create `backend/.env`:

```env
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret
ANTHROPIC_API_KEY=your-anthropic-api-key
SCREENSHOTONE_ACCESS_KEY=your-screenshotone-access-key
SCREENSHOTONE_SECRET_KEY=your-screenshotone-secret-key

# Scan sources (optional — enable as needed)
SERPAPI_API_KEY=               # Google Ads Transparency Center scanning
APIFY_API_KEY=                 # Meta/Instagram Ad Library scanning

# Billing (optional for local dev)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PROFESSIONAL=price_...
STRIPE_PRICE_BUSINESS=price_...
STRIPE_PRICE_EXTRA_DEALER_STARTER=price_...
STRIPE_PRICE_EXTRA_DEALER_PROFESSIONAL=price_...
STRIPE_PRICE_EXTRA_DEALER_BUSINESS=price_...
FRONTEND_URL=http://localhost:3000

# Infrastructure
REDIS_URL=redis://localhost:6379/0
SENTRY_DSN=                    # Leave empty to disable
RESEND_API_KEY=                # Email notifications
RESEND_FROM_EMAIL=Dealer Intel <notifications@resend.dev>

# App
DEBUG=true
CORS_ORIGINS=http://localhost:3000
ENABLE_DANGEROUS_ENDPOINTS=false
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_SENTRY_DSN=        # Leave empty to disable
NEXT_PUBLIC_MAPBOX_TOKEN=      # For the dealer geographic map
```

### 3. Set Up Database

1. Go to your Supabase project dashboard → **SQL Editor**
2. Run `supabase/schema.sql` to create the baseline tables
3. Run each file in `supabase/migrations/` in order (001 through 018)

Or use the Supabase CLI:

```bash
supabase link --project-ref your-project-ref
supabase db push
```

### 4. Create Storage Bucket

In Supabase → **Storage**:
1. Create a bucket called `campaign-assets`
2. Set it to **Public** for development (configure RLS policies for production)

### 5. Start the Application

```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Project Structure

```
dealer-intel-saas/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, middleware, lifespan
│   │   ├── auth.py                  # Supabase JWT verification, user resolution
│   │   ├── config.py               # Pydantic Settings, plan limits, AI thresholds
│   │   ├── database.py             # Supabase client (service role)
│   │   ├── models.py               # Pydantic request/response schemas
│   │   ├── tasks.py                # asyncio.create_task() scan dispatch
│   │   ├── plan_enforcement.py     # Plan limit middleware
│   │   ├── logging_config.py       # Structured JSON logging
│   │   ├── routers/
│   │   │   ├── dashboard.py        # Dashboard stats & analytics
│   │   │   ├── campaigns.py        # Campaign & asset CRUD, scan triggers
│   │   │   ├── distributors.py     # Distributor CRUD, Google Ads ID lookup
│   │   │   ├── matches.py          # Match listing, approval, flagging
│   │   │   ├── scanning.py         # Scan jobs: start, retry, batch, analyze
│   │   │   ├── feedback.py         # AI accuracy feedback & calibration
│   │   │   ├── reports.py          # PDF & CSV compliance reports
│   │   │   ├── organizations.py    # Org settings, logo upload
│   │   │   ├── schedules.py        # Recurring scan schedules
│   │   │   ├── billing.py          # Stripe checkout, portal, webhooks
│   │   │   ├── team.py             # Team members & invites
│   │   │   ├── alerts.py           # In-app alert management
│   │   │   └── compliance_rules.py # Custom compliance rule CRUD
│   │   └── services/
│   │       ├── ai_service.py               # Claude image analysis pipeline
│   │       ├── cv_matching.py              # Perceptual hashing (pHash/dHash/wHash)
│   │       ├── embedding_service.py        # CLIP ViT-B-32 semantic embeddings
│   │       ├── screenshot_service.py       # ScreenshotOne integration
│   │       ├── extraction_service.py       # Playwright image extraction from pages
│   │       ├── page_discovery.py           # Auto-discover dealer subpages
│   │       ├── page_cache_service.py       # Cache discovered page URLs
│   │       ├── serpapi_service.py          # Google Ads Transparency scanning
│   │       ├── apify_meta_service.py       # Meta Ad Library scanning
│   │       ├── apify_instagram_service.py  # Instagram scanning
│   │       ├── scheduler_service.py        # APScheduler + Redis lock
│   │       ├── notification_service.py     # Resend email notifications
│   │       ├── report_service.py           # PDF/CSV report generation
│   │       ├── retention_service.py        # Data retention cleanup
│   │       └── adaptive_threshold_service.py  # Feedback-driven threshold tuning
│   ├── tests/
│   │   ├── conftest.py             # Fixtures, mock Supabase client
│   │   ├── test_auth.py            # JWT verification tests
│   │   ├── test_tenant_isolation.py # Cross-org data isolation tests
│   │   └── test_billing_webhook.py # Stripe webhook handler tests
│   ├── requirements.txt
│   ├── Dockerfile
│   └── gunicorn.conf.py
├── frontend/
│   ├── app/
│   │   ├── layout.tsx              # Root layout with providers
│   │   ├── page.tsx                # Dashboard
│   │   ├── login/page.tsx          # Auth: login
│   │   ├── reset-password/page.tsx # Auth: password reset
│   │   ├── landing/page.tsx        # Public landing page
│   │   ├── pricing/page.tsx        # Public pricing page
│   │   ├── campaigns/              # Campaign list & detail
│   │   ├── distributors/           # Distributor list & detail
│   │   ├── matches/                # Match list & detail review
│   │   ├── scans/                  # Scan job management
│   │   ├── alerts/                 # Alert management
│   │   ├── settings/               # Org settings, billing, team
│   │   ├── error.tsx               # Error boundary (Sentry)
│   │   ├── global-error.tsx        # Root error boundary
│   │   └── not-found.tsx           # 404 page
│   ├── components/
│   │   ├── ui/                     # shadcn/ui primitives
│   │   ├── layout/                 # Sidebar, header, auth gate
│   │   ├── dashboard/              # Stat cards, charts, map, alerts, trial banner
│   │   ├── marketing/              # Landing page navbar & footer
│   │   └── settings/               # Team management section
│   ├── lib/
│   │   ├── api.ts                  # Axios API client
│   │   ├── hooks.ts                # React Query hooks
│   │   ├── auth-context.tsx        # Supabase auth provider
│   │   ├── query-provider.tsx      # React Query provider
│   │   ├── supabase.ts             # Supabase browser client
│   │   ├── upgrade-events.ts       # Plan upgrade event bus
│   │   └── utils.ts                # Utility functions
│   ├── sentry.client.config.ts
│   ├── sentry.server.config.ts
│   ├── sentry.edge.config.ts
│   ├── next.config.js
│   ├── tailwind.config.ts
│   └── package.json
├── supabase/
│   ├── schema.sql                  # Baseline database schema
│   └── migrations/                 # 001–018 ordered SQL migrations
├── .github/workflows/ci.yml       # CI: tests, build, auto-migrate
├── .do/app.yaml                    # DigitalOcean App Platform spec
├── docker-compose.yml              # Local dev: Redis + API
├── run-all-ports.sh                # Dev helper script
├── log.md                          # Development log
└── README.md
```

## API Endpoints

All endpoints are served by the FastAPI backend under `/api/v1`.

### Auth
- `GET /api/v1/auth/me` — Get current user, org, role

### Dashboard
- `GET /api/v1/dashboard/stats` — Aggregate statistics
- `GET /api/v1/dashboard/recent-matches` — Latest matches
- `GET /api/v1/dashboard/recent-alerts` — Latest alerts
- `GET /api/v1/dashboard/coverage-by-channel` — Match coverage by channel
- `GET /api/v1/dashboard/coverage-by-distributor` — Match coverage by distributor
- `GET /api/v1/dashboard/compliance-trend` — Compliance trend over time

### Campaigns
- `GET /api/v1/campaigns` — List campaigns
- `POST /api/v1/campaigns` — Create campaign
- `GET /api/v1/campaigns/{id}` — Get campaign detail
- `PATCH /api/v1/campaigns/{id}` — Update campaign
- `DELETE /api/v1/campaigns/{id}` — Delete campaign
- `GET /api/v1/campaigns/{id}/assets` — List campaign assets
- `POST /api/v1/campaigns/{id}/assets` — Create asset metadata
- `POST /api/v1/campaigns/{id}/assets/upload` — Upload asset file
- `GET /api/v1/campaigns/assets/{id}` — Get asset
- `DELETE /api/v1/campaigns/assets/{id}` — Delete asset
- `POST /api/v1/campaigns/{id}/scans/start` — Start campaign scan
- `GET /api/v1/campaigns/{id}/scans` — List campaign scans
- `GET /api/v1/campaigns/{id}/scans/{scan_id}` — Get scan detail
- `POST /api/v1/campaigns/{id}/scans/{scan_id}/analyze` — Analyze scan
- `GET /api/v1/campaigns/{id}/matches` — Get campaign matches
- `GET /api/v1/campaigns/{id}/scan-stats` — Scan statistics

### Distributors
- `GET /api/v1/distributors` — List distributors
- `POST /api/v1/distributors` — Create distributor
- `GET /api/v1/distributors/{id}` — Get distributor detail
- `PATCH /api/v1/distributors/{id}` — Update distributor
- `DELETE /api/v1/distributors/{id}` — Delete distributor
- `GET /api/v1/distributors/{id}/matches` — Get distributor matches
- `POST /api/v1/distributors/bulk` — Bulk create distributors
- `POST /api/v1/distributors/{id}/lookup-google-ads-id` — Lookup Google Ads advertiser ID
- `PATCH /api/v1/distributors/{id}/google-ads-id` — Set Google Ads ID
- `GET /api/v1/distributors/lookup-google-ads-id-by-name` — Lookup by company name

### Matches
- `GET /api/v1/matches` — List matches (with filters)
- `GET /api/v1/matches/stats` — Match statistics
- `GET /api/v1/matches/{id}` — Get match detail
- `PATCH /api/v1/matches/{id}` — Update match
- `POST /api/v1/matches/{id}/approve` — Approve match
- `POST /api/v1/matches/{id}/flag` — Flag as violation
- `DELETE /api/v1/matches/{id}` — Delete match
- `DELETE /api/v1/matches` — Bulk delete matches
- `POST /api/v1/matches/link-google-ads-distributors` — Link Google Ads matches to distributors

### Scanning
- `POST /api/v1/scans/start` — Start a new scan
- `GET /api/v1/scans` — List scan jobs
- `GET /api/v1/scans/{id}` — Get scan detail
- `POST /api/v1/scans/{id}/retry` — Retry failed scan
- `DELETE /api/v1/scans/{id}` — Delete scan
- `POST /api/v1/scans/{id}/analyze` — Analyze scan results
- `POST /api/v1/scans/batch` — Batch scan multiple distributors
- `POST /api/v1/scans/quick-scan` — Quick single-distributor scan
- `POST /api/v1/scans/{id}/reprocess` — Reprocess scan images

### Schedules
- `GET /api/v1/schedules` — List scan schedules
- `POST /api/v1/schedules` — Create schedule
- `PATCH /api/v1/schedules/{id}` — Update schedule
- `DELETE /api/v1/schedules/{id}` — Delete schedule

### Reports
- `GET /api/v1/reports/compliance` — Generate compliance report (PDF or CSV via `format` param)

### Organizations
- `GET /api/v1/organizations/settings` — Get org settings
- `PATCH /api/v1/organizations/settings` — Update org settings
- `POST /api/v1/organizations/test-email` — Send test notification email
- `GET /api/v1/organizations/logo` — Get org logo URL
- `POST /api/v1/organizations/logo` — Upload org logo
- `DELETE /api/v1/organizations/logo` — Delete org logo

### Billing
- `POST /api/v1/billing/checkout` — Create Stripe checkout session
- `POST /api/v1/billing/portal` — Create Stripe customer portal session
- `GET /api/v1/billing/usage` — Get current usage vs plan limits
- `POST /api/v1/billing/webhook` — Stripe webhook handler

### Team
- `GET /api/v1/team/members` — List team members
- `POST /api/v1/team/invites` — Send team invite
- `GET /api/v1/team/invites` — List pending invites
- `DELETE /api/v1/team/invites/{id}` — Cancel invite
- `POST /api/v1/team/invites/{id}/accept` — Accept invite

### Alerts
- `GET /api/v1/alerts` — List alerts
- `GET /api/v1/alerts/count` — Unread alert count
- `PATCH /api/v1/alerts/{id}/read` — Mark alert as read
- `POST /api/v1/alerts/read-all` — Mark all alerts as read
- `DELETE /api/v1/alerts/{id}` — Delete alert

### Compliance Rules
- `GET /api/v1/compliance-rules` — List rules
- `POST /api/v1/compliance-rules` — Create rule
- `PATCH /api/v1/compliance-rules/{id}` — Update rule
- `DELETE /api/v1/compliance-rules/{id}` — Delete rule

### Feedback (AI Calibration)
- `POST /api/v1/feedback` — Submit match feedback
- `GET /api/v1/feedback/stats` — Accuracy statistics
- `GET /api/v1/feedback/threshold-recommendations` — Threshold recommendations
- `GET /api/v1/feedback/pending-reviews` — Pending review queue
- `GET /api/v1/feedback/settings` — Current AI settings
- `GET /api/v1/feedback/accuracy-trend` — Accuracy trend over time
- `GET /api/v1/feedback/adaptive-thresholds` — Calculated adaptive thresholds
- `POST /api/v1/feedback/invalidate-cache` — Clear threshold cache

### System
- `GET /` — API info
- `GET /health` — Health check (DB connectivity, active task count)
- `GET /api/v1` — API version and endpoint summary

## AI Pipeline

1. **Image Extraction** — Playwright navigates dealer websites, scrolls to trigger lazy loading, and extracts all images above minimum dimensions. For pages where extraction fails, falls back to full-page screenshot tiling.

2. **Page Discovery** — Automatically discovers subpages on dealer websites (inventory, specials, promotions) up to a configurable depth.

3. **CLIP Embedding Pre-Filter** — Computes CLIP ViT-B-32 embeddings for extracted images and campaign assets. Images below a cosine similarity threshold are skipped before reaching Claude.

4. **Perceptual Hash Pre-Filter** — Computes pHash, dHash, wHash, and average hash for fast near-duplicate detection. Images with no hash resemblance to any asset are filtered out.

5. **Claude Analysis** — Multi-stage visual analysis:
   - **Filtering** — Domain-specific relevance detection (cheap model: Claude Haiku)
   - **Ensemble Matching** — Visual similarity + asset detection + hash comparison (weighted ensemble)
   - **Verification** — Boolean gate verification for borderline confidence scores
   - **Compliance Assessment** — Brand element detection, modification identification, custom rule evaluation

6. **Adaptive Thresholds** — Confidence calibration by source type (screenshot, banner, ad, organic) and channel (website, Google Ads, Facebook). Thresholds adjust automatically based on user feedback (approve/flag actions).

## AI Configuration

Key thresholds are configurable via environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `EXACT_MATCH_THRESHOLD` | 90 | Score for exact match classification |
| `STRONG_MATCH_THRESHOLD` | 75 | Score for strong match classification |
| `PARTIAL_MATCH_THRESHOLD` | 55 | Score for partial match classification |
| `WEAK_MATCH_THRESHOLD` | 40 | Score for weak match classification |
| `REGULAR_IMAGE_MATCH_THRESHOLD` | 55 | Min score to create a match (regular images) |
| `SCREENSHOT_MATCH_THRESHOLD` | 55 | Min score to create a match (screenshots) |
| `FILTER_RELEVANCE_THRESHOLD` | 0.7 | Min relevance to pass the filter stage |
| `CLIP_SIMILARITY_THRESHOLD` | 0.25 | Min CLIP cosine similarity to proceed to Claude |
| `HASH_PREFILTER_MAX_DIFF` | 30 | Max avg hash difference to pass pre-filter (0–64) |
| `MAX_PAGES_PER_SITE` | 15 | Max subpages to scan per dealer website |
| `MAX_IMAGES_PER_PAGE` | 50 | Max images to extract per page |

## Plans & Pricing

| Feature | Free (14-day trial) | Starter | Professional | Business |
|---------|---------------------|---------|--------------|----------|
| Dealers | 2 | 10 | 40 | 100 |
| Campaigns | 1 | 3 | 10 | Unlimited |
| Scans/month | 5 total | 15 | 40 | 150 |
| Channels | Website | Website | All | All |
| Scheduled scans | — | Biweekly/Monthly | Weekly+ | Daily+ |
| Team seats | 1 | 1 | 3 | 10 |
| PDF reports | 1 | — | Yes | Yes |
| Compliance rules | — | — | 10 | Unlimited |
| Email notifications | — | — | Yes | Yes |
| Data retention | 21 days | 90 days | 180 days | 365 days |

## Estimated Costs

| Component | Monthly Cost |
|-----------|-------------|
| DigitalOcean API (2GB RAM) | $25 |
| DigitalOcean Managed Redis | $15 |
| Supabase (Free/Pro) | $0–25 |
| Vercel (Frontend) | $0–20 |
| ScreenshotOne | $25+ |
| Anthropic (Claude) | $20–100 |
| SerpApi (Google Ads) | $0–75 |
| Apify (Meta/Instagram) | $0–49 |
| Sentry (Free tier) | $0 |
| **Total** | **~$85–335/month** |

## Deployment

### Backend — DigitalOcean App Platform

The backend deploys via the spec in `.do/app.yaml`. On push to `main`, DigitalOcean builds the Docker image and deploys automatically.

```bash
# Or deploy manually via doctl
doctl apps create --spec .do/app.yaml
```

Key settings:
- Instance: `professional-xs` (2GB RAM) with `WEB_CONCURRENCY=1`
- Health check: `GET /health` (checks DB connectivity)
- All secrets configured as runtime environment variables

### Frontend — Vercel

```bash
cd frontend
npx vercel
```

Set environment variables in the Vercel dashboard:
- `NEXT_PUBLIC_API_URL` — Your DigitalOcean API URL
- `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_SENTRY_DSN` (optional)
- `NEXT_PUBLIC_MAPBOX_TOKEN` (optional)

### Local Development with Docker

```bash
docker-compose up
```

Starts Redis and the API service. Frontend runs separately via `npm run dev`.

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on every push/PR to `main`:

1. **Backend Tests** — Python 3.11, `pytest` with mock Supabase
2. **Frontend Build** — Node 20, `npm ci && npm run build`
3. **Migrations** — On merge to `main` only: `supabase db push` via Supabase CLI

## Security Notes

- All secrets load from environment variables — nothing hardcoded
- Supabase Auth with JWT verification against JWKS (ES256/RS256 + HS256 fallback)
- Rate limiting via SlowAPI (120/min default, stricter on sensitive endpoints)
- CORS origins configurable via `CORS_ORIGINS` env var
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, CSP
- Stripe webhook signature verification
- API keys should be rotated after initial setup
- Configure Supabase Storage RLS policies for production

---


