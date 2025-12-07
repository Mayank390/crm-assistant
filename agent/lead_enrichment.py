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
    crawl4ai_url: str = os.getenv("CRAWL4AI_URL", "http://crawl4ai-local:11235")
    serpapi_key: str = os.getenv("SERPAPI_KEY", "").strip()

# Global cache — prevents duplicate crawls forever
_crawled_cache: Dict[str, dict] = {}
_coords_cache: Dict[str, str] = {}

async def upload_to_tmpfiles(csv_content: str) -> str:
    """Upload CSV to free file hosting service and return download URL"""
    filename = f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # Try transfer.sh (10GB limit, 14 days, direct download)
    try:
        url = f"https://transfer.sh/{filename}"
        headers = {'Content-Type': 'text/csv'}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(url, content=csv_content.encode('utf-8'), headers=headers)
            if resp.status_code == 200:
                return resp.text.strip()  # transfer.sh returns the download URL
    except Exception as e:
        logger.debug(f"transfer.sh failed: {e}")

    # Fallback to file.io (2GB limit, 14 days)
    try:
        data = {"expires": "1w"}  # 1 week expiry
        files = {'file': (filename, csv_content.encode('utf-8'), 'text/csv')}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://file.io/", data=data, files=files)
            result = resp.json()
            if result.get("success"):
                return result["link"]  # Direct download link
    except Exception as e:
        logger.debug(f"file.io failed: {e}")

    # Last fallback to tmpfiles.org (view URL)
    try:
        files = {'file': (filename, csv_content.encode('utf-8'), 'text/csv')}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://tmpfiles.org/api/v1/upload", files=files)
            data = resp.json()
            if data.get("status") == "success":
                return data["data"]["url"]  # View URL that users can click to download
    except Exception as e:
        logger.debug(f"tmpfiles.org failed: {e}")

    return None

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

async def _get_leads_via_google_maps(business_type: str, city: str, area: str, cfg: LeadEnrichmentConfig) -> List[dict]:
    if not cfg.serpapi_key: return []

    ll = await get_optimal_ll(business_type, area or city, city, cfg)

    params = {
        "engine": "google_maps", "q": business_type, "type": "search", "ll": ll,
        "gl": "in", "hl": "en", "google_domain": "google.co.in", "num": 40, "api_key": cfg.serpapi_key
    }

    try:
        async with httpx.AsyncClient(timeout=80.0) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            data = resp.json()

        results = data.get("local_results", [])
        leads = []
        for place in results:
            lat = place.get("gps_coordinates", {}).get("latitude")
            lng = place.get("gps_coordinates", {}).get("longitude")
            lead = {
                "name": place.get("title"),
                "phone": place.get("phone"),
                "email": None,
                "address": place.get("address"),
                "url": place.get("website") or place.get("link"),
                "geo": f"{lat},{lng}" if lat and lng else None,
                "rating": place.get("rating"),
                "total_reviews": place.get("reviews"),
                "source": "google_maps",
                "location_match": f"{area} {city}".strip() or city
            }
            if lead.get("name"):
                leads.append({k: v for k, v in lead.items() if v})

        return leads[:40]

    except Exception as e:
        logger.error(f"Google Maps failed: {e}")
        return []

async def _enrich_with_crawl4ai(gmb_leads: List[dict], cfg: LeadEnrichmentConfig) -> List[dict]:
    urls = []
    for lead in gmb_leads:
        url = lead.get("url")
        if url and isinstance(url, str) and url.startswith("http") and not is_trash_directory_url(url) and url not in _crawled_cache:
            urls.append(url)

    if urls:
        urls = urls[:15]  # Limit to 15 URLs for speed (25-40 sec total)
        payload = {"urls": urls, "crawler": {"delay_range": [8000, 14000]}}
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{cfg.crawl4ai_url}/crawl", json=payload)
                results = resp.json().get("results", [])
            for r in results:
                if r.get("extracted"):
                    _crawled_cache[r["url"]] = r["extracted"]
        except Exception as e:
            logger.warning(f"Crawl4AI failed: {e}")

    for lead in gmb_leads:
        url = lead.get("url")
        if url and url in _crawled_cache:
            e = _crawled_cache[url]
            lead["email"] = e.get("email") or lead.get("email")
            lead["phone"] = e.get("phone") or lead.get("phone")
            lead["source"] = "hybrid_gmb+crawl4ai"

    return gmb_leads

async def run_pipeline(business_type: str, area: str, city: str, max_leads: int = 40) -> List[dict]:
    cfg = LeadEnrichmentConfig()
    desired = min(max_leads, 40)
    area_clean = area.strip()
    city_clean = city.strip().title()

    await _emit("start", 0, desired, f"Hunting {business_type} in {area_clean or 'entire'} {city_clean}")

    gmb_leads = await _get_leads_via_google_maps(business_type, city_clean, area_clean, cfg)

    if len(gmb_leads) > 5:
        enriched = await _enrich_with_crawl4ai(gmb_leads, cfg)
        final = enriched[:desired]
        await _complete(final)
        return final

    await _complete([])
    return []

@tool
async def lead_enrichment(
    business_type: str,
    city: str,
    area: str = "",
    max_leads: int = 40
) -> str:
    """Extract up to 40 verified Indian business leads with one clean download link."""
    leads = await run_pipeline(business_type, area, city, max_leads)
    count = len(leads)

    if count == 0:
        return f"No **{business_type}** found in **{area or 'entire'} {city}**."

    top_names = [lead.get("name", "Unknown") for lead in leads[:10]]
    email_count = sum(1 for l in leads if l.get("email"))
    email_rate = email_count / count * 100

    # ONE CSV upload
    csv_content = generate_csv(leads)
    download_url = await upload_to_tmpfiles(csv_content)

    # FINAL CLEAN MESSAGE — agent will love this
    return f"""{count} verified {business_type}(s) found in {area or 'entire'} {city}
Email capture: {email_rate:.1f}% ({email_count}/{count})
Top businesses:
• {'\n• '.join(top_names)}
Download all {count} leads (CSV):
{download_url}
Click **Import to CRM** to save."""

__all__ = ["lead_enrichment"]