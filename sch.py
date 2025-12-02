import json
import os
import re
import time
import sys
import urllib3
import unicodedata
import bolaloca
import sportsonline
import streamcenter
import flashscore
from difflib import SequenceMatcher

# Suppress warnings globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
            return (
                mapping_data.get('team_names', {}),
                mapping_data.get('league_names', {})
            )
    except FileNotFoundError:
        print("⚠️  Warning: manual_mapping.json not found. Using empty aliases.")
        return {}, {}
    except json.JSONDecodeError as e:
        print(f"⚠️  Warning: Error parsing manual_mapping.json: {e}")
        return {}, {}

# Load mapping at module level
TEAM_NAMES, LEAGUE_NAMES = load_manual_mapping()

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

def normalize_team_name(name):
    """
    Normalize team name for matching purposes.
    First tries to get display name from mapping, then normalizes it.
    This ensures variants map to the same normalized value.
    """
    normalized = normalize_text(name)
    # If there's a mapping, use the display name for normalization
    display_name = TEAM_NAMES.get(normalized, name)
    # Normalize the result for matching
    return normalize_text(display_name)

def normalize_league_name(name):
    """
    Normalize league name for matching purposes.
    First tries to get display name from mapping, then normalizes it.
    """
    normalized = normalize_text(name)
    # If there's a mapping, use the display name for normalization
    display_name = LEAGUE_NAMES.get(normalized, name)
    # Normalize the result for matching
    return normalize_text(display_name)

def get_display_team_name(name):
    """
    Get display name for team. Returns mapped name if found, original if not.
    """
    normalized = normalize_text(name)
    return TEAM_NAMES.get(normalized, name)

def get_display_league_name(name):
    """
    Get display name for league. Returns mapped name if found, title case original if not.
    """
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
    Check if two team pairs match using fuzzy matching
    Handles both normal and reversed team order
    Returns True if teams are similar enough
    """
    # Normalize teams
    t1a = normalize_team_name(team1_a)
    t2a = normalize_team_name(team2_a)
    t1b = normalize_team_name(team1_b)
    t2b = normalize_team_name(team2_b)
    
    # Check direct match (Team1A vs Team1B AND Team2A vs Team2B)
    sim1 = calculate_similarity(t1a, t1b)
    sim2 = calculate_similarity(t2a, t2b)
    
    if sim1 >= threshold and sim2 >= threshold:
        return True
    
    # Check reversed match (Team1A vs Team2B AND Team2A vs Team1B)
    # This handles cases like "Miami vs LA Clippers" matching "LA Clippers vs Miami"
    sim1_rev = calculate_similarity(t1a, t2b)
    sim2_rev = calculate_similarity(t2a, t1b)
    
    if sim1_rev >= threshold and sim2_rev >= threshold:
        return True
    
    return False

# ============================================
# KEY GENERATION FUNCTIONS
# ============================================

def create_composite_key(match):
    """
    Create a composite key using multiple fields
    Priority: date + time + league + sorted teams
    """
    date = match.get('kickoff_date', '')
    time = match.get('kickoff_time', '')
    league = normalize_league_name(match.get('league', ''))
    
    team1 = normalize_team_name(match['team1']['name'])
    team2 = normalize_team_name(match['team2']['name'])
    
    # Sort teams to handle reversed matches
    teams = sorted([team1, team2])
    teams_key = '-'.join(teams)
    
    # Combine all available fields
    key_parts = []
    if date:
        key_parts.append(date)
    if time:
        key_parts.append(time)
    if league:
        key_parts.append(league)
    key_parts.append(teams_key)
    
    return '|'.join(key_parts)

def create_fallback_key(match):
    """
    Create a fallback key using only teams
    Used when date/time/league might be missing
    """
    team1 = normalize_team_name(match['team1']['name'])
    team2 = normalize_team_name(match['team2']['name'])
    teams = sorted([team1, team2])
    return '-'.join(teams)

# ============================================
# ADVANCED MATCHING FUNCTION
# ============================================

def find_matching_entry(match, merged_dict):
    """
    Find if a match already exists in merged dictionary
    Returns the key if found, None otherwise
    
    Matching Strategy:
    1. Exact composite key match (date+time+league+teams)
    2. Fuzzy matching on teams with same date/time
    3. Fuzzy matching on teams only (if date/time vary slightly)
    """
    # Level 1: Try composite key (most accurate)
    composite_key = create_composite_key(match)
    if composite_key in merged_dict:
        return composite_key
    
    # Level 2: Try fuzzy matching with date/time constraint
    match_date = match.get('kickoff_date', '')
    match_time = match.get('kickoff_time', '')
    
    for existing_key, existing_match in merged_dict.items():
        existing_date = existing_match.get('kickoff_date', '')
        existing_time = existing_match.get('kickoff_time', '')
        
        # If date and time match, use fuzzy matching on teams
        if match_date == existing_date and match_time == existing_time:
            if fuzzy_match_teams(
                match['team1']['name'], match['team2']['name'],
                existing_match['team1']['name'], existing_match['team2']['name'],
                threshold=50  # Lowered threshold for more flexible matching
            ):
                return existing_key
        
        # Level 3: Fuzzy match on teams only (if time differs by max 15 min)
        if match_date == existing_date:
            # Check if time is within 15 minutes
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
                            threshold=80  # Threshold for time-fuzzy matching (±15 min)
                        ):
                            return existing_key
                except:
                    pass
    
    return None

# ============================================
# SCRAPER & MERGE FUNCTIONS
# ============================================

def get_cached_data(filename, max_age_minutes=60):
    """Try to load data from local JSON if it's recent enough"""
    if os.path.exists(filename):
        try:
            file_age = (time.time() - os.path.getmtime(filename)) / 60
            if file_age < max_age_minutes:
                print(f"Loading cached data from {filename} ({file_age:.1f} min old)...")
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error reading cache {filename}: {e}")
    return None

