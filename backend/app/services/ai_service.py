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

# Configure Anthropic client
anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
CLAUDE_MODEL = "claude-opus-4-20250514"
ENSEMBLE_MODEL = "claude-opus-4-20250514"
FILTER_MODEL = settings.filter_model


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


async def download_image(url: str) -> bytes:
    """Download image from URL with caching, timeout, and error handling.

    Results are cached in-memory so the same URL is only fetched once per
    server lifetime (or until the LRU evicts it).
    """
    if url.startswith("data:"):
        try:
            header, encoded = url.split(",", 1)
            return base64.b64decode(encoded)
        except Exception as e:
            log.error("Error decoding base64 data URL: %s", e)
            raise

    cached = _image_cache.get(url)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            _image_cache.put(url, response.content)
            return response.content
        except httpx.HTTPStatusError as e:
            log.error("HTTP error downloading image: %d - %s", e.response.status_code, url[:100])
            raise
        except httpx.TimeoutException:
            log.error("Timeout downloading image: %s", url[:100])
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
) -> bytes:
    """
    Type-specific image optimization for better API performance and accuracy.
    
    Args:
        image_bytes: Raw image bytes
        analysis_type: One of 'screenshot', 'asset', 'default'
    
    Returns:
        Optimized image bytes
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
        log.warning("Image optimization failed: %s, using original", e)
        return image_bytes


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
) -> str:
    """
    Call Anthropic Claude API with retry logic and image support.
    
    Args:
        prompt: Text prompt for the model
        images: List of image bytes to include
        max_retries: Number of retry attempts
        model: Override model (defaults to CLAUDE_MODEL / Opus)
    
    Returns:
        Response text from Claude
    """
    if max_retries is None:
        max_retries = settings.max_retries
    
    use_model = model or CLAUDE_MODEL
    last_error = None
    
    # Build message content with images
    content = [{"type": "text", "text": prompt + "\n\nRespond ONLY with valid JSON matching the required schema. No markdown, no explanation outside the JSON."}]
    
    for img_bytes in images:
        img_b64 = encode_image_base64(img_bytes)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_b64
            }
        })
    
    for attempt in range(max_retries):
        try:
            # Run synchronous Anthropic call in executor
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: anthropic_client.messages.create(
                    model=use_model,
                    max_tokens=2048,
                    temperature=0,
                    messages=[{"role": "user", "content": content}]
                )
            )
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


def get_filter_prompt() -> str:
    """Get domain-specific filtering prompt for dealer/distributor monitoring."""
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
    return """You are a CAMPAIGN COMPLIANCE AUDITOR for a dealer/distributor marketing monitoring platform.

IMAGE 1 (FIRST IMAGE): The APPROVED campaign creative — the official marketing asset.
IMAGE 2 (SECOND IMAGE): An image discovered on a dealer's website or ad platform.

YOUR TASK: Determine if Image 2 is running the SAME marketing campaign as Image 1.

WHAT "SAME CAMPAIGN" MEANS:
A match means the dealer is displaying this specific campaign — the same promotional message,
the same visual design, the same offer. The image does NOT need to be a pixel-perfect copy.
Websites render creatives through HTML/CSS, so the same campaign will often appear with slight
differences in font rendering, spacing, resolution, or aspect ratio. These rendering differences
do NOT disqualify a match.

TEMPLATE CREATIVES — EXPECTED DEALER CUSTOMIZATION:
The approved asset is often a TEMPLATE that contains placeholder fields dealers are expected
to fill in with their own information. The following substitutions are NORMAL, EXPECTED, and
should NOT be treated as unauthorized modifications:
- "Dealer Name", "Your Dealer", "Dealer Logo" or similar placeholders replaced with the
  dealer's actual name, branding, or logo
- Placeholder phone numbers, addresses, or URLs replaced with dealer-specific contact info
- Generic CTA buttons customized with dealer-specific destinations
These template customizations mean the dealer is CORRECTLY using the creative as intended.
They should NOT lower the similarity score or be flagged as modifications.

EVALUATION FRAMEWORK — analyze in order:
1. PRODUCT IDENTITY: Is the same specific product featured? (same model, same photo/render)
2. CAMPAIGN MESSAGE: Is the same promotional offer/headline/CTA present?
3. VISUAL DESIGN: Does the layout, color scheme, and composition match the campaign?
4. BRAND ELEMENTS: Are the same logos, brand colors, and trade dress present?

