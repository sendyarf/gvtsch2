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
# manual_mapping.json    - Normalization for team & league names
# manual_sch.json       - Can add servers to existing OR create new schedules
# flashscore.json       - Primary source (has logo, league, date)
# bolaloca.json         - Missing logos, has league & date
# streamcenter.json     - Different league names, teams often swapped, has logo & date
# sportsonline.json     - Missing logo, league, date (only has time & team names)
# soco.json             - Only merge servers to existing matches
# flashscore_home.json  - For enrichment (fill missing logos & league names)

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

def enrich_with_flashscore_home(matches, home_data):
    """
    Fill missing data (logos, league names) using Flashscore home data.
    - bolaloca.json needs logos
    - sportsonline.json needs logos (and league, but we don't overwrite existing)
    Matches primarily on Team Names with fuzzy matching.
    """
    print("\nEnriching data using Flashscore home data...")
    
    # Pre-process home_data into a dictionary for faster lookup
    # Key: sorted normalized team names
    home_lookup = {}
    for item in home_data:
        t1 = normalize_team_name(item['team1']['name'])
        t2 = normalize_team_name(item['team2']['name'])
        if t1 and t2:
            teams_key = '-'.join(sorted([t1, t2]))
            home_lookup[teams_key] = item

    enriched_count = 0
    
    for match in matches:
        # Create key for this match
        mt1 = normalize_team_name(match['team1']['name'])
        mt2 = normalize_team_name(match['team2']['name'])
        
        if not mt1 or not mt2:
            continue
            
        match_teams_key = '-'.join(sorted([mt1, mt2]))
        
        # Try direct lookup first
        home_item = home_lookup.get(match_teams_key)
        
        # If not found, try fuzzy matching
        if not home_item:
            for key, item in home_lookup.items():
                if fuzzy_match_teams(
                    match['team1']['name'], match['team2']['name'],
                    item['team1']['name'], item['team2']['name'],
                    threshold=80
                ):
                    home_item = item
                    break
        
        if home_item:
            enriched = False
            
            # Determine team alignment (direct or reversed)
            ht1 = normalize_team_name(home_item['team1']['name'])
            ht2 = normalize_team_name(home_item['team2']['name'])
            
            # Check if teams are aligned (direct) or reversed
            sim_direct_t1 = calculate_similarity(mt1, ht1)
            sim_direct_t2 = calculate_similarity(mt2, ht2)
            sim_rev_t1 = calculate_similarity(mt1, ht2)
            sim_rev_t2 = calculate_similarity(mt2, ht1)
            
            if (sim_direct_t1 + sim_direct_t2) >= (sim_rev_t1 + sim_rev_t2):
                # Direct alignment: match.team1 = home.team1, match.team2 = home.team2
                source_t1, source_t2 = home_item['team1'], home_item['team2']
            else:
                # Reversed alignment: match.team1 = home.team2, match.team2 = home.team1
                source_t1, source_t2 = home_item['team2'], home_item['team1']
            
            # Fill missing logos for team1 (needed for bolaloca.json & sportsonline.json)
            if not match['team1'].get('logo') and source_t1.get('logo'):
                match['team1']['logo'] = source_t1['logo']
                enriched = True
                
            # Fill missing logos for team2
            if not match['team2'].get('logo') and source_t2.get('logo'):
                match['team2']['logo'] = source_t2['logo']
                enriched = True
            
            # Enrich league name if flashscore_home has more complete info
            match_league = match.get('league', '')
            home_league = home_item.get('league', '')
            
            if home_league and match_league:
                # Normalize for comparison
                norm_match_league = normalize_text(match_league)
                norm_home_league = normalize_text(home_league)
                
                # If home league is more specific (contains match league)
                # e.g., "Euroleague" vs "EUROPE - Euroleague"
                if (norm_match_league in norm_home_league and 
                    len(home_league) > len(match_league)):
                    # Format the league nicely
                    formatted_league = ' - '.join(part.strip().title() for part in home_league.split(' - '))
                    match['league'] = formatted_league
                    enriched = True
            elif home_league and not match_league:
                # If match has no league (sportsonline.json), use home league
                formatted_league = ' - '.join(part.strip().title() for part in home_league.split(' - '))
                match['league'] = formatted_league
                enriched = True
            
            if enriched:
                enriched_count += 1

    print(f"✅ Enriched {enriched_count} matches with additional metadata.")
    return matches

# ============================================
# MATCHING & MERGING LOGIC
# ============================================

