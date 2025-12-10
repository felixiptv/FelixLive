#!/usr/bin/env python3
import asyncio
from playwright.async_api import async_playwright
import aiohttp
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time
import re

# ------------------------
#  CONFIG
# ------------------------
API_URL = "https://api.ppv.to/api/streams"
PLAYLIST_FILE = "PPVLand.m3u8"
HEADLESS = True  # set False for debugging locally

# headers to write into playlist (VLC friendly)
STREAM_HEADERS = [
    '#EXTVLCOPT:http-origin=https://ppv.to',
    '#EXTVLCOPT:http-referrer=https://ppv.to/',
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/143.0'
]

# fallback logos
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
    "Cricket": "http://drewlive2423.duckdns.org:9000/Logos/Cricket.png",
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
    "Ice Hockey": "PPVLand - NHL Action",
    "Cricket": "PPVLand - Cricket"
}

ICONS = {
    "American Football": "🏈", "Basketball": "🏀", "Ice Hockey": "🏒",
    "Baseball": "⚾", "Combat Sports": "🥊", "Wrestling": "🤼",
    "Football": "⚽", "Motorsports": "🏎️", "Darts": "🎯",
    "Live Now": "📡", "24/7 Streams": "📺", "default": "📺"
}

def get_icon(name):
    return ICONS.get(name, ICONS["default"])

# ------------------------
#  UTIL
# ------------------------
def now_ts():
    return int(time.time())

def pretty_time(ts):
    if not ts:
        return ""
    try:
        dt_utc = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        dt_est = dt_utc.astimezone(ZoneInfo("America/New_York"))
        dt_mt  = dt_utc.astimezone(ZoneInfo("America/Denver"))
        dt_uk  = dt_utc.astimezone(ZoneInfo("Europe/London"))
        return f"{dt_est.strftime('%I:%M %p ET')} / {dt_mt.strftime('%I:%M %p MT')} / {dt_uk.strftime('%H:%M UK')}"
    except Exception:
        return ""

# quick helper to build origin from referer
def build_origin_from_referer(referer):
    try:
        return "https://" + referer.split("/")[2]
    except Exception:
        return "https://ppv.to"

# ------------------------
#  NETWORK: API fetch + validation (Hybrid A + C)
# ------------------------
async def fetch_api_streams():
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/142.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(API_URL) as resp:
                if resp.status != 200:
                    txt = await resp.text()
                    print(f"❌ API returned {resp.status}. Body snippet: {txt[:300]!r}")
                    return []
                data = await resp.json()
                return data.get("streams", [])
    except Exception as e:
        print(f"❌ fetch_api_streams error: {e}")
        return []

# Strict Mode 1 validation: status-only (200 or 403) - but used as 'try then fallback'
async def validate_m3u8_status(url, referer):
    timeout = aiohttp.ClientTimeout(total=12)
    origin = build_origin_from_referer(referer or "https://ppv.to")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/143.0",
        "Referer": referer or "https://ppv.to/",
        "Origin": origin
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                # Accept 200 OK or 403 Forbidden (some hosts forbid direct fetch but exist)
                return resp.status in (200, 403)
    except Exception as e:
        # network failure or blocked - treat as invalid (we will fallback later)
        # Print debug short message
        print(f"   (validate) network error for {url}: {e}")
        return False

