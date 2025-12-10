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
#  TIME FORMAT
# ------------------------
def pretty_time(ts):
    if not ts:
        return ""
    try:
        dt_utc = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        dt_est = dt_utc.astimezone(ZoneInfo("America/New_York"))
        dt_mt  = dt_utc.astimezone(ZoneInfo("America/Denver"))
        dt_uk  = dt_utc.astimezone(ZoneInfo("Europe/London"))
        return f"{dt_est:%I:%M %p ET} / {dt_mt:%I:%M %p MT} / {dt_uk:%H:%M UK}"
    except:
        return ""


# ------------------------
#  API FETCH
# ------------------------
async def fetch_api_streams():
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(API_URL) as r:
                if r.status != 200:
                    print("❌ API error:", r.status)
                    return []
                j = await r.json()
                return j.get("streams", [])
    except Exception as e:
        print("❌ API fetch error:", e)
        return []


# ------------------------
#  VALIDATION (Strict Mode 1)
# ------------------------
async def validate_m3u8_status(url, referer):
    timeout = aiohttp.ClientTimeout(total=10)
    origin = "https://" + referer.split("/")[2] if "://" in referer else "https://ppv.to"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Origin": origin
    }

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(url) as r:
                return r.status in (200, 403)
    except:
        return False


# ------------------------
#  PLAYWRIGHT SCRAPER
# ------------------------
async def capture_m3u8_from_iframe(page, iframe_url, max_wait=6):
    found = set()

    async def route_handler(route):
        if route.request.resource_type in ("image", "stylesheet", "font", "media"):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)

    def on_response(resp):
        if ".m3u8" in resp.url:
            found.add(resp.url)

    page.on("response", on_response)

    try:
        await page.goto(iframe_url, timeout=10000, wait_until="domcontentloaded")
    except:
        pass

    # Try clicking player
    try:
        frames = await page.query_selector_all("iframe")
        if frames:
            try:
                player = page.frame_locator("iframe").first
                await player.locator("body").click(force=True, timeout=2000)
            except:
                pass
        else:
            try:
                await page.locator("body").click(force=True, timeout=2000)
            except:
                pass
    except:
        pass

    # Wait for requests to fire
    for _ in range(int(max_wait / 0.15)):
        if found:
            break
        await asyncio.sleep(0.15)

    page.remove_listener("response", on_response)
    return found


# ------------------------
#  LIVE NOW SCRAPER
# ------------------------
async def scrape_live_now(page):
    items = []
    try:
        await page.goto("https://ppv.to/", timeout=10000)
        await asyncio.sleep(1)
        cards = await page.query_selector_all("#livecards a.item-card")

        for c in cards:
            name_el = await c.query_selector(".card-title")
            img_el = await c.query_selector("img.card-img-top")

            name = (await name_el.inner_text()).strip() if name_el else "Live Event"
            img  = await img_el.get_attribute("src") if img_el else None
            href = await c.get_attribute("href")

            if href:
                if not href.startswith("http"):
                    href = "https://ppv.to" + href

                items.append({
                    "name": name,
                    "iframe": href,
                    "poster": img,
                    "category": "Live Now",
                    "starts_at": 0
                })
    except:
        pass

    return items


# ------------------------
#  PLAYLIST BUILDER
# ------------------------
def build_playlist(entries):
    lines = ["#EXTM3U"]

    seen = set()

    for e in entries:
        name = e["name"]
        cat  = e["category"]

        key = (name.lower().strip(), cat)
        if key in seen:
            continue
        seen.add(key)

        # clean tvg-id — FIXED VERSION
        clean_title = re.sub(r"\W+", "", name).lower()
        tvg_id = f"ppv-{clean_title}"[:64]

        logo = e.get("poster") or BACKUP_LOGOS.get(cat) or BACKUP_LOGOS["default"]
        group = GROUP_RENAME_MAP.get(cat, cat)

        starts = e.get("starts_at")
        tstr = pretty_time(starts) if starts else ""
        title = f"{name} - {tstr}" if tstr else name

        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{title}'
        )
        for h in STREAM_HEADERS:
            lines.append(h)

        # first URL only
        lines.append(e["urls"][0])

    return "\n".join(lines)


# ------------------------
#  MAIN
# ------------------------
async def main():
    start = time.time()
    print("🚀 PPV.TO Hybrid Interceptor (A + C Mode1)")

    api_data = await fetch_api_streams()
    if not api_data:
        print("❌ No API data. Exiting.")
        return

    # Flatten API streams
    candidates = []
    now = int(time.time())

    for c in api_data:
        cat = c.get("category", "Misc")
        cat_live = c.get("always_live") == 1

        for s in c.get("streams", []):
            iframe = s.get("iframe")
            if not iframe:
                continue

            starts = s.get("starts_at") or 0
            live_event = starts > 0 and starts <= now

            final_cat = cat
            if (not cat_live) and (not (s.get("always_live") == 1)) and live_event:
                final_cat = "Live Now"

            candidates.append({
                "name": s.get("name", "Event"),
                "iframe": iframe,
                "poster": s.get("poster"),
                "category": final_cat,
                "starts_at": starts
            })

    # Add homepage Live Now
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=HEADLESS)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        homepage_live = await scrape_live_now(page)
        candidates.extend(homepage_live)

        url_map = {}

        # Capture streams
        total = len(candidates)
        for i, item in enumerate(candidates, 1):
            print(f"\n[{i}/{total}] {get_icon(item['category'])} {item['name']}")
            caps = await capture_m3u8_from_iframe(page, item["iframe"])

            print(f"  → captured {len(caps)} stream(s)")
            url_map[id(item)] = list(caps)

        await browser.close()

    # Validate + fallback
    print("\n🔧 Validating… (strict but fallback enabled)")
    final_entries = []

    for item in candidates:
        caps = url_map.get(id(item), [])
        validated = []

        if caps:
            tasks = [validate_m3u8_status(u, item["iframe"]) for u in caps]
            results = await asyncio.gather(*tasks)

            for u, ok in zip(caps, results):
                if ok:
                    validated.append(u)

        # fallback if strict check fails
        final = validated if validated else caps

        if final:
            final_entries.append({
                "name": item["name"],
                "category": item["category"],
                "poster": item["poster"],
                "urls": final,
                "starts_at": item["starts_at"]
            })

    # Build playlist
    playlist = build_playlist(final_entries)

    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        f.write(playlist)

    print("\n✅ DONE!")
    print(f"✔ Streams written: {len(final_entries)}")
    print(f"✔ Output file: {PLAYLIST_FILE}")
    print(f"⏱ Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
