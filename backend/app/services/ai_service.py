"""
Anthropic Claude AI service for image analysis.

Pipeline (scale-optimised):
  Stage 0: Extraction filters — min dimensions, max per page (free)
  Stage 1: Perceptual hash pre-filter — skip images with no hash
           resemblance to any campaign asset (free, <1ms)
  Stage 2: CLIP embedding gate — skip images with low semantic
           similarity to all campaign assets (local GPU/CPU, ~20ms)
  Stage 3: Claude Haiku relevance filter (cheap, ~0.1s)
  Stage 4: Claude Opus ensemble matching + compliance (expensive)

Expensive Claude Opus calls only run on images that survived all
prior stages, reducing API calls by ~95% at scale.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
import httpx
import base64
import json
import re
import io
import asyncio
from PIL import Image, ImageEnhance
import imagehash
import anthropic

from ..config import get_settings, get_calibration_factor
from ..models import ImageFilterResult, ComplianceCheckResult
from .adaptive_threshold_service import (
    get_adaptive_threshold, 
    should_verify_match,
    get_calibration_factor_from_feedback
)
from . import embedding_service

log = logging.getLogger("dealer_intel.ai_service")

settings = get_settings()

# Configure Anthropic client.
#
# Timeout (2026-05-08 Phase-8 hardening): pass an explicit ``timeout`` to
# the SDK constructor. The SDK default is 600s. With
# ``settings.max_retries=5`` that meant a single hung TCP connection burned
# up to 50 minutes of wall-clock on one image — long enough to starve the
# per-page heartbeat past ``scan_idle_timeout_minutes`` and trip the
# cleanup auto-fail. The new ceiling is
# ``settings.anthropic_request_timeout_seconds`` (default 120s), bounding
# worst-case retry budget at 5 × 120s = 10 min, which the per-page
# ``page_hard_timeout_seconds`` backstop further constrains.
anthropic_client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key,
    timeout=settings.anthropic_request_timeout_seconds,
)

# ---------------------------------------------------------------------------
# Matcher Claude model — DO NOT BUMP WITHOUT RUNNING THE EVAL.
# ---------------------------------------------------------------------------
# Long, load-bearing comment because this constant has been swung back and
# forth four times and every wrong swap produces "0 matches in production"
# without any other observable signal. If you are reading this because you
# noticed ``ai_service`` calls ``opus-4-6`` while ``cost_tracker`` prices
# ``opus-4-7``, the constant is correct and ``cost_tracker`` is a superset
# of what we actually use — do not "fix" it. History:
#
#   * 2026-04-16  bumped 4-6 → 4-7 as part of the scaling plan.
#   * 2026-04-21  REVERTED 4-7 → 4-6 after running the eval. Opus 4.7
#                 scored materially worse on this account's image-matching
#                 workload — its rubric is more conservative on borderline
#                 cases and its scores have higher run-to-run variance even
#                 at the same image pair. See ``log.md`` "Decision: revert".
#   * 2026-05-08  Phase-8 RE-BUMPED 4-6 → 4-7. The author saw the 4-6
#                 constant, remembered the April 16 plan, and assumed it
#                 had "never propagated". They missed the April 21 revert
#                 entry sitting further down the same log. Result was
#                 invisible until 2026-05-11: every matcher call started
#                 returning HTTP 400 because Opus 4.7 deprecated the
#                 ``temperature`` parameter. We patched ``temperature``
#                 handling, the 400s went away, and we got 0 matches
#                 across a 45-dealer scan and a single-dealer probe even
#                 though the funnel told us 1 image had reached the final
#                 verifier.
#   * 2026-05-11  ROLLED BACK 4-7 → 4-6 after confirming asset
#                 ``fc70adce`` had matched on 2026-05-07 with 4-6
#                 (confidence 93, "exact") and produced 0 matches with
#                 4-7 against the same campaign on 2026-05-11.
#
# Ground rules for the next person who wants to bump this:
#   1. Run the eval at ``backend/eval/`` first; do NOT eyeball it.
#   2. Gate the bump on the eval report. Anthropic's marketing copy
#      ("better vision and instruction following") is not evidence for
#      our specific image-matching rubric.
#   3. If you do bump, update the test in
#      ``backend/tests/test_matcher_model_pin.py`` so future readers see
#      the deliberate decision in the diff. That test exists for the
#      sole purpose of forcing a maintainer to acknowledge this history.
CLAUDE_MODEL = "claude-opus-4-6"
ENSEMBLE_MODEL = "claude-opus-4-6"
FILTER_MODEL = settings.filter_model


# 2026-05-11 Phase-9: Anthropic deprecated the ``temperature`` parameter
# for the Opus 4.7 family (and announced the same is coming for the next
# Sonnet generation). Sending ``temperature`` to one of these models
# returns a 400 ``invalid_request_error`` — there is no graceful
# downgrade. The matcher itself rolled back to opus-4-6 the same day
# (see the long comment by ``CLAUDE_MODEL`` above), so this denylist is
# defensive: it only matters if a caller passes ``use_model="claude-
# opus-4-7"`` explicitly (a few internal probes do). Every other Claude
# slug (haiku-4-5, opus-4-6, sonnet-4-5, etc.) still accepts
# ``temperature=0`` and benefits from the determinism guarantee — that
# determinism is what the matcher's adaptive thresholds were calibrated
# against, and is itself a reason 4-6 outperforms 4-7 here.
_MODELS_THAT_REJECT_TEMPERATURE: tuple[str, ...] = (
    "claude-opus-4-7",
)


def _model_rejects_temperature(model_slug: str) -> bool:
    """Return True iff Anthropic will 400 if we send ``temperature`` to ``model_slug``."""
    if not model_slug:
        return False
    slug = model_slug.strip().lower()
    return any(slug.startswith(prefix) for prefix in _MODELS_THAT_REJECT_TEMPERATURE)


class _ImageCache:
    """In-memory LRU image cache that avoids re-downloading the same URL
    within a scan.  Bounded by entry count and total byte size."""

    def __init__(self, max_entries: int = 200, max_bytes: int = 200 * 1024 * 1024):
        self._store: dict[str, bytes] = {}
        self._order: list[str] = []
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._total_bytes = 0
        self.hits = 0
        self.misses = 0

    def get(self, url: str):
        data = self._store.get(url)
        if data is not None:
            self.hits += 1
            self._order.remove(url)
            self._order.append(url)
            return data
        self.misses += 1
        return None

    def put(self, url: str, data: bytes):
        if url in self._store:
            return
        while (
            len(self._order) >= self._max_entries
            or self._total_bytes + len(data) > self._max_bytes
        ) and self._order:
            evict_url = self._order.pop(0)
            evicted = self._store.pop(evict_url, None)
            if evicted:
                self._total_bytes -= len(evicted)
        self._store[url] = data
        self._order.append(url)
        self._total_bytes += len(data)

    def clear(self):
        self._store.clear()
        self._order.clear()
        self._total_bytes = 0
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / max(total, 1) * 100, 1),
            "cached_entries": len(self._store),
            "cached_mb": round(self._total_bytes / (1024 * 1024), 2),
        }


_image_cache = _ImageCache()

_VALID_IMAGE_CONTENT_TYPES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/bmp", "image/tiff", "image/svg+xml",
})


def _is_valid_image(data: bytes) -> bool:
    """Return True if Pillow can identify *data* as a supported image format."""
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        return True
    except Exception:
        return False


async def download_image(url: str) -> bytes:
    """Download image from URL with caching, timeout, and error handling.

    Results are cached in-memory so the same URL is only fetched once per
    server lifetime (or until the LRU evicts it).
    """
    if url.startswith("data:"):
        try:
            header, encoded = url.split(",", 1)
            data = base64.b64decode(encoded)
        except Exception as e:
            log.error("Error decoding base64 data URL: %s", e)
            raise
        if not _is_valid_image(data):
            raise ValueError("Data URL does not contain a valid image")
        return data

    cached = _image_cache.get(url)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            if not _is_valid_image(response.content):
                content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                raise ValueError(
                    f"Downloaded content is not a valid image "
                    f"(content-type='{content_type}', {len(response.content)} bytes): {url[:100]}"
                )

            _image_cache.put(url, response.content)
            return response.content
        except httpx.HTTPStatusError as e:
            log.error("HTTP error downloading image: %d - %s", e.response.status_code, url[:100])
            raise
        except httpx.TimeoutException:
            log.error("Timeout downloading image: %s", url[:100])
            raise
        except ValueError:
            raise
        except Exception as e:
            log.error("Error downloading image: %s - %s", e, url[:100])
            raise


def get_image_cache_stats() -> dict:
    """Return current image cache statistics."""
    return _image_cache.stats()


def clear_image_cache():
    """Clear the image cache (call between scans if needed)."""
    _image_cache.clear()


def encode_image_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64."""
    return base64.b64encode(image_bytes).decode('utf-8')


def optimize_image_for_api(
    image_bytes: bytes, 
    analysis_type: str = "default"
) -> Optional[bytes]:
    """
    Type-specific image optimization for better API performance and accuracy.
    
    Args:
        image_bytes: Raw image bytes
        analysis_type: One of 'screenshot', 'asset', 'default'
    
    Returns:
        Optimized image bytes, or None if the input is not a valid image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # Type-specific settings
        if analysis_type == "screenshot":
            # Screenshots: maintain detail for finding small assets
            max_size = (settings.screenshot_max_width, settings.screenshot_max_height)
            quality = 90
            enhance_contrast = 1.05
            enhance_sharpness = 1.02
        elif analysis_type == "asset":
            # Assets: high quality reference images
            max_size = (settings.max_image_width, settings.max_image_height)
            quality = 95
            enhance_contrast = 1.0  # Don't modify reference
            enhance_sharpness = 1.0
        else:
            # Default optimization
            max_size = (settings.max_image_width, settings.max_image_height)
            quality = 85
            enhance_contrast = 1.1
            enhance_sharpness = 1.05
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'P', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize if needed
        if img.width > max_size[0] or img.height > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Apply enhancements for non-asset images
        if enhance_contrast != 1.0:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(enhance_contrast)
        
        if enhance_sharpness != 1.0:
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(enhance_sharpness)
        
        # Save with compression
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        
        # Reduce quality if still too large
        while output.tell() > settings.max_image_bytes and quality > 30:
            quality -= 10
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
        
        optimized_bytes = output.getvalue()
        
        # Log compression stats
        original_size = len(image_bytes)
        new_size = len(optimized_bytes)
        if original_size > new_size:
            reduction = 100 - (new_size * 100 // original_size)
            log.debug("Optimized %s image: %.1fKB -> %.1fKB (%d%% reduction)", analysis_type, original_size / 1024, new_size / 1024, reduction)
        
        return optimized_bytes
        
    except Exception as e:
        log.warning("Image optimization failed (skipping image): %s", e)
        return None


async def compute_image_hashes(image_bytes: bytes) -> Dict[str, Any]:
    """
    Compute multiple perceptual hashes for an image.
    
    Returns dict with phash, dhash, whash values for robust comparison.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        return {
            "phash": imagehash.phash(img),
            "dhash": imagehash.dhash(img),
            "whash": imagehash.whash(img),
            "average_hash": imagehash.average_hash(img)
        }
    except Exception as e:
        log.error("Hash computation failed: %s", e)
        return None


