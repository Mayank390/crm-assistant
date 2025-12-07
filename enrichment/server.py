import asyncio
import json
import os
import random
import re
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin
from json import JSONDecodeError

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup

# === GROQ LLM EXTRACTION (THE MAGIC) ===
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_CLIENT = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL = os.getenv("GROQ_EXTRACTION_MODEL", "llama-3.3-70b-versatile")

# Global warmup flag
WARMED_UP = False

app = FastAPI(title="Crawl4AI Server + GROQ Lead Extraction")

@app.on_event("startup")
async def warmup_browser():
    global WARMED_UP
    if not WARMED_UP:
        logger.info("Warming up Crawl4AI browser...")
        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
                await crawler.arun("https://httpbin.org/html")  # Lightweight page
            WARMED_UP = True
            logger.info("Crawl4AI browser ready!")
        except Exception as e:
            logger.warning(f"Browser warmup failed: {e}")

class CrawlRequest(BaseModel):
    url: str
    page_options: Optional[dict] = None

class BatchCrawlRequest(BaseModel):
    urls: List[str]
    crawler: Optional[Dict[str, Any]] = None
    extraction: Optional[Dict[str, Any]] = None

@app.post("/v0/crawl")
async def crawl_url(request: CrawlRequest):
    """Legacy single crawl"""
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(request.url)
            extracted = await extract_with_groq(getattr(result, 'markdown', ''), request.url)
            return {
                "url": request.url,
                "content": getattr(result, 'markdown', '')[:2000],
                "success": result.success,
                "extracted": extracted
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/crawl")
async def crawl_batch(request: BatchCrawlRequest):
    """Optimized batch endpoint with concurrency and smart delays"""
    try:
        urls = request.urls[:15]  # Max 15 for speed
        crawler_config = request.crawler or {}
        delay_range = crawler_config.get("delay_range", [3000, 7000])  # Faster delays

        results = []
        semaphore = asyncio.Semaphore(3)  # 3 concurrent crawls

        async def crawl_one(url):
            async with semaphore:
                # Smart delay between requests
                await asyncio.sleep(random.uniform(*delay_range) / 1000)

                lead = {"url": url, "name": None, "phone": None, "email": None, "source": "failed"}

                for attempt in range(3):
                    try:
                        async with AsyncWebCrawler(verbose=False) as crawler:
                            result = await crawler.arun(
                                url=url,
                                bypass_csp=True,
                                wait_for="networkidle",
                                timeout=60000,  # Faster timeout
                                headless=True,
                                js_code="""
                                    // Force load lazy content, remove heavy elements
                                    document.querySelectorAll('img, video, iframe').forEach(el => el.remove());
                                    document.querySelectorAll('[data-src], [loading="lazy"]').forEach(el => {
                                        if (el.dataset.src) el.src = el.dataset.src;
                                    });
                                    window.scrollTo(0, document.body.scrollHeight);
                                """,
                                delay_before_return_html=4000,  # Faster
                            )

                        if result.success and result.markdown and len(result.markdown) > 500:
                            extracted = await extract_with_groq(result.markdown, url)
                            if extracted.get("phone") or extracted.get("email"):
                                extracted["source"] = "groq"
                                return extracted

                            # Fallback to heuristic
                            heuristic = await extract_with_heuristics(result.markdown, url)
                            if heuristic.get("phone") or heuristic.get("email"):
                                heuristic["source"] = "heuristic"
                                return heuristic

                    except Exception as e:
                        logger.warning(f"Attempt {attempt+1} failed {url}: {str(e)[:100]}")
                        if attempt == 2:
                            # Final fallback
                            try:
                                if result and getattr(result, "html", None):
                                    fallback = await extract_with_heuristics(result.html, url)
                                    if fallback.get("phone") or fallback.get("email"):
                                        fallback["source"] = "fallback_html"
                                        return fallback
                            except:
                                pass
                        await asyncio.sleep(2)

                return lead

        # Run concurrent crawls
        tasks = [crawl_one(url) for url in urls]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and collect successful results
        for result in batch_results:
            if isinstance(result, dict):
                results.append(result)

        logger.info(f"Batch complete: {len(results)}/{len(urls)} successful extractions")
        return {"results": results}

    except Exception as e:
        logger.error(f"Batch crawl error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def extract_with_groq(markdown: str, url: str) -> Dict[str, Any]:
    lead = {
        "name": None, "url": url, "address": None,
        "phone": None, "email": None, "hours": None, "geo": None,
        "source": "groq"
    }

    if not markdown or len(markdown.strip()) < 100:
        return lead

    prompt = f"""

You are extracting Indian business contact details. Be aggressive — if a phone or email exists anywhere on the page, extract it.

Rules:
- Accept +91, 0, or no prefix
- Accept WhatsApp numbers
- Accept multiple numbers → pick the main one
- Accept emails in text, images, or "mailto:"
- Never return null if you see something that looks like a contact

Return EXACTLY valid JSON, no explanations:

{{
  "name": "Business Name or null",
  "phone": "+91XXXXXXXXXX or null",
  "email": "info@domain.com or null",
  "address": "Full address or null",
  "hours": "10 AM - 8 PM or null",
  "geo": "lat,lng or null"
}}

Content:

{markdown[:14000]}

"""

    try:
        response = GROQ_CLIENT.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=400,
        )

        raw = response.choices[0].message.content.strip()

        # Clean any code blocks or junk
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "", 1).strip()

        # FINAL SAFETY: Parse and re-serialize to guarantee valid JSON
        data = json.loads(raw)
        lead.update({k: v for k, v in data.items() if v})

        # Clean phone
        if lead.get("phone"):
            phones = re.findall(r'[\+]?[6-9]\d{9,14}', str(lead["phone"]))
            if phones:
                p = phones[0]
                lead["phone"] = f"+91{p.lstrip('+91')}" if not p.startswith("+91") else p

        # Clean email
        if lead.get("email"):
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(lead["email"]))
            lead["email"] = emails[0] if emails else None

    except json.JSONDecodeError:
        logger.warning(f"Groq returned invalid JSON for {url}, falling back to heuristic")
        return await extract_with_heuristics(markdown, url)
    except Exception as e:
        logger.warning(f"Groq extraction failed {url}: {e}")
        return await extract_with_heuristics(markdown, url)

    return lead


async def extract_with_heuristics(markdown: str, url: str) -> Dict[str, Any]:
    """Fallback heuristic extraction (kept for redundancy)"""
    lead = {
        "name": None, "url": url, "address": None,
        "phone": None, "email": None, "hours": None, "geo": None,
        "source": "crawl4ai-heuristic"
    }

    soup = BeautifulSoup(markdown, "html.parser")
    text = soup.get_text(" ", strip=True).lower()

    # Name from title
    if soup.title and soup.title.string:
        lead["name"] = soup.title.string.split("|")[0].split("-")[0].strip()

    # Phone
    phones = re.findall(r'[\+]?[6-9]\d{9,12}', text)
    if phones:
        p = phones[0]
        lead["phone"] = f"+91{p}" if not p.startswith("+") else p

    # Email
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    if emails:
        lead["email"] = emails[0]

    return lead

@app.get("/health")
async def health():
    return {"status": "ok", "extraction": "groq+heuristic"}

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=11235,
        log_level="info"
    )
