import json
import os
import re
import time
import sys
import urllib3
import unicodedata
from difflib import SequenceMatcher

# Suppress warnings globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================
# DATA SOURCES DOCUMENTATION
# ============================================
# Priority Order (Creation & Merging):
# 1. manual_sch.json    - Highest priority. Create new or merge servers.
# 2. flashscore.json    - Primary data source. Create new (no servers).
# 3. adstrim.json      - Create new or merge servers.
# 4. bolaloca.json      - Create new or merge servers. No logos (needs enrichment).
# 5. streamcenter.json  - Create new or merge servers.
#
# Merge Only Sources:
# 6. sportsonline.json  - Only merge servers.
# 7. soco.json          - Only merge servers.
#
# Enrichment:
# Enrichment:
# - Sport/Status: SofaScore (sofascore.json) fills missing sport type, status, status_desc.
# - manual_mapping.json - Normalization for team & league names.

# ============================================
# NORMALIZATION FUNCTIONS
# ============================================

def normalize_text(text):
    """Remove special characters, spaces, accents, and lowercase"""
    if not text:
        return ""
    # Normalize unicode to NFD (decompose accents)
    text = unicodedata.normalize('NFD', text)
    # Remove accent marks (combining characters)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    # Lowercase
    text = text.lower()
    # Remove all non-alphanumeric characters
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def slugify(text):
    """Create a slug for GitHub URL (e.g., 'AC Milan' -> 'ac-milan')"""
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = text.lower()
    # Replace non-alphanumeric (except hyphens) with space first to handle separators
    text = re.sub(r'[^a-z0-9-]', ' ', text)
    # Replace spaces with hyphens
    text = re.sub(r'\s+', '-', text)
    return text.strip('-')

# ============================================
# MANUAL MAPPING DICTIONARIES
# ============================================