SCORING RUBRIC:
- 90-100: Same campaign — identical or near-identical rendering of the creative
          (includes template creatives with expected dealer-name customization)
- 75-89:  Same campaign — clearly the same creative with minor rendering differences
          (different resolution, slight cropping, font rendering differences)
- 60-74:  Same campaign — recognizably the same creative but with modifications
          (text overlays, watermarks, resizing, color shifts)
- 40-59:  Ambiguous — shares significant elements but may be a different version
- 0-39:   Different campaign — different product, different offer, or different design

AUTOMATIC SCORE 0 (different campaign entirely):
- Different brand (e.g. iPhone creative vs Samsung creative)
- Different product model (e.g. Galaxy S25 vs Galaxy S26)
- Same product but completely different creative design/photo
- Competitor's campaign material

Modifications to identify:
- cropping, resizing, color_changes, text_added, text_removed, overlay_added, quality_degraded, watermark_added
- Do NOT list dealer-name placeholder substitution as a modification

Return JSON with:
- similarity_score: 0-100
- is_match: true if similarity_score >= 55
- match_type: "exact"/"strong"/"partial"/"weak"/"none"
- modifications: array of detected modifications (exclude expected template customizations)
- modification_severity: "none"/"minor"/"moderate"/"major"
- analysis: explain what campaign elements match and what differs"""


def get_detection_prompt() -> str:
    """Get prompt for detecting a campaign creative within a screenshot or page section."""
    return """You are a CAMPAIGN COMPLIANCE AUDITOR scanning a webpage for a specific marketing campaign.

IMAGE 1 (FIRST IMAGE): The APPROVED CAMPAIGN CREATIVE — the official marketing asset we are looking for.
IMAGE 2 (SECOND IMAGE): A screenshot from a dealer's website (may be a full page, a page section, or an extracted element).

YOUR TASK: Determine if Image 2 contains the SAME marketing campaign shown in Image 1.

WHAT "SAME CAMPAIGN" MEANS:
The dealer's website may render the same campaign creative through HTML/CSS rather than embedding
the original image file. This means the same campaign can appear with different font rendering,
slightly different spacing, different resolution, or different aspect ratio. These rendering
differences are EXPECTED and do NOT disqualify a match.

A match requires:
- The same product being promoted (same model, same visual)
- The same campaign message or offer
- Recognizably the same visual design/layout

A match does NOT require:
- Pixel-identical rendering
- Exact same resolution or dimensions
- Identical font rendering or text spacing

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
- 85-100: Same campaign clearly visible — same product, same design, same message
- 70-84:  Same campaign very likely — recognizable design with rendering differences
- 55-69:  Probable match — significant shared elements but notable differences
- 0-39:   Not a match — different product, different campaign, or different brand

AUTOMATIC asset_found: false:
- Different brand entirely (e.g. searching for Samsung, found Apple)
- Different product model (e.g. searching for Galaxy S26, found Galaxy S25)
- Same product but a completely different campaign design
- No promotional content visible in the screenshot

