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


def template_match(
    screenshot_bytes: bytes,
    asset_bytes: bytes,
    scale_range: Tuple[float, float] = (0.10, 1.8),
    scale_steps: int = 50,
    threshold: float = 0.40,
) -> List[Dict[str, Any]]:
    """
    Find the asset in the screenshot using multi-scale normalised
    cross-correlation.

    Uses denser sampling at smaller scales (0.10–0.5) where web renders
    most commonly resize creatives, and coarser steps at larger scales.

    Returns a list of match dicts sorted by confidence (highest first).
    Each dict: {x, y, width, height, confidence, method}.
    """
    screenshot = _bytes_to_cv(screenshot_bytes)
    asset = _bytes_to_cv(asset_bytes)
    ss_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    asset_gray = cv2.cvtColor(asset, cv2.COLOR_BGR2GRAY)

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
    min_good_matches: int = 8,
    ratio_thresh: float = 0.78,
) -> List[Dict[str, Any]]:
    """
    Find the asset in the screenshot using ORB keypoint detection
    and brute-force Hamming matching with Lowe's ratio test.

    Returns a list of match dicts (usually 0 or 1 items).
    Each dict: {x, y, width, height, confidence, method, good_matches}.
    """
    screenshot = _bytes_to_cv(screenshot_bytes)
    asset = _bytes_to_cv(asset_bytes)
    ss_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    asset_gray = cv2.cvtColor(asset, cv2.COLOR_BGR2GRAY)

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
    if inliers < min_good_matches // 2:
        log.debug("Too few inliers (%d)", inliers)
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
    template_threshold: float = 0.40,
    feature_min_matches: int = 8,
) -> List[Dict[str, Any]]:
    """
    Combined matching: try template matching first (faster, more precise
    for exact renders), fall back to feature matching (handles more
    visual variation).

    Returns all found locations sorted by confidence.
    """
    results: List[Dict[str, Any]] = []

    try:
        t_matches = template_match(
            screenshot_bytes, asset_bytes,
            threshold=template_threshold,
        )
        results.extend(t_matches)
    except Exception as e:
        log.error("Template matching error: %s", e)

    try:
        f_matches = feature_match(
            screenshot_bytes, asset_bytes,
            min_good_matches=feature_min_matches,
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

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results