async def compare_with_hash(
    asset_url: str, 
    discovered_url: str
) -> Dict[str, Any]:
    """
    Fast perceptual hash comparison for detecting exact/near-exact matches.
    
    This provides a quick pre-filter before expensive AI analysis.
    """
    try:
        asset_bytes = await download_image(asset_url)
        discovered_bytes = await download_image(discovered_url)
        
        asset_hashes = await compute_image_hashes(asset_bytes)
        discovered_hashes = await compute_image_hashes(discovered_bytes)
        
        if not asset_hashes or not discovered_hashes:
            return {"similarity_score": 0, "is_exact": False, "is_similar": False, "error": "Hash computation failed"}
        
        # Calculate differences (lower = more similar)
        phash_diff = asset_hashes["phash"] - discovered_hashes["phash"]
        dhash_diff = asset_hashes["dhash"] - discovered_hashes["dhash"]
        whash_diff = asset_hashes["whash"] - discovered_hashes["whash"]
        avg_diff = asset_hashes["average_hash"] - discovered_hashes["average_hash"]
        
        # Average difference across hash types
        total_diff = (phash_diff + dhash_diff + whash_diff + avg_diff) / 4
        
        # Convert to similarity score (0-100)
        # Max difference is 64 for 8x8 hash
        similarity = max(0, 100 - (total_diff * 100 / 64))
        
        return {
            "similarity_score": round(similarity),
            "is_exact": total_diff < 5,
            "is_similar": total_diff < 15,
            "is_related": total_diff < 25,
            "hash_differences": {
                "phash": int(phash_diff),
                "dhash": int(dhash_diff),
                "whash": int(whash_diff),
                "average": int(avg_diff)
            }
        }
        
    except Exception as e:
        log.error("Hash comparison error: %s", e)
        return {
            "similarity_score": 0,
            "is_exact": False,
            "is_similar": False,
            "error": str(e)
        }


async def call_anthropic_with_retry(
    prompt: str,
    images: List[bytes],
    max_retries: int = None,
    model: str = None,
    cache_prefix_images: int = 0,
) -> str:
    """
    Call Anthropic Claude API with retry logic and image support.

    Args:
        prompt: Text prompt for the model
        images: List of image bytes to include
        max_retries: Number of retry attempts
        model: Override model (defaults to CLAUDE_MODEL / Opus)
        cache_prefix_images: Number of leading images to mark as a cacheable
            prefix via Anthropic prompt caching (`cache_control: ephemeral`).
            The prompt text + the first N images become a stable prefix that
            subsequent calls within the 5-minute cache TTL can reuse for ~90%
            input-token discount.  Defaults to 0 (no caching, fully backward
            compatible with the legacy call signature).

            Use this when the same campaign asset(s) are compared against many
            different discovered images in a tight loop — the asset stays the
            same across calls, so caching it pays off after the first call.

    Returns:
        Response text from Claude
    """
    if max_retries is None:
        max_retries = settings.max_retries

    use_model = model or CLAUDE_MODEL
    last_error = None

    # Build message content with images, filtering out any None entries
    valid_images = [img for img in images if img is not None]
    if not valid_images:
        raise ValueError("No valid images to send to API — all images failed validation or optimization")

    # Cap the cacheable prefix at the number of images actually present, and
    # at 3 (Anthropic allows up to 4 cache breakpoints per request; we use
    # at most one — on the last cacheable image — leaving headroom for callers
    # that want to add more later).
    cache_prefix = max(0, min(cache_prefix_images, len(valid_images)))

    # Prompt text leads.  When caching is requested, the cache breakpoint goes
    # on the LAST cacheable image; everything from the start of the message
    # through that block becomes the cached prefix.  The prompt text varies
    # per-operation (filter vs compare vs compliance), but is identical across
    # repeated calls to the same operation, so it caches naturally.
    text_block = {
        "type": "text",
        "text": prompt + "\n\nRespond ONLY with valid JSON matching the required schema. No markdown, no explanation outside the JSON.",
    }
    content: List[Dict[str, Any]] = [text_block]

    for idx, img_bytes in enumerate(valid_images):
        img_b64 = encode_image_base64(img_bytes)
        block: Dict[str, Any] = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_b64,
            },
        }
        # Mark the LAST cacheable image as the cache breakpoint.  Anthropic
        # caches everything from start-of-message up to and including this
        # block.  Cache will only actually be created if the prefix exceeds
        # the per-model minimum (1024 tokens for Opus, 2048 for Haiku); below
        # that threshold the marker is silently ignored, no error.
        if cache_prefix > 0 and idx == cache_prefix - 1:
            block["cache_control"] = {"type": "ephemeral"}
        content.append(block)

    # 2026-05-11 Phase-9: ``claude-opus-4-7`` deprecated the
    # ``temperature`` parameter and rejects requests that include it
    # (HTTP 400 invalid_request_error: "temperature is deprecated for
    # this model"). The probe uncovered that EVERY matcher comparison
    # call had been failing this way since the model upgrade — which
    # is the actual cause of the "0 matches" outcome that we'd been
    # blaming on score thresholds and download failures. We drop the
    # parameter for any opus-4-7-or-later slug; older Claude models
    # (haiku-4-5, opus-4-6) still accept it, so keep it on those.
    create_kwargs: Dict[str, Any] = {
        "model": use_model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }
    if not _model_rejects_temperature(use_model):
        create_kwargs["temperature"] = 0

    for attempt in range(max_retries):
        try:
            # Run synchronous Anthropic call in executor
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: anthropic_client.messages.create(**create_kwargs),
            )
            try:
                from . import cost_tracker
                usage = getattr(response, "usage", None)
                if usage is not None:
                    cost_tracker.record_anthropic(
                        model=use_model,
                        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                        cache_creation_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
                        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                    )
            except Exception as cost_err:
                log.debug("Cost capture skipped: %s", cost_err)
            return response.content[0].text
            
        except Exception as e:
            error_str = str(e).lower()
            last_error = e
            
            # Check if retryable
            is_retryable = any(x in error_str for x in [
                '500', '503', 'internal', 'unavailable', 'overloaded',
                'rate', 'quota', 'timeout', 'connection'
            ])
            
            if not is_retryable:
                log.error("Non-retryable error: %s", e)
                raise
            
            if attempt < max_retries - 1:
                backoff = settings.initial_backoff * (2 ** attempt)
                log.warning("Attempt %d failed: %s", attempt + 1, e)
                log.warning("Retrying in %.1fs...", backoff)
                await asyncio.sleep(backoff)
            else:
                log.error("All %d attempts failed", max_retries)
    
    raise last_error


def extract_json_from_response(response_text: str) -> dict:
    """
    Extract JSON from response text robustly.
    
    Handles various formats including markdown code blocks.
    """
    text = response_text.strip()
    
    # Try to find JSON in markdown code block first
    code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find any JSON object
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    
    # Last resort: parse whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"Could not extract JSON from response: {text[:200]}...")


def get_filter_prompt(asset_aware: bool = False, asset_count: int = 1) -> str:
    """Get filtering prompt. When asset_aware=True, expects asset image(s) + candidate."""
    if asset_aware:
        if asset_count == 1:
            asset_desc = "IMAGE 1 (FIRST IMAGE): The APPROVED CAMPAIGN CREATIVE — the reference marketing asset."
            candidate_desc = "IMAGE 2 (SECOND IMAGE): An image discovered on a dealer's website."
        else:
            asset_lines = [f"IMAGE {i+1}: Approved campaign creative #{i+1}." for i in range(asset_count)]
            asset_desc = "\n".join(asset_lines)
            candidate_desc = f"IMAGE {asset_count+1} (LAST IMAGE): An image discovered on a dealer's website."

        return f"""You are a QUICK CAMPAIGN MATCHER for a dealer/distributor marketing monitoring system.

{asset_desc}
{candidate_desc}

YOUR TASK: Quickly determine if the discovered image COULD BE the same as ANY of the campaign creatives.
This is a fast pre-screen, not a final verdict. When in doubt, say yes.

LIKELY SAME CAMPAIGN (is_relevant: true, confidence > 0.8):
- Same product/equipment prominently featured as any creative
- Same promotional offer, headline, or pricing visible
- Same visual design, layout, or color scheme as any creative
- Same brand + same campaign message

POSSIBLY RELATED (is_relevant: true, confidence 0.5-0.8):
- Same brand but unclear if same specific campaign
- Similar product category with overlapping visual elements

CLEARLY DIFFERENT (is_relevant: false):
- Different brand entirely from all creatives
- Different product category from all creatives
- UI elements, navigation icons, logos only, maps, avatars
- Generic stock photos with no campaign resemblance
- A completely different promotional campaign for the same brand

Return JSON:
- is_relevant: true/false
- confidence: 0.0-1.0
- reason: brief explanation"""
    else:
        return """Analyze this image for a DEALER/DISTRIBUTOR MARKETING MONITORING system.

CONTEXT: We're monitoring if authorized dealers are using approved campaign creatives correctly.

HIGHLY RELEVANT (is_relevant: true, confidence > 0.8):
- Vehicle/equipment/product advertisements
- Promotional banners with pricing or offers
- Seasonal sale creatives
- Branded promotional content with manufacturer logos
- Dealer-specific advertising materials
- Marketing campaign materials

RELEVANT (is_relevant: true, confidence 0.5-0.8):
- Generic product photos with visible branding
- Social media ad creatives
- Display advertisements
- Promotional imagery

IRRELEVANT (is_relevant: false):
- Company logos only (standalone, small icons)
- Generic stock photos WITHOUT any branding
- UI elements, buttons, navigation icons
- Profile pictures, avatars
- Maps, charts, graphs
- Pure text without product imagery

Return your analysis as JSON with these fields:
- is_relevant: true/false
- confidence: 0.0-1.0
- reason: brief explanation
- detected_elements: array of elements found (e.g., ["logo", "product", "pricing", "offer_text"])"""


