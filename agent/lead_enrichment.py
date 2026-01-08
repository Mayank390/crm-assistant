# lead_enrichment.py — FINAL 2025: CLEAN RESPONSE + 1 DOWNLOAD LINK + NO DUPLICATES

from __future__ import annotations
import csv
import io
import logging
import os
from dataclasses import dataclass
from typing import List, Dict
from urllib.parse import urlparse
import asyncio
import httpx
from langchain_core.tools import tool
from agent.tools import get_generation_websocket
from azure.storage.blob import (BlobServiceClient, ContentSettings,generate_blob_sas, BlobSasPermissions)
from datetime import datetime, timedelta
import re
import json
#from websocket_handler import WebSocketManager as ws_manager

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class LeadEnrichmentConfig:
    serpapi_key: str = os.getenv("SERPAPI_KEY", "").strip()

# Global cache for coordinates
_coords_cache: Dict[str, str] = {}

IMPORT_INTENT_RE = re.compile(
    r'\b(import|add|push|upload|save|store|insert|put)\b.*\b(crm|database|system|leads?)\b'
    r'|\b(to|into|in)\s+(crm|database|system|my\s+crm)\b'
    r'|\bimport\s+(to|into|in|them|these|those)\b',
    re.IGNORECASE
)

'''async def upload_to_tmpfiles(csv_content: str) -> str:
    """Upload CSV to free file hosting service and return download URL"""
    filename = f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # Try transfer.sh first (10GB limit, 14 days, direct download)
    try:
        url = f"https://transfer.sh/{filename}"
        headers = {'Content-Type': 'text/csv'}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(url, content=csv_content.encode('utf-8'), headers=headers)
            if resp.status_code == 200:
                download_url = resp.text.strip()
                logger.info(f"Successfully uploaded to transfer.sh: {download_url}")
                return download_url
    except Exception as e:
        logger.warning(f"transfer.sh failed: {e}")

    # Fallback to file.io (2GB limit, 14 days)
    try:
        data = {"expires": "1w"}  # 1 week expiry
        files = {'file': (filename, csv_content.encode('utf-8'), 'text/csv')}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://file.io/", data=data, files=files)
            result = resp.json()
            if result.get("success"):
                download_url = result["link"]
                logger.info(f"Successfully uploaded to file.io: {download_url}")
                return download_url
    except Exception as e:
        logger.warning(f"file.io failed: {e}")

    # Last fallback to tmpfiles.org - try to get direct download URL
    try:
        files = {'file': (filename, csv_content.encode('utf-8'), 'text/csv')}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://tmpfiles.org/api/v1/upload", files=files)
            data = resp.json()
            if data.get("status") == "success":
                view_url = data["data"]["url"]
                # Try to convert view URL to direct download URL
                # tmpfiles.org view URLs are like: https://tmpfiles.org/dl/xxxxx/filename.csv
                # Direct download URLs are like: https://tmpfiles.org/download/xxxxx/filename.csv
                if "tmpfiles.org/" in view_url:
                    # Replace 'dl' with 'download' in the URL to get direct download
                    download_url = view_url.replace("/dl/", "/download/")
                    logger.info(f"Successfully uploaded to tmpfiles.org: {download_url}")
                    return download_url
                else:
                    # Fallback to view URL if we can't convert
                    logger.warning(f"Could not convert tmpfiles.org view URL to download URL, using view URL: {view_url}")
                    return view_url
    except Exception as e:
        logger.error(f"tmpfiles.org failed: {e}")

    # If all services fail, raise an exception instead of returning None
    raise Exception("All file upload services failed. Unable to generate download link for leads.")'''

def generate_csv(leads: List[dict]) -> str:
    if not leads:
        return ""

    fieldnames = sorted({k for lead in leads for k in lead.keys()})

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore"
    )

    writer.writeheader()
    writer.writerows(leads)
    return output.getvalue()

async def upload_csv_to_azure(csv_content: str) -> str:
    logger.info("Starting async Azure CSV upload")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _upload_csv_to_azure_sync,
        csv_content
    )


def _upload_csv_to_azure_sync(csv_content: str) -> str:

    account = os.environ["AZURE_STORAGE_ACCOUNT"]
    key = os.environ["AZURE_STORAGE_KEY"]
    container = os.environ["AZURE_STORAGE_CONTAINER"]

    filename = f"leads_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    blob_service = BlobServiceClient(
        account_url=f"https://{account}.blob.core.windows.net",
        credential=key
    )

    blob_client = blob_service.get_blob_client(
        container=container,
        blob=filename
    )

    blob_client.upload_blob(
        csv_content.encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="text/csv",
            content_disposition=f'attachment; filename="{filename}"'
        )
    )

    sas = generate_blob_sas(
        account_name=account,
        container_name=container,
        blob_name=filename,
        account_key=key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(minutes=10)
    )


    return f"https://{account}.blob.core.windows.net/{container}/{filename}?{sas}"


