import json
import base64
import time
import os
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urljoin, quote
import sys

try:
    import requests
except ImportError:
    print("[WARN] requests library not available")
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[WARN] beautifulsoup4 not available")
    BeautifulSoup = None

# Configure console output to use UTF-8 to prevent encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================
# CONSTANTS
# ============================================
MANUAL_MAPPING_FILE = 'manual_mapping.json'
# OpenAI-compatible chat completions API (sumopod proxy -> GLM models).
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://ai.sumopod.com").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "glm-5.3-flash")
AI_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "4096"))
# Backwards-compatible aliases (older code referenced the DeepSeek names).
DEEPSEEK_API_KEY = os.environ.get(
    "AI_API_KEY",
    os.environ.get("DEEPSEEK_API_KEY", ""),
)
DEEPSEEK_MODEL = AI_MODEL
BATCH_SIZE = 30

# ============================================
# HELPERS
# ============================================

def encode_url_to_base64(url):
    """Encode URL to base64"""
    return base64.b64encode(url.encode()).decode()


def build_player_url(stream_url):
    """Build the multi.govoet.cc player URL with a query-safe hls value.

    The multi.govoet.cc player reads the query via `URLSearchParams` and then
    runs `atob()` on the value. URLSearchParams converts '+' to a space, which
    breaks atob() whenever the base64 contains a '+' (common for URLs). To avoid
    that, every base64 char is percent-encoded; URLSearchParams decodes it back
    to the exact base64 string, so atob() always succeeds.
    """
    encoded_url = quote(base64.b64encode(stream_url.encode()).decode(), safe='')
    return f"https://multi.govoet.cc/?hls={encoded_url}"


# The splash CDN rotates between these hosts over time. The signed stream token
# (txSecret/txTime) is per stream + time, not host-bound, so we generate the SAME
# stream URL on each known host; if the site switches hosts, the frontend can
# still play from whichever host is currently serving.
STREAM_HOSTS = [
    "https://pull.niur.live",
    "https://pull.niues.live",
]


def variant_stream_urls(stream_url):
    """Return the same signed stream URL rewritten on every known HLS host."""
    try:
        from urllib.parse import urlparse
        u = urlparse(stream_url)
        path, query = u.path, u.query
        out = []
        for host in STREAM_HOSTS:
            v = f"{host}{path}"
            if query:
                v += f"?{query}"
            if v not in out:
                out.append(v)
        return out or [stream_url]
    except Exception:
        return [stream_url]

def normalize_text(text):
    """Normalize text for lookup: strip accents, lowercase, remove non-alphanum"""
    if not text:
        return ''
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.lower()
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def setup_driver():
    """No-op kept for compatibility; scraping now uses requests + BeautifulSoup."""
    return None

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ============================================
# LEAGUE TRANSLATION (via AI — sumopod/GLM)
# ============================================

def load_league_mapping():
    """
    Load existing league mappings from manual_mapping.json.
    Mendukung format flat LAMA maupun per-negara BARU (deteksi otomatis).
    Returns: (lookup dict: normalized_alias -> canonical, raw mapping data)
    """
    try:
        from mapping_loader import load_manual_mapping as _load
        _, league_lookup, mapping_data = _load(MANUAL_MAPPING_FILE)
        return league_lookup, mapping_data
    except Exception:
        return {}, {'team_names': {}, 'league_names': {}}


