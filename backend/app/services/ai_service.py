"""
Anthropic Claude AI service for image analysis.

All image analysis powered by Claude Opus 4.5:
- Image filtering for relevance
- Visual similarity comparison
- Asset detection in screenshots
- Multi-stage verification
- Compliance analysis
- Perceptual hashing for fast pre-filtering
- Domain-specific prompts for dealer/distributor monitoring
- Confidence calibration based on source type and channel
- Optimized batch processing with parallel execution
"""
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

settings = get_settings()

# Configure Anthropic client
anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
CLAUDE_MODEL = "claude-opus-4-20250514"  # Claude Opus 4.5 model


# =============================================================================
# IMAGE DOWNLOAD AND OPTIMIZATION
# =============================================================================

async def download_image(url: str) -> bytes:
    """Download image from URL with timeout and error handling.
    
    Also handles base64 data URLs (data:image/...;base64,...).
    """
    # Handle base64 data URLs
    if url.startswith("data:"):
        try:
            # Extract base64 data from data URL
            # Format: data:image/png;base64,<base64data>
            header, encoded = url.split(",", 1)
            return base64.b64decode(encoded)
        except Exception as e:
            print(f"[AI] Error decoding base64 data URL: {e}")
            raise
    
    # Regular HTTP(S) URL
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            print(f"[AI] HTTP error downloading image: {e.response.status_code} - {url[:100]}")
            raise
        except httpx.TimeoutException:
            print(f"[AI] Timeout downloading image: {url[:100]}")
            raise
        except Exception as e:
            print(f"[AI] Error downloading image: {e} - {url[:100]}")
            raise


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
            print(f"[AI] Optimized {analysis_type} image: {original_size/1024:.1f}KB -> {new_size/1024:.1f}KB ({reduction}% reduction)")
        
        return optimized_bytes
        
    except Exception as e:
        print(f"[AI] Image optimization failed: {e}, using original")
        return image_bytes


# =============================================================================
# PERCEPTUAL HASHING
# =============================================================================

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
        print(f"[AI] Hash computation failed: {e}")
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
        print(f"[AI Hash] Error: {e}")
        return {
            "similarity_score": 0,
            "is_exact": False,
            "is_similar": False,
            "error": str(e)
        }


# =============================================================================
# ANTHROPIC API CALLS WITH RETRY
# =============================================================================

