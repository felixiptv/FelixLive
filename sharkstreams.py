import asyncio
from playwright.async_api import async_playwright
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIG ---
CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
]

SHARKSTREAMS_MAIN = "https://sharkstreams.net"

# --- UTIL FUNCTIONS ---
async def check_m3u8(url, referer):
    headers = {"Referer": referer, "User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status in [200, 403]
    except:
        return False

# --- PLAYWRIGHT FUNCTIONS ---
async def get_m3u8_from_player(player_url):
    """Open player.php URL and capture m3u8 streams."""
    streams = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        def handle_response(response):
            if ".m3u8" in response.url:
                print("✅ Found M3U8:", response.url)
                streams.add(response.url)

        page.on("response", handle_response)
        await page.goto(player_url, wait_until="domcontentloaded")
        await asyncio.sleep(6)  # wait for player to request m3u8
        await browser.close()

    # Validate URLs
    valid_urls = []
    for url in streams:
        if await check_m3u8(url, player_url):
            valid_urls.append(url)
    return valid_urls

# --- SCRAPE MAIN PAGE ---
async def get_all_player_urls():
    async with aiohttp.ClientSession() as session:
        async with session.get(SHARKSTREAMS_MAIN) as resp:
            html = await resp.text()
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "player.php?channel=" in href:
            full_url = SHARKSTREAMS_MAIN.rstrip("/") + "/" + href.lstrip("/")
            links.append(full_url)
    print(f"Found {len(links)} player URLs")
    return links

# --- BUILD PLAYLIST ---
def build_m3u(streams):
    lines = ["#EXTM3U"]
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
    player_urls = await get_all_player_urls()
    all_streams = []

    for idx, player_url in enumerate(player_urls, start=1):
        print(f"\n🔎 Processing {idx}/{len(player_urls)}: {player_url}")
        urls = await get_m3u8_from_player(player_url)
        if urls:
            all_streams.append({
                "name": player_url.split("=")[-1],
                "urls": urls
            })
        else:
            print(f"⚠️ No valid stream found for {player_url}")

    playlist = build_m3u(all_streams)
    filename = f"SharkStreams_All_{datetime.utcnow().strftime('%Y%m%d%H%M')}.m3u8"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n✅ Playlist saved as {filename}")

if __name__ == "__main__":
    asyncio.run(main())
