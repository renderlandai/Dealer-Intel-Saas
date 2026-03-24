"""Gunicorn production config for Dealer Intel API."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Uvicorn workers for async FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# DO App Platform basic tier has 512MB-1GB RAM; keep workers conservative.
# Playwright + CLIP model are memory-heavy, so 2 workers is safe.
workers = int(os.getenv("WEB_CONCURRENCY", min(2, multiprocessing.cpu_count())))

# Timeouts — scans can be long-running
timeout = 300
graceful_timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# Preload app so CLIP model loads once, shared across workers
preload_app = True
