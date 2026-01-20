"""Scanning and analysis routes."""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Optional, Dict, Any
from uuid import UUID

from ..database import supabase
from ..models import ScanJobCreate, ScanJob, ScanSource
from ..services import apify_service, ai_service

router = APIRouter(prefix="/scans", tags=["scanning"])


@router.post("/start", response_model=ScanJob)
async def start_scan(
    scan_request: ScanJobCreate,
    background_tasks: BackgroundTasks
):
    """
    Start a new scan job.
    
    This will:
    1. Create a scan job record
    2. Trigger the appropriate Apify scraper
    3. Return the job ID for status tracking
    """
    # Create scan job record
    job_data = {
        "organization_id": str(scan_request.organization_id),
        "campaign_id": str(scan_request.campaign_id) if scan_request.campaign_id else None,
        "source": scan_request.source.value,
        "status": "pending"
    }
    
    result = supabase.table("scan_jobs").insert(job_data).execute()
    scan_job = result.data[0]
    scan_job_id = UUID(scan_job["id"])
    
    # Get distributors to scan
    if scan_request.distributor_ids:
        distributors = supabase.table("distributors")\
            .select("*")\
            .in_("id", [str(d) for d in scan_request.distributor_ids])\
            .execute()
    else:
        distributors = supabase.table("distributors")\
            .select("*")\
            .eq("organization_id", str(scan_request.organization_id))\
            .eq("status", "active")\
            .execute()
    
    distributor_list = distributors.data
    
    # Build distributor mappings
    if scan_request.source == ScanSource.GOOGLE_ADS:
        # Map advertiser names to distributor IDs
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in distributor_list]
        mapping = {
            (d.get("google_ads_advertiser_id") or d["name"]).lower(): UUID(d["id"])
            for d in distributor_list
        }
        
        print(f"[Scan] Starting Google Ads scan for {len(names)} advertisers")
        print(f"[Scan] Campaign ID for auto-analysis: {scan_request.campaign_id}")
        
        # Start scrape in background
        background_tasks.add_task(
            run_google_ads_scan,
            names,
            scan_job_id,
            mapping,
            scan_request.campaign_id  # Pass campaign_id for auto-analysis!
        )
        
    elif scan_request.source in [ScanSource.FACEBOOK, ScanSource.INSTAGRAM]:
        # Get Facebook URLs
        urls = [d["facebook_url"] for d in distributor_list if d.get("facebook_url")]
        mapping = {
            d["name"].lower(): UUID(d["id"])
            for d in distributor_list
        }
        
        print(f"[Scan] Starting Facebook scan for {len(urls)} pages")
        print(f"[Scan] Campaign ID for auto-analysis: {scan_request.campaign_id}")
        
        background_tasks.add_task(
            run_facebook_scan,
            urls,
            scan_job_id,
            mapping,
            scan_request.campaign_id  # Pass campaign_id for auto-analysis!
        )
        
    elif scan_request.source == ScanSource.WEBSITE:
        # Get website URLs
        urls = [d["website_url"] for d in distributor_list if d.get("website_url")]
        mapping = {
            d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: UUID(d["id"])
            for d in distributor_list if d.get("website_url")
        }
        
        print(f"[Scan] Starting website scan for {len(urls)} URLs: {urls}")
        print(f"[Scan] Campaign ID for auto-analysis: {scan_request.campaign_id}")
        
        background_tasks.add_task(
            run_website_scan,
            urls,
            scan_job_id,
            mapping,
            scan_request.campaign_id  # Pass campaign_id for auto-analysis!
        )
    
    return scan_job