# ------------------------
#  PLAYWRIGHT CAPTURE (collect multiple .m3u8s) - fast capture (A)
# ------------------------
async def capture_m3u8_from_iframe(page, iframe_url, max_wait=8):
    """
    Use Playwright to navigate iframe_url, listen to responses and capture any .m3u8
    Returns set of URLs captured (may be empty).
    """
    found = set()

    # don't waste bandwidth on heavy resources
    async def route_handler(route):
        if route.request.resource_type in ("image", "stylesheet", "font", "media"):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)

    # response handler
    def on_response(response):
        try:
            u = response.url
            if ".m3u8" in u:
                found.add(u)
        except Exception:
            pass

    page.on("response", on_response)

    # try to go to the iframe url - short timeout for speed
    try:
        await page.goto(iframe_url, timeout=10000, wait_until="domcontentloaded")
    except Exception:
        # sometimes the initial load fails; continue to attempt clicks/waits
        pass

    # Attempt to detect nested iframe and interact
    try:
        # small pause to let JS create nested iframe
        await asyncio.sleep(0.3)
        # if there are nested iframes, click inside first
        frames = await page.query_selector_all("iframe")
        if frames and len(frames) > 0:
            # click on nested iframe body if possible
            try:
                player_frame = page.frame_locator("iframe").first
                await player_frame.locator("body").click(timeout=2000, force=True)
            except Exception:
                # fallback: try clicking main page
                try:
                    await page.locator("body").click(timeout=1000, force=True)
                except Exception:
                    pass
        else:
            # click main body to trigger lazy load players
            try:
                await page.locator("body").click(timeout=1000, force=True)
            except Exception:
                pass
    except Exception:
        pass

    # Wait briefly for requests to be fired
    total_wait = 0.0
    step = 0.15
    while total_wait < max_wait and not found:
        await asyncio.sleep(step)
        total_wait += step

    page.remove_listener("response", on_response)
    return found

# ------------------------
#  SCRAPE 'Live Now' FROM HOME (optional additional streams)
# ------------------------
async def scrape_live_now(page, base_url="https://ppv.to/"):
    items = []
    try:
        await page.goto(base_url, timeout=12000, wait_until="domcontentloaded")
        await asyncio.sleep(1.2)
        cards = await page.query_selector_all("#livecards a.item-card")
        for c in cards:
            href = await c.get_attribute("href")
            title_el = await c.query_selector(".card-title")
            img_el = await c.query_selector("img.card-img-top")
            name = (await title_el.inner_text()).strip() if title_el else "Live Event"
            poster = await img_el.get_attribute("src") if img_el else None
            if href:
                iframe_url = href if href.startswith("http") else f"{base_url.rstrip('/')}{href}"
                items.append({
                    "name": name,
                    "iframe": iframe_url,
                    "category": "Live Now",
                    "poster": poster
                })
    except Exception:
        pass
    return items

# ------------------------
#  BUILD PLAYLIST
# ------------------------
def build_m3u_playlist(stream_entries):
    """
    stream_entries - list of dicts:
      {
        'name': str,
        'category': str,
        'poster': str,
        'urls': [url1, url2...],
        'starts_at': int|None,
      }
    """
    lines = ["#EXTM3U"]
    seen = set()
    for e in stream_entries:
        title = e.get("name", "Unnamed")
        key = (title.strip().lower(), e.get("category", ""))
        if key in seen:
            continue
        seen.add(key)

        group = GROUP_RENAME_MAP.get(e.get("category"), e.get("category") or "Misc")
        logo = e.get("poster") or BACKUP_LOGOS.get(e.get("category")) or BACKUP_LOGOS["default"]
        tvg_id = f"ppv-{re.sub(r'\\W+','', title).lower()}"[:64]

        # Append display time if available
        starts_at = e.get("starts_at")
        display_time = pretty_time(starts_at) if starts_at else ""
        display_title = f"{title} - {display_time}" if display_time else title

        # write entry
        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{title}" tvg-logo="{logo}" group-title="{group}",{display_title}')
        for h in STREAM_HEADERS:
            lines.append(h)
        # prefer first URL
        if e.get("urls"):
            lines.append(e["urls"][0])
        else:
            lines.append("")  # guard
    return "\n".join(lines)