def get_comparison_prompt() -> str:
    """Get prompt for campaign-aware visual comparison."""
    return """You are a CAMPAIGN CREATIVE AUDITOR for a dealer/distributor marketing monitoring platform.

IMAGE 1 (FIRST IMAGE): The APPROVED campaign creative — the specific visual asset provided to dealers.
IMAGE 2 (SECOND IMAGE): An image discovered on a dealer's website or ad platform.

YOUR TASK: Determine if Image 2 is the SAME VISUAL CREATIVE as Image 1.

CRITICAL DISTINCTION — SAME CREATIVE vs SAME PROMOTION:
You are checking whether the dealer used this SPECIFIC VISUAL ASSET, not whether they are
running the same promotion. Two images can advertise the SAME offer (same discount, same
promo code, same product) but be COMPLETELY DIFFERENT CREATIVES with different layouts,
photos, typography, and visual design. That is NOT a match.

A MATCH requires the discovered image to be visually derived from the approved creative —
the same layout, the same imagery/photos, the same design composition. It must be
recognizably the SAME VISUAL ARTWORK, not merely the same marketing message.

SAME CREATIVE (is a match):
- Same visual layout and composition
- Same product photo/render in the same arrangement
- Same background, graphic elements, and design structure
- Acceptable differences: resolution, slight cropping, font rendering, aspect ratio,
  dealer name/logo inserted into template placeholders

NOT THE SAME CREATIVE (NOT a match, even if same promotion):
- Different layout or composition (e.g. horizontal vs vertical, different arrangement)
- Different product photo or imagery (even if same product category)
- Different background, color scheme, or graphic design
- Dealer-created banner that advertises the same offer but with their own design
- Same promo code, same discount percentage, but different visual artwork

TEMPLATE CREATIVES — EXPECTED DEALER CUSTOMIZATION:
The approved asset may be a TEMPLATE with placeholder fields. The following substitutions
are normal and should NOT reduce the score:
- "Dealer Name" / "Your Dealer" replaced with actual dealer name/branding/logo
- Placeholder phone numbers, addresses, or URLs replaced with dealer-specific info
- Generic CTA buttons customized with dealer-specific destinations

SCORING RUBRIC:
- 90-100: Same creative — identical or near-identical rendering of the visual asset
          (includes template creatives with expected dealer-name customization)
- 75-89:  Same creative — clearly the same artwork with minor rendering differences
          (different resolution, slight cropping, font rendering differences)
- 65-74:  Same creative — recognizably the same artwork but with modifications
          (text overlays, watermarks, resizing, color shifts)
- 40-64:  Ambiguous — shares significant visual elements but may be a different creative.
          DO NOT mark as a match unless you are confident it is the same artwork.
- 0-39:   Different creative — different visual design, layout, or imagery

AUTOMATIC SCORE 0-20:
- Different brand entirely
- Same promotion/offer but DIFFERENT visual design (dealer made their own banner)
- Same product but different photo, layout, or graphic design
- Different product or offer entirely

Modifications to identify (only when it IS the same creative):
- cropping, resizing, color_changes, text_added, text_removed, overlay_added, quality_degraded, watermark_added
- Do NOT list dealer-name placeholder substitution as a modification

Return JSON with:
- similarity_score: 0-100
- is_match: true ONLY if similarity_score >= 70 (you are confident this is the same visual creative)
- match_type: "exact"/"strong"/"partial"/"weak"/"none"
- modifications: array of detected modifications (exclude expected template customizations)
- modification_severity: "none"/"minor"/"moderate"/"major"
- analysis: explain what visual elements match and what differs"""


def get_detection_prompt() -> str:
    """Get prompt for detecting a campaign creative within a screenshot or page section."""
    return """You are a CAMPAIGN CREATIVE AUDITOR scanning a webpage for a specific visual asset.

IMAGE 1 (FIRST IMAGE): The APPROVED CAMPAIGN CREATIVE — the specific visual asset we are looking for.
IMAGE 2 (SECOND IMAGE): A screenshot from a dealer's website (may be a full page, a page section, or an extracted element).

YOUR TASK: Determine if Image 2 contains the SAME VISUAL CREATIVE shown in Image 1.

CRITICAL DISTINCTION — SAME CREATIVE vs SAME PROMOTION:
You are looking for this SPECIFIC VISUAL ASSET on the page, not just the same promotion.
Two banners can advertise the SAME offer (same discount, same promo code) but use completely
different visual designs, photos, and layouts. That is NOT a match. The page must contain
the actual approved creative artwork — the same layout, same imagery, same visual composition.

A match requires:
- The same visual layout and composition as the approved creative
- The same product photo/render in the same arrangement
- Recognizably the same visual artwork/design

A match does NOT require:
- Pixel-identical rendering
- Exact same resolution or dimensions
- Identical font rendering or text spacing

NOT a match (even if same promotion):
- A dealer-created banner advertising the same offer with different visual design
- Same promo code or discount but different layout, photos, or artwork
- Same brand/product but different creative composition

TEMPLATE CREATIVES:
The approved asset may be a template with placeholders like "Dealer Name" that dealers
replace with their own name/branding. This is expected and correct usage — it should
NOT reduce the confidence score or be treated as a modification.

SCAN ALL AREAS of Image 2:
- Hero/banner sections at the top
- Promotional blocks in the main content
- Sidebar advertisements
- Carousels and sliders (may show only one slide)
- Footer promotional areas
- Floating or overlay promotions

CONFIDENCE SCORING:
- 85-100: Same creative clearly visible — same artwork, same design, same visual composition
- 70-84:  Same creative very likely — recognizable artwork with rendering differences
- 55-69:  Probable match — significant shared visual elements but notable differences
- 0-39:   Not a match — different visual design, different creative, or not found

AUTOMATIC asset_found: false:
- Different brand entirely
- Same promotion/offer but DIFFERENT visual design (dealer made their own banner)
- Same product but different photo, layout, or graphic design
- Different product or offer entirely
- No promotional content visible in the screenshot

Return JSON with:
- asset_found: true ONLY if confidence >= 65
- confidence: 0-100
- location: where found (header/sidebar/main_content/footer/banner/hero/carousel/popup/unknown)
- appearance: how it appears (exact/resized/cropped/modified/none)
- modifications: array of modifications detected
- reasoning: explain which VISUAL DESIGN elements match — layout, imagery, composition"""


def get_compliance_prompt(rules_text: str, zombie_check: str) -> str:
    """Get prompt for compliance analysis - evaluates the creative itself."""
    return f"""COMPLIANCE ANALYSIS — evaluate whether the CREATIVE ITSELF has been modified.

IMAGE 1 (FIRST IMAGE): The ORIGINAL APPROVED ASSET — the official marketing creative.
IMAGE 2 (SECOND IMAGE): The DISCOVERED IMAGE — a crop from a distributor's webpage that
contains the creative. This image was automatically extracted and may include small amounts
of surrounding webpage context (navigation bars, dealer logos, page headers/footers, menu
items, or site chrome). This surrounding context is NORMAL and expected — it is NOT part of
the creative and must be IGNORED during compliance evaluation.

STEP 1 — VERIFY MATCH:
Confirm the discovered image contains the original campaign creative.
- Focus on the CORE CREATIVE CONTENT: the product imagery, promotional text, offer details,
  call-to-action buttons, and brand elements that appear in the original asset.
- IGNORE any surrounding webpage elements (dealer navigation, site headers, menu bars,
  breadcrumbs, dealer logos outside the creative boundary). These are standard website
  context from the ad placement, not modifications.
- If the core creative is NOT present at all, set asset_visible: false.

BRAND RULES:
{rules_text}

{zombie_check}

STEP 2 — IF ASSET IS VISIBLE, CHECK THE CREATIVE FOR VIOLATIONS:

IMPORTANT: Only flag issues that are modifications TO THE CREATIVE ITSELF.
Do NOT flag surrounding website navigation, dealer site branding, or page
chrome as modifications — those are part of the webpage, not the ad.

CRITICAL — TEMPLATE CUSTOMIZATION IS COMPLIANT:
The approved asset is often a TEMPLATE with placeholder fields like "Dealer Name",
"Your Dealer", or "Dealer Logo". Dealers are EXPECTED and REQUIRED to replace these
placeholders with their own name, branding, and contact information. This is the
intended use of the template. Therefore:
- Replacing "Dealer Name" / "Your Dealer" with the dealer's actual name = COMPLIANT
- Replacing placeholder logos with the dealer's own logo = COMPLIANT
- Replacing placeholder phone numbers, addresses, or URLs = COMPLIANT
- Adjusting CTA buttons with dealer-specific text or links = COMPLIANT
These are NOT violations. Do NOT list them as modifications or compliance issues.

1. ASSET INTEGRITY (evaluate the creative content only):
   - Has the creative been cropped so that key content is missing?
   - Has it been stretched, distorted, or significantly resized?
   - Have elements been overlaid ON TOP of the creative?
   - Have the creative's colors been altered? (e.g. colorized, desaturated, tinted,
     color scheme changed, converted to/from grayscale). ANY color change is a VIOLATION.

2. UNAUTHORIZED MODIFICATIONS (not template customization, not surrounding page elements):
   - Has the core campaign imagery been changed or replaced?
   - Have brand logos (manufacturer/OEM logos, not dealer placeholders) been removed or obscured?
   - Has the promotional offer, pricing, or terms been altered from the original?
   - Has the creative's quality been significantly degraded?
   - Have unauthorized elements been overlaid on the creative?

3. BRAND COMPLIANCE:
   - Are all required brand elements from the original creative still visible?
   - Have forbidden elements been added ON the creative itself?
   - Do the colors match the approved creative exactly?

COMPLIANCE RULES:
- is_compliant: true if the creative is visible AND its visual presentation has not been modified
  (template placeholder substitution with dealer info is NOT a modification)
- is_compliant: false if ANY of the following are true:
  * The creative's colors have been changed (colorized, tinted, desaturated, or otherwise altered)
  * The core campaign imagery has been changed or replaced
  * Brand elements have been removed or obscured
  * The promotional offer, pricing, or terms have been altered
  * The creative is not present
- Color changes are ALWAYS a violation — the dealer must use the creative with the exact
  color scheme provided in the approved asset
- Surrounding webpage UI (dealer nav, headers, site logos) is NOT a violation
- Dealer-name/logo placeholder substitution is NOT a violation — it is expected template usage
- When the creative is clearly present with only expected template customizations AND no
  color changes, it IS compliant

Return JSON with:
- is_compliant: true if the creative is present and unmodified
- asset_visible: true if the campaign creative is clearly identifiable
- issues: array of {{type, description, severity}} — only issues with the CREATIVE ITSELF
- modifications_detected: array of actual creative modifications (not webpage context)
- brand_elements: {{logo_visible, tagline_visible, colors_accurate, asset_prominent}}
- zombie_ad: true/false
- zombie_reason: explanation if zombie
- analysis_summary: explain your compliance decision"""


