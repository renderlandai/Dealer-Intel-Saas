"""Dealer Intel SaaS - FastAPI Backend."""
import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .logging_config import setup_logging
from contextlib import asynccontextmanager
from fastapi import Depends
from .auth import AuthUser, get_current_user
from .routers import campaigns, distributors, matches, dashboard, scanning, feedback, reports, organizations, schedules, billing, team, alerts, compliance_rules
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
app.add_middleware(SlowAPIMiddleware)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            "%s %s %d %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


app.add_middleware(RequestLoggingMiddleware)

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
app.include_router(billing.router, prefix="/api/v1")
app.include_router(team.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(compliance_rules.router, prefix="/api/v1")


if settings.enable_dangerous_endpoints:
    log.warning("ENABLE_DANGEROUS_ENDPOINTS is ON — bulk delete and debug routes are active")
else:
    log.info("Dangerous endpoints disabled (ENABLE_DANGEROUS_ENDPOINTS=false)")


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
    """Health check — verifies database connectivity and background task state."""
    from .tasks import _running_tasks

    checks: dict = {"database": "unknown"}
    healthy = True

    try:
        from .database import supabase
        supabase.table("organizations").select("id", count="exact").limit(1).execute()
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        healthy = False
        log.warning("Health check: database unreachable — %s", e)

    checks["background_tasks_running"] = len(_running_tasks)

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
            "billing": "/api/v1/billing",
            "team": "/api/v1/team",
            "alerts": "/api/v1/alerts",
            "compliance-rules": "/api/v1/compliance-rules",
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










