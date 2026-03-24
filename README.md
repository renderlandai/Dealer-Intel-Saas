# Dealer Intel SaaS

AI-powered campaign asset monitoring for distributor networks. Automatically detect where and how your approved campaign assets appear across dealer and distributor digital channels.

![Dashboard Preview](https://via.placeholder.com/800x400?text=Dealer+Intel+Dashboard)

## Features

- **Asset Tracking**: Upload approved campaign assets and track their usage across distributor networks
- **Multi-Channel Monitoring**: Scan Google Ads, Facebook, Instagram, YouTube, and dealer websites
- **AI-Powered Matching**: Claude Opus 4.5 performs multi-stage image analysis with ensemble matching
- **Perceptual Hashing**: Fast pre-filtering with pHash, dHash, and wHash algorithms
- **Modification Detection**: Detect resized, cropped, recolored, or altered versions of assets
- **Compliance Reporting**: Identify missing brand elements, expired promotions ("zombie ads"), and unauthorized modifications
- **Adaptive Thresholds**: AI confidence calibration based on feedback and source types
- **Real-Time Dashboard**: Monitor compliance rates, alerts, geographic coverage, and asset analytics

## Prerequisites

- Python 3.11+
- Node.js 18+
- Supabase account
- Anthropic API key (Claude)
- ScreenshotOne account (access key)

## Quick Setup

### 1. Clone and Install Dependencies

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 2. Configure Environment Variables

Create `backend/.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ANTHROPIC_API_KEY=your-anthropic-api-key
SCREENSHOTONE_ACCESS_KEY=your-screenshotone-access-key
SCREENSHOTONE_SECRET_KEY=your-screenshotone-secret-key
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

### 3. Set Up Database

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor**
3. Copy and paste the contents of `supabase/schema.sql`
4. Click **Run** to create all tables
5. Run migrations from `supabase/migrations/` folder in order

### 4. Create Storage Bucket

In Supabase:
1. Go to **Storage**
2. Create a new bucket called `campaign-assets`
3. Set it to **Public** for MVP (configure policies for production)

### 5. Start the Application

```bash
# Terminal 1: Backend
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Project Structure

```
dealer-intel/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Environment & AI threshold configuration
│   │   ├── database.py          # Supabase client
│   │   ├── models.py            # Pydantic schemas
│   │   ├── routers/
│   │   │   ├── campaigns.py     # Campaign & Asset CRUD
│   │   │   ├── distributors.py  # Distributor CRUD
│   │   │   ├── matches.py       # Match management
│   │   │   ├── dashboard.py     # Dashboard stats & analytics
│   │   │   ├── scanning.py      # Scan jobs & analysis
│   │   │   └── feedback.py      # AI accuracy feedback & calibration
│   │   └── services/
│   │       ├── ai_service.py              # Claude image analysis pipeline
│   │       ├── screenshot_service.py      # ScreenshotOne integration
│   │       └── adaptive_threshold_service.py  # Dynamic threshold tuning
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── page.tsx             # Dashboard
│   │   ├── campaigns/           # Campaign management
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   ├── distributors/        # Distributor management
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   ├── matches/             # Match review
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   └── scans/               # Scan job management
│   │       └── page.tsx
│   ├── components/
│   │   ├── ui/                  # shadcn/ui components
│   │   ├── layout/              # Sidebar, Header
│   │   └── dashboard/           # Dashboard widgets
│   │       ├── stat-card.tsx
│   │       ├── recent-matches.tsx
│   │       ├── alerts-panel.tsx
│   │       ├── channel-chart.tsx
│   │       ├── DealerMap.tsx
│   │       └── LiveAuditFeed.tsx
│   └── lib/
│       ├── api.ts               # API client
│       ├── hooks.ts             # React Query hooks
│       ├── query-provider.tsx   # React Query provider
│       └── utils.ts             # Utility functions
├── supabase/
│   ├── schema.sql               # Database schema
│   └── migrations/              # Database migrations
│       ├── 001_deduplicate_matches.sql
│       ├── 002_add_matches_count.sql
│       ├── 003_add_discovered_image_to_view.sql
│       ├── 004_add_match_feedback.sql
│       └── 005_performance_indexes.sql
└── README.md
```

## API Endpoints

### Dashboard
- `GET /api/v1/dashboard/stats` - Get dashboard statistics
- `GET /api/v1/dashboard/recent-matches` - Get recent matches
- `GET /api/v1/dashboard/recent-alerts` - Get recent alerts
- `GET /api/v1/dashboard/coverage-by-channel` - Match coverage by channel
- `GET /api/v1/dashboard/coverage-by-distributor` - Match coverage by distributor
- `GET /api/v1/dashboard/compliance-trend` - Compliance trend over time

### Campaigns
- `GET /api/v1/campaigns` - List campaigns
- `POST /api/v1/campaigns` - Create campaign
- `GET /api/v1/campaigns/{id}` - Get campaign
- `DELETE /api/v1/campaigns/{id}` - Delete campaign
- `GET /api/v1/campaigns/{id}/assets` - Get campaign assets
- `POST /api/v1/campaigns/{id}/assets/upload` - Upload asset
- `DELETE /api/v1/campaigns/assets/{id}` - Delete asset
- `POST /api/v1/campaigns/{id}/scans/start` - Start campaign-specific scan
- `GET /api/v1/campaigns/{id}/scans` - Get campaign scans
- `GET /api/v1/campaigns/{id}/scans/{scan_id}` - Get specific scan
- `POST /api/v1/campaigns/{id}/scans/{scan_id}/analyze` - Analyze scan
- `GET /api/v1/campaigns/{id}/matches` - Get campaign matches
- `GET /api/v1/campaigns/{id}/scan-stats` - Get scan statistics

### Distributors
- `GET /api/v1/distributors` - List distributors
- `POST /api/v1/distributors` - Create distributor
- `GET /api/v1/distributors/{id}` - Get distributor
- `PATCH /api/v1/distributors/{id}` - Update distributor
- `DELETE /api/v1/distributors/{id}` - Delete distributor
- `GET /api/v1/distributors/{id}/matches` - Get distributor matches
- `POST /api/v1/distributors/{id}/lookup-google-ads-id` - Lookup Google Ads advertiser ID
- `PATCH /api/v1/distributors/{id}/google-ads-id` - Set Google Ads ID

### Matches
- `GET /api/v1/matches` - List matches with filters
- `GET /api/v1/matches/{id}` - Get match details
- `GET /api/v1/matches/stats` - Get match statistics
- `POST /api/v1/matches/{id}/approve` - Approve match
- `POST /api/v1/matches/{id}/flag` - Flag as violation
- `DELETE /api/v1/matches/{id}` - Delete match
- `DELETE /api/v1/matches` - Delete all matches

### Scanning
- `POST /api/v1/scans/start` - Start a new scan
- `GET /api/v1/scans` - List scan jobs
- `GET /api/v1/scans/{id}` - Get scan job details
- `DELETE /api/v1/scans/{id}` - Delete scan
- `DELETE /api/v1/scans` - Delete all scans
- `POST /api/v1/scans/{id}/analyze` - Analyze scan results

### Feedback (AI Improvement)
- `POST /api/v1/feedback` - Submit match feedback
- `GET /api/v1/feedback/stats` - Get accuracy statistics
- `GET /api/v1/feedback/threshold-recommendations` - Get threshold recommendations
- `GET /api/v1/feedback/pending-reviews` - Get pending review queue
- `GET /api/v1/feedback/settings` - Get current AI settings
- `GET /api/v1/feedback/accuracy-trend` - Get accuracy trend over time
- `GET /api/v1/feedback/adaptive-thresholds` - Get calculated adaptive thresholds
- `POST /api/v1/feedback/invalidate-cache` - Clear threshold cache

## AI Pipeline

1. **ScreenshotOne** captures full-page screenshots from:
   - Google Ads Transparency Center (per advertiser)
   - Facebook/Meta Ad Library (per page)
   - Dealer websites (full-page with lazy-load support)

2. **Perceptual Hashing** provides fast pre-filtering:
   - pHash, dHash, wHash, average hash algorithms
   - Quick detection of exact/near-exact matches

3. **Claude Opus 4.5** performs multi-stage analysis:
   - **Filtering**: Domain-specific relevance detection
   - **Ensemble Matching**: Visual similarity + asset detection + hash comparison
   - **Verification**: Boolean gate verification for borderline matches
   - **Compliance Analysis**: Brand element detection, modification identification

4. **Adaptive Thresholds** optimize accuracy:
   - Confidence calibration by source type and channel
   - Feedback-driven threshold tuning
   - Automatic cache invalidation

## AI Configuration

Key thresholds can be configured via environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `EXACT_MATCH_THRESHOLD` | 90 | Score for exact match |
| `STRONG_MATCH_THRESHOLD` | 75 | Score for strong match |
| `PARTIAL_MATCH_THRESHOLD` | 55 | Score for partial match |
| `WEAK_MATCH_THRESHOLD` | 40 | Score for weak match |
| `REGULAR_IMAGE_MATCH_THRESHOLD` | 55 | Min score for regular images |
| `SCREENSHOT_MATCH_THRESHOLD` | 55 | Min score for screenshots |
| `FILTER_RELEVANCE_THRESHOLD` | 0.7 | Min relevance to pass filter |

## Estimated Costs

| Component | Monthly Cost |
|-----------|-------------|
| Supabase (Free tier) | $0 |
| ScreenshotOne (Starter) | $25+ |
| Anthropic (Claude) | $20-100 |
| Vercel (Free tier) | $0 |
| **Total** | **~$45-125/month** |

## Deployment

### Deploy Backend to Railway

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and deploy
railway login
cd backend
railway init
railway up
```

### Deploy Frontend to Vercel

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
cd frontend
vercel
```

## Next Steps

1. **Configure ScreenshotOne**: Sign up at [screenshotone.com](https://screenshotone.com) and add your access key to `.env`

2. **Add Authentication**: Implement Supabase Auth for user management

3. **Set Up Scheduled Scans**: Use Supabase Edge Functions or a cron service for automated monitoring

4. **Review AI Feedback**: Use the `/api/v1/feedback` endpoints to monitor and improve AI accuracy

## Security Notes

- Rotate API keys after initial setup
- Configure proper RLS policies in Supabase for production
- Use environment variables for all secrets
- Enable CORS restrictions for production

---

Built with love using FastAPI, Next.js, Supabase, and Anthropic Claude