def get_verification_prompt() -> str:
    """Get prompt for multi-stage campaign verification using boolean gates."""
    return """You are a CAMPAIGN VERIFICATION AGENT performing a structured audit.

IMAGE 1: The APPROVED campaign creative
IMAGE 2: The image discovered on a dealer's website or ad platform

PROTOCOL — Execute these steps in order:

STEP 1 - IDENTIFY:
Examine both images. List the product, brand, promotional text, offer details,
and visual design elements in each. Use OCR to read all visible text.

STEP 2 - VERIFY EACH GATE:

□ GATE_BRAND: Is the same brand represented in both?
  - Same manufacturer/company logo or branding
  - FAIL if different brands entirely

□ GATE_PRODUCT: Is the same specific product featured?
  - Same model, same visual representation (same photo or render)
  - PASS even if rendered at different resolution or slightly different angle
  - FAIL if different product model or different product entirely

□ GATE_MESSAGE: Is the same campaign message/headline present?
  - Same core promotional text or headline
  - PASS if the message is the same even with minor wording/formatting differences
  - FAIL if completely different messaging or no promotional text match

□ GATE_OFFER: Is the same offer/deal being promoted?
  - Same pricing, discount, financing terms, or call-to-action
  - PASS if same offer even if formatting differs
  - FAIL if different offer terms or no offer in one image

□ GATE_DESIGN: Is the visual design recognizably the same campaign?
  - Same color scheme, layout structure, visual hierarchy
  - PASS even with rendering differences (font smoothing, spacing, resolution)
  - FAIL if completely different visual design

STEP 3 - VERDICT:
- is_match: true ONLY if GATE_BRAND passes AND GATE_PRODUCT passes AND at least 2 of the
  remaining 3 gates (message / offer / design) ALSO pass — i.e. 4 of 5 gates total.
- A campaign match requires the right brand AND the right product AND multiple
  corroborating campaign elements. Brand + product + design alone is NOT enough — those
  three gates can all be true for a different campaign on the same site (a dealer's
  unrelated promo banner, a stock product photo, a CV-localized crop of webpage chrome
  that happens to have the same color palette). Demanding message OR offer to also
  agree is what distinguishes "the same creative" from "the same dealership".
- When truly uncertain (50/50), lean toward FALSE. It is worse to publish a STRONG
  MATCH on a navigation bar than to miss a real match — a missed match shows up on
  the next scan; a false match erodes operator trust in the system permanently.

Return JSON with:
- gate_brand: true/false
- gate_product: true/false
- gate_message: true/false
- gate_offer: true/false
- gate_design: true/false
- gates_passed: count of true gates (0-5)
- is_match: true ONLY if gate_brand AND gate_product AND gates_passed >= 4
- verdict: one-line explanation of your decision"""


def get_localization_prompt() -> str:
    """Prompt that asks Claude to find a campaign creative in a full-page screenshot
    and return its pixel bounding box so we can crop it out cleanly."""
    return """You are a CAMPAIGN LOCALIZATION AGENT. Your job is to find where a specific
marketing campaign creative appears on a webpage screenshot.

IMAGE 1 (FIRST IMAGE): The APPROVED CAMPAIGN CREATIVE — the official marketing asset.
IMAGE 2 (SECOND IMAGE): A FULL-PAGE SCREENSHOT of a dealer's website.

YOUR TASK: Find every location where the campaign creative (or a close rendering of it)
appears in the full-page screenshot, and return the PIXEL BOUNDING BOX for each occurrence.

WHAT COUNTS AS THE SAME CAMPAIGN:
- Same product being promoted (same model, same visual)
- Same or very similar promotional message/headline
- Recognizably the same visual design
- The website may render it via HTML/CSS, so slight differences in font rendering,
  spacing, or resolution are expected and still count

BOUNDING BOX RULES:
- Coordinates are in pixels relative to the top-left corner of the full-page screenshot
- The box should tightly wrap ONLY the campaign creative — do NOT include adjacent ads,
  navigation bars, footers, or unrelated content
- Add ~10px padding around the creative for clean cropping
- If the creative spans the full width of the page, that's fine — just don't include
  content above or below that isn't part of the creative

Return JSON with:
- found: true/false — whether the campaign creative appears anywhere on the page
- locations: array of objects, each with:
  - x: left edge in pixels
  - y: top edge in pixels
  - width: width in pixels
  - height: height in pixels
  - confidence: 0-100 how confident this is the same campaign
  - reasoning: brief explanation of why this is a match
- page_dimensions: {width, height} of the full screenshot (for validation)"""


async def localize_assets_in_screenshot(
    screenshot_bytes: bytes,
    asset_bytes_list: List[Tuple[bytes, str, str]],
) -> List[Dict[str, Any]]:
    """
    For each campaign asset, ask Claude to find it in the full-page screenshot
    and return bounding boxes.

    Args:
        screenshot_bytes: Full-page screenshot PNG bytes
        asset_bytes_list: List of (image_bytes, asset_id, asset_name)

    Returns:
        List of {asset_id, asset_name, x, y, width, height, confidence}
    """
    prompt = get_localization_prompt()
    screenshot_optimized = optimize_image_for_api(screenshot_bytes, "screenshot")

    if screenshot_optimized is None:
        log.warning("Screenshot failed optimization — skipping localization")
        return []

    all_locations: List[Dict[str, Any]] = []

    for asset_bytes, asset_id, asset_name in asset_bytes_list:
        try:
            asset_optimized = optimize_image_for_api(asset_bytes, "asset")
            if asset_optimized is None:
                log.warning("Asset '%s' failed optimization — skipping", asset_name)
                continue
            response_text = await call_anthropic_with_retry(
                prompt, [asset_optimized, screenshot_optimized]
            )
            result = extract_json_from_response(response_text)

            if not result.get("found", False):
                log.info("Asset '%s' not found on page", asset_name)
                continue

            locations = result.get("locations", [])
            log.info("Asset '%s' found at %d location(s)", asset_name, len(locations))

            for loc in locations:
                conf = loc.get("confidence", 0)
                if conf < 50:
                    continue
                all_locations.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "x": int(loc.get("x", 0)),
                    "y": int(loc.get("y", 0)),
                    "width": int(loc.get("width", 0)),
                    "height": int(loc.get("height", 0)),
                    "confidence": conf,
                    "reasoning": loc.get("reasoning", ""),
                })

        except Exception as e:
            log.error("Error localizing asset '%s': %s", asset_name, e)
            continue

    return all_locations


async def filter_image(
    image_url: str,
    asset_urls: Optional[List[str]] = None,
) -> ImageFilterResult:
    """
    Use Claude Haiku to quickly filter irrelevant images.

    When *asset_urls* are provided the filter becomes **asset-aware**: it
    sends all campaign assets alongside the discovered image and asks
    "could this be the same as ANY of these campaigns?".  This ensures
    images matching any asset pass through, not just the first one.
    """
    try:
        image_bytes = await download_image(image_url)
        image_bytes = optimize_image_for_api(image_bytes, "default")
        if image_bytes is None:
            raise ValueError("Discovered image failed optimization/validation")

        if asset_urls:
            asset_images = []
            for url in asset_urls:
                try:
                    ab = await download_image(url)
                    optimized = optimize_image_for_api(ab, "asset")
                    if optimized is not None:
                        asset_images.append(optimized)
                except Exception as e:
                    log.warning("Could not download asset for filter: %s", e)
            if asset_images:
                prompt = get_filter_prompt(asset_aware=True, asset_count=len(asset_images))
                images = asset_images + [image_bytes]
                cache_n = len(asset_images)
            else:
                prompt = get_filter_prompt(asset_aware=False)
                images = [image_bytes]
                cache_n = 0
        else:
            prompt = get_filter_prompt(asset_aware=False)
            images = [image_bytes]
            cache_n = 0

        response_text = await call_anthropic_with_retry(
            prompt, images, model=FILTER_MODEL, cache_prefix_images=cache_n,
        )
        result = extract_json_from_response(response_text)
        
        is_relevant = result.get("is_relevant", False)
        confidence = result.get("confidence", 0.5)
        
        if is_relevant and confidence < settings.filter_relevance_threshold:
            is_relevant = False
            result["reason"] = f"Below relevance threshold ({confidence:.2f} < {settings.filter_relevance_threshold})"
        
        return ImageFilterResult(
            is_relevant=is_relevant,
            confidence=confidence,
            reason=result.get("reason", "Unknown")
        )
        
    except Exception as e:
        log.error("Filter error: %s", e)
        return ImageFilterResult(
            is_relevant=True,
            confidence=0.5,
            reason=f"Filter error: {str(e)}"
        )


