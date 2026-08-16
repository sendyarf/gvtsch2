import json
import base64
import re
import sys
from datetime import datetime

try:
    import pytz
except ImportError:
    print("[WARN] pytz not available — falling back to no conversion")
    pytz = None

try:
    import requests
except ImportError:
    print("[WARN] requests library not available")
    requests = None

# Configure console output UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================
# CONSTANTS
# backup https://timst.cfd/streams
# ============================================
API_BASE = "https://timstreams.st/api"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}


def encode_url_to_base64(url):
    """Encode URL to base64."""
    return base64.b64encode(url.encode()).decode()


def build_player_url(embed_url):
    """Wrap an embed URL into the govoet player via iframe base64 param."""
    return f"https://multi.govoet.cc/?iframe={encode_url_to_base64(embed_url)}"


LANG_PATTERNS = [
    ('DE', ['german', 'deutsch']),
    ('ES', ['spanish', 'espanol', 'espa']),
    ('PT', ['portuguese', 'portugues']),
    ('IT', ['italian', 'italiano']),
    ('FR', ['french', 'francais', 'français']),
    ('PL', ['polish', 'polski']),
    ('EN', ['english']),
    ('AR', ['arabic', 'العربية']),
]


def detect_stream_label(name, embed_url):
    """Map a stream name/URL to a CH-xx server label. Defaults to CH-EN."""
    text = f"{name or ''} {embed_url or ''}".lower()
    for code, words in LANG_PATTERNS:
        for word in words:
            if word in text:
                return f"CH-{code}"
    return "CH-EN"


def split_name(name):
    """Best-effort split of an event name into team1 / team2."""
    if not name:
        return "", ""
    # Strip event-code prefix like "UFC 330:" when a matchup follows
    if ":" in name and (" vs " in name.split(":", 1)[1] or "@" in name.split(":", 1)[1]):
        name = name.split(":", 1)[1].strip()
    if " vs " in name:
        parts = name.split(" vs ", 1)
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    if "@" in name:
        parts = name.split("@", 1)
        t1 = parts[0].strip()
        t2 = parts[1].strip() if len(parts) > 1 else ""
        # Strip trailing event code like "761716" from teams
        t1 = re.sub(r'[\s-]*\d+$', '', t1)
        t2 = re.sub(r'[\s-]*\d+$', '', t2)
        return t1, t2
    if ":" in name:
        parts = name.split(":", 1)
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    return name.strip(), ""


SOURCE_TZ = 'America/New_York'
TARGET_TZ = 'Asia/Jakarta'

def parse_time(time_str):
    """ISO datetime (US Eastern, naive) -> (date, time) in Asia/Jakarta."""
    try:
        dt_naive = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
    except Exception:
        dt_naive = None

    if dt_naive is not None and pytz is not None:
        try:
            source_tz = pytz.timezone(SOURCE_TZ)
            target_tz = pytz.timezone(TARGET_TZ)
            dt = source_tz.localize(dt_naive).astimezone(target_tz)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except Exception:
            pass

    return datetime.now().strftime("%Y-%m-%d"), "00:00"


def scrape_timstreams():
    """Scrape all live/upcoming events from the timstreams API."""
    if requests is None:
        print("[ERR] requests library is required")
        return []

    url = f"{API_BASE}/live-upcoming"

    try:
        print(f"Fetching {url}...")
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        print(f"  HTTP {resp.status_code}")

        events = data.get('events', [])
        genres = {g['id']: g['name'] for g in data.get('genres', [])}
        sub_genres = {}
        for g in data.get('genres', []):
            for s in g.get('sub_categories', []):
                sub_genres[s['id']] = s['name']

        print(f"\nFound {len(events)} total events\n")

        matches = []
        for ev in events:
            try:
                name = ev.get('name', '').strip()
                if not name:
                    continue

                streams = ev.get('streams') or []
                servers = []
                for s in streams:
                    embed_url = (s.get('url') or '').strip()
                    if not embed_url:
                        continue
                    if not embed_url.startswith('http'):
                        embed_url = 'https://' + embed_url.lstrip('/')
                    servers.append({
                        "url": build_player_url(embed_url),
                        "label": detect_stream_label(s.get('name'), embed_url)
                    })

                if not servers:
                    continue

                team1_name, team2_name = split_name(name)

                # League: prefer sub-category name, else category name
                league = ""
                if ev.get('sub_genre') and sub_genres.get(ev['sub_genre']):
                    league = sub_genres[ev['sub_genre']]
                elif ev.get('genre') and genres.get(ev['genre']):
                    league = genres[ev['genre']]

                match_date, match_time = parse_time(ev.get('time') or '')
                match_id = ev.get('url') or ''

                team1_obj = {"name": team1_name}
                if ev.get('logo'):
                    team1_obj["logo"] = ev['logo']

                matches.append({
                    "id": match_id,
                    "league": league,
                    "team1": team1_obj,
                    "team2": {"name": team2_name},
                    "kickoff_date": match_date,
                    "kickoff_time": match_time,
                    "match_date": match_date,
                    "match_time": match_time,
                    "duration": "3.0",
                    "servers": servers
                })

                print(f"  Event: {name}")
                print(f"    League: {league} | Time: {match_date} {match_time}")
                print(f"    Servers: {len(servers)}")

            except Exception:
                continue

        return matches

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def save_to_json(matches, filename="timstreams.json"):
    """Save matches to JSON file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Successfully saved {len(matches)} matches to {filename}")
        return True
    except Exception as e:
        print(f"❌ Error saving to file: {e}")
        return False


def main():
    print("=" * 60)
    print("TIMSTREAMS MATCH SCRAPER")
    print("=" * 60)

    matches = scrape_timstreams()

    if matches:
        save_to_json(matches, "timstreams.json")

        print("\n" + "=" * 60)
        print(f"SUMMARY: Found {len(matches)} event(s)")
        print("=" * 60)

        for i, match in enumerate(matches, 1):
            t1 = match['team1'].get('name') or match['team1']['name']
            t2 = match['team2'].get('name')
            label = f"{t1} vs {t2}" if t2 else t1
            print(f"\n{i}. {label}")
            print(f"   League: {match['league']}")
            print(f"   Date: {match['match_date']} {match['match_time']}")
            print(f"   Servers: {len(match['servers'])}")
    else:
        print("\n❌ No events found")


if __name__ == "__main__":
    main()