Return JSON with:
- asset_found: true if confidence >= 55
- confidence: 0-100
- location: where found (header/sidebar/main_content/footer/banner/hero/carousel/popup/unknown)
- appearance: how it appears (exact/resized/cropped/modified/none)
- modifications: array of modifications detected
- reasoning: explain which campaign elements match — product, message, design, brand elements"""


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
   - Are the creative's colors significantly altered?

2. UNAUTHORIZED MODIFICATIONS (not template customization, not surrounding page elements):
   - Has the core campaign imagery been changed or replaced?
   - Have brand logos (manufacturer/OEM logos, not dealer placeholders) been removed or obscured?
   - Has the promotional offer, pricing, or terms been altered from the original?
   - Has the creative's quality been significantly degraded?
   - Have unauthorized elements been overlaid on the creative?

3. BRAND COMPLIANCE:
   - Are all required brand elements from the original creative still visible?
   - Have forbidden elements been added ON the creative itself?

COMPLIANCE RULES:
- is_compliant: true if the creative is visible AND its core content has not been materially modified
  (template placeholder substitution with dealer info is NOT a material modification)
- is_compliant: false if the creative's core imagery, brand elements, or offer terms have been
  altered, or the creative is not present
- Surrounding webpage UI (dealer nav, headers, site logos) is NOT a violation
- Dealer-name/logo placeholder substitution is NOT a violation — it is expected template usage
- When the creative is clearly present with only expected template customizations, it IS compliant

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
- is_match: true if GATE_BRAND passes AND GATE_PRODUCT passes AND at least 1 of the remaining 3 gates passes
- A campaign match requires the right brand AND the right product AND at least some shared campaign elements
- When truly uncertain (50/50), lean toward true — it is worse to miss a real match than to flag a false one

Return JSON with:
- gate_brand: true/false
- gate_product: true/false
- gate_message: true/false
- gate_offer: true/false
- gate_design: true/false
- gates_passed: count of true gates (0-5)
- is_match: true if gate_brand AND gate_product AND gates_passed >= 3
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

    all_locations: List[Dict[str, Any]] = []

    for asset_bytes, asset_id, asset_name in asset_bytes_list:
        try:
            asset_optimized = optimize_image_for_api(asset_bytes, "asset")
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


async def filter_image(image_url: str) -> ImageFilterResult:
    """
    Use Claude Haiku to quickly filter irrelevant images.
    Haiku is ~30x cheaper than Opus and fast enough for a yes/no relevance check.
    """
    try:
        image_bytes = await download_image(image_url)
        image_bytes = optimize_image_for_api(image_bytes, "default")
        
        prompt = get_filter_prompt()
        
        response_text = await call_anthropic_with_retry(prompt, [image_bytes], model=FILTER_MODEL)
        result = extract_json_from_response(response_text)
        
        # Apply relevance threshold
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
        # On error, mark as relevant to avoid missing content
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
    prompt = get_detection_prompt()

    response_text = await call_anthropic_with_retry(prompt, [asset_bytes, screenshot_bytes], model=ENSEMBLE_MODEL)
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
            response_text = await call_anthropic_with_retry(prompt, [asset_bytes, tile_optimized], model=ENSEMBLE_MODEL)
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
        
        prompt = get_verification_prompt()
        
        response_text = await call_anthropic_with_retry(prompt, [asset_bytes, discovered_bytes], model=ENSEMBLE_MODEL)
        result = extract_json_from_response(response_text)
        
        gates_passed = result.get("gates_passed", 0)
        gate_brand = result.get("gate_brand", False)
        gate_product = result.get("gate_product", False)

        is_match = result.get("is_match", False) and gate_brand and gate_product and gates_passed >= 3

        verified_score = gates_passed * 20

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
        
        response_text = await call_anthropic_with_retry(prompt, [asset_bytes, discovered_bytes])
        result = extract_json_from_response(response_text)
        
        log.info("Compliance result: is_compliant=%s", result.get('is_compliant'))
        
        return ComplianceCheckResult(
            is_compliant=result.get("is_compliant", True),
            issues=result.get("issues", []),
            brand_elements=result.get("brand_elements", {}),
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
        # For regular images, visual comparison is primary
        final_score = (
            visual_score * settings.ensemble_visual_weight +
            detection_score * settings.ensemble_detection_weight +
            hash_score * settings.ensemble_hash_weight
        )
    
    # Agreement bonus - ONLY if multiple methods agree on STRONG match (>60)
    agreement_count = sum(1 for s in [visual_score, detection_score, hash_score] if s > 60)
    if agreement_count >= 2:
        final_score = min(100, final_score + settings.ensemble_agreement_bonus)
    
    # Hash exact match bonus - ONLY for true exact matches (very strict)
    if hash_result.get("is_exact"):
        # Only boost if hash shows near-identical images
        final_score = max(final_score, 85)
    
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
    
    # STRICT: Require score to meet threshold - don't just trust asset_found
    threshold = settings.screenshot_match_threshold if is_screenshot else settings.regular_image_match_threshold
    is_match = final_score >= threshold and (asset_found or final_score >= settings.partial_match_threshold)
    
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
) -> bool:
    """
    Stage 1 pre-filter: check if the image has ANY perceptual hash
    resemblance to at least one campaign asset.

    Returns True if the image should continue to the next stage.
    This is free and instant (~0.5ms per comparison).
    """
    img_hashes = await compute_image_hashes(image_bytes)
    if img_hashes is None:
        return True  # can't compute → don't discard

    threshold = settings.hash_prefilter_max_diff

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


def _passes_clip_prefilter(
    image_bytes: bytes,
    asset_embeddings: list,
) -> bool:
    """
    Stage 2 pre-filter: check CLIP semantic similarity between the
    discovered image and campaign assets.

    Returns True if the image should continue to Claude.
    Runs locally on CPU (~20ms per image).
    """
    if not asset_embeddings:
        return True  # no embeddings → skip gate

    img_emb = embedding_service.compute_embedding(image_bytes)
    if img_emb is None:
        return True  # model unavailable → don't discard

    best_sim = embedding_service.best_asset_similarity(img_emb, asset_embeddings)
    passes = best_sim >= settings.clip_similarity_threshold
    log.debug("CLIP best similarity: %.3f (threshold %.2f) → %s",
              best_sim, settings.clip_similarity_threshold, "PASS" if passes else "SKIP")
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
    """Download each campaign asset and compute CLIP embeddings once."""
    bytes_list = []
    for asset in campaign_assets:
        try:
            bytes_list.append(await download_image(asset["file_url"]))
        except Exception as e:
            log.warning("Could not download asset %s for embedding: %s",
                        asset.get("name", asset["id"]), e)
    if not bytes_list:
        return []
    embeddings = embedding_service.compute_embeddings_batch(bytes_list)
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
) -> tuple:
    """
    Full processing pipeline for a discovered image.

    Returns (result_dict, stage) where stage indicates the last pipeline
    stage reached.  When no match is found result_dict is None.

    Stages: "download_failed", "hash_rejected", "clip_rejected",
            "filter_rejected", "below_threshold", "verification_rejected",
            "matched"
    """
    log.info("Processing image: %s", image_url[:80])
    log.debug("Source type: %s", source_type or "not specified")
    
    # Determine if this is a screenshot
    is_screenshot = (
        source_type == "page_screenshot" or
        "screenshot" in image_url.lower() or
        "screenshotUrl" in image_url or
        "/screenshots/" in image_url
    )

    # --- Stage 1 & 2: local pre-filters (skip for screenshots) ---
    if not is_screenshot:
        try:
            image_bytes_for_prefilter = await download_image(image_url)
        except Exception as e:
            log.warning("Could not download image for pre-filter: %s", e)
            return None, "download_failed"

        # Stage 1: Hash pre-filter
        if asset_hashes_cache:
            passes_hash = await _passes_hash_prefilter(image_bytes_for_prefilter, asset_hashes_cache)
            if not passes_hash:
                log.debug("REJECTED by hash pre-filter (no asset resemblance)")
                return None, "hash_rejected"

        # Stage 2: CLIP embedding pre-filter
        if asset_embeddings_cache:
            passes_clip = _passes_clip_prefilter(image_bytes_for_prefilter, asset_embeddings_cache)
            if not passes_clip:
                log.debug("REJECTED by CLIP pre-filter (low semantic similarity)")
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
        log.debug("Stage 3: Haiku relevance filter")
        filter_result = await filter_image(image_url)
        log.debug("Filter: is_relevant=%s, confidence=%.2f", filter_result.is_relevant, filter_result.confidence)
        
        if not filter_result.is_relevant:
            log.debug("Image filtered out as not relevant")
            return None, "filter_rejected"
    
    # Stage 4: Ensemble matching against each asset (Claude Opus)
    log.debug("Stage 4: ensemble matching against %d assets", len(campaign_assets))
    best_match = None
    best_score = 0
    
    for asset in campaign_assets:
        log.debug("Comparing with asset: %s", asset.get('name', asset['id']))
        
        comparison = await ensemble_match(
            asset["file_url"],
            image_url,
            is_screenshot=is_screenshot
        )
        
        score = comparison.get("similarity_score", 0)
        is_found = comparison.get("asset_found", False) or comparison.get("is_match", False)
        
        log.debug("Ensemble score: %d, Found/Match: %s", score, is_found)
        
        if is_found or score > best_score:
            if is_found:
                best_score = max(score, best_score)
                best_match = {"asset": asset, "comparison": comparison}
            elif score > best_score:
                best_score = score
                best_match = {"asset": asset, "comparison": comparison}
    
    threshold = adaptive_threshold
    
    if not best_match:
        log.info("No match found")
        return None, "below_threshold"
    
    asset_found = best_match["comparison"].get("asset_found", False)
    is_match = best_match["comparison"].get("is_match", False)
    
    if not asset_found and not is_match and best_score < threshold:
        log.debug("Best score %d below threshold %d", best_score, threshold)
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