async def compare_images(
    source_image_url: str,
    target_image_url: str
) -> Dict[str, Any]:
    """
    Compare two images for similarity and modifications.
    Uses Claude Opus 4.5 for accurate comparison.
    """
    try:
        source_bytes = await download_image(source_image_url)
        target_bytes = await download_image(target_image_url)
        
        source_bytes = optimize_image_for_api(source_bytes, "asset")
        target_bytes = optimize_image_for_api(target_bytes, "default")
        
        if source_bytes is None or target_bytes is None:
            failed = "source" if source_bytes is None else "target"
            log.warning("Comparison skipped: %s image failed optimization", failed)
            return {
                "similarity_score": 0,
                "is_match": False,
                "match_type": "none",
                "modifications": [],
                "error": f"{failed} image failed validation"
            }
        
        prompt = get_comparison_prompt()
        
        response_text = await call_anthropic_with_retry(prompt, [source_bytes, target_bytes], model=ENSEMBLE_MODEL)
        return extract_json_from_response(response_text)
        
    except Exception as e:
        log.error("Comparison error: %s", e)
        return {
            "similarity_score": 0,
            "is_match": False,
            "match_type": "none",
            "modifications": [],
            "error": str(e)
        }


async def detect_asset_in_screenshot(
    asset_image_url: str,
    screenshot_url: str
) -> Dict[str, Any]:
    """
    Detect if a marketing asset appears within a webpage screenshot.

    Uses a tiling strategy when enabled: splits the screenshot into
    overlapping viewport-height tiles and checks each one individually.
    This preserves detail and prevents the asset from being shrunk to
    an unrecognisable size in a single downscaled image.

    Falls back to single-image detection when tiling is disabled.
    """
    try:
        log.info("Detecting asset in screenshot")

        asset_bytes = await download_image(asset_image_url)
        screenshot_bytes = await download_image(screenshot_url)
        asset_bytes = optimize_image_for_api(asset_bytes, "asset")

        if asset_bytes is None:
            log.warning("Asset image failed optimization — skipping detection")
            return {
                "asset_found": False, "similarity_score": 0,
                "is_match": False, "match_type": "none",
                "modifications": [], "error": "Asset image failed validation"
            }

        if settings.enable_tiling_fallback:
            return await _detect_asset_tiled(asset_bytes, screenshot_bytes)
        else:
            return await _detect_asset_single(asset_bytes, screenshot_bytes)

    except Exception as e:
        log.error("Error detecting asset: %s", e, exc_info=True)
        return {
            "asset_found": False,
            "similarity_score": 0,
            "is_match": False,
            "match_type": "none",
            "modifications": [],
            "error": str(e)
        }


async def _detect_asset_single(
    asset_bytes: bytes,
    screenshot_bytes: bytes
) -> Dict[str, Any]:
    """Original single-image detection (legacy path)."""
    screenshot_bytes = optimize_image_for_api(screenshot_bytes, "screenshot")
    if screenshot_bytes is None:
        return {
            "asset_found": False, "similarity_score": 0,
            "is_match": False, "match_type": "none",
            "modifications": [], "error": "Screenshot failed validation"
        }
    prompt = get_detection_prompt()

    response_text = await call_anthropic_with_retry(
        prompt, [asset_bytes, screenshot_bytes],
        model=ENSEMBLE_MODEL, cache_prefix_images=1,
    )
    result = extract_json_from_response(response_text)

    asset_found = result.get("asset_found", False)
    confidence = result.get("confidence", 0)
    actually_found = asset_found and confidence >= 55

    log.debug("Single-image detection: found=%s, confidence=%d", asset_found, confidence)

    return {
        "asset_found": actually_found,
        "similarity_score": confidence,
        "is_match": actually_found and confidence >= settings.screenshot_match_threshold,
        "match_type": _get_match_type_from_appearance(result.get("appearance", "none"), confidence),
        "modifications": result.get("modifications", []),
        "location": result.get("location", "unknown"),
        "analysis": result.get("reasoning", "")
    }