async def run_google_ads_scan(
    advertiser_names: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None
):
    """Background task to run Google Ads scan."""
    try:
        run_id = await apify_service.start_google_ads_scrape(
            advertiser_names,
            scan_job_id
        )
        
        # Wait for completion (poll status)
        import asyncio
        while True:
            status = await apify_service.get_run_status(run_id)
            if status["status"] in ["SUCCEEDED", "FAILED", "ABORTED"]:
                break
            await asyncio.sleep(10)
        
        if status["status"] == "SUCCEEDED":
            await apify_service.process_google_ads_results(
                run_id,
                scan_job_id,
                distributor_mapping
            )
            # Auto-analyze if campaign is specified
            if campaign_id:
                try:
                    await auto_analyze_scan(scan_job_id, campaign_id)
                    supabase.table("scan_jobs").update({
                        "status": "completed",
                        "completed_at": "now()"
                    }).eq("id", str(scan_job_id)).execute()
                except Exception as analysis_error:
                    print(f"[Google Ads Scan] Analysis failed: {analysis_error}")
                    supabase.table("scan_jobs").update({
                        "status": "failed",
                        "error_message": f"Analysis failed: {str(analysis_error)}"
                    }).eq("id", str(scan_job_id)).execute()
            else:
                # No campaign - mark as completed without analysis
                supabase.table("scan_jobs").update({
                    "status": "completed",
                    "completed_at": "now()"
                }).eq("id", str(scan_job_id)).execute()
        else:
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": f"Apify run {status['status']}"
            }).eq("id", str(scan_job_id)).execute()
            
    except Exception as e:
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e)
        }).eq("id", str(scan_job_id)).execute()


async def run_facebook_scan(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None
):
    """Background task to run Facebook scan."""
    try:
        run_id = await apify_service.start_facebook_ads_scrape(
            page_urls,
            scan_job_id
        )
        
        import asyncio
        while True:
            status = await apify_service.get_run_status(run_id)
            if status["status"] in ["SUCCEEDED", "FAILED", "ABORTED"]:
                break
            await asyncio.sleep(10)
        
        if status["status"] == "SUCCEEDED":
            await apify_service.process_facebook_results(
                run_id,
                scan_job_id,
                distributor_mapping
            )
            # Auto-analyze if campaign is specified
            if campaign_id:
                try:
                    await auto_analyze_scan(scan_job_id, campaign_id)
                    supabase.table("scan_jobs").update({
                        "status": "completed",
                        "completed_at": "now()"
                    }).eq("id", str(scan_job_id)).execute()
                except Exception as analysis_error:
                    print(f"[Facebook Scan] Analysis failed: {analysis_error}")
                    supabase.table("scan_jobs").update({
                        "status": "failed",
                        "error_message": f"Analysis failed: {str(analysis_error)}"
                    }).eq("id", str(scan_job_id)).execute()
            else:
                # No campaign - mark as completed without analysis
                supabase.table("scan_jobs").update({
                    "status": "completed",
                    "completed_at": "now()"
                }).eq("id", str(scan_job_id)).execute()
        else:
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": f"Apify run {status['status']}"
            }).eq("id", str(scan_job_id)).execute()
            
    except Exception as e:
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e)
        }).eq("id", str(scan_job_id)).execute()


