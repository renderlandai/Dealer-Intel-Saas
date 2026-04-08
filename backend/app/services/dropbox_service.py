"""Dropbox auto-sync — watch /Dealer Intel/ subfolders, auto-create campaigns, import images."""
import base64
import json
import logging
import time
import uuid as uuid_lib
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.dropbox")

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ROOT_FOLDER = "/Dealer Intel"


def _refresh_token(integration: Dict[str, Any]) -> Optional[str]:
    """Refresh an expired Dropbox access token. Returns new token or None."""
    settings = get_settings()
    refresh = integration.get("refresh_token")
    if not refresh:
        return None
    try:
        resp = httpx.post("https://api.dropboxapi.com/oauth2/token", data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": settings.dropbox_client_id,
            "client_secret": settings.dropbox_client_secret,
        }, timeout=15)
        new_token = resp.json().get("access_token")
        if new_token:
            supabase.table("integrations").update({
                "access_token": new_token,
            }).eq("id", integration["id"]).execute()
            return new_token
    except Exception as e:
        log.error("Dropbox token refresh failed: %s", e)
    return None


def _dbx_request(integration: Dict[str, Any], method: str, url: str, **kwargs) -> Optional[httpx.Response]:
    """Make a Dropbox API request with automatic token refresh on 401."""
    token = integration["access_token"]
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"

    resp = httpx.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)

    if resp.status_code == 401:
        new_token = _refresh_token(integration)
        if not new_token:
            return None
        integration["access_token"] = new_token
        headers["Authorization"] = f"Bearer {new_token}"
        resp = httpx.request(method, url, headers=headers, timeout=30, **kwargs)

    return resp


def _list_folder(integration: Dict[str, Any], path: str) -> List[Dict[str, Any]]:
    """List all entries in a Dropbox folder, handling pagination."""
    entries = []
    resp = _dbx_request(
        integration, "POST",
        "https://api.dropboxapi.com/2/files/list_folder",
        headers={"Content-Type": "application/json"},
        json={"path": path, "include_non_downloadable_files": False, "limit": 2000},
    )
    if not resp:
        log.error("Dropbox list_folder returned None for path '%s'", path)
        return entries
    if resp.status_code != 200:
        log.error("Dropbox list_folder %d for path '%s': %s", resp.status_code, path, resp.text[:300])
        return entries

    data = resp.json()
    entries.extend(data.get("entries", []))
    log.info("Dropbox list_folder '%s': found %d entries", path, len(entries))

    while data.get("has_more"):
        resp = _dbx_request(
            integration, "POST",
            "https://api.dropboxapi.com/2/files/list_folder/continue",
            headers={"Content-Type": "application/json"},
            json={"cursor": data["cursor"]},
        )
        if not resp or resp.status_code != 200:
            break
        data = resp.json()
        entries.extend(data.get("entries", []))

    return entries


def _import_image(integration: Dict[str, Any], entry: Dict[str, Any], campaign_id: str) -> bool:
    """Download a single image from Dropbox and create an asset record."""
    name = entry["name"]
    dbx_path = entry["path_lower"]

    api_arg = json.dumps({"path": dbx_path}, ensure_ascii=True)
    dl_resp = _dbx_request(
        integration, "POST",
        "https://content.dropboxapi.com/2/files/download",
        headers={"Dropbox-API-Arg": api_arg},
    )
    if not dl_resp:
        log.error("Download returned None for '%s'", dbx_path)
        return False
    if dl_resp.status_code != 200:
        log.error("Download failed %d for '%s': %s", dl_resp.status_code, dbx_path, dl_resp.text[:200])
        return False

    content = dl_resp.content
    ext = name.rsplit(".", 1)[-1].lower()
    content_type = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp",
    }.get(ext, "image/png")

    timestamp = int(time.time() * 1000)
    random_id = uuid_lib.uuid4().hex[:12]
    storage_path = f"assets/{campaign_id}/{timestamp}_{random_id}_{name}"

    file_url = None
    try:
        bucket = supabase.storage.from_("campaign-assets")
        bucket.upload(
            path=storage_path, file=content,
            file_options={"contentType": content_type, "upsert": "true"},
        )
        file_url = bucket.get_public_url(storage_path)
    except Exception:
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

    return True