async def _detect_asset_tiled(
    asset_bytes: bytes,
    screenshot_bytes: bytes
) -> Dict[str, Any]:
    """
    Split the screenshot into overlapping tiles and check each one for the asset.

    Each tile is viewport-height so the asset (if present) occupies a meaningful
    portion of the image, making Claude's detection far more reliable.
    """
    try:
        img = Image.open(io.BytesIO(screenshot_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        width, height = img.size
        tile_h = settings.tile_height
        overlap = settings.tile_overlap

        tiles: List[bytes] = []
        y = 0
        while y < height:
            bottom = min(y + tile_h, height)
            tile = img.crop((0, y, width, bottom))
            buf = io.BytesIO()
            tile.save(buf, format='JPEG', quality=90)
            tiles.append(buf.getvalue())
            y += tile_h - overlap
            if bottom == height:
                break

        log.debug("Tiling: %d tiles from %dx%d screenshot", len(tiles), width, height)

        best: Dict[str, Any] = {
            "asset_found": False,
            "similarity_score": 0,
            "confidence": 0,
        }

        prompt = get_detection_prompt()

        for idx, tile_bytes in enumerate(tiles):
            tile_optimized = optimize_image_for_api(tile_bytes, "screenshot")
            if tile_optimized is None:
                log.debug("Tile %d/%d: skipped (optimization failed)", idx + 1, len(tiles))
                continue
            response_text = await call_anthropic_with_retry(
                prompt, [asset_bytes, tile_optimized],
                model=ENSEMBLE_MODEL, cache_prefix_images=1,
            )
            result = extract_json_from_response(response_text)

            found = result.get("asset_found", False)
            conf = result.get("confidence", 0)
            log.debug("Tile %d/%d: found=%s, confidence=%d", idx + 1, len(tiles), found, conf)

            if conf > best["confidence"]:
                best = result
                best["tile_index"] = idx

            if found and conf >= 55:
                log.debug("Asset found in tile %d — stopping search", idx + 1)
                break

        asset_found = best.get("asset_found", False)
        confidence = best.get("confidence", 0)
        actually_found = asset_found and confidence >= 55

        return {
            "asset_found": actually_found,
            "similarity_score": confidence,
            "is_match": actually_found and confidence >= settings.screenshot_match_threshold,
            "match_type": _get_match_type_from_appearance(best.get("appearance", "none"), confidence),
            "modifications": best.get("modifications", []),
            "location": best.get("location", "unknown"),
            "analysis": best.get("reasoning", ""),
            "tiles_checked": len(tiles),
            "matched_tile": best.get("tile_index"),
        }

    except Exception as e:
        log.warning("Tiling failed, falling back to single-image: %s", e)
        return await _detect_asset_single(asset_bytes, screenshot_bytes)


async def verify_borderline_match(
    asset_url: str,
    discovered_url: str,
    initial_score: int
) -> Dict[str, Any]:
    """
    Second-pass verification for borderline matches using boolean gates.
    Uses Claude Opus 4.5 for agentic verification.
    """
    try:
        log.info("Verifying borderline match (initial score: %d)", initial_score)
        
        asset_bytes = await download_image(asset_url)
        discovered_bytes = await download_image(discovered_url)
        
        asset_bytes = optimize_image_for_api(asset_bytes, "asset")
        discovered_bytes = optimize_image_for_api(discovered_bytes, "default")
        
        if asset_bytes is None or discovered_bytes is None:
            log.warning("Verification skipped: image failed optimization")
            return {"verified_score": initial_score, "is_match": False, "error": "Image failed validation"}
        
        prompt = get_verification_prompt()

        response_text = await call_anthropic_with_retry(
            prompt, [asset_bytes, discovered_bytes],
            model=ENSEMBLE_MODEL, cache_prefix_images=1,
        )
        result = extract_json_from_response(response_text)
        
        gates_passed = result.get("gates_passed", 0)
        gate_brand = result.get("gate_brand", False)
        gate_product = result.get("gate_product", False)

        # Require 4 of 5 gates to pass (was 3). With only 3 gates the
        # verifier was rubber-stamping CV-localized crops on the basis of
        # brand + product + design (all three are easy to fake on a
        # roughly asset-sized crop of webpage chrome) and publishing a
        # mechanical 60-point match. Lifting the bar to 4 means the
        # verifier needs at least one of message / offer to corroborate,
        # which is exactly the signal that distinguishes "this is the
        # campaign creative" from "this is some other dealer-branded
        # rectangle on the same site".
        is_match = (
            result.get("is_match", False)
            and gate_brand
            and gate_product
            and gates_passed >= 4
        )

        # Compress the gate→score mapping so 4 gates lands in PARTIAL
        # (65) rather than STRONG (80), and 5 gates lands in STRONG (80)
        # rather than EXACT (100). The previous gates_passed * 20 curve
        # mechanically minted 80% confidence the moment Claude said
        # brand+product+message+design — exactly the failure mode the
        # operator saw on a `SUPPORT  ABOUT` nav-bar crop. The new curve:
        #   3 gates -> 50 (just below regular threshold; verifier's
        #              `is_match` boolean now also requires 4, so 3 is
        #              effectively rejected — but if a future caller
        #              relies on verified_score directly we still report
        #              it honestly).
        #   4 gates -> 65 (PARTIAL match)
        #   5 gates -> 80 (STRONG match)
        _GATE_SCORE_CURVE = {0: 0, 1: 0, 2: 25, 3: 50, 4: 65, 5: 80}
        verified_score = _GATE_SCORE_CURVE.get(int(gates_passed), 0)

        log.debug("Verification complete: gates_passed=%d, is_match=%s", gates_passed, is_match)
        log.debug("Gates: brand=%s, product=%s, message=%s, offer=%s, design=%s", gate_brand, gate_product, result.get('gate_message'), result.get('gate_offer'), result.get('gate_design'))

        return {
            "verified_score": verified_score,
            "is_match": is_match,
            "gates": {
                "brand": gate_brand,
                "product": gate_product,
                "message": result.get("gate_message", False),
                "offer": result.get("gate_offer", False),
                "design": result.get("gate_design", False),
            },
            "gates_passed": gates_passed,
            "verdict": result.get("verdict", ""),
        }
        
    except Exception as e:
        log.error("Verification error: %s", e)
        # STRICT: On error, default to NO match
        return {
            "verified_score": initial_score,
            "is_match": False,
            "error": str(e)
        }


# ---------------------------------------------------------------------------
# Phase-9 follow-up #3 (2026-05-11): full-page screenshot containment
# fallback. See backend/app/services/scan_runners.py:_process_one_page for
# the call site and ``settings.enable_containment_fallback`` for the on/off
# switch. Lives here next to the other Opus-call helpers so prompt drift
# stays in one file.
# ---------------------------------------------------------------------------

_CONTAINMENT_PROMPT = """You are a CONTAINMENT MATCHER for a dealer marketing compliance system.

IMAGE 1 (FIRST IMAGE): An APPROVED CAMPAIGN CREATIVE. This is typically a
SCREENSHOT of a hero banner / ad slot / rendered marketing surface as it
should appear on dealer websites. The asset itself may include surrounding
chrome (yellow background panels, headlines like "POWER & PERFORMANCE",
call-to-action buttons like "PRODUCTS", spec callouts, etc.) — those
elements are PART of the campaign creative, not noise.

IMAGE 2 (SECOND IMAGE): A FULL-PAGE SCREENSHOT of a single dealer webpage,
top-to-bottom. The campaign creative may appear ANYWHERE within this
screenshot:
* at any vertical position (above the fold, mid-page, footer)
* at any size (full-width hero, half-width promo card, sidebar tile)
* possibly cropped at the page edge
* possibly composed from CSS background colour + an isolated equipment
  PNG + HTML text rather than a single image file (the rendered result
  still counts as a containment hit — what matters is what a human visitor
  to the page would see)

YOUR TASK: Decide whether the campaign creative shown in IMAGE 1 actually
appears, in recognizable form, somewhere within IMAGE 2.

Say is_match=true ONLY when ALL of the following are true:
* The same headline text or tagline is visible (e.g. "POWER & PERFORMANCE",
  the specific promo wording from IMAGE 1)
* The same featured product / equipment is in the same prominent position
  (same model, same pose if recognizable)
* The same call-to-action or offer wording is visible (e.g. "PRODUCTS",
  "SHOP NOW", a specific price)
* The overall colour scheme and layout match (e.g. yellow-dominant hero
  with the equipment on the left and CTA on the right)

Reject (is_match=false) when ANY of the following holds:
* IMAGE 1 is a generic logo or product photo that any dealer site could
  carry without running this campaign
* The page only shares the brand colour or font but lacks the specific
  creative content (no matching headline, no matching offer)
* The same product appears but with a different headline / different offer
  / different CTA — that's a different campaign, not this one
* The creative is "kind of there" — strong recognition or nothing

Output ONLY a single JSON object with these keys, no markdown, no prose:
{
  "is_match": true|false,
  "confidence_score": 0-100,
  "location_hint": "header|hero|mid_page|sidebar|footer|unknown",
  "rationale": "<one sentence describing what you saw or what was missing>"
}
"""


async def containment_match_full_page(
    full_page_screenshot_url: str,
    campaign_assets: List[Dict[str, Any]],
    threshold: int,
    *,
    page_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fallback matcher for pages where per-image matching produced 0 hits.

    Sends each campaign asset alongside the page's full-page screenshot to
    Opus with a containment prompt ("does the asset appear anywhere in this
    screenshot?"). Returns a list of hits — one per asset that scored at or
    above ``threshold`` — in the shape:

        {
            "asset": <campaign_asset row>,
            "confidence_score": int,
            "rationale": str,
            "location_hint": str,
            "raw": <full parsed Opus response>,
        }

    Returns ``[]`` when the screenshot can't be downloaded, the asset list
    is empty, or no asset cleared the threshold. Per-asset failures are
    swallowed and logged so one bad asset can't poison the whole fallback.

    Cost: one Opus call per (asset, page) pair. The wiring in
    ``_process_one_page`` only fires this when the per-image stage returned
    0 matches AND the campaign has at most
    ``settings.containment_fallback_max_assets`` assets, so the worst-case
    cost stays bounded.
    """
    if not full_page_screenshot_url or not campaign_assets:
        return []

    try:
        screenshot_bytes = await download_image(full_page_screenshot_url)
    except Exception as e:
        log.warning(
            "Containment fallback: could not download page screenshot %s — %s",
            full_page_screenshot_url[:80], e,
        )
        return []

    screenshot_optimized = optimize_image_for_api(screenshot_bytes, "default")
    if screenshot_optimized is None:
        log.warning(
            "Containment fallback: page screenshot failed optimization (page=%s)",
            page_url,
        )
        return []

    async def _check_one_asset(asset: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        asset_url = asset.get("file_url")
        if not asset_url:
            return None
        try:
            asset_bytes = await download_image(asset_url)
        except Exception as e:
            log.warning(
                "Containment fallback: could not download asset %s — %s",
                asset.get("name") or asset.get("id"), e,
            )
            return None
        asset_optimized = optimize_image_for_api(asset_bytes, "asset")
        if asset_optimized is None:
            return None

        try:
            response_text = await call_anthropic_with_retry(
                _CONTAINMENT_PROMPT,
                [asset_optimized, screenshot_optimized],
                model=ENSEMBLE_MODEL,
                # Cache the asset + prompt prefix; the screenshot varies
                # per page so it's the suffix and not cached. With many
                # pages-with-0-matches in the same scan this saves real
                # tokens.
                cache_prefix_images=1,
            )
        except Exception as e:
            log.warning(
                "Containment fallback: Opus call failed for asset %s on page %s — %s",
                asset.get("name") or asset.get("id"), page_url, e,
            )
            return None

        try:
            parsed = extract_json_from_response(response_text)
        except Exception as e:
            log.warning(
                "Containment fallback: Opus returned non-JSON for asset %s — %s",
                asset.get("name") or asset.get("id"), e,
            )
            return None

        is_match = bool(parsed.get("is_match"))
        try:
            confidence = int(parsed.get("confidence_score") or 0)
        except (TypeError, ValueError):
            confidence = 0

        log.info(
            "Containment fallback: asset=%s page=%s is_match=%s confidence=%d location=%s",
            asset.get("name") or asset.get("id"),
            page_url, is_match, confidence,
            parsed.get("location_hint"),
        )

        if not is_match or confidence < threshold:
            return None

        return {
            "asset": asset,
            "confidence_score": confidence,
            "rationale": parsed.get("rationale", ""),
            "location_hint": parsed.get("location_hint", "unknown"),
            "raw": parsed,
        }

    # Fire all asset checks in parallel — each call already shares the
    # cached asset prefix with itself across pages, but within a single
    # page the assets are independent of each other and there's no reason
    # to serialise them.
    results = await asyncio.gather(
        *[_check_one_asset(a) for a in campaign_assets],
        return_exceptions=True,
    )

    hits: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, BaseException):
            log.warning("Containment fallback: per-asset task crashed — %s", r)
            continue
        if r:
            hits.append(r)
    return hits


async def analyze_compliance(
    discovered_image_url: str,
    original_asset_url: str,
    brand_rules: Dict[str, Any],
    campaign_end_date: Optional[str] = None
) -> ComplianceCheckResult:
    """
    Deep compliance analysis comparing discovered image to original asset.
    Uses Claude Opus 4.5 for accurate compliance checks.
    """
    try:
        log.info("Analyzing compliance with Claude Opus 4.5")
        
        discovered_bytes = await download_image(discovered_image_url)
        asset_bytes = await download_image(original_asset_url)
        
        discovered_bytes = optimize_image_for_api(discovered_bytes, "default")
        asset_bytes = optimize_image_for_api(asset_bytes, "asset")
        
        if discovered_bytes is None or asset_bytes is None:
            log.warning("Compliance skipped: image failed optimization")
            return ComplianceCheckResult(
                is_compliant=True,
                issues=[],
                brand_elements={},
                zombie_ad=False,
                analysis_summary="Skipped — image failed validation"
            )
        
        # Build rules text
        rules_text = ""
        if brand_rules.get("required_elements"):
            rules_text += f"Required elements that MUST be present: {', '.join(brand_rules['required_elements'])}\n"
        if brand_rules.get("forbidden_elements"):
            rules_text += f"Forbidden elements that must NOT appear: {', '.join(brand_rules['forbidden_elements'])}\n"
        if brand_rules.get("brand_colors"):
            rules_text += f"Brand colors: {', '.join(brand_rules['brand_colors'])}\n"
        
        zombie_check = ""
        if campaign_end_date:
            zombie_check = f"""
ZOMBIE AD CHECK:
- Campaign end date: {campaign_end_date}
- If this campaign has expired but the asset is still displayed, flag as zombie_ad: true
- Look for date-specific text indicating the promotion has ended
"""
        
        prompt = get_compliance_prompt(rules_text, zombie_check)

        response_text = await call_anthropic_with_retry(
            prompt, [asset_bytes, discovered_bytes],
            cache_prefix_images=1,
        )
        result = extract_json_from_response(response_text)
        
        log.info("Compliance result: is_compliant=%s", result.get('is_compliant'))
        
        return ComplianceCheckResult(
            is_compliant=result.get("is_compliant", True),
            issues=result.get("issues", []),
            brand_elements=result.get("brand_elements", {}),
            asset_visible=result.get("asset_visible"),
            zombie_ad=result.get("zombie_ad", False),
            zombie_days=None,
            analysis_summary=result.get("analysis_summary", "")
        )
        
    except Exception as e:
        log.error("Compliance analysis error: %s", e, exc_info=True)
        # STRICT: Default to NOT compliant on errors - requires manual review
        return ComplianceCheckResult(
            is_compliant=False,
            issues=[{"type": "analysis_error", "description": str(e), "severity": "high"}],
            brand_elements={},
            analysis_summary=f"Analysis failed - requires manual review: {str(e)}"
        )


async def ensemble_match(
    asset_url: str,
    discovered_url: str,
    is_screenshot: bool = False
) -> Dict[str, Any]:
    """
    Combine multiple matching strategies for more robust results.
    
    Uses:
    - Visual similarity (Claude comparison)
    - Asset detection (for screenshots)
    - Perceptual hashing (fast pre-filter)
    """
    log.info("Starting ensemble match")
    
    # Run methods in parallel
    if is_screenshot:
        # For screenshots, only run detection — perceptual hashing the whole
        # page against a small asset is meaningless and drags down scores.
        detection_result = await detect_asset_in_screenshot(asset_url, discovered_url)
        if isinstance(detection_result, Exception):
            detection_result = {"similarity_score": 0, "asset_found": False}
        hash_result = {"similarity_score": 0}
        visual_result = {"similarity_score": 0}

    else:
        results = await asyncio.gather(
            compare_images(asset_url, discovered_url),
            compare_with_hash(asset_url, discovered_url),
            return_exceptions=True
        )
        visual_result = results[0] if not isinstance(results[0], Exception) else {"similarity_score": 0}
        hash_result = results[1] if not isinstance(results[1], Exception) else {"similarity_score": 0}
        detection_result = {"similarity_score": 0, "asset_found": False}
    
    # Extract scores
    visual_score = visual_result.get("similarity_score", 0)
    detection_score = detection_result.get("similarity_score", 0)
    hash_score = hash_result.get("similarity_score", 0)
    asset_found = detection_result.get("asset_found", False)
    
    # Weighted ensemble
    if is_screenshot:
        # For screenshots, detection carries 100% weight — hash is skipped
        final_score = detection_score * 1.0
    else:
        # For regular images, only visual + hash are available (detection is
        # not run).  Normalise their weights so they sum to 1.0.
        vw = settings.ensemble_visual_weight
        hw = settings.ensemble_hash_weight
        total = vw + hw or 1.0
        final_score = (
            visual_score * (vw / total) +
            hash_score * (hw / total)
        )
    
    # Agreement bonus — only count methods that were actually run
    active_scores = [visual_score, hash_score] if not is_screenshot else [detection_score]
    agreement_count = sum(1 for s in active_scores if s > 60)
    if agreement_count >= 2:
        final_score = min(100, final_score + settings.ensemble_agreement_bonus)
    
    # Hash exact match bonus - ONLY for true exact matches (very strict)
    if hash_result.get("is_exact"):
        # Only boost if hash shows near-identical images
        final_score = max(final_score, 85)

    # Hash-veto for non-screenshot comparisons.
    #
    # Perceptual hashing is the most truthful signal we compute — it
    # reflects pixel-level resemblance and cannot hallucinate. When the
    # visual scorer claims a strong match (≥ 75) but the hash similarity
    # disagrees by a wide margin (≤ 55), the visual model is almost
    # certainly hallucinating on a CV-localized crop or a coincidentally
    # asset-shaped piece of UI chrome (the "STRONG MATCH on a nav bar"
    # failure mode). Cap the final score at hash + 10 in that case so a
    # real but compressed render still scores well, but a hallucinated
    # match cannot publish above the regular_image_match_threshold.
    #
    # Skipped for screenshots because the hash path isn't run there —
    # whole-page hashes against a small banner are meaningless and the
    # detection path carries its own scoring discipline.
    if (
        not is_screenshot
        and visual_score >= 75
        and hash_score <= 55
    ):
        capped = min(final_score, hash_score + 10)
        if capped < final_score:
            log.info(
                "Hash-veto: visual=%d but hash=%d — capping final %d -> %d "
                "(visual likely hallucinated; trust the hash)",
                visual_score, hash_score, final_score, capped,
            )
        final_score = capped

    # Determine match type based on STRICT thresholds
    if final_score >= settings.exact_match_threshold:
        match_type = "exact"
    elif final_score >= settings.strong_match_threshold:
        match_type = "strong"
    elif final_score >= settings.partial_match_threshold:
        match_type = "partial"
    elif final_score >= settings.weak_match_threshold:
        match_type = "weak"
    else:
        match_type = "none"
    
    # STRICT: Score alone decides match — never let asset_found override a low score
    threshold = settings.screenshot_match_threshold if is_screenshot else settings.regular_image_match_threshold
    is_match = final_score >= threshold
    
    log.debug("Ensemble scores - Visual: %d, Detection: %d, Hash: %d", visual_score, detection_score, hash_score)
    log.debug("Ensemble final: %.1f, Match: %s, Type: %s", final_score, is_match, match_type)
    
    return {
        "similarity_score": round(final_score),
        "is_match": is_match,
        "asset_found": asset_found,
        "match_type": match_type,
        "method_scores": {
            "visual": visual_score,
            "detection": detection_score,
            "hash": hash_score
        },
        "modifications": visual_result.get("modifications", []) or detection_result.get("modifications", []),
        "analysis": visual_result.get("analysis", "") or detection_result.get("analysis", "")
    }


async def calibrate_confidence(
    raw_score: int,
    source_type: str,
    channel: str
) -> int:
    """
    Adjust confidence based on source type and channel.
    Uses adaptive calibration from feedback if available, otherwise defaults.
    """
    try:
        factor = await get_calibration_factor_from_feedback(source_type, channel)
    except Exception as e:
        log.warning("Error getting adaptive calibration: %s", e)
        factor = get_calibration_factor(source_type, channel)
        
    calibrated = int(raw_score * factor)
    return min(100, max(0, calibrated))


def _get_match_type_from_appearance(appearance: str, confidence: int) -> str:
    """Convert appearance type and confidence to match type."""
    if appearance == "exact" and confidence >= settings.exact_match_threshold:
        return "exact"
    elif appearance in ["exact", "resized"] and confidence >= settings.strong_match_threshold:
        return "strong"
    elif appearance in ["exact", "resized", "cropped", "modified"] and confidence >= settings.partial_match_threshold:
        return "partial"
    elif confidence >= settings.weak_match_threshold:
        return "weak"
    return "none"


def _get_match_type_from_score(score: int) -> str:
    """Get match type from score using configured thresholds."""
    if score >= settings.exact_match_threshold:
        return "exact"
    elif score >= settings.strong_match_threshold:
        return "strong"
    elif score >= settings.partial_match_threshold:
        return "partial"
    elif score >= settings.weak_match_threshold:
        return "weak"
    return "none"


async def batch_filter_images(image_urls: List[str]) -> List[ImageFilterResult]:
    """Filter multiple images in optimized batches."""
    results = []
    batch_size = settings.batch_size
    
    for i in range(0, len(image_urls), batch_size):
        batch = image_urls[i:i + batch_size]
        
        # Process batch in parallel
        batch_results = await asyncio.gather(
            *[filter_image(url) for url in batch],
            return_exceptions=True
        )
        
        for j, result in enumerate(batch_results):
            if isinstance(result, Exception):
                results.append(ImageFilterResult(
                    is_relevant=True,
                    confidence=0.5,
                    reason=f"Filter error: {str(result)}"
                ))
            else:
                results.append(result)
        
        # Rate limiting between batches
        if i + batch_size < len(image_urls):
            await asyncio.sleep(settings.batch_delay)
    
    return results


async def _passes_hash_prefilter(
    image_bytes: bytes,
    asset_hashes_cache: List[Dict[str, Any]],
    strict: bool = False,
) -> bool:
    """
    Stage 1 pre-filter: check if the image has ANY perceptual hash
    resemblance to at least one campaign asset.

    Returns True if the image should continue to the next stage.
    This is free and instant (~0.5ms per comparison).

    ``strict`` tightens the threshold for inputs that have already been
    pre-selected for asset-likeness by an upstream step — currently
    used for ``cv_localized_from_screenshot`` crops, where the loose
    default would let nearly anything through (the crop has already
    been geometrically biased to look asset-shaped, so the hash check
    needs to do more discriminating work, not less).
    """
    img_hashes = await compute_image_hashes(image_bytes)
    if img_hashes is None:
        return True  # can't compute → don't discard

    threshold = (
        settings.hash_prefilter_strict_max_diff
        if strict
        else settings.hash_prefilter_max_diff
    )

    for asset_h in asset_hashes_cache:
        diffs = [
            img_hashes["phash"] - asset_h["phash"],
            img_hashes["dhash"] - asset_h["dhash"],
            img_hashes["whash"] - asset_h["whash"],
            img_hashes["average_hash"] - asset_h["average_hash"],
        ]
        avg_diff = sum(diffs) / 4
        if avg_diff <= threshold:
            return True

    return False


async def _passes_clip_prefilter(
    image_bytes: bytes,
    asset_embeddings: list,
    strict: bool = False,
) -> bool:
    """
    Stage 2 pre-filter: check CLIP semantic similarity between the
    discovered image and campaign assets.

    Returns True if the image should continue to Claude.
    Runs locally on CPU (~20ms per image) in a thread executor.

    ``strict`` lifts the cosine threshold for CV-localized crops, which
    have already been geometrically pre-selected and so should clear a
    higher bar than a generic extracted image to justify the Claude
    spend that follows.
    """
    if not asset_embeddings:
        return True

    img_emb = await embedding_service.compute_embedding_async(image_bytes)
    if img_emb is None:
        return True

    threshold = (
        settings.clip_similarity_strict_threshold
        if strict
        else settings.clip_similarity_threshold
    )

    best_sim = embedding_service.best_asset_similarity(img_emb, asset_embeddings)
    passes = best_sim >= threshold
    log.debug("CLIP best similarity: %.3f (threshold %.2f, strict=%s) → %s",
              best_sim, threshold, strict, "PASS" if passes else "SKIP")
    return passes


async def _precompute_asset_hashes(
    campaign_assets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Download each campaign asset and compute perceptual hashes once."""
    results = []
    for asset in campaign_assets:
        try:
            asset_bytes = await download_image(asset["file_url"])
            hashes = await compute_image_hashes(asset_bytes)
            if hashes:
                results.append(hashes)
        except Exception as e:
            log.warning("Could not hash asset %s: %s", asset.get("name", asset["id"]), e)
    return results


async def _precompute_asset_embeddings(
    campaign_assets: List[Dict[str, Any]],
) -> list:
    """Download each campaign asset and compute CLIP embeddings once.

    Uses the async embedding path so the event loop stays responsive
    during the (potentially heavy) model load + encode.
    """
    bytes_list = []
    for asset in campaign_assets:
        try:
            bytes_list.append(await download_image(asset["file_url"]))
        except Exception as e:
            log.warning("Could not download asset %s for embedding: %s",
                        asset.get("name", asset["id"]), e)
    if not bytes_list:
        return []
    embeddings = await embedding_service.compute_embeddings_batch_async(bytes_list)
    return [e for e in embeddings if e is not None]


async def process_discovered_image(
    discovered_image_id: str,
    image_url: str,
    campaign_assets: List[Dict[str, Any]],
    brand_rules: Dict[str, Any],
    source_type: Optional[str] = None,
    channel: Optional[str] = None,
    asset_hashes_cache: Optional[List[Dict[str, Any]]] = None,
    asset_embeddings_cache: Optional[list] = None,
    extraction_method: Optional[str] = None,
) -> tuple:
    """
    Full processing pipeline for a discovered image.

    Returns (result_dict, stage) where stage indicates the last pipeline
    stage reached.  When no match is found result_dict is None.

    Stages: "download_failed", "hash_rejected", "clip_rejected",
            "filter_rejected", "below_threshold", "verification_rejected",
            "asset_invisible_rejected", "matched"
    """
    log.info("Processing image: %s", image_url[:80])
    log.debug("Source type: %s, extraction_method: %s", source_type or "not specified", extraction_method or "n/a")
    
    # Determine if this is a screenshot — ONLY trust the explicit source_type flag.
    # URL-based checks matched the Supabase bucket name ("scan-screenshots")
    # and caused every stored image to bypass all pre-filters.
    is_screenshot = source_type == "page_screenshot"

    # CV-localized crops have already been geometrically pre-selected
    # for asset-likeness by OpenCV template matching, so the local
    # pre-filters need to do *more* discriminating work, not less. Use
    # the strict thresholds in that case.
    is_cv_localized = extraction_method == "cv_localized_from_screenshot"

    # --- Stage 1 & 2: local pre-filters (skip for screenshots) ---
    if not is_screenshot:
        try:
            image_bytes_for_prefilter = await download_image(image_url)
        except Exception as e:
            log.warning("Could not download image for pre-filter: %s", e)
            return None, "download_failed"

        # Stage 1: Hash pre-filter
        if asset_hashes_cache:
            passes_hash = await _passes_hash_prefilter(
                image_bytes_for_prefilter, asset_hashes_cache,
                strict=is_cv_localized,
            )
            if not passes_hash:
                log.debug("REJECTED by hash pre-filter (no asset resemblance, strict=%s)", is_cv_localized)
                return None, "hash_rejected"

        # Stage 2: CLIP embedding pre-filter
        if asset_embeddings_cache:
            passes_clip = await _passes_clip_prefilter(
                image_bytes_for_prefilter, asset_embeddings_cache,
                strict=is_cv_localized,
            )
            if not passes_clip:
                log.debug("REJECTED by CLIP pre-filter (low semantic similarity, strict=%s)", is_cv_localized)
                return None, "clip_rejected"
    
    # Get adaptive threshold for this source/channel
    adaptive_threshold, threshold_meta = await get_adaptive_threshold(
        source_type or ("page_screenshot" if is_screenshot else "website_banner"),
        channel or "website"
    )
    
    log.debug("Using adaptive threshold: %d (Confidence: %s)", adaptive_threshold, threshold_meta['confidence'])
    
    log.debug("Image type: %s", "SCREENSHOT" if is_screenshot else "regular image")
    
    # Stage 3: Claude Haiku relevance filter (skip for screenshots)
    if is_screenshot:
        log.debug("Stage 3: skipping filter for screenshot")
        filter_result = ImageFilterResult(
            is_relevant=True,
            confidence=1.0,
            reason="Screenshot - checking for contained assets"
        )
    else:
        log.debug("Stage 3: Haiku relevance filter (asset-aware)")
        asset_urls = [a["file_url"] for a in campaign_assets if a.get("file_url")] or None
        filter_result = await filter_image(image_url, asset_urls=asset_urls)
        log.debug("Filter: is_relevant=%s, confidence=%.2f", filter_result.is_relevant, filter_result.confidence)
        
        if not filter_result.is_relevant:
            log.debug("Image filtered out as not relevant")
            return None, "filter_rejected"
    
    # Stage 4: Ensemble matching against each asset (Claude Opus)
    #
    # Phase-7 change: the per-asset ensemble used to be a serial `for asset
    # in campaign_assets:` loop. With N campaign assets every borderline
    # image was paying N × Opus round-trips back-to-back — for a dealer
    # with 10 pages, 10 images per page, 5 assets, that's 500 sequential
    # Opus calls (~25 minutes per dealer just on this loop). asyncio.gather
    # fires them in parallel; each `ensemble_match` already internally
    # parallelises its sub-calls (visual + hash) so this is purely a
    # latency win, no extra tokens or different inputs. Same prompts,
    # same model, same scoring — only the await order changes.
    log.debug("Stage 4: ensemble matching against %d assets (parallel)", len(campaign_assets))
    comparisons = await asyncio.gather(
        *[
            ensemble_match(
                asset["file_url"],
                image_url,
                is_screenshot=is_screenshot,
            )
            for asset in campaign_assets
        ],
        return_exceptions=True,
    )

    best_match = None
    best_score = 0
    for asset, comparison in zip(campaign_assets, comparisons):
        if isinstance(comparison, BaseException):
            log.warning(
                "Ensemble match raised for asset %s: %s",
                asset.get("name", asset.get("id")), comparison,
            )
            continue
        score = comparison.get("similarity_score", 0)
        log.debug(
            "Asset %s ensemble score: %d",
            asset.get("name", asset.get("id")), score,
        )
        if score > best_score:
            best_score = score
            best_match = {"asset": asset, "comparison": comparison}
    
    threshold = adaptive_threshold
    
    if not best_match:
        log.info("No match found")
        return None, "below_threshold"
    
    if best_score < threshold:
        log.debug("Best score %d below threshold %d — rejected", best_score, threshold)
        return None, "below_threshold"
    
    # Verify borderline matches
    needs_verification = await should_verify_match(
        best_score,
        source_type or ("page_screenshot" if is_screenshot else "website_banner"),
        channel or "website"
    )
    
    if needs_verification:
        log.debug("Verifying borderline match (score: %d)", best_score)
        verification = await verify_borderline_match(
            best_match["asset"]["file_url"],
            image_url,
            best_score
        )
        
        if not verification.get("is_match", False):
            log.debug("Verification rejected match")
            return None, "verification_rejected"
        
        best_score = verification.get("verified_score", best_score)
        log.debug("Verification passed with score: %d", best_score)
    
    # Apply confidence calibration
    calibrated_score = await calibrate_confidence(best_score, source_type or "unknown", channel or "unknown")
    log.debug("Calibrated score: %d -> %d", best_score, calibrated_score)
    
    # Compliance analysis
    log.debug("Compliance analysis")
    compliance = await analyze_compliance(
        image_url,
        best_match["asset"]["file_url"],
        brand_rules,
        best_match["asset"].get("campaign_end_date")
    )

    # Final safety net: asset_visible gate.
    #
    # The compliance prompt explicitly asks Claude to set ``asset_visible:
    # false`` when the campaign creative is not actually present in the
    # discovered image. Until now we were reading that flag and ignoring
    # it, which let a hallucinated visual score publish a STRONG MATCH on
    # a CV-localized crop of unrelated webpage chrome (nav bars, footer
    # strips, etc.). If Claude — looking at the same crop the visual
    # matcher rated highly — says the asset is NOT visible, that is a
    # higher-signal contradiction than the visual score is worth, and we
    # discard the match.
    #
    # ``asset_visible`` is optional: a None value means the model didn't
    # populate the field (or the call failed) and we fall through to the
    # existing publishing path. Only an explicit ``False`` vetoes.
    if compliance.asset_visible is False:
        log.info(
            "Match rejected by asset_visible gate — Claude says creative "
            "is NOT visible in discovered image (visual score=%d, "
            "asset=%s, image_id=%s)",
            calibrated_score,
            best_match["asset"].get("name", best_match["asset"].get("id")),
            discovered_image_id,
        )
        return None, "asset_invisible_rejected"

    match_type = _get_match_type_from_score(calibrated_score)
    
    log.info("Final: %s match, score %d, compliant=%s", match_type, calibrated_score, compliance.is_compliant)
    
    return {
        "discovered_image_id": discovered_image_id,
        "asset_id": best_match["asset"]["id"],
        "confidence_score": calibrated_score,
        "match_type": match_type,
        "is_modified": len(best_match["comparison"].get("modifications", [])) > 0,
        "modifications": best_match["comparison"].get("modifications", []),
        "compliance_status": "compliant" if compliance.is_compliant else "violation",
        "compliance_issues": compliance.issues,
        "ai_analysis": {
            "filter": {
                "is_relevant": filter_result.is_relevant,
                "confidence": filter_result.confidence
            },
            "comparison": best_match["comparison"],
            "compliance": {
                "is_compliant": compliance.is_compliant,
                "asset_visible": compliance.asset_visible,
                "brand_elements": compliance.brand_elements,
                "zombie_ad": compliance.zombie_ad,
                "summary": compliance.analysis_summary
            },
            "ensemble_scores": best_match["comparison"].get("method_scores", {}),
            "calibration_applied": best_score != calibrated_score
        }
    }, "matched"


async def process_images_batch(
    images: List[Dict],
    campaign_assets: List[Dict],
    brand_rules: Dict[str, Any]
) -> List[Optional[Dict[str, Any]]]:
    """
    Process multiple images in optimized parallel batches.

    Pre-computes asset hashes and CLIP embeddings once, then reuses
    them for every discovered image to avoid redundant downloads.
    """
    # Pre-compute caches once for all images
    log.info("Pre-computing asset hashes and embeddings for %d assets", len(campaign_assets))
    asset_hashes = await _precompute_asset_hashes(campaign_assets)
    asset_embeddings = await _precompute_asset_embeddings(campaign_assets)
    log.info("Cached %d hash sets, %d CLIP embeddings", len(asset_hashes), len(asset_embeddings))

    results = []
    batch_size = settings.batch_size
    
    for i in range(0, len(images), batch_size):
        batch = images[i:i + batch_size]
        
        batch_results = await asyncio.gather(
            *[
                process_discovered_image(
                    img["id"],
                    img["image_url"],
                    campaign_assets,
                    brand_rules,
                    source_type=img.get("source_type"),
                    channel=img.get("channel"),
                    asset_hashes_cache=asset_hashes,
                    asset_embeddings_cache=asset_embeddings,
                )
                for img in batch
            ],
            return_exceptions=True
        )
        
        for j, result in enumerate(batch_results):
            if isinstance(result, Exception):
                log.error("Error processing image in batch: %s", result)
                results.append((None, "error"))
            else:
                results.append(result)
        
        if i + batch_size < len(images):
            await asyncio.sleep(settings.batch_delay)
    
    return results


