"""
OpenCV-based visual matching for locating campaign creatives on web pages.

Two complementary strategies:
  1. Multi-scale template matching — slides the asset across the screenshot
     at many scales and returns the best correlation. Fast (~50ms), works
     well for exact/near-exact renders.
  2. ORB feature matching — extracts keypoints from both images and matches
     them via brute-force Hamming distance. Handles scale changes, slight
     rotation, partial occlusion, and CSS rendering differences.

Both methods return bounding boxes in full-page screenshot coordinates
so the caller can crop cleanly.
"""
import io
import logging
from typing import List, Dict, Any, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("dealer_intel.cv_matching")


def _pil_to_cv(pil_img: Image.Image) -> np.ndarray:
    """Convert PIL Image to OpenCV BGR ndarray."""
    if pil_img.mode == "RGBA":
        pil_img = pil_img.convert("RGB")
    elif pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _bytes_to_cv(img_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image bytes")
    return img


def _bytes_to_gray(img_bytes: bytes) -> np.ndarray:
    img = _bytes_to_cv(img_bytes)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


# 2026-06-05: default cap on the longest side of the screenshot fed into
# matchTemplate. matchTemplate cost scales with screenshot AREA, so tall
# rental/catalog pages (1920x20000+) cost 10-25x a normal page and routinely
# blew the per-page extract budget. ``find_asset_on_page`` downscales the
# screenshot (and the asset, to preserve relative scale) below this cap, runs
# the match, and scales the resulting bounding boxes back to full-page space.
DEFAULT_MAX_MATCH_DIM = 4000


def _downscale_factor(gray: np.ndarray, max_dim: int) -> float:
    """Return a <=1.0 factor that brings the longest side to ``max_dim``."""
    if not max_dim or max_dim <= 0:
        return 1.0
    longest = max(gray.shape[:2])
    if longest <= max_dim:
        return 1.0
    return max_dim / float(longest)


def _resize_gray(gray: np.ndarray, factor: float) -> np.ndarray:
    if factor >= 1.0:
        return gray
    h, w = gray.shape[:2]
    return cv2.resize(
        gray,
        (max(1, int(w * factor)), max(1, int(h * factor))),
        interpolation=cv2.INTER_AREA,
    )


def template_match(
    screenshot_bytes: bytes,
    asset_bytes: bytes,
    scale_range: Tuple[float, float] = (0.10, 1.8),
    scale_steps: int = 50,
    threshold: float = 0.70,
) -> List[Dict[str, Any]]:
    """
    Find the asset in the screenshot using multi-scale normalised
    cross-correlation.

    Uses denser sampling at smaller scales (0.10–0.5) where web renders
    most commonly resize creatives, and coarser steps at larger scales.

    Returns a list of match dicts sorted by confidence (highest first).
    Each dict: {x, y, width, height, confidence, method}.

    Threshold rationale: the previous default of 0.40 was disastrously
    permissive — TM_CCOEFF_NORMED of 0.40 means "weakly correlated", and
    at 50 scale steps from 10% to 180% there is almost always *some*
    sub-region of a web page that lands above 0.40 against any asset.
    The matcher then cropped that region and fed it back into the AI
    pipeline, which would happily confirm OpenCV's own guess (the crop
    was sized like the asset, so Claude's leading "is this it?" prompt
    over-scored). Industry practice for "real" template matches is
    ≥ 0.70; we lift to that. Pages that don't have the asset rendered
    cleanly will simply produce zero crops — preferable to producing
    junk crops that publish as STRONG MATCH.
    """
    ss_gray = _bytes_to_gray(screenshot_bytes)
    asset_gray = _bytes_to_gray(asset_bytes)
    return _template_match_gray(
        ss_gray, asset_gray,
        scale_range=scale_range, scale_steps=scale_steps, threshold=threshold,
    )


def _template_match_gray(
    ss_gray: np.ndarray,
    asset_gray: np.ndarray,
    scale_range: Tuple[float, float] = (0.10, 1.8),
    scale_steps: int = 50,
    threshold: float = 0.70,
) -> List[Dict[str, Any]]:
    """Template-match on pre-decoded grayscale arrays (see ``template_match``)."""
    ss_h, ss_w = ss_gray.shape[:2]
    a_h, a_w = asset_gray.shape[:2]

    best: Optional[Dict[str, Any]] = None

    lo, hi = scale_range
    mid = 0.5
    small_steps = int(scale_steps * 0.6)
    large_steps = scale_steps - small_steps
    scales = np.concatenate([
        np.linspace(lo, mid, small_steps),
        np.linspace(mid, hi, large_steps + 1)[1:],
    ])

    for scale in scales:
        new_w = int(a_w * scale)
        new_h = int(a_h * scale)
        if new_w < 30 or new_h < 30:
            continue
        if new_w > ss_w or new_h > ss_h:
            continue

        scaled = cv2.resize(asset_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(ss_gray, scaled, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            if best is None or max_val > best["confidence"]:
                best = {
                    "x": int(max_loc[0]),
                    "y": int(max_loc[1]),
                    "width": new_w,
                    "height": new_h,
                    "confidence": round(float(max_val), 4),
                    "scale": round(float(scale), 3),
                    "method": "template",
                }

    if best:
        log.debug(
            "Template match at (%d,%d) %dx%d scale=%.3f conf=%.3f",
            best["x"], best["y"], best["width"], best["height"],
            best["scale"], best["confidence"],
        )
        return [best]

    log.debug("No template match above threshold")
    return []


def feature_match(
    screenshot_bytes: bytes,
    asset_bytes: bytes,
    min_good_matches: int = 18,
    ratio_thresh: float = 0.72,
) -> List[Dict[str, Any]]:
    """
    Find the asset in the screenshot using ORB keypoint detection
    and brute-force Hamming matching with Lowe's ratio test.

    Returns a list of match dicts (usually 0 or 1 items).
    Each dict: {x, y, width, height, confidence, method, good_matches}.
    """
    ss_gray = _bytes_to_gray(screenshot_bytes)
    asset_gray = _bytes_to_gray(asset_bytes)
    return _feature_match_gray(
        ss_gray, asset_gray,
        min_good_matches=min_good_matches, ratio_thresh=ratio_thresh,
    )


def _feature_match_gray(
    ss_gray: np.ndarray,
    asset_gray: np.ndarray,
    min_good_matches: int = 18,
    ratio_thresh: float = 0.72,
) -> List[Dict[str, Any]]:
    """Feature-match on pre-decoded grayscale arrays (see ``feature_match``)."""
    orb = cv2.ORB_create(nfeatures=2000)

    kp_asset, desc_asset = orb.detectAndCompute(asset_gray, None)
    kp_ss, desc_ss = orb.detectAndCompute(ss_gray, None)

    if desc_asset is None or desc_ss is None:
        log.debug("Not enough keypoints")
        return []
    if len(kp_asset) < 4 or len(kp_ss) < 4:
        log.debug("Too few keypoints")
        return []

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = bf.knnMatch(desc_asset, desc_ss, k=2)

    good = []
    for pair in raw_matches:
        if len(pair) == 2:
            m, n = pair
            if m.distance < ratio_thresh * n.distance:
                good.append(m)

    log.debug("%d good matches out of %d", len(good), len(raw_matches))

    if len(good) < min_good_matches:
        log.debug("Below threshold (%d)", min_good_matches)
        return []

    src_pts = np.float32([kp_asset[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_ss[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if M is None:
        log.debug("Homography failed")
        return []

    inliers = int(mask.sum()) if mask is not None else 0
    # Require RANSAC inliers to comfortably outnumber the noise floor.
    # The previous threshold of `min_good_matches // 2` (i.e. 4 inliers
    # against 8 raw matches) accepted any homography that two text
    # corners and two button edges could agree on, which is exactly
    # what produced false-positive bounding boxes on UI chrome. With
    # min_good_matches lifted to 18, we also lift the inlier floor to
    # 75% of the matched-pair count so a real homography has to back
    # most of the keypoints, not a minority.
    if inliers < max(8, int(min_good_matches * 0.75)):
        log.debug("Too few inliers (%d, needed %d)", inliers, max(8, int(min_good_matches * 0.75)))
        return []

    h, w = asset_gray.shape[:2]
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(corners, M)
    pts = projected.reshape(-1, 2)

    x_min = max(0, int(pts[:, 0].min()))
    y_min = max(0, int(pts[:, 1].min()))
    x_max = min(ss_gray.shape[1], int(pts[:, 0].max()))
    y_max = min(ss_gray.shape[0], int(pts[:, 1].max()))

    bw = x_max - x_min
    bh = y_max - y_min
    if bw < 50 or bh < 30:
        log.debug("Bounding box too small (%dx%d)", bw, bh)
        return []

    confidence = round(min(1.0, inliers / max(len(good), 1)), 4)

    result = {
        "x": x_min,
        "y": y_min,
        "width": bw,
        "height": bh,
        "confidence": confidence,
        "method": "feature",
        "good_matches": len(good),
        "inliers": inliers,
    }
    log.debug(
        "Feature match at (%d,%d) %dx%d conf=%.3f inliers=%d",
        x_min, y_min, bw, bh, confidence, inliers,
    )
    return [result]


def find_asset_on_page(
    screenshot_bytes: bytes,
    asset_bytes: bytes,
    template_threshold: float = 0.70,
    feature_min_matches: int = 18,
    max_match_dim: int = DEFAULT_MAX_MATCH_DIM,
) -> List[Dict[str, Any]]:
    """
    Combined matching: try template matching first (faster, more precise
    for exact renders), fall back to feature matching (handles more
    visual variation).

    The screenshot is decoded once and downscaled so its longest side is at
    most ``max_match_dim`` px before matching (the asset is downscaled by the
    same factor to preserve relative scale). This bounds OpenCV cost on tall
    catalog pages; resulting bounding boxes are scaled back to full-page space.
    Pass ``max_match_dim=0`` to disable downscaling.

    Returns all found locations sorted by confidence.
    """
    results: List[Dict[str, Any]] = []

    try:
        ss_gray_full = _bytes_to_gray(screenshot_bytes)
        asset_gray_full = _bytes_to_gray(asset_bytes)
    except Exception as e:
        log.error("CV decode error: %s", e)
        return []

    factor = _downscale_factor(ss_gray_full, max_match_dim)
    ss_gray = _resize_gray(ss_gray_full, factor)
    asset_gray = _resize_gray(asset_gray_full, factor)
    if factor < 1.0:
        log.debug(
            "Downscaled screenshot %dx%d by %.3f for CV matching",
            ss_gray_full.shape[1], ss_gray_full.shape[0], factor,
        )

    try:
        t_matches = _template_match_gray(
            ss_gray, asset_gray, threshold=template_threshold,
        )
        results.extend(t_matches)
    except Exception as e:
        log.error("Template matching error: %s", e)

    try:
        f_matches = _feature_match_gray(
            ss_gray, asset_gray, min_good_matches=feature_min_matches,
        )
        for fm in f_matches:
            overlaps = False
            for existing in results:
                ox = max(0, min(fm["x"] + fm["width"], existing["x"] + existing["width"]) - max(fm["x"], existing["x"]))
                oy = max(0, min(fm["y"] + fm["height"], existing["y"] + existing["height"]) - max(fm["y"], existing["y"]))
                overlap_area = ox * oy
                smaller = min(fm["width"] * fm["height"], existing["width"] * existing["height"])
                if smaller > 0 and overlap_area / smaller > 0.5:
                    overlaps = True
                    break
            if not overlaps:
                results.extend(f_matches)
    except Exception as e:
        log.error("Feature matching error: %s", e)

    # Map bounding boxes from the downscaled match space back to full-page
    # screenshot coordinates so the caller crops the right region.
    if factor < 1.0 and results:
        inv = 1.0 / factor
        for r in results:
            r["x"] = int(r["x"] * inv)
            r["y"] = int(r["y"] * inv)
            r["width"] = int(r["width"] * inv)
            r["height"] = int(r["height"] * inv)

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results