async def run_website_scan(
    website_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None
):
    """Background task to run website scan."""
    print(f"[Website Scan] Background task started for job {scan_job_id}")
    print(f"[Website Scan] URLs to scan: {website_urls}")
    print(f"[Website Scan] Campaign ID: {campaign_id}")
    
    try:
        run_id = await apify_service.start_website_crawl(
            website_urls,
            scan_job_id
        )
        
        print(f"[Website Scan] Apify run started: {run_id}")
        
        import asyncio
        poll_count = 0
        while True:
            status = await apify_service.get_run_status(run_id)
            poll_count += 1
            print(f"[Website Scan] Poll #{poll_count}: Status = {status['status']}")
            
            if status["status"] in ["SUCCEEDED", "FAILED", "ABORTED"]:
                break
            await asyncio.sleep(10)
        
        if status["status"] == "SUCCEEDED":
            print(f"[Website Scan] Apify run succeeded, processing results...")
            discovered_count = await apify_service.process_website_results(
                run_id,
                scan_job_id,
                distributor_mapping
            )
            print(f"[Website Scan] Processed results: {discovered_count} images discovered")
            
            # Auto-analyze if campaign is specified
            if campaign_id:
                print(f"[Website Scan] Starting auto-analysis for campaign {campaign_id}...")
                try:
                    await auto_analyze_scan(scan_job_id, campaign_id)
                    print(f"[Website Scan] Auto-analysis completed successfully")
                    # Mark as completed AFTER analysis succeeds
                    supabase.table("scan_jobs").update({
                        "status": "completed",
                        "completed_at": "now()"
                    }).eq("id", str(scan_job_id)).execute()
                except Exception as analysis_error:
                    print(f"[Website Scan] Auto-analysis FAILED: {analysis_error}")
                    import traceback
                    traceback.print_exc()
                    supabase.table("scan_jobs").update({
                        "status": "failed",
                        "error_message": f"Analysis failed: {str(analysis_error)}"
                    }).eq("id", str(scan_job_id)).execute()
            else:
                print(f"[Website Scan] No campaign_id provided, skipping auto-analysis")
                # Mark as completed (no analysis needed)
                supabase.table("scan_jobs").update({
                    "status": "completed",
                    "completed_at": "now()"
                }).eq("id", str(scan_job_id)).execute()
        else:
            print(f"[Website Scan] Apify run failed with status: {status['status']}")
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": f"Apify run {status['status']}"
            }).eq("id", str(scan_job_id)).execute()
            
    except Exception as e:
        print(f"[Website Scan] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e)
        }).eq("id", str(scan_job_id)).execute()


