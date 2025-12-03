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
    Check if two team pairs match using fuzzy matching
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
    
    # Reversed match
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
# DATA ENRICHMENT FUNCTION (NEW)
# ============================================

def enrich_with_flashscore_home(matches, home_data):
    """
    Fill missing data in matches using flashscore_home.json.
    Matches primarily on Team Names since dates/times might be missing in home_data.
    """
    print("\nEnriching data using flashscore_home.json...")
    
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
        # Create lookup key for current match
        t1 = normalize_team_name(match['team1']['name'])
        t2 = normalize_team_name(match['team2']['name'])
        teams_key = '-'.join(sorted([t1, t2]))

        # Check if we have reference data
        if teams_key in home_lookup:
            ref_data = home_lookup[teams_key]
            updated = False

            # 1. Fill League if missing or if ref has better data
            if not match.get('league') and ref_data.get('league'):
                match['league'] = ref_data['league']
                updated = True
            
            # 2. Fill Logos if missing
            if not match['team1'].get('logo') and ref_data['team1'].get('logo'):
                match['team1']['logo'] = ref_data['team1']['logo']
                updated = True
            
            if not match['team2'].get('logo') and ref_data['team2'].get('logo'):
                match['team2']['logo'] = ref_data['team2']['logo']
                updated = True
                
            # 3. Fill Kickoff Date and Time if missing
            if not match.get('kickoff_date') and ref_data.get('kickoff_date'):
                match['kickoff_date'] = ref_data['kickoff_date']
                updated = True
                
            if not match.get('kickoff_time') and ref_data.get('kickoff_time'):
                match['kickoff_time'] = ref_data['kickoff_time']
                updated = True

            if updated:
                enriched_count += 1
    
    print(f"✅ Enriched {enriched_count} matches with additional metadata.")
    return matches

# ============================================
# MATCHING & MERGING LOGIC
# ============================================

def find_matching_entry(match, merged_dict):
    """Find if a match already exists in merged dictionary"""
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
                threshold=50
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
        
        # NEW: Match by Time + Teams only (for data without dates like sportsonline)
        # This handles cases where one or both entries don't have dates
        if (not match_date or not existing_date) and match_time and existing_time:
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

def main():
    print("Starting schedule merge...")
    
    # Load all sources
    # Priority: Manual -> Bolaloca -> Sportsonline -> Streamcenter
    sources = [
        ('manual_sch.json', load_json_safe('manual_sch.json')),
        ('bolaloca.json', load_json_safe('bolaloca.json')),
        ('sportsonline.json', load_json_safe('sportsonline.json')),
        ('streamcenter.json', load_json_safe('streamcenter.json'))
    ]
    
    merged_data = {}
    
    for source_name, matches in sources:
        print(f"Processing {source_name} ({len(matches)} matches)...")
        if not isinstance(matches, list):
            print(f"⚠️  Warning: {source_name} content is not a list. Skipping.")
            continue
            
        for match in matches:
            # Find existing match
            existing_key = find_matching_entry(match, merged_data)
            
            if existing_key:
                # Merge servers
                existing_match = merged_data[existing_key]
                
                # Check for duplicate servers
                existing_urls = {s['url'] for s in existing_match.get('servers', [])}
                new_servers = match.get('servers', [])
                
                # If source is manual_sch.json, prepend servers (priority)
                if source_name == 'manual_sch.json':
                    # Filter out duplicates from new servers just in case
                    unique_new = [s for s in new_servers if s['url'] not in existing_urls]
                    # Prepend
                    existing_match['servers'] = unique_new + existing_match.get('servers', [])
                else:
                    # Append non-duplicates
                    for server in new_servers:
                        if server['url'] not in existing_urls:
                            existing_match.setdefault('servers', []).append(server)
                            existing_urls.add(server['url'])
                            
                # Update metadata if missing (optional, but good practice)
                if not existing_match.get('kickoff_time') and match.get('kickoff_time'):
                    existing_match['kickoff_time'] = match['kickoff_time']
                if not existing_match.get('kickoff_date') and match.get('kickoff_date'):
                    existing_match['kickoff_date'] = match['kickoff_date']
                    
            else:
                # Add new match
                # Generate key
                key = create_composite_key(match)
                # Ensure servers is a list
                if 'servers' not in match:
                    match['servers'] = []
                merged_data[key] = match

    # Convert to list
    final_data = list(merged_data.values())
    
    # Enrich with Flashscore Home data
    home_data = load_json_safe('flashscore_home.json')
    if home_data:
        final_data = enrich_with_flashscore_home(final_data, home_data)
        
    # APPLY MANUAL MAPPING FOR DISPLAY
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

    # FILTER: Remove matches with empty date or time
    print("\nFiltering matches with missing date or time...")
    original_count = len(final_data)
    final_data = [
        m for m in final_data 
        if m.get('kickoff_date') and m.get('kickoff_time')
    ]
    filtered_count = original_count - len(final_data)
    if filtered_count > 0:
        print(f"⚠️  Filtered out {filtered_count} matches with missing date/time.")

    # Save
    with open('sch.json', 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)
        
    print(f"\n✅ Successfully generated sch.json")
    print(f"  - Final match count: {len(final_data)} matches")

if __name__ == "__main__":
    main()