def find_matching_entry(match, merged_dict, allow_time_only=False):
    """
    Find if a match already exists in merged dictionary.
    
    Args:
        match: The match to find
        merged_dict: Dictionary of existing matches
        allow_time_only: If True, allow matching by time + teams only 
                        (for sportsonline.json which has no date)
    """
    composite_key = create_composite_key(match)
    if composite_key in merged_dict:
        return composite_key
    
    match_date = match.get('kickoff_date', '')
    match_time = match.get('kickoff_time', '')
    
    for existing_key, existing_match in merged_dict.items():
        existing_date = existing_match.get('kickoff_date', '')
        existing_time = existing_match.get('kickoff_time', '')
        
        # Strict Date/Time match -> Fuzzy Team match (when both have dates)
        if match_date and existing_date and match_date == existing_date and match_time == existing_time:
            if fuzzy_match_teams(
                match['team1']['name'], match['team2']['name'],
                existing_match['team1']['name'], existing_match['team2']['name'],
                threshold=50  # Lower threshold for exact date/time match
            ):
                return existing_key
        
        # Fuzzy Time match (±15 mins) -> Fuzzy Team match (when both have dates)
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
        
        # Match by Time + Teams only (for sportsonline.json which has no date)
        if allow_time_only and (not match_date or not existing_date) and match_time and existing_time:
            try:
                from datetime import datetime
                t1 = datetime.strptime(match_time, "%H:%M")
                t2 = datetime.strptime(existing_time, "%H:%M")
                diff_minutes = abs((t1 - t2).total_seconds() / 60)
                
                # Same time or very close (±5 mins for higher confidence)
                if diff_minutes <= 5:
                    if fuzzy_match_teams(
                        match['team1']['name'], match['team2']['name'],
                        existing_match['team1']['name'], existing_match['team2']['name'],
                        threshold=85  # Higher threshold since no date verification
                    ):
                        return existing_key
            except:
                pass

        # Match by Date + Strong Team Match (Relaxed Time)
        # Handles timezone differences or slightly different times
        if match_date and existing_date and match_date == existing_date:
             if match_time and existing_time:
                try:
                    from datetime import datetime
                    t1 = datetime.strptime(match_time, "%H:%M")
                    t2 = datetime.strptime(existing_time, "%H:%M")
                    diff_minutes = abs((t1 - t2).total_seconds() / 60)
                    
                    # Allow up to 3 hours difference if teams match strongly
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
    
    Args:
        existing_match: The match to merge servers into
        new_servers: List of new servers to add
        existing_urls: Set of existing server URLs (for dedup)
        prepend: If True, add servers at start (for manual_sch.json priority)
    """
    if prepend:
        unique_new = [s for s in new_servers if s['url'] not in existing_urls]
        existing_match['servers'] = unique_new + existing_match.get('servers', [])
    else:
        for server in new_servers:
            if server['url'] not in existing_urls:
                existing_match.setdefault('servers', []).append(server)
                existing_urls.add(server['url'])

def main():
    print("Starting schedule merge...")
    print("=" * 50)
    
    # Load Flashscore Data
    flashscore_detailed = load_json_safe('flashscore.json')
    flashscore_home = load_json_safe('flashscore_home.json')

    # Clean Flashscore Home Data (remove "Preview" from time)
    if isinstance(flashscore_home, list):
        for item in flashscore_home:
            if item.get('kickoff_time'):
                item['kickoff_time'] = item['kickoff_time'].replace('Preview', '').strip()

    # ============================================
    # PHASE 1: Primary Sources (can create new schedules)
    # ============================================
    # Priority order: manual_sch -> flashscore -> bolaloca -> streamcenter
    primary_sources = [
        ('manual_sch.json', load_json_safe('manual_sch.json'), True),  # prepend servers
        ('flashscore.json', flashscore_detailed, False),
        ('bolaloca.json', load_json_safe('bolaloca.json'), False),
        ('streamcenter.json', load_json_safe('streamcenter.json'), False),
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
                            
                # Update metadata if missing
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
    # PHASE 2: sportsonline.json (merge servers only, no date available)
    # ============================================
    sportsonline_data = load_json_safe('sportsonline.json')
    print(f"Processing sportsonline.json ({len(sportsonline_data)} matches) - Server merge only (no date)...")
    sportsonline_merged = 0
    if isinstance(sportsonline_data, list):
        for match in sportsonline_data:
            # Use time-only matching since sportsonline has no date
            existing_key = find_matching_entry(match, merged_data, allow_time_only=True)
            if existing_key:
                existing_match = merged_data[existing_key]
                existing_urls = {s['url'] for s in existing_match.get('servers', [])}
                new_servers = match.get('servers', [])
                
                for server in new_servers:
                    if server['url'] not in existing_urls:
                        existing_match.setdefault('servers', []).append(server)
                        existing_urls.add(server['url'])
                        sportsonline_merged += 1
    print(f"  ✅ Merged {sportsonline_merged} servers from sportsonline.json")

    # ============================================
    # PHASE 3: soco.json (server-only source)
    # ============================================
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
                
                for server in new_servers:
                    if server['url'] not in existing_urls:
                        existing_match.setdefault('servers', []).append(server)
                        existing_urls.add(server['url'])
                        soco_merged += 1
    print(f"  ✅ Merged {soco_merged} servers from soco.json")

    # Convert to list
    final_data = list(merged_data.values())
    
    # ============================================
    # PHASE 4: Enrich with Flashscore Home (logos & leagues)
    # ============================================
    # This fills missing logos (bolaloca, sportsonline) and enriches league names
    if isinstance(flashscore_home, list) and flashscore_home:
        final_data = enrich_with_flashscore_home(final_data, flashscore_home)
        
    # ============================================
    # PHASE 5: Apply Manual Mapping for Display
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
    # PHASE 6: Filter matches with missing date/time
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
    # PHASE 7: Save output
    # ============================================
    with open('sch.json', 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)
        
    print(f"\n{'=' * 50}")
    print(f"✅ Successfully generated sch.json")
    print(f"  - Final match count: {len(final_data)} matches")

if __name__ == "__main__":
    main()