#!/usr/bin/env python3
"""
PPV.TO HIGH-CAPTURE MODE — FINALIZED

- Initial capture (fast, MAX_WAIT_INITIAL=8s)
- Retry missing streams with longer wait (MAX_WAIT_RETRY=15s)
- Safe f-string handling (backslash issue fixed)
- Builds full M3U8 playlist
"""
import asyncio
from playwright.async_api import async_playwright
import aiohttp
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time
import re
from typing import List, Dict

# -------- CONFIG ----------
API_URL = "https://api.ppv.to/api/streams"
PLAYLIST_FILE = "PPVLand.m3u8"
HEADLESS = True

CAPTURE_CONCURRENCY = 3
MAX_WAIT_INITIAL = 8.0
MAX_WAIT_RETRY = 15.0
RETRY_CONCURRENCY = 2

STREAM_HEADERS = [
    '#EXTVLCOPT:http-origin=https://ppv.to',
    '#EXTVLCOPT:http-referrer=https://ppv.to/',
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/143.0'
]

BACKUP_LOGOS = {
    "24/7 Streams": "http://drewlive2423.duckdns.org:9000/Logos/247.png",
    "Wrestling": "http://drewlive2423.duckdns.org:9000/Logos/Wrestling.png",
    "Football": "http://drewlive2423.duckdns.org:9000/Logos/Football.png",
    "Basketball": "http://drewlive2423.duckdns.org:9000/Logos/Basketball.png",
    "Baseball": "http://drewlive2423.duckdns.org:9000/Logos/Baseball.png",
    "American Football": "http://drewlive2423.duckdns.org:9000/Logos/NFL3.png",
    "Combat Sports": "http://drewlive2423.duckdns.org:9000/Logos/CombatSports2.png",
    "Darts": "http://drewlive2423.duckdns.org:9000/Logos/Darts.png",
    "Motorsports": "http://drewlive2423.duckdns.org:9000/Logos/Motorsports2.png",
    "Live Now": "http://drewlive2423.duckdns.org:9000/Logos/DrewLiveSports.png",
    "Ice Hockey": "http://drewlive2423.duckdns.org:9000/Logos/Hockey.png",
    "default": "http://drewlive2423.duckdns.org:9000/Logos/Default.png"
}

GROUP_RENAME_MAP = {
    "24/7 Streams": "PPVLand - Live Channels 24/7",
    "Wrestling": "PPVLand - Wrestling Events",
    "Football": "PPVLand - Global Football Streams",
    "Basketball": "PPVLand - Basketball Hub",
    "Baseball": "PPVLand - MLB",
    "American Football": "PPVLand - NFL Action",
    "Combat Sports": "PPVLand - Combat Sports",
    "Darts": "PPVLand - Darts",
    "Motorsports": "PPVLand - Racing Action",
    "Live Now": "PPVLand - Live Now",
    "Ice Hockey": "PPVLand - NHL Action"
}

ICONS = {"American Football":"🏈","Basketball":"🏀","Ice Hockey":"🏒","Baseball":"⚾",
         "Combat Sports":"🥊","Wrestling":"🤼","Football":"⚽","Motorsports":"🏎️",
         "Darts":"🎯","Live Now":"📡","24/7 Streams":"📺","default":"📺"}

def get_icon(name): return ICONS.get(name, ICONS["default"])

def pretty_time(ts):
    if not ts:
        return ""
    try:
        dt_utc = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        dt_est = dt_utc.astimezone(ZoneInfo("America/New_York"))
        dt_mt  = dt_utc.astimezone(ZoneInfo("America/Denver"))
        dt_uk  = dt_utc.astimezone(ZoneInfo("Europe/London"))
        return f"{dt_est:%I:%M %p ET} / {dt_mt:%I:%M %p MT} / {dt_uk:%H:%M UK}"
    except Exception:
        return ""

async def fetch_api_streams():
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(API_URL) as r:
                if r.status != 200:
                    print(f"❌ API returned {r.status}")
                    return []
                data = await r.json()
                return data.get("streams", [])
    except Exception as e:
        print("❌ API fetch error:", e)
        return []

