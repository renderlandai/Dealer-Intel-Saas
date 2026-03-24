"""
CLIP embedding service for fast visual similarity pre-filtering.

Computes image embeddings locally using a lightweight CLIP model, then
uses cosine similarity to discard images that have no visual relationship
to any campaign asset — before making expensive Claude API calls.

Typical latency: ~20ms per image on CPU (clip-ViT-B-32).
"""
import io
import logging
from typing import List, Optional

import numpy as np
from PIL import Image

from ..config import get_settings

log = logging.getLogger("dealer_intel.embedding")

settings = get_settings()

_model = None
_model_load_attempted = False


def _get_model():
    """Lazy-load the CLIP model on first use. Returns None if unavailable."""
    global _model, _model_load_attempted
    if _model is not None:
        return _model
    if _model_load_attempted:
        return None
    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        log.info("Loading CLIP model: %s", settings.clip_model_name)
        _model = SentenceTransformer(settings.clip_model_name)
        log.info("CLIP model loaded successfully")
        return _model
    except Exception as e:
        log.warning("CLIP model unavailable — embedding pre-filter disabled: %s", e)
        return None


def compute_embedding(image_bytes: bytes) -> Optional[np.ndarray]:
    """Compute a CLIP embedding vector for a single image."""
    model = _get_model()
    if model is None:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        embedding = model.encode(img, convert_to_numpy=True)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding
    except Exception as e:
        log.warning("Embedding computation failed: %s", e)
        return None


def compute_embeddings_batch(images_bytes: List[bytes]) -> List[Optional[np.ndarray]]:
    """Compute CLIP embeddings for a batch of images."""
    model = _get_model()
    if model is None:
        return [None] * len(images_bytes)

    pil_images = []
    valid_indices = []
    for i, img_bytes in enumerate(images_bytes):
        try:
            pil_images.append(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
            valid_indices.append(i)
        except Exception as e:
            log.warning("Could not open image %d for embedding: %s", i, e)

    if not pil_images:
        return [None] * len(images_bytes)

    try:
        raw = model.encode(pil_images, convert_to_numpy=True, batch_size=32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalised = raw / norms
    except Exception as e:
        log.error("Batch embedding failed: %s", e)
        return [None] * len(images_bytes)

    results: List[Optional[np.ndarray]] = [None] * len(images_bytes)
    for j, idx in enumerate(valid_indices):
        results[idx] = normalised[j]
    return results


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised vectors."""
    return float(np.dot(a, b))


def best_asset_similarity(
    image_embedding: np.ndarray,
    asset_embeddings: List[np.ndarray],
) -> float:
    """Return the highest cosine similarity between an image and any asset."""
    if not asset_embeddings:
        return 0.0
    sims = [cosine_similarity(image_embedding, ae) for ae in asset_embeddings]
    return max(sims)
