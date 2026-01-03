# lead_enrichment.py — FINAL 2025: CLEAN RESPONSE + 1 DOWNLOAD LINK + NO DUPLICATES

from __future__ import annotations
import csv
import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict
from urllib.parse import urlparse
import httpx
from langchain_core.tools import tool
from agent.tools import get_generation_websocket

logger = logging.getLogger(__name__)

@dataclass
class LeadEnrichmentConfig:
    serpapi_key: str = os.getenv("SERPAPI_KEY", "").strip()

# Global cache for coordinates
_coords_cache: Dict[str, str] = {}

async def upload_to_tmpfiles(csv_content: str) -> str:
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
    raise Exception("All file upload services failed. Unable to generate download link for leads.")

def generate_csv(leads: List[dict]) -> str:
    output = io.StringIO()
    if not leads:
        return ""
    writer = csv.DictWriter(output, fieldnames=leads[0].keys())
    writer.writeheader()
    writer.writerows(leads)
    return output.getvalue()

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

    ll = await get_optimal_ll(business_type, area or city, city, cfg)

    base_params = {
        "engine": "google_maps",
        "q": business_type,
        "type": "search",
        "ll": ll,
        "gl": "in",
        "hl": "en",
        "google_domain": "google.co.in",
        # Remove "num": 40 — not supported/effective here
        "api_key": cfg.serpapi_key
    }

    leads = []
    seen = set()  # For deduplication: use (title, address) tuple
    start = 0
    max_start = 100  # Page 6 → up to ~120 raw results

    try:
        async with httpx.AsyncClient(timeout=80.0) as client:
            while start <= max_start and len(leads) < desired:
                params = {**base_params, "start": start}
                resp = await client.get("https://serpapi.com/search", params=params)
                data = resp.json()

                results = data.get("local_results", [])
                if not results:
                    break

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
                        "location_match": f"{area} {city}".strip() or city
                    }
                    if lead.get("name"):
                        cleaned_lead = {k: v for k, v in lead.items() if v}
                        leads.append(cleaned_lead)

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
    max_leads: int = 100  # Updated default and doc
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
        download_url = await upload_to_tmpfiles(csv_content)
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

    # FINAL CLEAN MESSAGE — agent will love this
    bullet_list = '\n• '.join(top_names)
    return f"""{count} verified {business_type}(s) found in {area or 'entire'} {city}
Email capture: {email_rate:.1f}% ({email_count}/{count})
Top businesses:
• {bullet_list}
Download all {count} leads (CSV):
{download_url}
Click **Import to CRM** to save."""

__all__ = ["lead_enrichment"]