async def capture_m3u8(page, iframe_url, max_wait=MAX_WAIT_INITIAL):
    found = None

    async def route_handler(route):
        if route.request.resource_type in ("image","stylesheet","font","media"):
            await route.abort()
        else:
            await route.continue_()

    def handle_response(resp):
        nonlocal found
        if ".m3u8" in resp.url and not found:
            found = resp.url

    page.on("response", handle_response)
    await page.route("**/*", route_handler)

    try:
        await page.goto(iframe_url, timeout=15000, wait_until="domcontentloaded")
    except:
        pass

    waited = 0.0
    step = 0.1
    while waited < max_wait and not found:
        await asyncio.sleep(step)
        waited += step

    page.remove_listener("response", handle_response)
    try:
        await page.unroute("**/*", route_handler)
    except:
        pass
    return found

def build_playlist(entries: List[Dict]):
    lines = ["#EXTM3U"]
    seen = set()
    for e in entries:
        key = (e["name"].lower().strip(), e["category"])
        if key in seen:
            continue
        seen.add(key)

        clean_name = re.sub(r'\W+', '', e['name']).lower()
        tvg_id = f"ppv-{clean_name}"[:64]

        logo = e.get("poster") or BACKUP_LOGOS.get(e["category"], BACKUP_LOGOS["default"])
        group = GROUP_RENAME_MAP.get(e["category"], e["category"])
        display = pretty_time(e.get("starts_at"))
        title = f"{e['name']} - {display}" if display else e["name"]

        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{e["name"]}" tvg-logo="{logo}" group-title="{group}",{title}')
        for h in STREAM_HEADERS:
            lines.append(h)
        lines.append(e["url"])
    return "\n".join(lines)

async def main():
    t0 = time.time()
    print("\n=== PPV.TO HIGH-CAPTURE MODE — FINALIZED ===\n")

    api_streams = await fetch_api_streams()
    if not api_streams:
        print("❌ No API data. Exiting.")
        return

    now = int(time.time())
    candidates = []
    for cat in api_streams:
        cat_name = cat.get("category", "Misc")
        for s in cat.get("streams", []):
            iframe = s.get("iframe")
            if iframe:
                starts = s.get("starts_at") or 0
                final_cat = "Live Now" if (starts > 0 and starts <= now) else cat_name
                candidates.append({
                    "name": s.get("name") or "Unnamed Event",
                    "iframe": iframe,
                    "category": final_cat,
                    "poster": s.get("poster"),
                    "starts_at": starts
                })

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=HEADLESS)
        context = await browser.new_context()

        cap_sem = asyncio.Semaphore(CAPTURE_CONCURRENCY)
        results = []
        failed = []

        async def worker(item, wait_time=MAX_WAIT_INITIAL):
            async with cap_sem:
                page = await context.new_page()
                url = await capture_m3u8(page, item["iframe"], max_wait=wait_time)
                await page.close()
                if url:
                    results.append({**item, "url": url})
                    print(f"✔ Captured: {item['name']}")
                else:
                    failed.append(item)
                    print(f"✖ Failed: {item['name']}")

        # --- Initial capture ---
        await asyncio.gather(*(worker(it) for it in candidates))

        print(f"\n⚡ Initial capture complete. Found {len(results)} streams.")
        print(f"⏱ {len(failed)} streams failed, retrying with longer wait...\n")

        # --- Retry failed streams ---
        retry_sem = asyncio.Semaphore(RETRY_CONCURRENCY)
        retry_results = []

        async def retry_worker(item):
            async with retry_sem:
                page = await context.new_page()
                url = await capture_m3u8(page, item["iframe"], max_wait=MAX_WAIT_RETRY)
                await page.close()
                if url:
                    retry_results.append({**item, "url": url})
                    print(f"✔ Retry success: {item['name']}")
                else:
                    print(f"✖ Retry failed: {item['name']}")

        await asyncio.gather(*(retry_worker(it) for it in failed))

        results.extend(retry_results)
        await browser.close()

    playlist = build_playlist(results)
    with open(PLAYLIST_FILE, "w", encoding="utf-8") as fh:
        fh.write(playlist)

    print("\n✅ Done.")
    print(f"Streams captured: {len(results)} / {len(candidates)}")
    print(f"Playlist: {PLAYLIST_FILE}")
    print(f"Elapsed: {time.time()-t0:.2f}s\n")

if __name__ == "__main__":
    asyncio.run(main())
