"""Dealer Intel SaaS - FastAPI Backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import campaigns, distributors, matches, dashboard, scanning, feedback

settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Dealer Intel API",
    description="AI-powered campaign asset monitoring for distributor networks",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(campaigns.router, prefix="/api/v1")
app.include_router(distributors.router, prefix="/api/v1")
app.include_router(matches.router, prefix="/api/v1")
app.include_router(scanning.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")


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
    """Health check endpoint."""
    return {"status": "healthy"}


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
            "feedback": "/api/v1/feedback"
        }
    }