async def auto_analyze_scan(scan_job_id: UUID, campaign_id: UUID):
    """
    Automatically analyze discovered images after scan completion.
    
    This function is called automatically when a campaign-linked scan completes.
    It matches discovered images against campaign assets and performs compliance checks.
    """
    print(f"[Auto-Analyze] ========================================")
    print(f"[Auto-Analyze] Starting analysis for scan {scan_job_id}")
    print(f"[Auto-Analyze] Campaign ID: {campaign_id}")
    print(f"[Auto-Analyze] ========================================")
    
    try:
        # Get scan job details
        job = supabase.table("scan_jobs")\
            .select("*")\
            .eq("id", str(scan_job_id))\
            .single()\
            .execute()
        
        if not job.data:
            print(f"[Auto-Analyze] ERROR: Scan job {scan_job_id} not found")
            return
        
        print(f"[Auto-Analyze] Scan job found: {job.data.get('status')}")
        print(f"[Auto-Analyze] Organization ID: {job.data.get('organization_id')}")
        
        # Get unprocessed discovered images
        images = supabase.table("discovered_images")\
            .select("*")\
            .eq("scan_job_id", str(scan_job_id))\
            .eq("is_processed", False)\
            .execute()
        
        print(f"[Auto-Analyze] Found {len(images.data) if images.data else 0} unprocessed images")
        
        if not images.data:
            print(f"[Auto-Analyze] No unprocessed images found for scan {scan_job_id}")
            # Update scan job to show 0 processed
            supabase.table("scan_jobs").update({
                "processed_items": 0
            }).eq("id", str(scan_job_id)).execute()
            return
        
        # Log discovered images
        print(f"[Auto-Analyze] Discovered images to analyze:")
        for idx, img in enumerate(images.data):
            print(f"[Auto-Analyze]   [{idx+1}] ID: {img.get('id')}")
            print(f"[Auto-Analyze]       URL: {img.get('image_url', 'N/A')[:100]}...")
            print(f"[Auto-Analyze]       Source: {img.get('source_url', 'N/A')[:80]}")
            print(f"[Auto-Analyze]       Type: {img.get('source_type', 'N/A')}")
            print(f"[Auto-Analyze]       Channel: {img.get('channel', 'N/A')}")
        
        # Get campaign assets
        assets = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", str(campaign_id))\
            .execute()
        
        print(f"[Auto-Analyze] Found {len(assets.data) if assets.data else 0} campaign assets")
        
        if not assets.data:
            print(f"[Auto-Analyze] *** ERROR: No assets found for campaign {campaign_id} ***")
            print(f"[Auto-Analyze] Cannot perform audit without campaign assets to match against!")
            print(f"[Auto-Analyze] Please upload assets to the campaign first.")
            # Mark images as processed anyway to avoid re-processing
            for img in images.data:
                supabase.table("discovered_images").update({
                    "is_processed": True
                }).eq("id", img["id"]).execute()
            supabase.table("scan_jobs").update({
                "processed_items": len(images.data),
                "error_message": "No campaign assets to match against"
            }).eq("id", str(scan_job_id)).execute()
            return
        
        # Log campaign assets with accessibility check
        print(f"[Auto-Analyze] Campaign assets to match against:")
        for idx, asset in enumerate(assets.data):
            asset_url = asset.get('file_url', 'N/A')
            print(f"[Auto-Analyze]   [{idx+1}] ID: {asset.get('id')}")
            print(f"[Auto-Analyze]       Name: {asset.get('name', 'N/A')}")
            print(f"[Auto-Analyze]       URL: {asset_url[:100]}...")
            # Check if URL looks like a Supabase storage URL
            if 'supabase' in asset_url.lower() and '/storage/v1/' in asset_url:
                print(f"[Auto-Analyze]       WARNING: Supabase storage URL - ensure bucket is public")
        
        # Get brand rules
        rules = supabase.table("compliance_rules")\
            .select("*")\
            .eq("organization_id", job.data["organization_id"])\
            .eq("is_active", True)\
            .execute()
        
        print(f"[Auto-Analyze] Found {len(rules.data) if rules.data else 0} compliance rules")
        
        brand_rules = {}
        for rule in rules.data:
            if rule["rule_type"] == "required_element":
                brand_rules.setdefault("required_elements", []).append(
                    rule["rule_config"].get("element")
                )
            elif rule["rule_type"] == "forbidden_element":
                brand_rules.setdefault("forbidden_elements", []).append(
                    rule["rule_config"].get("element")
                )
        
        print(f"[Auto-Analyze] Brand rules: {brand_rules}")
        print(f"[Auto-Analyze] ----------------------------------------")
        print(f"[Auto-Analyze] Starting Gemini image analysis...")
        print(f"[Auto-Analyze] ----------------------------------------")
        
        # Run analysis
        await run_image_analysis(
            images.data, 
            assets.data, 
            brand_rules,
            job.data["organization_id"],
            str(scan_job_id)  # Pass scan_job_id for matches_count update
        )
        
        # Update scan job with processed count
        supabase.table("scan_jobs").update({
            "processed_items": len(images.data)
        }).eq("id", str(scan_job_id)).execute()
        
        print(f"[Auto-Analyze] ========================================")
        print(f"[Auto-Analyze] COMPLETED for scan {scan_job_id}")
        print(f"[Auto-Analyze] Processed: {len(images.data)} images")
        print(f"[Auto-Analyze] ========================================")
        
    except Exception as e:
        print(f"[Auto-Analyze] *** CRITICAL ERROR for scan {scan_job_id} ***")
        print(f"[Auto-Analyze] Error: {e}")
        import traceback
        traceback.print_exc()
        # Update scan job with error
        supabase.table("scan_jobs").update({
            "error_message": f"Analysis failed: {str(e)}"
        }).eq("id", str(scan_job_id)).execute()


@router.get("", response_model=List[ScanJob])
async def list_scan_jobs(
    organization_id: Optional[UUID] = None,
    status: Optional[str] = None,
    limit: int = 20
):
    """List scan jobs."""
    query = supabase.table("scan_jobs").select("*")
    
    if organization_id:
        query = query.eq("organization_id", str(organization_id))
    if status:
        query = query.eq("status", status)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/{job_id}", response_model=ScanJob)