# Add logging function to debug import intent detection
def check_import_intent(user_query: str) -> bool:
    """Check if user query contains import intent with detailed logging."""
    has_intent = bool(IMPORT_INTENT_RE.search(user_query))
    
    logger.info(f"[check_import_intent] Query: '{user_query}'")
    logger.info(f"[check_import_intent] Has import intent: {has_intent}")
    
    if has_intent:
        match = IMPORT_INTENT_RE.search(user_query)
        if match:
            logger.info(f"[check_import_intent] Matched pattern: '{match.group()}'")
    
    return has_intent


async def get_optimal_ll(business_type: str, area: str, city: str, cfg: LeadEnrichmentConfig) -> str:
    key = f"{area}|{city}".strip("|").lower()
    if key in _coords_cache:
        return _coords_cache[key]

    location = area if area and area.lower() != city.lower() else city
    params = {"engine": "google_maps", "q": f"{business_type} in {location}", "type": "search", "gl": "in", "num": 1, "api_key": cfg.serpapi_key}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            data = resp.json()
            first = data.get("local_results", [{}])[0]
            lat = first.get("gps_coordinates", {}).get("latitude")
            lng = first.get("gps_coordinates", {}).get("longitude")
            if lat and lng:
                result = f"@{lat},{lng},18z"
                _coords_cache[key] = result
                return result
    except:
        pass

    fallback = {"gachibowli": "@17.4486,78.3911,18z", "koramangala": "@12.9279,77.6285,18z"}
    result = fallback.get(area.lower(), "@17.3850,78.4867,16z")
    _coords_cache[key] = result
    return result

def is_trash_directory_url(url: str) -> bool:
    if not url or not url.startswith("http"): return True
    trash = {"justdial", "sulekha", "indiamart", "magicbricks", "99acres", "facebook", "instagram"}
    return any(domain in urlparse(url).netloc.lower() for domain in trash)

async def _emit(stage: str, completed: int, total: int, message: str):
    ws = get_generation_websocket()
    if ws:
        try:
            await ws.send_json({"type": "pipeline_progress", "stage": stage, "completed": completed, "total": total, "message": message})
        except: pass

async def _complete(leads: List[dict]):
    ws = get_generation_websocket()
    if ws:
        try:
            await ws.send_json({"type": "pipeline_complete", "leads": leads})
        except: pass

async def _get_leads_via_google_maps(business_type: str, city: str, area: str, cfg: LeadEnrichmentConfig, desired: int = 40) -> List[dict]:
    if not cfg.serpapi_key:
        return []
    
    search_areas = [area,f"{area} {city}" if area else city,city]

    #ll = await get_optimal_ll(business_type, search_areas, city, cfg)

    base_params = {
        "engine": "google_maps",
        "q": business_type,
        "type": "search",
        #"ll": ll,
        "gl": "in",
        "hl": "en",
        "google_domain": "google.co.in",
        # Remove "num": 40 — not supported/effective here
        "api_key": cfg.serpapi_key
    }

    leads = []
    seen = set()
    start = 0
    empty_pages = 0
    MAX_EMPTY_PAGES = 3

    try:
        async with httpx.AsyncClient(timeout=80.0) as client:
            for search_area in search_areas:
                if len(leads) >= desired:
                    break

                ll = await get_optimal_ll(business_type, search_area, city, cfg)

                start = 0
                empty_pages = 0
                MAX_EMPTY_PAGES = 3

                while len(leads) < desired and empty_pages < MAX_EMPTY_PAGES:
                    params = {
                        **base_params,
                        "ll": ll,
                        "start": start
                    }

                    resp = await client.get("https://serpapi.com/search", params=params)
                    data = resp.json()
                    results = data.get("local_results", [])

                    if not results:
                        empty_pages += 1
                        start += 20
                        continue

                    empty_pages = 0

                    for place in results:
                        if len(leads) >= desired:
                            break

                        title = place.get("title")
                        address = place.get("address")
                        key = (title, address)

                        if key in seen:
                            continue
                        seen.add(key)

                        lat = place.get("gps_coordinates", {}).get("latitude")
                        lng = place.get("gps_coordinates", {}).get("longitude")

                        lead = {
                            "name": title,
                            "phone": place.get("phone"),
                            "email": None,
                            "address": address,
                            "url": place.get("website") or place.get("link"),
                            "geo": f"{lat},{lng}" if lat and lng else None,
                            "rating": place.get("rating"),
                            "total_reviews": place.get("reviews"),
                            "source": "google_maps",
                            "location_match": search_area
                        }

                        if lead.get("name"):
                            leads.append({k: v for k, v in lead.items() if v})

                    start += 20

        return leads

    except Exception as e:
        logger.error(f"Google Maps failed: {e}")
        return []