def run_scrapers():
    force_update = "--force" in sys.argv
    if force_update:
        print("Force update detected. Ignoring cache.")

    # Bolaloca
    data_bolaloca = None
    if not force_update:
        data_bolaloca = get_cached_data('bolaloca.json')
    
    if data_bolaloca is None:
        print("Running Bolaloca scraper...")
        try:
            data_bolaloca = bolaloca.parse_bolaloca()
        except Exception as e:
            print(f"Bolaloca failed: {e}")
            data_bolaloca = []
    
    # Sportsonline
    data_sportsonline = None
    if not force_update:
        data_sportsonline = get_cached_data('sportsonline.json')

    if data_sportsonline is None:
        print("Running Sportsonline scraper...")
        try:
            data_sportsonline = sportsonline.parse_sportsonline()
        except Exception as e:
            print(f"Sportsonline failed: {e}")
            data_sportsonline = []
    
    # Streamcenter
    data_streamcenter = None
    if not force_update:
        data_streamcenter = get_cached_data('streamcenter.json')

    if data_streamcenter is None:
        print("Running Streamcenter scraper...")
        try:
            data_streamcenter = streamcenter.parse_streamcenter()
        except Exception as e:
            print(f"Streamcenter failed: {e}")
            data_streamcenter = []
    
    # Flashscore
    data_flashscore = None
    if not force_update:
        data_flashscore = get_cached_data('flashscore.json')

    if data_flashscore is None:
        print("Running Flashscore scraper...")
        try:
            data_flashscore = flashscore.scrape_flashscore()
        except Exception as e:
            print(f"Flashscore failed: {e}")
            data_flashscore = []
    
    return data_bolaloca, data_sportsonline, data_streamcenter, data_flashscore

def merge_data(d1, d2, d3, d4):
    """
    Advanced merge using composite keys and fuzzy matching
    Priority: Flashscore first (d4), then others
    """
    merged = {}
    
    def merge_match(match):
        # Try to find existing match
        existing_key = find_matching_entry(match, merged)
        
        if existing_key:
            # Match found - merge servers
            existing_urls = set(s['url'] for s in merged[existing_key]['servers'])
            for srv in match['servers']:
                if srv['url'] not in existing_urls:
                    merged[existing_key]['servers'].append(srv)
                    existing_urls.add(srv['url'])
            
            # Update missing metadata
            if not merged[existing_key]['league'] and match['league']:
                merged[existing_key]['league'] = match['league']
            
            if not merged[existing_key]['team1'].get('logo') and match['team1'].get('logo'):
                merged[existing_key]['team1']['logo'] = match['team1']['logo']
            if not merged[existing_key]['team2'].get('logo') and match['team2'].get('logo'):
                merged[existing_key]['team2']['logo'] = match['team2']['logo']
        else:
            # New match - create new entry
            new_key = create_composite_key(match)
            merged[new_key] = match
    
    # Process Flashscore FIRST as priority source
    print(f"Merging {len(d4)} matches from Flashscore (PRIORITY)...")
    for match in d4:
        merge_match(match)
    
    # Then process other sources
    print(f"Merging {len(d1)} matches from Bolaloca...")
    for match in d1:
        merge_match(match)
    
    print(f"Merging {len(d2)} matches from Sportsonline...")
    for match in d2:
        merge_match(match)
    
    print(f"Merging {len(d3)} matches from Streamcenter...")
    for match in d3:
        merge_match(match)
    
    return list(merged.values())

def normalize_output_data(matches):
    """
    Normalize team and league names in output data to Flashscore format
    """
    print("\nNormalizing output to Flashscore format...")
    
    for match in matches:
        # Apply Flashscore display formatting
        match['team1']['name'] = get_display_team_name(match['team1']['name'])
        
        if match['team2']['name']:
            match['team2']['name'] = get_display_team_name(match['team2']['name'])
        
        # Apply league formatting
        if match.get('league'):
            match['league'] = get_display_league_name(match.get('league', ''))
    
    print(f"✅ Applied Flashscore formatting to {len(matches)} matches")
    return matches

# ============================================
# MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    d1, d2, d3, d4 = run_scrapers()
    
    # Save individual files
    print("\nSaving individual source files...")
    with open('bolaloca.json', 'w', encoding='utf-8') as f:
        json.dump(d1, f, indent=2, ensure_ascii=False)
    with open('sportsonline.json', 'w', encoding='utf-8') as f:
        json.dump(d2, f, indent=2, ensure_ascii=False)
    with open('streamcenter.json', 'w', encoding='utf-8') as f:
        json.dump(d3, f, indent=2, ensure_ascii=False)
    with open('flashscore.json', 'w', encoding='utf-8') as f:
        json.dump(d4, f, indent=2, ensure_ascii=False)
    
    
    print(f"\nMerging data from all sources...")
    print(f"  - Bolaloca: {len(d1)} matches")
    print(f"  - Sportsonline: {len(d2)} matches")
    print(f"  - Streamcenter: {len(d3)} matches")
    print(f"  - Flashscore: {len(d4)} matches")
    print(f"  - Total before merge: {len(d1) + len(d2) + len(d3) + len(d4)} matches")
    
    final_data = merge_data(d1, d2, d3, d4)
    
    # Apply Flashscore formatting to output
    final_data = normalize_output_data(final_data)
    
    with open('sch.json', 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Successfully generated sch.json")
    print(f"  - Final match count: {len(final_data)} matches")
    print(f"  - Duplicates removed: {len(d1) + len(d2) + len(d3) + len(d4) - len(final_data)} matches")