# ------------------------
#  MAIN MERGE WORKFLOW
# ------------------------
async def main():
    started = time.time()
    print("\n" + "="*60)
    print("🚀  PPV.TO HYBRID (A + C StrictMode1) INTERCEPTOR")
    print("="*60 + "\n")

    categories = await fetch_api_streams()
    if not categories:
        print("❌ No categories returned from API. Exiting.")
        return

    # Flatten streams from API
    capture_candidates = []
    now = now_ts()
    for cat in categories:
        cat_name = cat.get("category", "") or "Misc"
        cat_always_live = cat.get("always_live") == 1
        for s in cat.get("streams", []) or []:
            iframe = s.get("iframe")
            if not iframe:
                continue
            starts_at = s.get("starts_at", 0) or 0
            # If event is scheduled and started, mark as Live Now
            is_live_event = starts_at > 0 and starts_at <= now
            final_cat = cat_name
            if not cat_always_live and not (s.get("always_live") == 1) and is_live_event:
                final_cat = "Live Now"
            capture_candidates.append({
                "id": s.get("id"),
                "name": s.get("name") or "Unnamed Event",
                "iframe": iframe,
                "category": final_cat,
                "poster": s.get("poster"),
                "starts_at": starts_at
            })

    # Sort by start time for nicer playlist order
    capture_candidates.sort(key=lambda x: x.get("starts_at") or 0)

    # Playwright capture
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()

        url_map = {}  # key -> set(captured urls)

        total = len(capture_candidates)
        for idx, item in enumerate(capture_candidates, start=1):
            print(f"[{idx}/{total}] Scanning: {get_icon(item['category'])} {item['name']} ({item['category']})")
            try:
                captured = await capture_m3u8_from_iframe(page, item["iframe"], max_wait=6)
            except Exception as e:
                print(f"   ❌ capture error: {e}")
                captured = set()

            if captured:
                print(f"   ➤ Captured {len(captured)} m3u8(s)")
            else:
                print(f"   - No m3u8 captured for this iframe")

            key = f"{item['name']}::{item['category']}::{item['iframe']}"
            url_map[key] = {"captured": list(captured), "validated": []}

        # Also try scraping 'Live Now' cards on homepage (additional sources)
        try:
            live_now = await scrape_live_now(page)
            if live_now:
                print(f"\n🔎 Found {len(live_now)} 'Live Now' items from homepage")
            for ln in live_now:
                key = f"{ln['name']}::{ln['category']}::{ln['iframe']}"
                captured = await capture_m3u8_from_iframe(page, ln["iframe"], max_wait=6)
                url_map[key] = {"captured": list(captured), "validated": []}
                capture_candidates.append({
                    "id": None,
                    "name": ln["name"],
                    "iframe": ln["iframe"],
                    "category": ln["category"],
                    "poster": ln.get("poster"),
                    "starts_at": 0
                })
        except Exception:
            pass

        await browser.close()

    # VALIDATION PHASE (StrictMode1) - try to validate captured URLs, but FALLBACK to captured set if validation fails
    print("\n🔧 Validating captured URLs (status-only). Will fallback to captured if validation fails.")
    final_entries = []
    # use a single aiohttp session for many checks
    for item in capture_candidates:
        key = f"{item['name']}::{item['category']}::{item['iframe']}"
        record = url_map.get(key, {"captured": [], "validated": []})
        captured_urls = record["captured"] or []

        validated = []
        # Attempt validation on each captured url (concurrent per item)
        if captured_urls:
            tasks = [validate_m3u8_status(u, item["iframe"]) for u in captured_urls]
            try:
                results = await asyncio.gather(*tasks)
            except Exception:
                results = [False]*len(captured_urls)

            for u, ok in zip(captured_urls, results):
                if ok:
                    validated.append(u)
                else:
                    # skip but keep for fallback later
                    pass

        # Hybrid fallback: if validated is empty but captured exists -> fallback to captured
        final_urls = validated if validated else captured_urls

        if final_urls:
            final_entries.append({
                "name": item.get("name"),
                "category": item.get("category"),
                "poster": item.get("poster"),
                "urls": final_urls,
                "starts_at": item.get("starts_at")
            })
            print(f"  ✓ {item.get('name')} -> using {len(final_urls)} url(s) [{ 'validated' if validated else 'fallback' }]")
        else:
            print(f"  ✖ {item.get('name')} -> no usable urls")

    # Deduplicate by name+category
    dedup = {}
    for e in final_entries:
        key = (e["name"].strip().lower(), e["category"])
        if key not in dedup:
            dedup[key] = e

    playlist_list = list(dedup.values())

    # Write playlist
    print(f"\n💾 Writing {len(playlist_list)} streams to {PLAYLIST_FILE} ...")
    playlist = build_m3u_playlist(playlist_list)
    with open(PLAYLIST_FILE, "w", encoding="utf-8") as fh:
        fh.write(playlist)

    print("\n" + "="*60)
    print("✅ MISSION COMPLETE")
    print(f"📊 WORKING STREAMS: {len(playlist_list)}")
    print(f"⏱ TIME: {time.time() - started:.2f}s")
    print(f"📺 Playlist saved as: {PLAYLIST_FILE}")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
