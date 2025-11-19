import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

SHARKSTREAMS_MAIN = "https://sharkstreams.net"
CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0',
]

async def fetch_channel_ids():
    """Scrape the main page to get all channel IDs dynamically."""
    async with aiohttp.ClientSession() as session:
        async with session.get(SHARKSTREAMS_MAIN) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    channel_ids = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "player.php?channel=" in href:
            cid = href.split("channel=")[-1]
            channel_ids.add(cid)
    print(f"Found {len(channel_ids)} channel IDs")
    return sorted(channel_ids, key=int)

async def get_m3u8_urls(channel_id):
    """Call get-stream.php to retrieve actual .m3u8 URLs for a channel."""
    url = f"{SHARKSTREAMS_MAIN}/get-stream.php?channel={channel_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            urls = [line.strip() for line in text.splitlines() if ".m3u8" in line]
            return urls

def build_m3u(channels):
    """Build an M3U playlist from the captured streams."""
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
    channel_ids = await fetch_channel_ids()
    all_channels = []

    for idx, cid in enumerate(channel_ids, start=1):
        print(f"\n🔎 Fetching streams for channel {cid} ({idx}/{len(channel_ids)})")
        urls = await get_m3u8_urls(cid)
        if urls:
            print(f"✅ Found {len(urls)} streams for channel {cid}")
            all_channels.append({"id": cid, "urls": urls})
        else:
            print(f"⚠️ No streams found for channel {cid}")

    playlist = build_m3u(all_channels)
    filename = f"SharkStreams_All_{datetime.utcnow().strftime('%Y%m%d%H%M')}.m3u8"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n✅ Playlist saved as {filename}")

if __name__ == "__main__":
    asyncio.run(main())
