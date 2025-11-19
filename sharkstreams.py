import asyncio
import re
import requests
import logging
from datetime import datetime
from playwright.async_api import async_playwright

# --- LOGGING SETUP (Console Only) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("scraper")

# --- CONFIGURATION ---
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

FALLBACK_LOGOS = {
    "american football": "http://drewlive24.duckdns.org:9000/Logos/Am-Football2.png",
    "nfl": "http://drewlive24.duckdns.org:9000/Logos/Am-Football2.png",
    "football": "https://external-content.duckduckgo.com/iu/?u=https://i.imgur.com/RvN0XSF.png",
    "soccer": "https://external-content.duckduckgo.com/iu/?u=https://i.imgur.com/RvN0XSF.png",
    "fight": "http://drewlive24.duckdns.org:9000/Logos/Combat-Sports.png",
    "mma": "http://drewlive24.duckdns.org:9000/Logos/Combat-Sports.png",
    "ufc": "http://drewlive24.duckdns.org:9000/Logos/Combat-Sports.png",
    "boxing": "http://drewlive24.duckdns.org:9000/Logos/Combat-Sports.png",
    "wwe": "http://drewlive24.duckdns.org:9000/Logos/Combat-Sports.png",
    "basketball": "http://drewlive24.duckdns.org:9000/Logos/Basketball5.png",
    "nba": "http://drewlive24.duckdns.org:9000/Logos/Basketball5.png",
    "motor sports": "http://drewlive24.duckdns.org:9000/Logos/Motorsports3.png",
    "f1": "http://drewlive24.duckdns.org:9000/Logos/Motorsports3.png",
    "nascar": "http://drewlive24.duckdns.org:9000/Logos/Motorsports3.png",
    "darts": "http://drewlive24.duckdns.org:9000/Logos/Darts.png",
    "tennis": "http://drewlive24.duckdns.org:9000/Logos/Tennis-2.png",
    "rugby": "http://drewlive24.duckdns.org:9000/Logos/Rugby.png",
    "cricket": "http://drewlive24.duckdns.org:9000/Logos/Cricket.png",
    "golf": "http://drewlive24.duckdns.org:9000/Logos/Golf.png",
    "baseball": "http://drewlive24.duckdns.org:9000/Logos/MLB.png",
    "mlb": "http://drewlive24.duckdns.org:9000/Logos/MLB.png",
    "nhl": "http://drewlive24.duckdns.org:9000/Logos/NHL.png",
    "hockey": "http://drewlive24.duckdns.org:9000/Logos/NHL.png",
    "other": "http://drewlive24.duckdns.org:9000/Logos/DrewLiveSports.png"
}

TV_IDS = {
    "baseball": "MLB.Baseball.Dummy.us",
    "mlb": "MLB.Baseball.Dummy.us",
    "fight": "PPV.EVENTS.Dummy.us",
    "mma": "PPV.EVENTS.Dummy.us",
    "ufc": "PPV.EVENTS.Dummy.us",
    "boxing": "PPV.EVENTS.Dummy.us",
    "wwe": "PPV.EVENTS.Dummy.us",
    "american football": "Football.Dummy.us",
    "nfl": "Football.Dummy.us",
    "ncaaf": "Football.Dummy.us",
    "football": "Soccer.Dummy.us",
    "soccer": "Soccer.Dummy.us",
    "basketball": "Basketball.Dummy.us",
    "nba": "Basketball.Dummy.us",
    "hockey": "NHL.Hockey.Dummy.us",
    "nhl": "NHL.Hockey.Dummy.us",
    "tennis": "Tennis.Dummy.us",
    "darts": "Darts.Dummy.us",
    "motor sports": "Racing.Dummy.us",
    "f1": "Racing.Dummy.us",
    "rugby": "Rugby.Dummy.us",
    "cricket": "Cricket.Dummy.us",
    "other": "Sports.Dummy.us"
}

total_matches = 0
total_streams = 0
total_failures = 0


def strip_non_ascii(text: str) -> str:
    """Remove emojis and non-ASCII characters."""
    if not text:
        return ""
    return re.sub(r"[^\x00-\x7F]+", "", text).strip()


def format_time_et(date_str: str) -> str:
    """Converts '2025-11-18 19:00:00' to 'Nov 18 - 07:00 PM ET'"""
    try:
        dt_obj = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S")
        return dt_obj.strftime("%b %d - %I:%M %p ET")
    except ValueError:
        return f"{date_str} ET"


def is_current_or_future(date_str: str) -> bool:
    """Checks if the event date is Today or in the Future."""
    try:
        event_dt = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S")
        today = datetime.now().date()
        # Return True if event is today or in the future
        return event_dt.date() >= today
    except ValueError:
        return True # Default to showing it if date parse fails