async def get_scan_job(job_id: UUID):
    """Get scan job details."""
    result = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(job_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return result.data


@router.delete("/{job_id}")
async def delete_scan_job(job_id: UUID):
    """
    Delete a scan job and all its associated data.
    
    This will cascade delete:
    - discovered_images (via ON DELETE CASCADE)
    - matches linked to those discovered images (via ON DELETE CASCADE)
    """
    # First delete matches that reference discovered images from this scan
    discovered = supabase.table("discovered_images")\
        .select("id")\
        .eq("scan_job_id", str(job_id))\
        .execute()
    
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        supabase.table("matches")\
            .delete()\
            .in_("discovered_image_id", discovered_ids)\
            .execute()
    
    # Delete the scan job (discovered_images cascade automatically)
    result = supabase.table("scan_jobs")\
        .delete()\
        .eq("id", str(job_id))\
        .execute()
    
    return {"status": "deleted", "job_id": str(job_id)}


@router.delete("")
async def delete_all_scans():
    """
    Delete all scan jobs and associated data. Use with caution - for testing purposes.
    """
    # First delete all matches that reference discovered images
    supabase.table("matches")\
        .delete()\
        .neq("discovered_image_id", "00000000-0000-0000-0000-000000000000")\
        .execute()
    
    # Delete all scan jobs (discovered_images cascade automatically)
    result = supabase.table("scan_jobs")\
        .delete()\
        .neq("id", "00000000-0000-0000-0000-000000000000")\
        .execute()
    
    deleted_count = len(result.data) if result.data else 0
    
    return {"status": "deleted", "count": deleted_count}


@router.post("/{job_id}/analyze")
async def analyze_discovered_images(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    campaign_id: Optional[UUID] = None
):
    """
    Analyze discovered images from a completed scan.
    
    This will:
    1. Filter images with Gemini Flash
    2. Match against campaign assets
    3. Run compliance checks with Gemini Pro
    4. Create match records
    """
    # Get scan job
    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(job_id))\
        .single()\
        .execute()
    
    if not job.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    if job.data["status"] != "completed":
        raise HTTPException(status_code=400, detail="Scan job not completed yet")
    
    # Get unprocessed discovered images
    images = supabase.table("discovered_images")\
        .select("*")\
        .eq("scan_job_id", str(job_id))\
        .eq("is_processed", False)\
        .execute()
    
    if not images.data:
        return {"message": "No unprocessed images found", "count": 0}
    
    # Get campaign assets
    if campaign_id:
        assets = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", str(campaign_id))\
            .execute()
    else:
        # Get all assets for the organization
        assets = supabase.table("assets")\
            .select("*, campaigns!inner(organization_id)")\
            .eq("campaigns.organization_id", job.data["organization_id"])\
            .execute()
    
    # Get brand rules
    rules = supabase.table("compliance_rules")\
        .select("*")\
        .eq("organization_id", job.data["organization_id"])\
        .eq("is_active", True)\
        .execute()
    
    brand_rules = {}
    for rule in rules.data:
        if rule["rule_type"] == "required_element":
            brand_rules.setdefault("required_elements", []).append(
                rule["rule_config"].get("element")
            )
        elif rule["rule_type"] == "forbidden_element":
            brand_rules.setdefault("forbidden_elements", []).append(
                rule["rule_config"].get("element")
            )
    
    # Run analysis in background
    background_tasks.add_task(
        run_image_analysis,
        images.data,
        assets.data,
        brand_rules,
        job.data["organization_id"],
        str(job_id)  # Pass scan_job_id for matches_count update
    )
    
    return {
        "message": "Analysis started",
        "image_count": len(images.data),
        "asset_count": len(assets.data)
    }