def auto_sync_org(integration: Dict[str, Any]) -> Dict[str, Any]:
    """
    Full auto-sync for one org's Dropbox integration.
    
    Scans /Dealer Intel/ subfolders:
    - New subfolder → create campaign + folder mapping
    - New images in mapped subfolders → import as assets
    """
    org_id = integration["organization_id"]
    integration_id = integration["id"]

    # Ensure /Dealer Intel/ exists
    _dbx_request(
        integration, "POST",
        "https://api.dropboxapi.com/2/files/create_folder_v2",
        headers={"Content-Type": "application/json"},
        json={"path": ROOT_FOLDER, "autorename": False},
    )

    root_entries = _list_folder(integration, ROOT_FOLDER.lower())
    subfolders = [e for e in root_entries if e.get(".tag") == "folder"]

    # Load existing mappings
    existing_mappings = supabase.table("dropbox_folder_mappings")\
        .select("id, folder_path, campaign_id")\
        .eq("integration_id", integration_id)\
        .execute()
    mapped_paths = {m["folder_path"]: m for m in (existing_mappings.data or [])}

    campaigns_created = 0
    images_imported = 0
    images_skipped = 0

    for folder in subfolders:
        folder_path = folder["path_lower"]
        folder_name = folder["name"]

        if folder_path in mapped_paths:
            campaign_id = mapped_paths[folder_path]["campaign_id"]
        else:
            # Auto-create campaign
            try:
                result = supabase.table("campaigns").insert({
                    "name": folder_name,
                    "organization_id": org_id,
                    "description": f"Auto-created from Dropbox folder: {folder_name}",
                }).execute()
                campaign_id = result.data[0]["id"]
                campaigns_created += 1

                supabase.table("dropbox_folder_mappings").insert({
                    "integration_id": integration_id,
                    "organization_id": org_id,
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "campaign_id": campaign_id,
                }).execute()

                log.info("Auto-created campaign '%s' for Dropbox folder '%s'", folder_name, folder_path)
            except Exception as e:
                log.error("Failed to create campaign for folder '%s': %s", folder_name, e)
                continue

        # Get existing asset names for this campaign
        existing = supabase.table("assets")\
            .select("name")\
            .eq("campaign_id", campaign_id)\
            .execute()
        existing_names = {r["name"] for r in (existing.data or [])}

        # List images in this subfolder
        folder_entries = _list_folder(integration, folder_path)
        log.info(
            "Subfolder '%s': %d total entries, tags: %s",
            folder_path, len(folder_entries),
            [f"{e.get('name')} ({e.get('.tag')})" for e in folder_entries[:10]],
        )

        image_entries = [
            e for e in folder_entries
            if e.get(".tag") == "file"
            and e.get("name", "").rsplit(".", 1)[-1].lower() in IMAGE_EXTENSIONS
            and e.get("size", 0) <= MAX_FILE_SIZE
        ]
        log.info("Subfolder '%s': %d images after filter", folder_path, len(image_entries))

        for img in image_entries:
            if img["name"] in existing_names:
                images_skipped += 1
                continue
            try:
                success = _import_image(integration, img, campaign_id)
                if success:
                    existing_names.add(img["name"])
                    images_imported += 1
                    log.info("Imported '%s' into campaign %s", img["name"], campaign_id)
                else:
                    log.warning("_import_image returned False for '%s'", img["name"])
            except Exception as e:
                log.error("Failed to import %s: %s", img["name"], e)

    # Update last_synced_at
    supabase.table("integrations").update({
        "last_synced_at": "now()",
    }).eq("id", integration_id).execute()

    log.info(
        "Dropbox auto-sync for org %s: %d campaigns created, %d images imported, %d skipped",
        org_id, campaigns_created, images_imported, images_skipped,
    )

    return {
        "campaigns_created": campaigns_created,
        "images_imported": images_imported,
        "images_skipped": images_skipped,
    }


def sync_dropbox_folder(
    *,
    organization_id: UUID,
    access_token: str,
    refresh_token: str,
    folder_path: str,
    campaign_id: str,
) -> Dict[str, Any]:
    """Legacy manual sync — kept for backward compat with the manual sync button."""
    integration = {
        "id": None,
        "organization_id": str(organization_id),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

    existing = supabase.table("assets")\
        .select("name")\
        .eq("campaign_id", campaign_id)\
        .execute()
    existing_names = {r["name"] for r in (existing.data or [])}

    folder_entries = _list_folder(integration, folder_path)
    image_entries = [
        e for e in folder_entries
        if e.get(".tag") == "file"
        and e.get("name", "").rsplit(".", 1)[-1].lower() in IMAGE_EXTENSIONS
        and e.get("size", 0) <= MAX_FILE_SIZE
    ]

    imported = 0
    skipped = 0
    errors = 0

    for img in image_entries:
        if img["name"] in existing_names:
            skipped += 1
            continue
        try:
            if _import_image(integration, img, campaign_id):
                existing_names.add(img["name"])
                imported += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_images": len(image_entries),
        "message": f"Imported {imported} asset{'s' if imported != 1 else ''}, skipped {skipped} existing",
    }
