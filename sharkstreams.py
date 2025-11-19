import asyncio
from playwright.async_api import async_playwright
from datetime import datetime

SHARKSTREAMS_MAIN = "https://sharkstreams.net"
CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
]

async def get_player_urls():
    """Use Playwright to extract all player.php URLs from SharkStreams main page."""
    urls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(SHARKSTREAMS_MAIN, wait_until="networkidle")
        await asyncio.sleep(5)  # wait for JS to render channels
        anchors = await page.query_selector_all("a[href*='player.php?channel=']")
        for a in anchors:
            href = await a.get_attribute("href")
            if href:
                full_url = SHARKSTREAMS_MAIN.rstrip("/") + "/" + href.lstrip("/")
                urls.append(full_url)
        await browser.close()
    print(f"Found {len(urls)} player URLs")
    return urls

async def get_m3u8_from_player(player_url):
    """Open a player URL and capture m3u8 streams dynamically."""
    streams = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Intercept responses to capture .m3u8 URLs
        def handle_response(response):
            if ".m3u8" in response.url:
                print("✅ Found M3U8:", response.url)
                streams.add(response.url)

        page.on("response", handle_response)
        await page.goto(player_url, wait_until="networkidle")
        await asyncio.sleep(6)  # wait for player requests to fire
        await browser.close()
    return list(streams)

def build_m3u(channels):
    """Build M3U playlist from captured streams."""
    lines = ["#EXTM3U"]
    for ch in channels:
        name = f"Channel_{ch['id']}"
        urls = ch.get("urls", [])
        if not urls:
            continue
        lines.append(f'#EXTINF:-1,{name}')
        lines.extend(CUSTOM_HEADERS)
        lines.extend(urls)
    return "\n".join(lines)

async def main():
    player_urls = await get_player_urls()
    all_channels = []

    for idx, url in enumerate(player_urls, start=1):
        channel_id = url.split("channel=")[-1]
        print(f"\n🔎 Processing channel {channel_id} ({idx}/{len(player_urls)})")
        m3u8_urls = await get_m3u8_from_player(url)
        if m3u8_urls:
            all_channels.append({"id": channel_id, "urls": m3u8_urls})
            print(f"✅ Found {len(m3u8_urls)} streams for channel {channel_id}")
        else:
            print(f"⚠️ No streams found for channel {channel_id}")

    # Build playlist
    playlist = build_m3u(all_channels)
    filename = f"SharkStreams_All_{datetime.utcnow().strftime('%Y%m%d%H%M')}.m3u8"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n✅ Playlist saved as {filename}")

if __name__ == "__main__":
    asyncio.run(main())