def load_manual_mapping():
    """
    Load manual mapping from external JSON file.
    Falls back to empty dictionaries if file not found.
    """
    try:
        with open('manual_mapping.json', 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
            
            raw_teams = mapping_data.get('team_names', {})
            raw_leagues = mapping_data.get('league_names', {})
            
            # Normalize keys
            norm_teams = {normalize_text(k): v for k, v in raw_teams.items() if k}
            norm_leagues = {normalize_text(k): v for k, v in raw_leagues.items() if k}
            
            return norm_teams, norm_leagues
            
    except FileNotFoundError:
        print("⚠️  Warning: manual_mapping.json not found. Using empty aliases.")
        return {}, {}
    except json.JSONDecodeError as e:
        print(f"⚠️  Warning: Error parsing manual_mapping.json: {e}")
        return {}, {}

# Load mapping at module level
TEAM_NAMES, LEAGUE_NAMES = load_manual_mapping()

def normalize_team_name(name):
    """
    Normalize team name for matching purposes.
    First tries to get display name from mapping, then normalizes it.
    """
    normalized = normalize_text(name)
    # If there's a mapping, use the display name for normalization
    display_name = TEAM_NAMES.get(normalized, name)
    # Normalize the result for matching
    return normalize_text(display_name)

def normalize_league_name(name):
    """
    Normalize league name for matching purposes.
    """
    normalized = normalize_text(name)
    display_name = LEAGUE_NAMES.get(normalized, name)
    return normalize_text(display_name)

def get_display_team_name(name):
    """Get display name for team."""
    normalized = normalize_text(name)
    return TEAM_NAMES.get(normalized, name)

def get_display_league_name(name):
    """Get display name for league."""
    normalized = normalize_text(name)
    if normalized in LEAGUE_NAMES:
        return LEAGUE_NAMES[normalized]
    elif name:
        return name.title()
    return ""

# ============================================
# FUZZY MATCHING FUNCTIONS
# ============================================

def calculate_similarity(str1, str2):
    """Calculate similarity ratio between two strings (0-100)"""
    return SequenceMatcher(None, str1, str2).ratio() * 100

def fuzzy_match_teams(team1_a, team2_a, team1_b, team2_b, threshold=85):
    """
    Check if two team pairs match using fuzzy matching.
    Also handles reversed team order (common in streamcenter.json).
    """
    t1a = normalize_team_name(team1_a)
    t2a = normalize_team_name(team2_a)
    t1b = normalize_team_name(team1_b)
    t2b = normalize_team_name(team2_b)
    
    # Direct match
    sim1 = calculate_similarity(t1a, t1b)
    sim2 = calculate_similarity(t2a, t2b)
    
    if sim1 >= threshold and sim2 >= threshold:
        return True
    
    # Reversed match (handles streamcenter.json where teams are often swapped)
    sim1_rev = calculate_similarity(t1a, t2b)
    sim2_rev = calculate_similarity(t2a, t1b)
    
    if sim1_rev >= threshold and sim2_rev >= threshold:
        return True
    
    return False

# ============================================
# KEY GENERATION FUNCTIONS
# ============================================

def create_composite_key(match):
    """Create a composite key using multiple fields"""
    date = match.get('kickoff_date', '')
    time = match.get('kickoff_time', '')
    league = normalize_league_name(match.get('league', ''))
    
    team1 = normalize_team_name(match['team1']['name'])
    team2 = normalize_team_name(match['team2']['name'])
    
    teams = sorted([team1, team2])
    teams_key = '-'.join(teams)
    
    key_parts = []
    if date: key_parts.append(date)
    if time: key_parts.append(time)
    if league: key_parts.append(league)
    key_parts.append(teams_key)
    
    return '|'.join(key_parts)

# ============================================
# DATA ENRICHMENT FUNCTION
# ============================================

def enrich_from_sofascore(matches, sofascore_data):
    """
    Enrich matches using SofaScore data:
    1. Fill missing 'sport' field.
    2. Add 'status' and 'status_desc' if available.
    """
    if not sofascore_data:
        return matches
        
    print("\nEnriching from SofaScore...")
    
    # Pre-process sofascore data for faster lookup
    ss_lookup = {}
    ss_by_date = {} # date -> list of items
    
    for item in sofascore_data:
        t1 = normalize_team_name(item['team1']['name'])
        t2 = normalize_team_name(item['team2']['name'])
        if t1 and t2:
            teams_key = '-'.join(sorted([t1, t2]))
            ss_lookup[teams_key] = item
            
        date = item.get('kickoff_date')
        if date:
            if date not in ss_by_date:
                ss_by_date[date] = []
            ss_by_date[date].append(item)
    
    sport_count = 0
    status_count = 0
    
    for match in matches:
        mt1 = normalize_team_name(match['team1']['name'])
        mt2 = normalize_team_name(match['team2']['name'])
        match_teams_key = '-'.join(sorted([mt1, mt2]))
        
        # Try direct lookup first
        source_item = ss_lookup.get(match_teams_key)
        
        # If not found, try fuzzy matching within the SAME DATE
        if not source_item:
            match_date = match.get('kickoff_date')
            candidate_list = ss_by_date.get(match_date, []) if match_date else []
            
            # If no date, maybe check all? (Too slow, skip for now unless crucial)
            # Or if candidate list is empty, skip.
            
            if candidate_list:
                for item in candidate_list:
                    if fuzzy_match_teams(
                        match['team1']['name'], match['team2']['name'],
                        item['team1']['name'], item['team2']['name'],
                        threshold=80
                    ):
                        source_item = item
                        break
        
        if source_item:
            # 1. Fill missing sport
            if not match.get('sport') and source_item.get('sport'):
                match['sport'] = source_item['sport']
                sport_count += 1
            
            # 2. Add status and status_desc
            if source_item.get('status'):
                match['status'] = source_item['status']
                match['status_desc'] = source_item.get('status_desc', '')
                status_count += 1
    
    print(f"  ✅ Enriched {sport_count} matches with sport type.")
    print(f"  ✅ Enriched {status_count} matches with status.")
    return matches

# ============================================
# MATCHING & MERGING LOGIC
# ============================================

def find_matching_entry(match, merged_dict, allow_time_only=False):
    """
    Find if a match already exists in merged dictionary.
    """
    composite_key = create_composite_key(match)
    if composite_key in merged_dict:
        return composite_key
    
    match_date = match.get('kickoff_date', '')
    match_time = match.get('kickoff_time', '')
    
    for existing_key, existing_match in merged_dict.items():
        existing_date = existing_match.get('kickoff_date', '')
        existing_time = existing_match.get('kickoff_time', '')
        
        # Strict Date/Time match -> Fuzzy Team match
        if match_date and existing_date and match_date == existing_date and match_time == existing_time:
            if fuzzy_match_teams(
                match['team1']['name'], match['team2']['name'],
                existing_match['team1']['name'], existing_match['team2']['name'],
                threshold=50
            ):
                return existing_key
        
        # Fuzzy Time match (±15 mins)
        if match_date and existing_date and match_date == existing_date:
            if match_time and existing_time:
                try:
                    from datetime import datetime
                    t1 = datetime.strptime(match_time, "%H:%M")
                    t2 = datetime.strptime(existing_time, "%H:%M")
                    diff_minutes = abs((t1 - t2).total_seconds() / 60)
                    
                    if diff_minutes <= 15:
                        if fuzzy_match_teams(
                            match['team1']['name'], match['team2']['name'],
                            existing_match['team1']['name'], existing_match['team2']['name'],
                            threshold=80
                        ):
                            return existing_key
                except:
                    pass
        
        # Match by Time + Teams only (for sportsonline.json)
        if allow_time_only and (not match_date or not existing_date) and match_time and existing_time:
            try:
                from datetime import datetime
                t1 = datetime.strptime(match_time, "%H:%M")
                t2 = datetime.strptime(existing_time, "%H:%M")
                diff_minutes = abs((t1 - t2).total_seconds() / 60)
                
                if diff_minutes <= 5:
                    if fuzzy_match_teams(
                        match['team1']['name'], match['team2']['name'],
                        existing_match['team1']['name'], existing_match['team2']['name'],
                        threshold=85
                    ):
                        return existing_key
            except:
                pass

        # Match by Date + Strong Team Match (Relaxed Time)
        if match_date and existing_date and match_date == existing_date:
             if match_time and existing_time:
                try:
                    from datetime import datetime
                    t1 = datetime.strptime(match_time, "%H:%M")
                    t2 = datetime.strptime(existing_time, "%H:%M")
                    diff_minutes = abs((t1 - t2).total_seconds() / 60)
                    
                    if diff_minutes <= 180:
                        if fuzzy_match_teams(
                            match['team1']['name'], match['team2']['name'],
                            existing_match['team1']['name'], existing_match['team2']['name'],
                            threshold=85
                        ):
                            return existing_key
                except:
                    pass
    
    return None

def load_json_safe(filename):
    """Safely load JSON file"""
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return []

def merge_servers(existing_match, new_servers, existing_urls, prepend=False):
    """
    Merge servers into existing match.
    """
    if prepend:
        unique_new = [s for s in new_servers if s['url'] not in existing_urls]
        existing_match['servers'] = unique_new + existing_match.get('servers', [])
        for s in unique_new:
            existing_urls.add(s['url'])
    else:
        for server in new_servers:
            if server['url'] not in existing_urls:
                existing_match.setdefault('servers', []).append(server)
                existing_urls.add(server['url'])

def main():
    print("Starting schedule merge...")
    print("=" * 50)
    
    # Load Data
    manual_sch = load_json_safe('manual_sch.json')
    flashscore = load_json_safe('flashscore.json')
    adstrim = load_json_safe('adstrim.json')
    bolaloca = load_json_safe('bolaloca.json')
    streamcenter = load_json_safe('streamcenter.json')
    ikotv = load_json_safe('ikotv.json')
    sofascore = load_json_safe('sofascore.json')
    
    # ============================================
    # PHASE 1: Primary Sources (Create & Merge)
    # ============================================
    # Priority: manual_sch -> flashscore -> bolaloca -> streamcenter
    primary_sources = [
        ('manual_sch.json', manual_sch, True),  # prepend servers
        ('flashscore.json', flashscore, False),
        ('adstrim.json', adstrim, False),
        ('bolaloca.json', bolaloca, False),
        ('streamcenter.json', streamcenter, False),
    ]
    
    merged_data = {}
    
    for source_name, matches, prepend_servers in primary_sources:
        print(f"Processing {source_name} ({len(matches)} matches)...")
        if not isinstance(matches, list):
            print(f"⚠️  Warning: {source_name} content is not a list. Skipping.")
            continue
            
        for match in matches:
            # Find existing match
            existing_key = find_matching_entry(match, merged_data, allow_time_only=False)
            
            if existing_key:
                # Merge servers
                existing_match = merged_data[existing_key]
                existing_urls = {s['url'] for s in existing_match.get('servers', [])}
                new_servers = match.get('servers', [])
                
                merge_servers(existing_match, new_servers, existing_urls, prepend=prepend_servers)
                            
                # Update metadata if missing (e.g. time/date)
                if not existing_match.get('kickoff_time') and match.get('kickoff_time'):
                    existing_match['kickoff_time'] = match['kickoff_time']
                if not existing_match.get('kickoff_date') and match.get('kickoff_date'):
                    existing_match['kickoff_date'] = match['kickoff_date']
                    
            else:
                # Add new match
                key = create_composite_key(match)
                if 'servers' not in match:
                    match['servers'] = []
                merged_data[key] = match

    # ============================================
    # PHASE 2: Merge Only Sources
    # ============================================
    
    # sportsonline.json (no date)
    sportsonline_data = load_json_safe('sportsonline.json')
    print(f"Processing sportsonline.json ({len(sportsonline_data)} matches) - Server merge only...")
    sportsonline_merged = 0
    if isinstance(sportsonline_data, list):
        for match in sportsonline_data:
            existing_key = find_matching_entry(match, merged_data, allow_time_only=True)
            if existing_key:
                existing_match = merged_data[existing_key]
                existing_urls = {s['url'] for s in existing_match.get('servers', [])}
                new_servers = match.get('servers', [])
                merge_servers(existing_match, new_servers, existing_urls)
                sportsonline_merged += 1
    print(f"  ✅ Merged {sportsonline_merged} servers from sportsonline.json")

    # soco.json
    soco_data = load_json_safe('soco.json')
    print(f"Processing soco.json ({len(soco_data)} matches) - Server merge only...")
    soco_merged = 0
    if isinstance(soco_data, list):
        for match in soco_data:
            existing_key = find_matching_entry(match, merged_data, allow_time_only=False)
            if existing_key:
                existing_match = merged_data[existing_key]
                existing_urls = {s['url'] for s in existing_match.get('servers', [])}
                new_servers = match.get('servers', [])
                merge_servers(existing_match, new_servers, existing_urls)
                soco_merged += 1
    print(f"  ✅ Merged {soco_merged} servers from soco.json")

    # ikotv.json
    print(f"Processing ikotv.json ({len(ikotv)} matches) - Server merge only...")
    ikotv_merged = 0
    if isinstance(ikotv, list):
        for match in ikotv:
            # iKOTV has dates, so we don't strictly need allow_time_only=True, 
            # but it is safer to use standard matching first.
            existing_key = find_matching_entry(match, merged_data, allow_time_only=False)
            if existing_key:
                existing_match = merged_data[existing_key]
                existing_urls = {s['url'] for s in existing_match.get('servers', [])}
                new_servers = match.get('servers', [])
                merge_servers(existing_match, new_servers, existing_urls)
                ikotv_merged += 1
    print(f"  ✅ Merged {ikotv_merged} servers from ikotv.json")

    # Convert to list
    final_data = list(merged_data.values())
    
    # ============================================
    # PHASE 3: Enrich from SofaScore (sport, status)
    # ============================================
    final_data = enrich_from_sofascore(final_data, sofascore)
        
    # ============================================
    # PHASE 4: Apply Manual Mapping for Display
    # ============================================
    print("\nApplying manual mapping for display names...")
    for match in final_data:
        # Update League
        if match.get('league'):
            match['league'] = get_display_league_name(match['league'])
            
        # Update Team 1
        if match.get('team1') and match['team1'].get('name'):
            match['team1']['name'] = get_display_team_name(match['team1']['name'])
            
        # Update Team 2
        if match.get('team2') and match['team2'].get('name'):
            match['team2']['name'] = get_display_team_name(match['team2']['name'])

    # ============================================
    # PHASE 5: Filter matches with missing date/time
    # ============================================
    print("\nFiltering matches with missing date or time...")
    original_count = len(final_data)
    final_data = [
        m for m in final_data 
        if m.get('kickoff_date') and m.get('kickoff_time')
    ]
    filtered_count = original_count - len(final_data)
    if filtered_count > 0:
        print(f"⚠️  Filtered out {filtered_count} matches with missing date/time.")

    # ============================================
    # PHASE 6: Save output
    # ============================================
    with open('sch.json', 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)
        
    print(f"\n{'=' * 50}")
    print(f"✅ Successfully generated sch.json")
    print(f"  - Final match count: {len(final_data)} matches")

if __name__ == "__main__":
    main()
