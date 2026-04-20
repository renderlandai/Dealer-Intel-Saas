"""Pull labelled cases from production Supabase data into the local
fixture set.

Strategy:

  1. Pull rows from ``match_feedback`` (the user-feedback table that
     already exists in production — see
     ``supabase/migrations/004_add_match_feedback.sql``).
  2. Join through ``matches`` → ``assets`` + ``discovered_images`` to
     resolve the asset and discovered image URLs.
  3. Download both image files into ``fixtures/images/`` so the eval is
     reproducible even after the source URLs rot.
  4. Map each ``actual_verdict`` value to a manifest category and write
     the case to ``manifest.json``.

This script is INTERACTIVE in the sense that it does not overwrite
images or manifest entries that already exist — it only appends new
cases.  After it runs you should review the generated manifest and
hand-correct categories where the auto-mapping was too coarse.

Usage::

    # Pull up to 50 cases (default) — needs Supabase service role key.
    python -m eval.build_fixtures

    # Pull more cases.
    python -m eval.build_fixtures --limit 200

    # Pull only false-positive feedback (most useful for borderline tests).
    python -m eval.build_fixtures --verdict false_positive --limit 30

    # Skip the download step (dry-run).
    python -m eval.build_fixtures --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx

from .config import load_config
from .manifest import CATEGORIES, Expected, FixtureCase, Manifest

log = logging.getLogger("eval.build_fixtures")


# --- verdict → manifest category ---------------------------------------
#
# match_feedback.actual_verdict has 4 values:
#   - true_positive   → caught a real match (clear/template/modified positive)
#   - false_positive  → flagged something that wasn't a match
#   - true_negative   → correctly rejected
#   - false_negative  → missed a real match
#
# We can't perfectly auto-map these to the 10 manifest categories without
# human review, but we can pick a sensible default that the human
# labeller can refine.
_VERDICT_TO_CATEGORY: Dict[str, str] = {
    "true_positive":  "clear_positive",
    "false_positive": "borderline_false",
    "true_negative":  "different_brand",
    "false_negative": "modified_positive",
}


def _supabase_headers(service_role_key: str) -> Dict[str, str]:
    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _fetch_feedback_rows(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    limit: int,
    verdict_filter: Optional[str],
) -> List[Dict[str, Any]]:
    """Return rows joined with match → asset + discovered_image."""
    select_expr = (
        "id,was_correct,actual_verdict,ai_confidence,source_type,channel,match_type,"
        "match_id,created_at,"
        "match:match_id("
            "id,confidence_score,asset:asset_id(id,file_url,name),"
            "discovered_image:discovered_image_id(id,image_url,source_url),"
            "channel,source_url,screenshot_url"
        ")"
    )
    params: Dict[str, Any] = {
        "select": select_expr,
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if verdict_filter:
        params["actual_verdict"] = f"eq.{verdict_filter}"

    url = f"{base_url}/rest/v1/match_feedback"
    resp = await client.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json() or []


_DATA_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _decode_data_uri(url: str) -> tuple[bytes, Optional[str]]:
    """Return (bytes, ext) for a data: URI, or raise ValueError."""
    if not url.startswith("data:"):
        raise ValueError("not a data URI")
    try:
        header, payload = url.split(",", 1)
    except ValueError as e:
        raise ValueError("malformed data URI (no comma)") from e
    meta = header[5:]
    is_base64 = meta.endswith(";base64")
    mime = meta.split(";", 1)[0].strip().lower() if meta else ""
    ext = _DATA_MIME_TO_EXT.get(mime)
    if is_base64:
        try:
            data = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"base64 decode failed: {e}") from e
    else:
        data = unquote(payload).encode("latin-1", errors="ignore")
    return data, ext


async def _download(client: httpx.AsyncClient, url: str, dest: Path) -> None:
    if dest.exists():
        return
    if url.startswith("data:"):
        data, _ext = _decode_data_uri(url)
        if not data:
            raise ValueError("data URI decoded to empty bytes")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return
    resp = await client.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)


def _row_to_case(row: Dict[str, Any]) -> Optional[FixtureCase]:
    match = row.get("match") or {}
    asset = match.get("asset") or {}
    discovered = match.get("discovered_image") or {}

    asset_url = asset.get("file_url")
    discovered_url = (
        discovered.get("image_url")
        or match.get("screenshot_url")
        or discovered.get("source_url")
    )
    if not asset_url or not discovered_url:
        return None

    verdict = (row.get("actual_verdict") or "").lower()
    category = _VERDICT_TO_CATEGORY.get(verdict, "borderline_false")

    feedback_id = row.get("id")
    case_id = f"feedback-{feedback_id}"

    expected = Expected(
        is_relevant=True,  # if it reached match_feedback it survived the filter
        is_match=verdict in ("true_positive", "false_negative"),
    )

    return FixtureCase(
        id=case_id,
        category=category,
        # Filled in below once we know the on-disk filename.
        asset_path="",
        discovered_path="",
        expected=expected,
        notes=(
            f"Auto-imported from match_feedback verdict={verdict}. "
            f"REVIEW + RECATEGORISE before trusting."
        ),
        source={
            "feedback_id": feedback_id,
            "match_id": row.get("match_id"),
            "ai_confidence": row.get("ai_confidence"),
            "channel": row.get("channel"),
            "source_type": row.get("source_type"),
            "asset_url": asset_url,
            "discovered_url": discovered_url,
            "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )


def _ext_from_url(url: str) -> str:
    if url.startswith("data:"):
        try:
            _data, ext = _decode_data_uri(url)
        except ValueError:
            return ".jpg"
        return ext or ".jpg"
    lower = url.lower().split("?", 1)[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if lower.endswith(ext):
            return ext
    return ".jpg"  # Safe default; PIL will sniff the actual format.


async def _build(args) -> int:
    cfg = load_config()
    base_url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not base_url or not key:
        log.error(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the "
            "environment to pull labelled cases."
        )
        return 3

    cfg.images_dir.mkdir(parents=True, exist_ok=True)

    # Load existing manifest if present so we append rather than overwrite.
    if cfg.manifest_path.exists():
        manifest = Manifest.load(cfg.manifest_path)
        existing_ids = {c.id for c in manifest.cases}
    else:
        manifest = Manifest()
        existing_ids = set()

    headers = _supabase_headers(key)
    async with httpx.AsyncClient() as client:
        rows = await _fetch_feedback_rows(
            client, base_url, headers,
            limit=args.limit, verdict_filter=args.verdict,
        )
        log.info("Fetched %d feedback rows from Supabase.", len(rows))

        added = 0
        skipped = 0
        for row in rows:
            case = _row_to_case(row)
            if case is None:
                skipped += 1
                continue
            if case.id in existing_ids:
                skipped += 1
                continue

            asset_url = case.source["asset_url"]
            discovered_url = case.source["discovered_url"]
            asset_filename = f"asset_{case.id}{_ext_from_url(asset_url)}"
            disc_filename = f"discovered_{case.id}{_ext_from_url(discovered_url)}"
            case.asset_path = f"images/{asset_filename}"
            case.discovered_path = f"images/{disc_filename}"

            if not args.dry_run:
                try:
                    await _download(client, asset_url, cfg.images_dir / asset_filename)
                    await _download(client, discovered_url, cfg.images_dir / disc_filename)
                except Exception as e:  # noqa: BLE001
                    log.warning("Skipping %s — download failed: %s", case.id, e)
                    skipped += 1
                    continue

            manifest.cases.append(case)
            existing_ids.add(case.id)
            added += 1

    if args.dry_run:
        log.info("DRY RUN — would add %d cases (skipped %d).", added, skipped)
        return 0

    manifest.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest.save(cfg.manifest_path)
    log.info(
        "Wrote %s — %d new case(s) added, %d skipped, %d total.",
        cfg.manifest_path, added, skipped, len(manifest.cases),
    )
    log.info("REVIEW the manifest and re-categorise auto-imported cases:")
    log.info("  Categories available: %s", ", ".join(CATEGORIES))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval.build_fixtures",
        description="Seed eval fixtures from production match_feedback data.",
    )
    parser.add_argument("--limit", type=int, default=50,
                        help="Max rows to pull (default: 50).")
    parser.add_argument(
        "--verdict",
        choices=["true_positive", "false_positive", "true_negative", "false_negative"],
        help="Restrict to one verdict type (default: all).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't download images or write the manifest.")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    return asyncio.run(_build(args))


if __name__ == "__main__":
    sys.exit(main())
