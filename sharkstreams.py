import asyncio
from playwright.async_api import async_playwright
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIG ---
CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
]

# Replace with the SharkStreams pages you want to scrape
SHARKSTREAMS_PAGES = [
    "https://sharkstreams.net"  # You can add more URLs here
]

# Domains commonly used for actual video streams
VALID_EMBED_DOMAINS = [
    "doodstream.com", "streamtape.com", "rapidvideo.com",
    "streamwish.com", "vidstream.pro", "mp4upload.com"
]

# --- UTIL FUNCTIONS ---
async def check_m3u8_url(url, referer):
    """Check if an M3U8 URL is valid."""
    try:
        origin = "https://" + referer.split('/')[2]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
            "Referer": referer,
            "Origin": origin
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status in [200, 403]
    except Exception as e:
        print(f"❌ Error checking {url}: {e}")
        return False

# --- PLAYWRIGHT FUNCTIONS ---
async def grab_m3u8_from_iframe(page, iframe_url, depth=0):
    """Open iframe and capture m3u8 streams, handling nested iframes recursively."""
    if depth > 3:  # Prevent infinite nesting
        return set()
    
    found_streams = set()

    def handle_response(response):
        if ".m3u8" in response.url:
            print(f"✅ Found M3U8 Stream: {response.url}")
            found_streams.add(response.url)

    page.on("response", handle_response)
    print(f"🌐 Navigating to iframe (depth {depth}): {iframe_url}")
    try:
        await page.goto(iframe_url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"❌ Failed to load iframe page: {e}")
        page.remove_listener("response", handle_response)
        return set()

    # Wait a few seconds for JS to generate streams
    await asyncio.sleep(6)

    # Check for nested iframes
    nested_iframes = await page.locator("iframe").all()
    for nested in nested_iframes:
        src = await nested.get_attribute("src")
        width = await nested.get_attribute("width") or "0"
        height = await nested.get_attribute("height") or "0"
        if not src or width == "0" or height == "0":
            continue
        if any(domain in src for domain in VALID_EMBED_DOMAINS):
            nested_streams = await grab_m3u8_from_iframe(page, src, depth=depth+1)
            found_streams.update(nested_streams)

    page.remove_listener("response", handle_response)

    if not found_streams:
        print(f"❌ No M3U8 URLs captured for {iframe_url}")
        return set()

    # Validate URLs
    tasks = [check_m3u8_url(url, iframe_url) for url in found_streams]
    results = await asyncio.gather(*tasks)
    valid_urls = {url for url, ok in zip(found_streams, results) if ok}
    return valid_urls

# --- BUILD PLAYLIST ---
def build_m3u(streams):
    lines = ['#EXTM3U']
    for s in streams:
        urls = s.get("urls", [])
        if not urls:
            continue
        lines.append(f'#EXTINF:-1,{s["name"]}')
        lines.extend(CUSTOM_HEADERS)
        lines.extend(urls)
    return "\n".join(lines)

# --- MAIN ---
async def main():
    all_streams = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for url in SHARKSTREAMS_PAGES:
            print(f"\n🔎 Processing page: {url}")
            try:
                await page.goto(url, timeout=30000)
                iframes = await page.locator("iframe").all()
                iframe_url = None
                for i in iframes:
                    src = await i.get_attribute("src")
                    width = await i.get_attribute("width") or "0"
                    height = await i.get_attribute("height") or "0"
                    if not src or width == "0" or height == "0":
                        continue
                    if any(domain in src for domain in VALID_EMBED_DOMAINS):
                        iframe_url = src
                        break
                if iframe_url:
                    urls = await grab_m3u8_from_iframe(page, iframe_url)
                    all_streams.append({
                        "name": url.split("/")[-1] or "SharkStreams",
                        "urls": list(urls)
                    })
                else:
                    print("⚠️ No valid iframe found on this page")
            except Exception as e:
                print(f"❌ Failed processing {url}: {e}")

        await browser.close()

    # Build M3U playlist
    playlist = build_m3u(all_streams)
    filename = f"SharkStreams_{datetime.utcnow().strftime('%Y%m%d%H%M')}.m3u8"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"✅ Playlist saved as {filename}")

if __name__ == "__main__":
    asyncio.run(main())