async def run_pipeline(business_type: str, area: str, city: str, max_leads: int = 100) -> List[dict]:  # Changed default to 100
    cfg = LeadEnrichmentConfig()
    desired = min(max_leads, 100)  # Hard cap at 100 to avoid bad results
    area_clean = area.strip()
    city_clean = city.strip().title()

    await _emit("start", 0, desired, f"Hunting {business_type} in {area_clean or 'entire'} {city_clean}")

    gmb_leads = await _get_leads_via_google_maps(business_type, city_clean, area_clean, cfg, desired=desired)

    if len(gmb_leads) > 0:
        final = gmb_leads[:desired]
        await _complete(final)
        return final

    await _complete([])
    return []

@tool
async def lead_enrichment(
    business_type: str,
    city: str,
    area: str = "",
    max_leads: int = 100, # Updated default and doc
    user_query: str = "",
) -> str:
    """Extract up to 100 verified Indian business leads with one clean download link."""
    leads = await run_pipeline(business_type, area, city, max_leads)

    count = len(leads)

    if count == 0:
        return f"No **{business_type}** found in **{area or 'entire'} {city}**."

    top_names = [lead.get("name", "Unknown") for lead in leads[:10]]
    email_count = sum(1 for l in leads if l.get("email"))
    email_rate = email_count / count * 100

    # ONE CSV upload
    csv_content = generate_csv(leads)
    try:
        download_url = await upload_csv_to_azure(csv_content)
    except Exception as e:
        logger.error(f"Failed to upload leads CSV: {e}")
        # Return results without download link but still provide value
        bullet_list = '\n• '.join(top_names)
        return f"""{count} verified {business_type}(s) found in {area or 'entire'} {city}
Email capture: {email_rate:.1f}% ({email_count}/{count})
Top businesses:
• {bullet_list}

⚠️  Unable to generate download link due to temporary service issues.
Please try again in a few minutes or contact support if the issue persists."""
    has_import_intent = bool(IMPORT_INTENT_RE.search(user_query))
    
    ws = get_generation_websocket()
    user_id=None
    if ws:
        try:
            # Get user_id from global context
            import websocket_handler
            user_id = websocket_handler.user_id_global
            logger.info(f"[lead_enrichment] Retrieved user_id: {user_id}")
        except Exception as e:
            logger.error(f"[lead_enrichment] Failed to get user_id: {e}")
    
    if user_id:
        try:
            # Store leads in ws_manager for import_leads_tool to access
            from websocket_handler import ws_manager
            ws_manager.set_recent_leads(user_id, {
                "leads": leads,
                "count": count,
                "business_type": business_type,
                "location": f"{area or ''}, {city}".strip(", "),
                "download_url": download_url
            })
            logger.info(f"[lead_enrichment] Successfully stored {count} leads for user {user_id}")
        except Exception as e:
            logger.error(f"[lead_enrichment] Failed to store leads in ws_manager: {e}", exc_info=True)
    else:
        logger.warning("[lead_enrichment] No user_id available - leads not stored in ws_manager")
    
    # Build response message
    bullet_list = '\n• '.join(top_names)
    base_message = f"""{count} verified {business_type}(s) found in {area or 'entire'} {city}
Email capture: {email_rate:.1f}% ({email_count}/{count})
Top businesses:
• {bullet_list}
Download all {count} leads (CSV):
{download_url}"""
    
    # Check for import intent in user query
    has_import_intent = check_import_intent(user_query)
    logger.info(f"[lead_enrichment] Import intent detected: {has_import_intent} (query: '{user_query}')")
    
    # If user wants to import, send signal to frontend
    if ws and has_import_intent:
        try:
            await ws.send_json({
                "type": "leads_ready_for_import",
                "leads": leads,
                "count": count,
                "business_type": business_type,
                "location": f"{area or ''}, {city}".strip(", "),
                "download_url": download_url,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"[lead_enrichment] Sent leads_ready_for_import signal for {count} leads")
            
            # Return special signal to stop agent execution
            return "__LEADS_READY_FOR_IMPORT__"
        except Exception as e:
            logger.error(f"[lead_enrichment] Failed to send import signal: {e}", exc_info=True)
            # Fall through to return base_message
    
    # Default response - suggest import
    return base_message + "\n\nWant to import these leads to your CRM? Just ask me!"

__all__ = ["lead_enrichment"]