async def call_anthropic_with_retry(
    prompt: str,
    images: List[bytes],
    max_retries: int = None
) -> str:
    """
    Call Anthropic Claude API with retry logic and image support.
    
    Args:
        prompt: Text prompt for the model
        images: List of image bytes to include
        max_retries: Number of retry attempts
    
    Returns:
        Response text from Claude
    """
    if max_retries is None:
        max_retries = settings.max_retries
    
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
                    model=CLAUDE_MODEL,
                    max_tokens=2048,
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
                print(f"[AI] Non-retryable error: {e}")
                raise
            
            if attempt < max_retries - 1:
                backoff = settings.initial_backoff * (2 ** attempt)
                print(f"[AI] Attempt {attempt + 1} failed: {e}")
                print(f"[AI] Retrying in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
            else:
                print(f"[AI] All {max_retries} attempts failed")
    
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


# =============================================================================
# DOMAIN-SPECIFIC PROMPTS
# =============================================================================

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
    """Get prompt for visual similarity comparison - STRICT matching."""
    return """Compare these two images with STRICT accuracy. The first is the APPROVED original, the second is the DISCOVERED version.

CRITICAL: Be CONSERVATIVE and ACCURATE. Only report a match if there is clear visual evidence.

NEGATIVE CONSTRAINTS (Immediate 0 Score - NO EXCEPTIONS):
- DIFFERENT BRAND: (e.g. iPhone vs Pixel, Ford vs Chevy, Nike vs Adidas) -> Score 0
- DIFFERENT MODEL: (e.g. iPhone 14 vs iPhone 15, Camry vs Corolla) -> Score 0
- DIFFERENT CREATIVE: Same product but different photo/angle/shoot -> Score 0
- COMPETITOR ASSETS: If the image shows a competitor's product -> Score 0
- DIFFERENT PRODUCT: Similar category but not the EXACT same item -> Score 0

STRICT MATCHING CRITERIA:
- The images must share the SAME specific source photo/graphic
- Similar colors, layouts, or "vibes" alone are NOT matches
- Generic similarities (both show phones, both show cars) are NOT matches
- You must identify the EXACT SAME creative/photograph, not just similar products

SCORING GUIDELINES (be conservative):
- 90-100: EXACT match - identical or near-identical image
- 75-89: STRONG match - clearly the SAME creative with minor cropping
- 55-74: PARTIAL match - SAME creative but with text overlays or major cropping
- 0-39: NO MATCH - Different product, different brand, or different creative

IMPORTANT: Do NOT score above 40 if the products are different, even if the layout is identical.

Modifications to identify:
- cropping, resizing, color_changes, text_added, text_removed, overlay_added, quality_degraded, watermark_added

Return JSON with:
- similarity_score: 0-100 (score conservatively)
- is_match: true only if similarity_score >= 55
- match_type: "exact"/"strong"/"partial"/"weak"/"none"
- modifications: array of detected modifications
- modification_severity: "none"/"minor"/"moderate"/"major"
- analysis: brief description of what is similar and what is different"""


def get_detection_prompt() -> str:
    """Get prompt for detecting asset within a screenshot - STRICT matching."""
    return """TASK: Detect if a SPECIFIC marketing asset appears within a webpage screenshot.

IMAGE 1 (FIRST IMAGE): The SPECIFIC MARKETING ASSET (Target) we are searching for.
IMAGE 2 (SECOND IMAGE): A FULL WEBPAGE SCREENSHOT to examine.

CRITICAL: We are looking for the EXACT creative. Be STRICT.

NEGATIVE CONSTRAINTS (Immediate asset_found: false):
- IGNORE competitor ads (e.g. if Target is iPhone, ignore Pixel/Samsung ads)
- IGNORE similar products (e.g. if Target is Red Car, ignore Blue Car or different model)
- IGNORE different views (e.g. if Target is front-view, ignore side-view of same product)
- IGNORE different creatives of the same product (different photo shoot = no match)

STRICT MATCHING RULES:
1. The EXACT same image/creative must be visible - not a similar one
2. If you see a similar product but it is NOT the specific target asset, report asset_found: false
3. Be careful of "Lists" or "Grids" of products - locate only the SPECIFIC target creative
4. Different brand = automatic asset_found: false, confidence: 0
5. Different model = automatic asset_found: false, confidence: 0

The asset may appear smaller in the screenshot. Search these areas:
- Hero/banner sections
- Sidebars
- Main content area  
- Carousels and sliders
- Footer areas

CONFIDENCE SCORING (be conservative):
- 80-100: Confirmed SAME specific creative visible
- 60-79: Very likely the EXACT same asset
- 0-39: Different product, competitor product, or just similar layout

WHEN IN DOUBT, report asset_found: FALSE. It is better to miss a match than to flag a competitor's ad or wrong product.

Return JSON with:
- asset_found: true ONLY if confidence >= 60
- confidence: 0-100 (score conservatively)
- location: where found (header/sidebar/main_content/footer/banner/hero/carousel/popup/unknown)
- appearance: how it appears (exact/resized/cropped/modified/none)
- modifications: array of modifications detected
- reasoning: explain why it is the EXACT asset and not a look-alike or competitor"""


def get_compliance_prompt(rules_text: str, zombie_check: str) -> str:
    """Get prompt for compliance analysis - STRICT checking."""
    return f"""COMPLIANCE ANALYSIS - Be thorough and critical.

CRITICAL: First verify if the discovered image actually contains the original asset.
If the images are NOT the same creative, report asset_visible: false and is_compliant: false.

IMAGE 1 (FIRST IMAGE): The ORIGINAL APPROVED ASSET - official marketing creative.
IMAGE 2 (SECOND IMAGE): The DISCOVERED IMAGE - what was found on a distributor's site.

STEP 1 - VERIFY MATCH FIRST:
Before checking compliance, confirm the discovered image actually shows the original asset.
- If these are DIFFERENT images/creatives, set asset_visible: false
- Only proceed with compliance analysis if the SAME asset is clearly visible

BRAND RULES:
{rules_text}

{zombie_check}

STEP 2 - IF ASSET IS VISIBLE, CHECK FOR VIOLATIONS:

1. ASSET INTEGRITY:
   - Has it been cropped, stretched, or distorted?
   - Has it been overlaid with unauthorized content?
   - Are colors significantly altered?

2. UNAUTHORIZED MODIFICATIONS:
   - Has text been added or removed?
   - Have logos or brand elements been obscured?
   - Has quality been significantly degraded?

3. BRAND COMPLIANCE:
   - Are all required brand elements visible?
   - Have any forbidden elements been added?

COMPLIANCE RULES:
- is_compliant: true ONLY if asset is visible AND no significant modifications AND all brand rules followed
- is_compliant: false if ANY issues found OR asset not clearly visible
- When uncertain about compliance, default to is_compliant: false (requires review)

Return JSON with:
- is_compliant: true only if clearly compliant with no issues
- asset_visible: true only if the SAME asset is clearly identifiable
- issues: array of {{type, description, severity}} - list ALL issues found
- modifications_detected: array of modifications
- brand_elements: {{logo_visible, tagline_visible, colors_accurate, asset_prominent}}
- zombie_ad: true/false
- zombie_reason: explanation if zombie
- analysis_summary: explain your compliance decision"""


def get_verification_prompt() -> str:
    """Get prompt for multi-stage verification using boolean gates - AGENTIC approach."""
    return """VERIFICATION AGENT - You are a strict QA compliance agent performing verification.

IMAGE 1: The APPROVED original asset
IMAGE 2: The DISCOVERED image

PROTOCOL - Execute these steps in order:

STEP 1 - IDENTIFY:
List every distinct visual element in both images. Use OCR to read all text.

STEP 2 - VERIFY EACH GATE (Pass/Fail only - no partial credit):

□ GATE_LOGO: Is the EXACT same brand logo present in both images?
  - Not similar logos - must be IDENTICAL
  - Pass only if you can confirm it's the same logo

□ GATE_PRODUCT: Is the EXACT same product/vehicle/image shown?
  - Not similar product type - must be the SAME specific image
  - Compare: same angle, same photo, same vehicle/equipment
  - This is the CRITICAL gate. If the car/product is different, FAIL.

□ GATE_TEXT: Does the promotional text match?
  - Use OCR to extract text from both images
  - Compare exact strings - do they say the same thing?

□ GATE_OFFER: Is the SAME offer/pricing displayed?
  - Compare specific numbers, percentages, dates
  - Must be identical offer terms

□ GATE_LAYOUT: Is the composition/arrangement the same?
  - Similar element positioning
  - Similar visual hierarchy

STEP 3 - VERDICT:
- is_match: true ONLY if at least 3 of 5 gates PASS
- CRITICAL: If GATE_PRODUCT fails, is_match MUST be false regardless of other gates.
- CRITICAL: If the brand is different, is_match MUST be false.
- When uncertain, default to false.

Return JSON with:
- gate_logo: true/false
- gate_product: true/false
- gate_text: true/false
- gate_offer: true/false
- gate_layout: true/false
- gates_passed: count of true gates (0-5)
- is_match: true only if gates_passed >= 3 AND gate_product is true
- verdict: one-line explanation of your decision"""


# =============================================================================
# CORE ANALYSIS FUNCTIONS
# =============================================================================

async def filter_image(image_url: str) -> ImageFilterResult:
    """
    Use Claude Opus 4.5 to quickly filter irrelevant images.
    Enhanced with domain-specific prompts.
    """
    try:
        image_bytes = await download_image(image_url)
        image_bytes = optimize_image_for_api(image_bytes, "default")
        
        prompt = get_filter_prompt()
        
        response_text = await call_anthropic_with_retry(prompt, [image_bytes])
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
        print(f"[AI Filter] Error: {e}")
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
        
        response_text = await call_anthropic_with_retry(prompt, [source_bytes, target_bytes])
        return extract_json_from_response(response_text)
        
    except Exception as e:
        print(f"[AI Compare] Error: {e}")
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
    Uses Claude Opus 4.5 for accurate detection.
    """
    try:
        print(f"[AI] Detecting asset in screenshot...")
        
        asset_bytes = await download_image(asset_image_url)
        screenshot_bytes = await download_image(screenshot_url)
        
        asset_bytes = optimize_image_for_api(asset_bytes, "asset")
        screenshot_bytes = optimize_image_for_api(screenshot_bytes, "screenshot")
        
        prompt = get_detection_prompt()
        
        response_text = await call_anthropic_with_retry(prompt, [asset_bytes, screenshot_bytes])
        result = extract_json_from_response(response_text)
        
        asset_found = result.get("asset_found", False)
        confidence = result.get("confidence", 0)
        
        print(f"[AI] Asset detection: found={asset_found}, confidence={confidence}")
        
        # STRICT: Only consider it found if BOTH asset_found is true AND confidence is high enough
        actually_found = asset_found and confidence >= 60
        
        return {
            "asset_found": actually_found,
            "similarity_score": confidence,
            "is_match": actually_found and confidence >= settings.screenshot_match_threshold,
            "match_type": _get_match_type_from_appearance(result.get("appearance", "none"), confidence),
            "modifications": result.get("modifications", []),
            "location": result.get("location", "unknown"),
            "analysis": result.get("reasoning", "")
        }
        
    except Exception as e:
        print(f"[AI] Error detecting asset: {e}")
        import traceback
        traceback.print_exc()
        return {
            "asset_found": False,
            "similarity_score": 0,
            "is_match": False,
            "match_type": "none",
            "modifications": [],
            "error": str(e)
        }


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
        print(f"[AI] Verifying borderline match (initial score: {initial_score})...")
        
        asset_bytes = await download_image(asset_url)
        discovered_bytes = await download_image(discovered_url)
        
        asset_bytes = optimize_image_for_api(asset_bytes, "asset")
        discovered_bytes = optimize_image_for_api(discovered_bytes, "default")
        
        prompt = get_verification_prompt()
        
        response_text = await call_anthropic_with_retry(prompt, [asset_bytes, discovered_bytes])
        result = extract_json_from_response(response_text)
        
        # Boolean gate verification
        gates_passed = result.get("gates_passed", 0)
        gate_product = result.get("gate_product", False)
        
        # STRICT: Product gate is critical - must pass + at least 3 total gates
        is_match = result.get("is_match", False) and gate_product and gates_passed >= 3
        
        # Convert gates to score for compatibility (each gate = 20 points)
        verified_score = gates_passed * 20
        
        print(f"[AI] Verification complete: gates_passed={gates_passed}, is_match={is_match}")
        print(f"[AI] Gates: logo={result.get('gate_logo')}, product={gate_product}, text={result.get('gate_text')}, offer={result.get('gate_offer')}, layout={result.get('gate_layout')}")
        
        return {
            "verified_score": verified_score,
            "is_match": is_match,
            "gates": {
                "logo": result.get("gate_logo", False),
                "product": gate_product,
                "text": result.get("gate_text", False),
                "offer": result.get("gate_offer", False),
                "layout": result.get("gate_layout", False)
            },
            "gates_passed": gates_passed,
            "verdict": result.get("verdict", "")
        }
        
    except Exception as e:
        print(f"[AI] Verification error: {e}")
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
        print(f"[AI Compliance] Analyzing compliance with Claude Opus 4.5...")
        
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
        
        print(f"[AI Compliance] Result: is_compliant={result.get('is_compliant')}")
        
        return ComplianceCheckResult(
            is_compliant=result.get("is_compliant", True),
            issues=result.get("issues", []),
            brand_elements=result.get("brand_elements", {}),
            zombie_ad=result.get("zombie_ad", False),
            zombie_days=None,
            analysis_summary=result.get("analysis_summary", "")
        )
        
    except Exception as e:
        print(f"[AI Compliance] Error: {e}")
        import traceback
        traceback.print_exc()
        # STRICT: Default to NOT compliant on errors - requires manual review
        return ComplianceCheckResult(
            is_compliant=False,
            issues=[{"type": "analysis_error", "description": str(e), "severity": "high"}],
            brand_elements={},
            analysis_summary=f"Analysis failed - requires manual review: {str(e)}"
        )


# =============================================================================
# ENSEMBLE MATCHING
# =============================================================================

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
    print(f"[AI Ensemble] Starting ensemble match...")
    
    # Run methods in parallel
    if is_screenshot:
        results = await asyncio.gather(
            detect_asset_in_screenshot(asset_url, discovered_url),
            compare_with_hash(asset_url, discovered_url),
            return_exceptions=True
        )
        detection_result = results[0] if not isinstance(results[0], Exception) else {"similarity_score": 0, "asset_found": False}
        hash_result = results[1] if not isinstance(results[1], Exception) else {"similarity_score": 0}
        visual_result = {"similarity_score": 0}  # Skip for screenshots
        
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
        # For screenshots, detection is primary, hash is secondary
        final_score = (
            detection_score * (settings.ensemble_visual_weight + settings.ensemble_detection_weight) +
            hash_score * settings.ensemble_hash_weight
        )
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
    
    print(f"[AI Ensemble] Scores - Visual: {visual_score}, Detection: {detection_score}, Hash: {hash_score}")
    print(f"[AI Ensemble] Final: {final_score:.1f}, Match: {is_match}, Type: {match_type}")
    
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
        print(f"[AI] Error getting adaptive calibration: {e}")
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


# =============================================================================
# BATCH PROCESSING
# =============================================================================

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


# =============================================================================
# MAIN PROCESSING PIPELINE
# =============================================================================

async def process_discovered_image(
    discovered_image_id: str,
    image_url: str,
    campaign_assets: List[Dict[str, Any]],
    brand_rules: Dict[str, Any],
    source_type: Optional[str] = None,
    channel: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Full processing pipeline for a discovered image.
    
    Enhanced with:
    - Adaptive thresholds based on historical feedback
    - Ensemble matching
    - Borderline verification
    - Confidence calibration
    """
    print(f"[AI] Processing image: {image_url[:80]}...")
    print(f"[AI] Source type: {source_type or 'not specified'}")
    
    # Determine if this is a screenshot
    is_screenshot = (
        source_type == "page_screenshot" or
        "screenshot" in image_url.lower() or
        "screenshotUrl" in image_url or
        "/screenshots/" in image_url
    )
    
    # Get adaptive threshold for this source/channel
    adaptive_threshold, threshold_meta = await get_adaptive_threshold(
        source_type or ("page_screenshot" if is_screenshot else "website_banner"),
        channel or "website"
    )
    
    print(f"[AI] Using adaptive threshold: {adaptive_threshold} (Confidence: {threshold_meta['confidence']})")
    
    print(f"[AI] Image type: {'SCREENSHOT' if is_screenshot else 'regular image'}")
    
    # Step 1: Filter (skip for screenshots)
    if is_screenshot:
        print(f"[AI] Step 1: SKIPPING filter for screenshot")
        filter_result = ImageFilterResult(
            is_relevant=True,
            confidence=1.0,
            reason="Screenshot - checking for contained assets"
        )
    else:
        print(f"[AI] Step 1: Filtering for relevance...")
        filter_result = await filter_image(image_url)
        print(f"[AI] - Filter: is_relevant={filter_result.is_relevant}, confidence={filter_result.confidence}")
        
        if not filter_result.is_relevant:
            print(f"[AI] Image filtered out as not relevant")
            return None
    
    # Step 2: Ensemble matching against each asset
    print(f"[AI] Step 2: Ensemble matching against {len(campaign_assets)} assets...")
    best_match = None
    best_score = 0
    
    for asset in campaign_assets:
        print(f"[AI] - Comparing with asset: {asset.get('name', asset['id'])}")
        
        # Use ensemble matching
        comparison = await ensemble_match(
            asset["file_url"],
            image_url,
            is_screenshot=is_screenshot
        )
        
        score = comparison.get("similarity_score", 0)
        is_found = comparison.get("asset_found", False) or comparison.get("is_match", False)
        
        print(f"[AI]   Ensemble score: {score}, Found/Match: {is_found}")
        
        # Track best match
        if is_found or score > best_score:
            if is_found:
                best_score = max(score, best_score)
                best_match = {"asset": asset, "comparison": comparison}
            elif score > best_score:
                best_score = score
                best_match = {"asset": asset, "comparison": comparison}
    
    threshold = adaptive_threshold
    
    # Check if we have a match
    if not best_match:
        print(f"[AI] No match found")
        return None
    
    asset_found = best_match["comparison"].get("asset_found", False)
    is_match = best_match["comparison"].get("is_match", False)
    
    if not asset_found and not is_match and best_score < threshold:
        print(f"[AI] Best score {best_score} below threshold {threshold}")
        return None
    
    # Step 3: Verify borderline matches
    needs_verification = await should_verify_match(
        best_score,
        source_type or ("page_screenshot" if is_screenshot else "website_banner"),
        channel or "website"
    )
    
    if needs_verification:
        print(f"[AI] Step 3: Verifying borderline match (score: {best_score})...")
        verification = await verify_borderline_match(
            best_match["asset"]["file_url"],
            image_url,
            best_score
        )
        
        if not verification.get("is_match", False):
            print(f"[AI] Verification rejected match")
            return None
        
        # Use verified score
        best_score = verification.get("verified_score", best_score)
        print(f"[AI] Verification passed with score: {best_score}")
    
    # Apply confidence calibration
    calibrated_score = await calibrate_confidence(best_score, source_type or "unknown", channel or "unknown")
    print(f"[AI] Calibrated score: {best_score} -> {calibrated_score}")
    
    # Step 4: Compliance analysis
    print(f"[AI] Step 4: Compliance analysis...")
    compliance = await analyze_compliance(
        image_url,
        best_match["asset"]["file_url"],
        brand_rules,
        best_match["asset"].get("campaign_end_date")
    )
    
    # Determine match type
    match_type = _get_match_type_from_score(calibrated_score)
    
    print(f"[AI] Final: {match_type} match, score {calibrated_score}, compliant={compliance.is_compliant}")
    
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
    }


async def process_images_batch(
    images: List[Dict],
    campaign_assets: List[Dict],
    brand_rules: Dict[str, Any]
) -> List[Optional[Dict[str, Any]]]:
    """
    Process multiple images in optimized parallel batches.
    """
    results = []
    batch_size = settings.batch_size
    
    for i in range(0, len(images), batch_size):
        batch = images[i:i + batch_size]
        
        # Process batch in parallel
        batch_results = await asyncio.gather(
            *[
                process_discovered_image(
                    img["id"],
                    img["image_url"],
                    campaign_assets,
                    brand_rules,
                    source_type=img.get("source_type"),
                    channel=img.get("channel")
                )
                for img in batch
            ],
            return_exceptions=True
        )
        
        for j, result in enumerate(batch_results):
            if isinstance(result, Exception):
                print(f"[AI Batch] Error processing image: {result}")
                results.append(None)
            else:
                results.append(result)
        
        # Rate limiting between batches
        if i + batch_size < len(images):
            await asyncio.sleep(settings.batch_delay)
    
    return results