async def run_image_analysis(
    discovered_images: List[Dict],
    campaign_assets: List[Dict],
    brand_rules: Dict[str, Any],
    organization_id: Optional[str] = None,
    scan_job_id: Optional[str] = None
):
    """Background task to analyze images and create matches."""
    print(f"[Image Analysis] ========================================")
    print(f"[Image Analysis] Starting analysis")
    print(f"[Image Analysis] - Images to analyze: {len(discovered_images)}")
    print(f"[Image Analysis] - Assets to match: {len(campaign_assets)}")
    print(f"[Image Analysis] - Organization: {organization_id}")
    print(f"[Image Analysis] - Scan Job ID: {scan_job_id}")
    print(f"[Image Analysis] ========================================")
    
    matches_created = 0
    violations_found = 0
    skipped = 0
    errors = 0
    
    for idx, image in enumerate(discovered_images):
        print(f"\n[Image Analysis] [{idx + 1}/{len(discovered_images)}] Processing image: {image['id']}")
        print(f"[Image Analysis]   URL: {image['image_url'][:100]}...")
        print(f"[Image Analysis]   Source Type: {image.get('source_type', 'unknown')}")
        print(f"[Image Analysis]   Channel: {image.get('channel', 'unknown')}")
        
        try:
            result = await ai_service.process_discovered_image(
                image["id"],
                image["image_url"],
                campaign_assets,
                brand_rules,
                source_type=image.get("source_type"),  # Pass source type for screenshot detection
                channel=image.get("channel")  # Pass channel for calibration
            )
            
            if result:
                print(f"[Image Analysis]   MATCH FOUND!")
                print(f"[Image Analysis]     Asset ID: {result['asset_id']}")
                print(f"[Image Analysis]     Confidence: {result['confidence_score']}%")
                print(f"[Image Analysis]     Match Type: {result['match_type']}")
                print(f"[Image Analysis]     Compliance: {result['compliance_status']}")
                
                # DEDUPLICATION DISABLED FOR TESTING - always create new match
                try:
                    match_record = supabase.table("matches").insert({
                        "asset_id": str(result["asset_id"]),
                        "discovered_image_id": image["id"],
                        "distributor_id": image.get("distributor_id"),
                        "confidence_score": result["confidence_score"],
                        "match_type": result["match_type"],
                        "is_modified": result["is_modified"],
                        "modifications": result["modifications"],
                        "channel": image.get("channel"),
                        "source_url": image.get("source_url"),
                        "screenshot_url": image.get("image_url"),  # The discovered image URL for visual comparison
                        "compliance_status": result["compliance_status"],
                        "compliance_issues": result["compliance_issues"],
                        "ai_analysis": result["ai_analysis"],
                        "discovered_at": image.get("discovered_at")
                    }).execute()
                    
                    print(f"[Image Analysis]     Match record created: {match_record.data[0]['id'] if match_record.data else 'unknown'}")
                    matches_created += 1
                    
                    # Create alert if violation
                    if result["compliance_status"] == "violation":
                        org_id = organization_id or image.get("organization_id")
                        if org_id:
                            supabase.table("alerts").insert({
                                "organization_id": org_id,
                                "match_id": match_record.data[0]["id"] if match_record.data else None,
                                "distributor_id": image.get("distributor_id"),
                                "alert_type": "compliance_violation",
                                "severity": "warning",
                                "title": f"Compliance violation detected",
                                "description": result["ai_analysis"].get("compliance", {}).get("summary", "")
                            }).execute()
                        violations_found += 1
                        print(f"[Image Analysis]     VIOLATION ALERT created!")
                except Exception as db_error:
                    print(f"[Image Analysis]     Failed to create match record: {db_error}")
                    errors += 1
            else:
                print(f"[Image Analysis]   No match (below threshold or not relevant)")
                skipped += 1
                # Only create matches for actual confident matches - no noise
            
            # Mark image as processed
            supabase.table("discovered_images").update({
                "is_processed": True
            }).eq("id", image["id"]).execute()
            
        except Exception as e:
            print(f"[Image Analysis]   ERROR: {e}")
            import traceback
            traceback.print_exc()
            errors += 1
            # Still mark as processed to avoid infinite retry loops
            supabase.table("discovered_images").update({
                "is_processed": True
            }).eq("id", image["id"]).execute()
            continue
    
    print(f"\n[Image Analysis] ========================================")
    print(f"[Image Analysis] ANALYSIS COMPLETE")
    print(f"[Image Analysis] ----------------------------------------")
    print(f"[Image Analysis] Total processed: {len(discovered_images)}")
    print(f"[Image Analysis] Matches created: {matches_created}")
    print(f"[Image Analysis] Violations found: {violations_found}")
    print(f"[Image Analysis] Skipped (no match): {skipped}")
    print(f"[Image Analysis] Errors: {errors}")
    print(f"[Image Analysis] ========================================")
    
    # Update scan job with matches count
    # Get scan_job_id from the first discovered image if not passed directly
    job_id = scan_job_id
    if not job_id and discovered_images:
        job_id = discovered_images[0].get("scan_job_id")
    
    if job_id:
        print(f"[Image Analysis] Updating scan job {job_id} with matches_count={matches_created}")
        supabase.table("scan_jobs").update({
            "matches_count": matches_created
        }).eq("id", str(job_id)).execute()


