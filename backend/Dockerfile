FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for OpenCV, Playwright, and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch first so sentence-transformers does not pull the
# multi-GB CUDA build during the requirements install. Pin matches
# requirements.txt; keep both in sync if you bump the version.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
        torch==2.5.1+cpu \
    && pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only to keep image smaller)
RUN playwright install chromium --with-deps

# Pre-download the CLIP model into the image so the first scan does not
# pay the ~50MB model fetch + cold load latency. Same model name used by
# `embedding_service._get_model` (see config.clip_model_name default).
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('clip-ViT-B-32')"

COPY . .

EXPOSE 8000

# Default CMD = API. The DigitalOcean `worker` component overrides this
# (see .do/app.yaml) so the worker process does not bind a port and does
# not run gunicorn.
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
