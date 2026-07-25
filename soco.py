from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import json
import base64
import time
import os
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import sys

# Configure console output to use UTF-8 to prevent encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================
# CONSTANTS
# ============================================
MANUAL_MAPPING_FILE = 'manual_mapping.json'
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
DEEPSEEK_MODEL = 'deepseek-v4-flash'
BATCH_SIZE = 30

# ============================================
# HELPERS
# ============================================

def encode_url_to_base64(url):
    """Encode URL to base64"""
    return base64.b64encode(url.encode()).decode()

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
    """Setup Chrome driver with options"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Run in background
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# ============================================
# LEAGUE TRANSLATION (via DeepSeek AI)
# ============================================

def load_league_mapping():
    """
    Load existing league mappings from manual_mapping.json.
    Returns: (lookup dict: normalized_alias -> canonical, raw mapping data)
    """
    try:
        with open(MANUAL_MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        mapping_data = {'team_names': {}, 'league_names': {}}

    league_names_map = mapping_data.get('league_names', {})
    lookup = {}
    for canonical, aliases in league_names_map.items():
        lookup[normalize_text(canonical)] = canonical
        if isinstance(aliases, list):
            for alias in aliases:
                if alias:
                    lookup[normalize_text(alias)] = canonical
        elif isinstance(aliases, str) and aliases:
            lookup[normalize_text(aliases)] = canonical

    return lookup, mapping_data


def _call_deepseek_translate(batch, ref_list):
    """
    Call DeepSeek API to translate a batch of league names to standard English.
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

    url = 'https://api.deepseek.com/chat/completions'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
    }
    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
        'max_tokens': 4096
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            # Remove markdown code block if present
            if content.startswith('```'):
                content = re.sub(r'^```[a-zA-Z]*\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
            # Extract JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        else:
            print(f"    [ERR] DeepSeek API status {response.status_code}")
    except Exception as e:
        print(f"    [ERR] DeepSeek API call failed: {e}")

    return {}


def save_league_translations(translations, mapping_data):
    """
    Save AI-translated league names to manual_mapping.json.
    Format: "Canonical English Name": ["original_alias1", ...]
    """
    if not translations:
        return 0

    league_names = mapping_data.get('league_names', {})
    added = 0

    for alias, canonical in translations.items():
        if not canonical or canonical == 'SKIP' or canonical == alias:
            continue

        # Check if alias is already mapped
        already = False
        for can, als in league_names.items():
            if isinstance(als, list) and alias in als:
                already = True
                break
            if isinstance(als, str) and als == alias:
                already = True
                break
        if normalize_text(alias) == normalize_text(canonical):
            already = True
        if already:
            continue

        # Add to existing canonical or create new
        if canonical in league_names:
            existing = league_names[canonical]
            if isinstance(existing, list):
                if alias not in existing:
                    existing.append(alias)
                    added += 1
            else:
                league_names[canonical] = [existing, alias]
                added += 1
        else:
            league_names[canonical] = [alias]
            added += 1

    if added > 0:
        # Sort alphabetically
        mapping_data['league_names'] = dict(sorted(league_names.items(), key=lambda x: x[0].lower()))
        with open(MANUAL_MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print(f"  💾 Saved {added} new league translations to {MANUAL_MAPPING_FILE}")

    return added


def translate_leagues_with_ai(matches):
    """
    Detect untranslated (non-English) league names in scraped matches,
    call DeepSeek AI to translate them, save to manual_mapping.json,
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
        print(f"  Found {len(untranslated)} untranslated league names → calling DeepSeek AI...")

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
# SELENIUM SCRAPING
# ============================================

def scrape_with_selenium():
    """Scrape all matches using Selenium"""
    
    base_url = "https://socolive25.cv/"
    driver = None
    
    try:
        print("Starting Chrome driver...")
        driver = setup_driver()
        
        print(f"Navigating to {base_url}...")
        driver.get(base_url)
        
        # Wait for page to load
        time.sleep(3)
        
        # Click on "Nay" (Today) tab if needed
        try:
            today_tab = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'li[data-value="tday"]'))
            )
            if not today_tab.get_attribute('class') or 'active' not in today_tab.get_attribute('class'):
                print("Clicking on 'Today' tab...")
                today_tab.click()
                time.sleep(2)
        except:
            print("Today tab already active or not found")
        
        # Wait for match items to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'match-item'))
        )
        
        # Find all match items
        match_elements = driver.find_elements(By.CLASS_NAME, 'match-item')
        
        print(f"\nFound {len(match_elements)} total matches")
        print("Processing matches...\n")
        
        matches = []
        
        for match_elem in match_elements:
            try:
                # Check league name
                league_elem = match_elem.find_element(By.CLASS_NAME, 'match-item__comp')
                league_name = league_elem.text.strip()
                
                print(f"Processing: {league_name}")
                
                # Extract time
                try:
                    time_elem = match_elem.find_element(By.CSS_SELECTOR, '.match-item__time span')
                    time_text = time_elem.text.strip()
                except:
                    time_text = ""
                
                # Extract teams
                try:
                    home_team_elem = match_elem.find_element(By.CSS_SELECTOR, '.name-home span')
                    home_team = home_team_elem.text.strip()
                except:
                    home_team = "Unknown"
                
                try:
                    away_team_elem = match_elem.find_element(By.CSS_SELECTOR, '.name-away span')
                    away_team = away_team_elem.text.strip()
                except:
                    away_team = "Unknown"

                # Extract team logos (fallback for when SofaScore doesn't have them)
                home_logo = ''
                away_logo = ''
                try:
                    logo_selectors_home = [
                        '.name-home img', '.home-logo img', '.team-home img',
                        '.logo-home img', '.img-home img'
                    ]
                    for sel in logo_selectors_home:
                        try:
                            img = match_elem.find_element(By.CSS_SELECTOR, sel)
                            src = img.get_attribute('src') or ''
                            if src and 'http' in src:
                                home_logo = src
                                break
                        except:
                            continue
                except:
                    pass

                try:
                    logo_selectors_away = [
                        '.name-away img', '.away-logo img', '.team-away img',
                        '.logo-away img', '.img-away img'
                    ]
                    for sel in logo_selectors_away:
                        try:
                            img = match_elem.find_element(By.CSS_SELECTOR, sel)
                            src = img.get_attribute('src') or ''
                            if src and 'http' in src:
                                away_logo = src
                                break
                        except:
                            continue
                except:
                    pass
                
                print(f"  Match: {home_team} vs {away_team}")
                print(f"  Time: {time_text}")
                
                # Extract match URL
                try:
                    link_elem = match_elem.find_element(By.CLASS_NAME, 'link-match')
                    match_url = link_elem.get_attribute('href')
                except:
                    match_url = ""
                
                # Extract BLV channels
                blv_elements = match_elem.find_elements(By.CLASS_NAME, 'blv-item-scl')
                
                if not blv_elements:
                    print(f"  No BLV channels found, skipping...")
                    continue
                
                servers = []
                
                for blv_elem in blv_elements:
                    try:
                        blv_link = blv_elem.find_element(By.CLASS_NAME, 'dropdown-item')
                        blv_url = blv_link.get_attribute('href')
                        blv_name_elem = blv_link.find_element(By.TAG_NAME, 'span')
                        blv_name = blv_name_elem.text.strip()
                        
                        # Extract blv parameter
                        parsed_url = urlparse(blv_url)
                        query_params = parse_qs(parsed_url.query)
                        
                        if 'blv' not in query_params:
                            continue
                        
                        blv_id = query_params['blv'][0]
                        
                        # Create stream URL
                        stream_url = f"https://live.inplyr.com/room/{blv_id}.m3u8"
                        encoded_url = encode_url_to_base64(stream_url)
                        player_url = f"https://multi.govoet.cc/?hls={encoded_url}"
                        
                        servers.append({
                            "url": player_url,
                            "label": f"CH-VN"
                        })
                        
                        print(f"  Channel: {blv_name} (BLV ID: {blv_id})")
                    except Exception as e:
                        continue
                
                if not servers:
                    print(f"  No valid servers found, skipping...")
                    continue
                
                # Parse time
                try:
                    time_parts = time_text.split()
                    if len(time_parts) >= 2:
                        time_str = time_parts[0]
                        date_str = time_parts[1]
                        current_year = datetime.now().year
                        date_obj = datetime.strptime(f"{date_str}/{current_year} {time_str}", "%d/%m/%Y %H:%M")
                        match_date = date_obj.strftime("%Y-%m-%d")
                        match_time = date_obj.strftime("%H:%M")
                    else:
                        match_date = datetime.now().strftime("%Y-%m-%d")
                        match_time = "00:00"
                except:
                    match_date = datetime.now().strftime("%Y-%m-%d")
                    match_time = "00:00"
                
                # Create match ID
                match_id = urlparse(match_url).path.split('/')[-2] if match_url else ""
                
                # Build team objects — include logo if found
                team1_obj = {"name": home_team}
                if home_logo:
                    team1_obj["logo"] = home_logo

                team2_obj = {"name": away_team}
                if away_logo:
                    team2_obj["logo"] = away_logo

                # Create match object
                match_data = {
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
                }
                
                matches.append(match_data)
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
    
    finally:
        if driver:
            driver.quit()
            print("Browser closed")

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
    print("SOCOLIVE MATCH SCRAPER (SELENIUM)")
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
