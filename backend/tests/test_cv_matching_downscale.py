"""Regression tests for the 2026-06-05 CV-matching cost guardrail.

Tall rental/catalog pages produced 1920x20000+ full-page screenshots. Running
``cv2.matchTemplate`` against the full-resolution screenshot for every campaign
asset (a) cost minutes of CPU and (b) was called inline on the event loop, so
the per-page extract sub-cap (120s) could not cancel it — pages ran ~186s and
froze every other concurrent dealer, returning 0 images.

``find_asset_on_page`` now downscales the screenshot below ``max_match_dim``
before matching and scales the resulting bounding box back to full-page space.
These tests pin that the coordinate round-trip stays correct.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from app.services import cv_matching


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _distinctive_asset(w: int = 300, h: int = 150) -> np.ndarray:
    """A structured patch (large color blocks) with a single, unambiguous
    template peak. Uses low-frequency structure so it survives the area-average
    downscale the matcher now applies — exactly like a real hero creative."""
    arr = np.full((h, w, 3), fill_value=200, dtype=np.uint8)
    arr[0:h // 2, 0:w // 2] = (210, 30, 30)
    arr[h // 2:h, w // 2:w] = (30, 30, 210)
    arr[h // 4:3 * h // 4, w // 3:2 * w // 3] = (250, 220, 30)
    return arr


def _tall_page_with_asset(asset_arr: np.ndarray, x0: int, y0: int,
                          page_w: int = 1920, page_h: int = 9000) -> bytes:
    """Flat page with the asset pasted at (x0, y0)."""
    page = np.full((page_h, page_w, 3), fill_value=200, dtype=np.uint8)
    h, w = asset_arr.shape[:2]
    page[y0:y0 + h, x0:x0 + w] = asset_arr
    return _png_bytes(Image.fromarray(page))


def test_downscaled_match_maps_back_to_full_page_coords():
    asset_arr = _distinctive_asset()
    x0, y0 = 600, 7000
    screenshot = _tall_page_with_asset(asset_arr, x0, y0)
    asset = _png_bytes(Image.fromarray(asset_arr))

    # Default cap (4000) forces a ~0.44 downscale of the 9000px-tall page.
    matches = cv_matching.find_asset_on_page(screenshot, asset)

    assert matches, "asset pasted at full scale should be located"
    best = matches[0]
    # Coordinates must be reported in FULL-PAGE space, not downscaled space.
    assert abs(best["x"] - x0) <= 60, best
    assert abs(best["y"] - y0) <= 60, best
    assert abs(best["width"] - asset_arr.shape[1]) <= 60, best
    assert abs(best["height"] - asset_arr.shape[0]) <= 60, best


def test_disabling_cap_keeps_full_resolution_coords():
    asset_arr = _distinctive_asset()
    x0, y0 = 400, 1500
    # Page short enough that even with the cap there is no downscale; assert the
    # disabled path also returns correct coordinates.
    screenshot = _tall_page_with_asset(asset_arr, x0, y0, page_h=2000)
    asset = _png_bytes(Image.fromarray(asset_arr))

    matches = cv_matching.find_asset_on_page(screenshot, asset, max_match_dim=0)

    assert matches, "asset should be located with downscaling disabled"
    best = matches[0]
    assert abs(best["x"] - x0) <= 10, best
    assert abs(best["y"] - y0) <= 10, best