@router.post("/quick-scan")
async def quick_scan(
    organization_id: UUID,
    source: ScanSource,
    background_tasks: BackgroundTasks
):
    """
    Quick scan - starts a scan and immediately begins analysis.
    
    Convenience endpoint that combines start_scan and analyze.
    """
    # Create scan job
    job = await start_scan(
        ScanJobCreate(
            organization_id=organization_id,
            source=source
        ),
        background_tasks
    )
    
    return {
        "message": "Quick scan started",
        "job_id": job["id"],
        "source": source.value
    }


@router.post("/reprocess-unprocessed")
async def reprocess_unprocessed_images(
    campaign_id: UUID,
    background_tasks: BackgroundTasks,
    limit: int = 100
):
    """
    Reprocess images that were never analyzed.
    
    This handles cases where the auto-analysis failed or was interrupted.
    """
    # Get campaign info
    campaign = supabase.table("campaigns")\
        .select("organization_id")\
        .eq("id", str(campaign_id))\
        .single()\
        .execute()
    
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    organization_id = campaign.data["organization_id"]
    
    # Get unprocessed images (across all scans)
    unprocessed = supabase.table("discovered_images")\
        .select("*")\
        .eq("is_processed", False)\
        .limit(limit)\
        .execute()
    
    if not unprocessed.data:
        return {"message": "No unprocessed images found", "count": 0}
    
    # Get campaign assets
    assets = supabase.table("assets")\
        .select("*")\
        .eq("campaign_id", str(campaign_id))\
        .execute()
    
    if not assets.data:
        return {"message": "No campaign assets to match against", "count": 0}
    
    # Get brand rules
    rules = supabase.table("compliance_rules")\
        .select("*")\
        .eq("organization_id", organization_id)\
        .eq("is_active", True)\
        .execute()
    
    brand_rules = {}
    for rule in rules.data:
        if rule["rule_type"] == "required_element":
            brand_rules.setdefault("required_elements", []).append(
                rule["rule_config"].get("element")
            )
        elif rule["rule_type"] == "forbidden_element":
            brand_rules.setdefault("forbidden_elements", []).append(
                rule["rule_config"].get("element")
            )
    
    # Run analysis in background
    background_tasks.add_task(
        run_image_analysis,
        unprocessed.data,
        assets.data,
        brand_rules,
        organization_id
    )
    
    return {
        "message": "Reprocessing started",
        "image_count": len(unprocessed.data),
        "asset_count": len(assets.data)
    }


