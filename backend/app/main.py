"""Dealer Intel SaaS - FastAPI Backend."""
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import get_settings
from .logging_config import setup_logging
from contextlib import asynccontextmanager
from fastapi import Depends
from .auth import AuthUser, get_current_user
from .routers import campaigns, distributors, matches, dashboard, scanning, feedback, reports, organizations, schedules
from .services import scheduler_service

settings = get_settings()
setup_logging(debug=settings.debug)
log = logging.getLogger("dealer_intel.app")

# Sentry error tracking (no-op if DSN is empty)
if settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.2,
        environment="production" if not settings.debug else "development",
    )

# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

@asynccontextmanager
async def lifespan(application: FastAPI):
    await scheduler_service.start()
    yield
    await scheduler_service.shutdown()

app = FastAPI(
    title="Dealer Intel API",
    description="AI-powered campaign asset monitoring for distributor networks",
    version="1.0.0",
    debug=False,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware — origins from config, comma-separated
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler — prevent leaking internals in production
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"} if not settings.debug else {"detail": str(exc)},
    )

# Include routers
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(campaigns.router, prefix="/api/v1")
app.include_router(distributors.router, prefix="/api/v1")
app.include_router(matches.router, prefix="/api/v1")
app.include_router(scanning.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(schedules.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Dealer Intel API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check — verifies database connectivity."""
    checks = {"database": "unknown"}
    healthy = True

    try:
        from .database import supabase
        result = supabase.table("organizations").select("id", count="exact").limit(1).execute()
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        healthy = False
        log.warning("Health check: database unreachable — %s", e)

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if healthy else "degraded",
            "checks": checks,
        },
    )


@app.get("/api/v1")
async def api_root():
    """API root with available endpoints."""
    return {
        "endpoints": {
            "dashboard": "/api/v1/dashboard",
            "campaigns": "/api/v1/campaigns",
            "distributors": "/api/v1/distributors",
            "matches": "/api/v1/matches",
            "scans": "/api/v1/scans",
            "feedback": "/api/v1/feedback",
            "reports": "/api/v1/reports",
            "organizations": "/api/v1/organizations",
            "schedules": "/api/v1/schedules",
        }
    }


@app.get("/api/v1/auth/me")
async def get_me(user: AuthUser = Depends(get_current_user)):
    """Return the current authenticated user's info."""
    return {
        "user_id": str(user.user_id),
        "organization_id": str(user.org_id),
        "role": user.role,
        "email": user.email,
    }