def get_all_matches():
    """Scrapes SharkStreams homepage."""
    url = "https://sharkstreams.net"
    all_matches = []
    
    try:
        log.info(f"📡 Fetching {url}...")
        res = requests.get(url, headers=FETCH_HEADERS, timeout=10)
        res.raise_for_status()
        html = res.text

        pattern = re.compile(
            r'<div class="row">.*?<span class="ch-date">([^<]+)</span>.*?<span class="ch-category">([^<]+)</span>.*?<span class="ch-name">([^<]+)</span>.*?openEmbed\(\'([^\']+)\'\)',
            re.DOTALL
        )
        
        matches = pattern.findall(html)
        
        for m in matches:
            raw_date, category, name, embed_url = m
            clean_name = strip_non_ascii(name)
            
            # --- CONDITIONAL TITLE FORMATTING ---
            if is_current_or_future(raw_date):
                # If Live/Future: "Pistons vs Hawks (Nov 18 - 07:00 PM ET)"
                readable_time = format_time_et(raw_date)
                display_title = f"{clean_name} ({readable_time})"
            else:
                # If Old/Past: Just "NFL Redzone" (No confusing date)
                display_title = clean_name

            all_matches.append({
                "title": display_title,
                "category": strip_non_ascii(category),
                "embed_url": embed_url
            })

        log.info(f"✅ Found {len(all_matches)} matches from HTML")

    except Exception as e:
        log.warning(f"⚠️ Failed fetching main page: {e}")
    
    log.info(f"🎯 Total matches collected: {len(all_matches)}")
    return all_matches


async def extract_m3u8(page, embed_url):
    global total_failures
    found = None
    
    if not embed_url.startswith('http'):
        embed_url = f"https:{embed_url}" if embed_url.startswith('//') else embed_url

    try:
        async def on_request(request):
            nonlocal found
            if ".m3u8" in request.url and not found:
                if "prd.jwpltx.com" in request.url:
                    return
                found = request.url
                log.info(f"  ⚡ Stream detected: {found}")

        page.on("request", on_request)
        
        log.info(f"    • Navigating to player: {embed_url}")
        await page.goto(embed_url, wait_until="domcontentloaded", timeout=8000)
        
        try:
            play_selectors = ["button.vjs-big-play-button", ".jw-icon-display", "div[class*='play']", "video", "button"]
            for sel in play_selectors:
                if await page.is_visible(sel):
                    await page.click(sel, timeout=500)
                    break
            
            await page.mouse.click(300, 300)
            await asyncio.sleep(0.2)
            
            pages_now = page.context.pages
            if len(pages_now) > 1:
                for p in pages_now[1:]:
                    try: await p.close()
                    except: pass
            
            await page.bring_to_front()
            await page.mouse.click(300, 300)
            
        except Exception:
            pass 

        for _ in range(8):
            if found: break
            await asyncio.sleep(0.5)

        if not found:
            content = await page.content()
            matches = re.findall(r'(https?://[^\s"\'<>]+\.m3u8)', content)
            if matches:
                found = matches[0]
                log.info(f"  🕵️ Regex found stream in source code")

        return found

    except Exception as e:
        total_failures += 1
        log.warning(f"⚠️ Extraction failed for {embed_url}: {e}")
        return None


def get_logo_url(category):
    cat_clean = category.lower().replace("-", " ").strip()
    for key, url in FALLBACK_LOGOS.items():
        if key in cat_clean:
            return url
    return FALLBACK_LOGOS["other"]


async def process_match(index, match, total, ctx):
    global total_streams
    title = match.get("title", "Unknown")
    category = match.get("category", "Other")
    embed_url = match.get("embed_url")
    
    log.info(f"\n🎯 [{index}/{total}] {title}")
    
    if not embed_url:
        log.info("      ❌ No embed URL found")
        return match, None

    page = await ctx.new_page()
    m3u8 = await extract_m3u8(page, embed_url)
    await page.close()

    if m3u8:
        total_streams += 1
        log.info(f"      ✅ Stream OK")
        return match, m3u8
    else:
        log.info(f"      ❌ No stream found")
        return match, None


async def generate_playlist():
    global total_matches
    matches = get_all_matches()
    total_matches = len(matches)
    
    if not matches:
        log.warning("❌ No matches found.")
        return "#EXTM3U\n"

    content = ["#EXTM3U"]
    success = 0
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        
        for i, m in enumerate(matches, 1):
            match_data, url = await process_match(i, m, total_matches, ctx)
            
            if not url:
                continue

            title = match_data.get("title")
            raw_cat = match_data.get("category")
            logo = get_logo_url(raw_cat)
            
            cat_key = raw_cat.lower().replace(" ", "")
            tv_id = TV_IDS.get(cat_key, TV_IDS["other"])
            
            group_title = f"SharkStreams - {raw_cat}"

            content.append(
                f'#EXTINF:-1 tvg-id="{tv_id}" tvg-name="{title}" '
                f'tvg-logo="{logo}" group-title="{group_title}",{title}'
            )
            content.append(url)
            success += 1

        await browser.close()

    log.info(f"\n🎉 {success} working streams written to playlist.")
    return "\n".join(content)


if __name__ == "__main__":
    start = datetime.now()
    log.info("🚀 Starting SharkStreams run...")
    
    playlist = asyncio.run(generate_playlist())
    
    with open("SharkStreams.m3u8", "w", encoding="utf-8") as f:
        f.write(playlist)
        
    end = datetime.now()
    duration = (end - start).total_seconds()
    
    log.info("\n📊 FINAL SUMMARY ------------------------------")
    log.info(f"🕓 Duration: {duration:.2f} sec")
    log.info(f"📺 Matches:  {total_matches}")
    log.info(f"✅ Streams:  {total_streams}")
    log.info(f"❌ Failures: {total_failures}")
    log.info("------------------------------------------------")