@router.get("/debug/{scan_id}")
async def debug_scan(scan_id: UUID):
    """
    Debug endpoint to inspect scan details and identify issues.
    
    Returns detailed information about:
    - Scan job status
    - Discovered images
    - Campaign assets
    - Matches created
    """
    # Get scan job
    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(scan_id))\
        .single()\
        .execute()
    
    if not job.data:
        return {"error": "Scan job not found"}
    
    # Get discovered images
    discovered = supabase.table("discovered_images")\
        .select("*")\
        .eq("scan_job_id", str(scan_id))\
        .execute()
    
    # Get campaign assets if campaign_id exists
    assets = []
    if job.data.get("campaign_id"):
        assets_result = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", job.data["campaign_id"])\
            .execute()
        assets = assets_result.data
    
    # Get matches for this scan's discovered images
    matches = []
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        matches_result = supabase.table("matches")\
            .select("*")\
            .in_("discovered_image_id", discovered_ids)\
            .execute()
        matches = matches_result.data
    
    # Build debug report
    return {
        "scan_job": {
            "id": job.data["id"],
            "status": job.data["status"],
            "source": job.data["source"],
            "campaign_id": job.data.get("campaign_id"),
            "total_items": job.data.get("total_items", 0),
            "processed_items": job.data.get("processed_items", 0),
            "matches_count": job.data.get("matches_count", 0),
            "error_message": job.data.get("error_message"),
            "apify_run_id": job.data.get("apify_run_id"),
        },
        "discovered_images": {
            "count": len(discovered.data) if discovered.data else 0,
            "processed": len([d for d in discovered.data if d.get("is_processed")]) if discovered.data else 0,
            "unprocessed": len([d for d in discovered.data if not d.get("is_processed")]) if discovered.data else 0,
            "images": [
                {
                    "id": d["id"],
                    "source_type": d.get("source_type"),
                    "channel": d.get("channel"),
                    "is_processed": d.get("is_processed"),
                    "image_url": d["image_url"][:100] + "..." if len(d["image_url"]) > 100 else d["image_url"],
                    "distributor_id": d.get("distributor_id"),
                }
                for d in (discovered.data or [])[:10]  # Limit to first 10
            ]
        },
        "campaign_assets": {
            "count": len(assets),
            "assets": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "file_url": a["file_url"][:100] + "..." if len(a["file_url"]) > 100 else a["file_url"],
                }
                for a in assets[:10]  # Limit to first 10
            ],
            "warning": "No campaign assets found - cannot match!" if len(assets) == 0 and job.data.get("campaign_id") else None
        },
        "matches": {
            "count": len(matches),
            "matches": [
                {
                    "id": m["id"],
                    "asset_id": m["asset_id"],
                    "confidence_score": m.get("confidence_score"),
                    "match_type": m.get("match_type"),
                    "compliance_status": m.get("compliance_status"),
                }
                for m in matches[:10]  # Limit to first 10
            ]
        },
        "diagnosis": {
            "has_campaign": job.data.get("campaign_id") is not None,
            "has_discovered_images": len(discovered.data) > 0 if discovered.data else False,
            "has_campaign_assets": len(assets) > 0,
            "has_matches": len(matches) > 0,
            "all_images_processed": all(d.get("is_processed") for d in discovered.data) if discovered.data else True,
            "issues": _get_scan_issues(job.data, discovered.data, assets, matches)
        }
    }


def _get_scan_issues(job, discovered, assets, matches):
    """Identify potential issues with the scan."""
    issues = []
    
    if not job.get("campaign_id"):
        issues.append("No campaign linked to scan - cannot match against assets")
    
    if not discovered:
        issues.append("No images were discovered during the scan")
    elif len(discovered) == 0:
        issues.append("Scan completed but no images found")
    
    if job.get("campaign_id") and len(assets) == 0:
        issues.append("Campaign has no assets uploaded - upload assets before scanning")
    
    if discovered and len(discovered) > 0 and len(matches) == 0:
        unprocessed = [d for d in discovered if not d.get("is_processed")]
        if len(unprocessed) > 0:
            issues.append(f"{len(unprocessed)} images haven't been processed yet")
        else:
            issues.append("All images processed but no matches found - assets may not match discovered images or thresholds too high")
    
    # Check for asset URL accessibility issues
    for asset in assets:
        url = asset.get("file_url", "")
        if "supabase" in url.lower() and "/storage/v1/" in url:
            if "public" not in url.lower():
                issues.append(f"Asset '{asset.get('name')}' may not be publicly accessible (private Supabase storage)")
    
    if job.get("status") == "failed":
        issues.append(f"Scan failed: {job.get('error_message', 'Unknown error')}")
    
    return issues if issues else ["No issues detected"]

