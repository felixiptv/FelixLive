import asyncio
from playwright.async_api import async_playwright
import aiohttp
from datetime import datetime
import re

API_URL = "https://api.ppv.to/api/streams"

CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-origin=https://ppv.to',
    '#EXTVLCOPT:http-referrer=https://ppv.to/',
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0'
]

ALLOWED_CATEGORIES = {
    "24/7 Streams", "Wrestling", "Football", "Basketball", "Baseball",
    "Combat Sports", "American Football", "Darts", "Motorsports", "Ice Hockey"
}

CATEGORY_LOGOS = {
    "24/7 Streams": "http://drewlive24.duckdns.org:9000/Logos/247.png",
    "Wrestling": "http://drewlive24.duckdns.org:9000/Logos/Wrestling.png",
    "Football": "http://drewlive24.duckdns.org:9000/Logos/Football.png",
    "Basketball": "http://drewlive24.duckdns.org:9000/Logos/Basketball.png",
    "Baseball": "http://drewlive24.duckdns.org:9000/Logos/Baseball.png",
    "American Football": "http://drewlive24.duckdns.org:9000/Logos/NFL3.png",
    "Combat Sports": "http://drewlive24.duckdns.org:9000/Logos/CombatSports2.png",
    "Darts": "http://drewlive24.duckdns.org:9000/Logos/Darts.png",
    "Motorsports": "http://drewlive24.duckdns.org:9000/Logos/Motorsports2.png",
    "Live Now": "http://drewlive24.duckdns.org:9000/Logos/DrewLiveSports.png",
    "Ice Hockey": "http://drewlive24.duckdns.org:9000/Logos/Hockey.png"
}

CATEGORY_TVG_IDS = {
    "24/7 Streams": "24.7.Dummy.us",
    "Wrestling": "PPV.EVENTS.Dummy.us",
    "Football": "Soccer.Dummy.us",
    "Basketball": "Basketball.Dummy.us",
    "Baseball": "MLB.Baseball.Dummy.us",
    "American Football": "NFL.Dummy.us",
    "Combat Sports": "PPV.EVENTS.Dummy.us",
    "Darts": "Darts.Dummy.us",
    "Motorsports": "Racing.Dummy.us",
    "Live Now": "24.7.Dummy.us",
    "Ice Hockey": "NHL.Hockey.Dummy.us"
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

NFL_TEAMS = {...}  # (same as your original)
COLLEGE_TEAMS = {...}  # (same as your original)


# 🔥 NEW FALLBACK URL BUILDER
def build_poocloud_fallback(iframe_url):
    """Build fallback: https://gg.poocloud.in/<streamname>/index.m3u8"""
    try:
        match = re.search(r"/([^/]+)/\d+$", iframe_url)
        if not match:
            return None
        stream_name = match.group(1)
        return f"https://gg.poocloud.in/{stream_name}/index.m3u8"
    except:
        return None


# CHECK M3U8
async def check_m3u8_url(url, referer):
    try:
        origin = "https://" + referer.split('/')[2]
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": referer,
            "Origin": origin
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status in [200, 403]
    except:
        return False


# FETCH STREAM LIST FROM API
async def get_streams():
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(API_URL) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except:
        return None


# PLAYWRIGHT M3U8 CATCHER
async def grab_m3u8_from_iframe(page, iframe_url):
    found_streams = set()

    def handle_response(response):
        if ".m3u8" in response.url:
            found_streams.add(response.url)

    page.on("response", handle_response)

    try:
        await page.goto(iframe_url, timeout=30000)
    except:
        return set()

    await page.wait_for_timeout(5000)
    await asyncio.sleep(8)

    page.remove_listener("response", handle_response)

    if not found_streams:
        return set()

    # Validate
    valid = set()
    checks = [check_m3u8_url(url, iframe_url) for url in found_streams]
    results = await asyncio.gather(*checks)

    for u, ok in zip(found_streams, results):
        if ok:
            valid.add(u)

    return valid


# SCRAPE 'LIVE NOW'
async def grab_live_now_from_html(page, base_url="https://ppv.to/"):
    live_now = []
    await page.goto(base_url)
    await asyncio.sleep(3)

    cards = await page.query_selector_all("#livecards a.item-card")
    for card in cards:
        href = await card.get_attribute("href")
        name_el = await card.query_selector(".card-title")
        poster_el = await card.query_selector("img.card-img-top")

        name = await name_el.inner_text() if name_el else "Live"
        poster = await poster_el.get_attribute("src") if poster_el else None
        iframe = f"{base_url.rstrip('/')}{href}"

        live_now.append({
            "name": name.strip(),
            "iframe": iframe,
            "category": "Live Now",
            "poster": poster
        })

    return live_now


# BUILD M3U
def build_m3u(streams, url_map):
    lines = ['#EXTM3U']
    seen = set()

    for s in streams:
        key = f"{s['name']}::{s['category']}::{s['iframe']}"
        urls = url_map.get(key, [])

        if not urls:
            continue

        url = next(iter(urls))

        lines.append(f'#EXTINF:-1 group-title="{s["category"]}",{s["name"]}')
        lines.extend(CUSTOM_HEADERS)
        lines.append(url)

    return "\n".join(lines)


# MAIN
async def main():
    data = await get_streams()
    if not data or "streams" not in data:
        print("No API data")
        return

    streams = []
    for cat in data["streams"]:
        category = cat["category"]
        for stream in cat["streams"]:
            streams.append({
                "name": stream["name"],
                "iframe": stream["iframe"],
                "category": category,
                "poster": stream.get("poster")
            })

    # REMOVE DUPES
    unique = {}
    for s in streams:
        unique[s["name"].lower()] = s
    streams = list(unique.values())

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()

        url_map = {}

        for s in streams:
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            print(f"Scraping → {s['name']}")

            urls = await grab_m3u8_from_iframe(page, s["iframe"])

            # 🔥 FALLBACK HERE
            if not urls:
                fallback = build_poocloud_fallback(s["iframe"])
                if fallback:
                    print(f"⚠️ Using fallback: {fallback}")
                    urls = {fallback}

            url_map[key] = urls

        # PROCESS LIVE NOW
        live_now = await grab_live_now_from_html(page)
        streams.extend(live_now)

        for s in live_now:
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            urls = await grab_m3u8_from_iframe(page, s["iframe"])

            if not urls:
                fallback = build_poocloud_fallback(s["iframe"])
                if fallback:
                    urls = {fallback}

            url_map[key] = urls

        await browser.close()

    playlist = build_m3u(streams, url_map)
    with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
        f.write(playlist)

    print("Playlist saved!")


if __name__ == "__main__":
    asyncio.run(main())
