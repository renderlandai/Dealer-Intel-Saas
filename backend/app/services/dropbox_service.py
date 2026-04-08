"""Dropbox asset sync — pull images from a folder and import as campaign assets."""
import base64
import logging
import time
import uuid as uuid_lib
from typing import Any, Dict
from uuid import UUID

import httpx

from ..database import supabase

log = logging.getLogger("dealer_intel.dropbox")

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def sync_dropbox_folder(
    *,
    organization_id: UUID,
    access_token: str,
    refresh_token: str,
    folder_path: str,
    campaign_id: str,
) -> Dict[str, Any]:
    """List images in a Dropbox folder and import new ones as campaign assets."""

    existing = supabase.table("assets")\
        .select("name")\
        .eq("campaign_id", campaign_id)\
        .execute()
    existing_names = {r["name"] for r in (existing.data or [])}

    try:
        resp = httpx.post(
            "https://api.dropboxapi.com/2/files/list_folder",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"path": folder_path, "include_non_downloadable_files": False, "limit": 200},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        log.error("Dropbox list_folder failed: %s", e)
        return {"imported": 0, "skipped": 0, "errors": 1, "message": "Failed to list Dropbox folder"}

    entries = data.get("entries", [])
    image_files = [
        e for e in entries
        if e.get(".tag") == "file"
        and e.get("name", "").rsplit(".", 1)[-1].lower() in IMAGE_EXTENSIONS
        and e.get("size", 0) <= MAX_FILE_SIZE
    ]

    imported = 0
    skipped = 0
    errors = 0

    for entry in image_files:
        name = entry["name"]
        dbx_path = entry["path_lower"]

        if name in existing_names:
            skipped += 1
            continue

        try:
            dl_resp = httpx.post(
                "https://content.dropboxapi.com/2/files/download",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Dropbox-API-Arg": f'{{"path": "{dbx_path}"}}',
                },
                timeout=30,
            )
            if dl_resp.status_code != 200:
                log.warning("Dropbox download failed for %s: %d", name, dl_resp.status_code)
                errors += 1
                continue

            content = dl_resp.content
            ext = name.rsplit(".", 1)[-1].lower()
            content_type = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
            }.get(ext, "image/png")

            timestamp = int(time.time() * 1000)
            random_id = uuid_lib.uuid4().hex[:12]
            storage_path = f"assets/{campaign_id}/{timestamp}_{random_id}_{name}"

            file_url = None
            try:
                bucket = supabase.storage.from_("campaign-assets")
                bucket.upload(
                    path=storage_path,
                    file=content,
                    file_options={"contentType": content_type, "upsert": "true"},
                )
                file_url = bucket.get_public_url(storage_path)
            except Exception as storage_err:
                log.warning("Storage upload failed for %s, using base64: %s", name, storage_err)
                b64 = base64.b64encode(content).decode("utf-8")
                file_url = f"data:{content_type};base64,{b64}"

            supabase.table("assets").insert({
                "campaign_id": campaign_id,
                "name": name,
                "file_url": file_url,
                "file_type": content_type,
                "file_size": len(content),
                "metadata": {"source": "dropbox", "dropbox_path": dbx_path},
            }).execute()

            existing_names.add(name)
            imported += 1
            log.info("Imported asset from Dropbox: %s", name)

        except Exception as e:
            log.error("Failed to import %s from Dropbox: %s", name, e)
            errors += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_images": len(image_files),
        "message": f"Imported {imported} asset{'s' if imported != 1 else ''}, skipped {skipped} existing",
    }