def _call_deepseek_translate(batch, ref_list):
    """
    Call the AI chat API to translate a batch of league names to standard
    English. (Historical name kept; now targets AI_BASE_URL / AI_MODEL.)
    Returns dict: {original_name: translated_name}
    """
    try:
        import requests
    except ImportError:
        print("    [WARN] requests library not available for AI translation")
        return {}

    prompt = f"""You are a sports data expert. Translate these league/competition names to standard English.

RULES:
1. Always output in English only — no other language allowed
2. Club leagues format: "Country - Competition Name" (e.g. "France - Ligue 1", "Brazil - Serie A")
3. International competitions: "World - FIFA World Cup", "Europe - UEFA Champions League", "South America - Copa Libertadores"
4. Friendly matches: ALWAYS use "Club Friendly" (NOT "Amical club", NOT "Amistoso", NOT "Friendly Match", NOT "International Friendly")
5. Vietnamese names: translate fully (e.g. "Giải bóng đá vô địch Ecuador" = Ecuador league → "Ecuador - Primera A", "Giải bóng đá đội tuyển dự bị nhà nghề Mỹ" → "USA - MLS Next Pro")
6. Abbreviations: "BRA D1" → "Brazil - Serie A", "USA MLS" → "USA - MLS", "CON CSA" → "South America - Copa Sudamericana", "CON LIB" → "South America - Copa Libertadores", "UEFA CL" → "Europe - UEFA Champions League"
7. French names: "Amical club" → "Club Friendly", "Ligue 1" → "France - Ligue 1"
8. If completely invalid/spam/not a real competition → "SKIP"

Names to translate: {json.dumps(batch, ensure_ascii=False)}

Known leagues for reference (if helpful): {json.dumps(ref_list[:150], ensure_ascii=False)}

Respond ONLY with raw JSON object (no markdown, no explanation). Example:
{{"Amical club": "Club Friendly", "Giải VDQG Ecuador": "Ecuador - Primera A", "BRA D1": "Brazil - Serie A"}}"""

    url = f'{AI_BASE_URL}/v1/chat/completions'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
    }
    payload = {
        'model': AI_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
        'max_tokens': AI_MAX_TOKENS
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            message = response.json()['choices'][0]['message']
            content = (message.get('content') or '').strip()
            # Reasoning models may return the text in reasoning_content.
            if not content:
                content = (message.get('reasoning_content') or '').strip()
            # Remove markdown code block if present
            if content.startswith('```'):
                content = re.sub(r'^```[a-zA-Z]*\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
            # Extract JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        else:
            print(f"    [ERR] AI API status {response.status_code}")
    except Exception as e:
        print(f"    [ERR] AI API call failed: {e}")

    return {}


def save_league_translations(translations, mapping_data):
    """
    Save AI-translated league names to manual_mapping.json.
    Format-aware (mendukung file FLAT lama maupun PER-NEGARA baru via
    mapping_loader.add_alias). Entri baru ditaruh di grup 'International'
    pada format per-negara. Format: "Canonical English": ["original_alias", ...]
    """
    if not translations:
        return 0

    from mapping_loader import alias_exists, add_alias

    added = 0
    for alias, canonical in translations.items():
        if not canonical or canonical == 'SKIP' or canonical == alias:
            continue
        if normalize_text(alias) == normalize_text(canonical):
            continue
        if alias_exists(mapping_data, 'league_names', alias):
            continue
        if add_alias(mapping_data, 'league_names', canonical, alias,
                     country="International"):
            added += 1

    if added > 0:
        with open(MANUAL_MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print(f"  💾 Saved {added} new league translations to {MANUAL_MAPPING_FILE}")
    return added

    return added


def translate_leagues_with_ai(matches):
    """
    Detect untranslated (non-English) league names in scraped matches,
    call the AI to translate them, save to manual_mapping.json,
    and apply translations to the match list.
    """
    print("\n🌐 Checking league names for translation...")

    # Load existing mapping
    lookup, mapping_data = load_league_mapping()

    # Collect unique untranslated leagues
    unique_leagues = sorted(set(m.get('league', '') for m in matches if m.get('league')))
    untranslated = [lg for lg in unique_leagues if lg and normalize_text(lg) not in lookup]

    if not untranslated:
        print("  ✅ All league names are already mapped — no AI needed.")
    elif not DEEPSEEK_API_KEY:
        print(f"  ⚠️  {len(untranslated)} untranslated leagues found, but DEEPSEEK_API_KEY not set. Skipping AI.")
    else:
        print(f"  Found {len(untranslated)} untranslated league names → calling AI ({AI_MODEL})...")

        # Collect reference leagues from existing mapping keys (English names)
        ref_list = sorted(mapping_data.get('league_names', {}).keys())

        # Process in batches
        all_translations = {}
        batches = [untranslated[i:i+BATCH_SIZE] for i in range(0, len(untranslated), BATCH_SIZE)]
        for idx, batch in enumerate(batches):
            print(f"  Batch {idx+1}/{len(batches)} ({len(batch)} leagues)...")
            result = _call_deepseek_translate(batch, ref_list)
            if result:
                count = sum(1 for v in result.values() if v and v != 'SKIP')
                print(f"    [OK] Translated {count}/{len(batch)} names")
                all_translations.update(result)
            if idx < len(batches) - 1:
                time.sleep(1)

        # Save to manual_mapping.json
        save_league_translations(all_translations, mapping_data)

        # Update lookup with new translations
        for alias, canonical in all_translations.items():
            if canonical and canonical != 'SKIP':
                lookup[normalize_text(alias)] = canonical

    # Apply translations to matches
    translated_count = 0
    for match in matches:
        league = match.get('league', '')
        if league:
            canon = lookup.get(normalize_text(league))
            if canon and canon != league:
                match['league'] = canon
                translated_count += 1

    if translated_count:
        print(f"  ✅ Applied translations to {translated_count} match(es).")

    return matches


# ============================================
# SCRAPING (requests + BeautifulSoup)
# ============================================

def resolve_kickoff(time_text, now=None):
    """Parse "HH:MM DD/MM" (no year) into the kickoff datetime closest to `now`.

    The sites show no year, so it must be inferred. Choosing the nearest
    candidate year (previous / current / next) keeps a live match that just
    started, or one that kicked off before midnight, on its real date, while
    still rolling a year-boundary fixture (e.g. "05/01" seen in late December)
    into the next year. Returns None when the text cannot be parsed.
    """
    now = now or datetime.now()
    parts = time_text.split()
    if len(parts) < 2:
        return None
    time_str, date_str = parts[0], parts[1]
    try:
        base = datetime.strptime(f"{date_str}/{now.year} {time_str}", "%d/%m/%Y %H:%M")
    except ValueError:
        return None
    best = base
    for year in (now.year - 1, now.year + 1):
        try:
            cand = base.replace(year=year)
        except ValueError:
            continue  # e.g. 29/02 in a non-leap year
        if abs(cand - now) < abs(best - now):
            best = cand
    return best


def parse_time(time_text):
    """
    Parse time text like '18:00 08/08' -> (match_date, match_time).
    Falls back to today 00:00 if parsing fails.
    """
    kickoff = resolve_kickoff(time_text)
    if kickoff:
        return kickoff.strftime("%Y-%m-%d"), kickoff.strftime("%H:%M")
    return datetime.now().strftime("%Y-%m-%d"), "00:00"

def _img_src(img):
    """Get real image URL, respecting lazy-load data-src."""
    if img is None:
        return ''
    # data-src holds the real URL for lazy-loaded images
    src = img.get('data-src') or img.get('src') or ''
    if not src or src.startswith('data:'):
        return ''
    return src.strip()

# ============================================
# STREAM URL RESOLUTION (signed HLS)
# ============================================
# Since 2026 the site no longer serves plain `pull.niues.live` URLs. Real HLS
# links are signed: https://pull.niur.live/live/stream-{id}_lhd.m3u8?txSecret=...&txTime=...
# The site resolves them via two endpoints; we mirror the site's own logic:
#   1) index  : https://biz.vnres.co/api/live/livingRoom -> [ {id, stream}, ... ]
#      (one call covers all currently-online BLV channels; streams are .flv)
#   2) resolve: <base>/wp-json/soco/v1/stream/resolve?post_id=...&blv=...
#      (per match page; needs post_id present on that page)
STREAM_INDEX_URL = "https://biz.vnres.co/api/live/livingRoom"

# The splash domain rotates frequently (socolive3.watch -> socoliveq.tv ->
# socolivep.tv -> socolivei.tv/socolivev.tv -> socolive74.tv ...). Probe
# candidates and use whichever responds. The WP-API resolve URL is DERIVED from
# the working base below, so a rotation only needs a new entry here, never a
# second edit. Newest known-good domain goes first (highest priority).
CANDIDATE_BASES = [
    "https://socolive74.tv/",
    "https://socolivey.io/",
    "https://socolivei.tv/",
    "https://socolivel.tv/",
    "https://socolivep.tv/",
    "https://socoliveq.tv/",
    "https://socolive3.watch/",
    "https://socolive.net/",
]

RESOLVE_PATH = "/wp-json/soco/v1/stream/resolve"

# Only these hosts are playable. The index sometimes returns `pullNN.scstream.net`
# or `pull.niues.live` URLs (auth_key) which return 403; `pull.niur.live`
# (txSecret) plays fine.
ALLOWED_STREAM_HOSTS = {"pull.niur.live", "pull.niues.live"}

_POST_ID_CACHE = {}

def _is_playable_host(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname in ALLOWED_STREAM_HOSTS
    except Exception:
        return False

def _flv_to_m3u8(url):
    """Convert a signed .flv stream URL to .m3u8, keeping query params."""
    return re.sub(r'\.flv(?=([?#]|$))', '.m3u8', url, flags=re.IGNORECASE)

def fetch_stream_index():
    """{blv_id: signed m3u8 url} for all currently-online BLV channels."""
    from http_client import http_get
    try:
        resp = http_get(STREAM_INDEX_URL, headers={'Accept': 'application/json'}, timeout=20, retries=2)
        if resp.status_code != 200:
            print(f"  [warn] stream index HTTP {resp.status_code}")
            return {}
        rows = resp.json()
        rows = rows if isinstance(rows, list) else (rows.get('data', []) if isinstance(rows, dict) else [])
        index = {}
        for x in rows:
            blv_id = str(x.get('id') or '').strip()
            stream = str(x.get('stream') or '').strip()
            if not (blv_id and stream.startswith('http')):
                continue
            # Keep ALL channels here so `near_live` detection below still works;
            # host filtering to playable ones happens when we STORE the server.
            index[blv_id] = _flv_to_m3u8(stream)
        print(f"  [ok] stream index: {len(index)} channel(s)")
        return index
    except Exception as e:
        print(f"  [warn] stream index unavailable: {e}")
        return {}

def get_post_id(match_url):
    """post_id for the WP-API resolver, parsed from the match detail page."""
    if match_url in _POST_ID_CACHE:
        return _POST_ID_CACHE[match_url]
    from http_client import http_get
    post_id = None
    try:
        page = http_get(match_url, headers=HEADERS, timeout=25, retries=1).text
        m = re.search(r'post[_-]?id["\']?\s*[:=]\s*["\']?(\d{4,7})', page)
        if m:
            post_id = m.group(1)
    except Exception:
        pass
    _POST_ID_CACHE[match_url] = post_id
    return post_id

def resolve_stream(post_id, blv_id, base_url):
    """Per-channel resolve via the WP-API endpoint (mirrors the site's primary path).

    `base_url` is the working splash domain found at runtime; the resolve URL is
    built from it so a domain rotation does not need a code change.
    """
    from http_client import http_get
    if not post_id or not blv_id or not base_url:
        return None
    url = f"{base_url.rstrip('/')}{RESOLVE_PATH}?post_id={post_id}&blv={blv_id}"
    try:
        r = http_get(url, headers={'Accept': 'application/json'}, timeout=15, retries=2)
        data = r.json()
        if data.get('ok') is True and isinstance(data.get('stream'), str) and data['stream'].startswith('http'):
            stream = _flv_to_m3u8(data['stream'])
            return stream if _is_playable_host(stream) else None
    except Exception:
        pass
    return None

def scrape_with_selenium(stream_index=None):
    """Scrape all matches by fetching the page HTML directly."""
    if requests is None or BeautifulSoup is None:
        print("[ERR] requests/beautifulsoup4 are required")
        return []

    from http_client import http_get

    # 1) Find a working base domain.
    base_url = None
    for cand in CANDIDATE_BASES:
        try:
            r = http_get(cand, headers=HEADERS, timeout=15, retries=1)
            if r.status_code == 200 and len(r.text) > 5000:
                base_url = cand
                print(f"Base domain: {base_url}")
                break
        except Exception:
            continue
    if base_url is None:
        print("[ERR] no working base domain found")
        return []

    try:
        print(f"Fetching {base_url}...")
        resp = http_get(base_url, headers=HEADERS, timeout=30, retries=2)
        resp.raise_for_status()
        print(f"  HTTP {resp.status_code}, {len(resp.text)} bytes")

        # Pre-resolve BLV channel -> signed HLS URL once per cycle.
        if stream_index is None:
            stream_index = fetch_stream_index()

        soup = BeautifulSoup(resp.text, 'html.parser')
        match_elements = soup.select('.match-item')

        print(f"\nFound {len(match_elements)} total matches")
        print("Processing matches...\n")

        matches = []
        for match_elem in match_elements:
            try:
                # League name
                league_elem = match_elem.select_one('.match-item__comp')
                league_name = league_elem.get_text(strip=True) if league_elem else ''

                # Time
                time_elem = match_elem.select_one('.match-item__time span')
                time_text = time_elem.get_text(strip=True) if time_elem else ""

                # Teams
                home_team_elem = match_elem.select_one('.name-home span')
                home_team = home_team_elem.get_text(strip=True) if home_team_elem else "Unknown"
                away_team_elem = match_elem.select_one('.name-away span')
                away_team = away_team_elem.get_text(strip=True) if away_team_elem else "Unknown"

                # Logos
                home_logo = _img_src(match_elem.select_one('.logo-home img'))
                away_logo = _img_src(match_elem.select_one('.logo-away img'))

                print(f"  Match: {home_team} vs {away_team}")
                print(f"  Time: {time_text}")

                # Match URL
                link_elem = match_elem.select_one('a.link-match')
                match_url = urljoin(base_url, link_elem.get('href', '')) if link_elem else ""

                # BLV channels
                blv_elements = match_elem.select('.blv-item-scl')

                if not blv_elements:
                    print(f"  No BLV channels found, skipping...")
                    continue

                servers = []
                blv_ids = []
                blv_names = []
                for blv_elem in blv_elements:
                    blv_link = blv_elem.select_one('a.dropdown-item')
                    if blv_link is None:
                        continue
                    blv_url = urljoin(base_url, blv_link.get('href', ''))
                    blv_name_elem = blv_link.select_one('span')
                    blv_name = blv_name_elem.get_text(strip=True) if blv_name_elem else ''
                    query_params = parse_qs(urlparse(blv_url).query)
                    if 'blv' not in query_params:
                        continue
                    blv_ids.append(query_params['blv'][0])
                    blv_names.append(blv_name)

                if not blv_ids:
                    print(f"  No BLV channels found, skipping...")
                    continue

                # Only fetch the match page (post_id) when the match is near-live:
                # at least one of its channels is present in the (unfiltered) index.
                near_live = any(bid in stream_index for bid in blv_ids)
                match_post_id = get_post_id(match_url) if near_live else None

                for blv_id, blv_name in zip(blv_ids, blv_names):
                    try:
                        # Primary: the livingRoom index, which already returns the
                        # playable pull.niur.live (txSecret) URL for live channels.
                        stream_url = stream_index.get(blv_id)
                        if not _is_playable_host(stream_url) and near_live:
                            # Some channels are only reachable via the WP-API
                            # resolver (still only kept if it yields a niur URL).
                            resolved = resolve_stream(match_post_id, blv_id, base_url)
                            if resolved:
                                stream_url = resolved
                        if not stream_url or not _is_playable_host(stream_url):
                            print(f"  Channel: {blv_name} (BLV ID: {blv_id}) - no playable stream yet")
                            continue

                        # Store the stream on every known HLS host (fallback band)
                        # in case the site rotates the CDN host.
                        for vurl in variant_stream_urls(stream_url):
                            servers.append({
                                "url": build_player_url(vurl),
                                "label": f"CH-VN",
                            })
                        print(f"  Channel: {blv_name} (BLV ID: {blv_id})")
                    except Exception:
                        continue

                if not servers:
                    print(f"  No live stream link yet - keeping entry with empty servers.")
                else:
                    print(f"  Resolved {len(servers)} live stream(s).")

                match_date, match_time = parse_time(time_text)

                # Create match ID
                match_id = urlparse(match_url).path.split('/')[-2] if match_url else ""

                # Build team objects
                team1_obj = {"name": home_team}
                if home_logo:
                    team1_obj["logo"] = home_logo

                team2_obj = {"name": away_team}
                if away_logo:
                    team2_obj["logo"] = away_logo

                matches.append({
                    "id": match_id,
                    "league": league_name,
                    "team1": team1_obj,
                    "team2": team2_obj,
                    "kickoff_date": match_date,
                    "kickoff_time": match_time,
                    "match_date": match_date,
                    "match_time": match_time,
                    "duration": "3.0",
                    "servers": servers
                })
                print(f"  Added with {len(servers)} server(s)\n")

            except Exception as e:
                print(f"  Error processing match: {e}")
                continue

        return matches

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def save_to_json(matches, filename="soco.json"):
    """Save matches to JSON file"""
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
    print("SOCOLIVE MATCH SCRAPER")
    print("=" * 60)
    
    matches = scrape_with_selenium()
    
    if matches:
        # Translate league names to English via AI and save mappings
        matches = translate_leagues_with_ai(matches)

        save_to_json(matches, "soco.json")
        
        print("\n" + "=" * 60)
        print(f"SUMMARY: Found {len(matches)} match(es)")
        print("=" * 60)
        
        for i, match in enumerate(matches, 1):
            print(f"\n{i}. {match['team1']['name']} vs {match['team2']['name']}")
            print(f"   League: {match['league']}")
            print(f"   Date: {match['match_date']} {match['match_time']}")
            print(f"   Servers: {len(match['servers'])}")
            has_logos = bool(match['team1'].get('logo') or match['team2'].get('logo'))
            print(f"   Logos: {'✅' if has_logos else '❌'}")
    else:
        print("\n❌ No matches found")

if __name__ == "__main__":
    main()