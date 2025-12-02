import json
import os
import sys
from fetch_teams import get_teams_by_league, slugify
from sort_mapping import sort_and_format_mapping

MAPPING_FILE = r"d:\Sendy\govoet\script\gvtsch\manual_mapping.json"

def update_mapping_with_teams(league_id, season):
    print(f"Fetching teams for League ID {league_id}, Season {season}...")
    data = get_teams_by_league(league_id, season)

    if not data.get('response'):
        print("No data found from API. Check League ID and Season.")
        if data.get('errors'):
            print("API Errors:", data['errors'])
        return

    # Load existing mapping
    if not os.path.exists(MAPPING_FILE):
        print(f"Error: Mapping file not found at {MAPPING_FILE}")
        return

    try:
        with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
    except Exception as e:
        print(f"Error reading mapping file: {e}")
        return

    if "team_names" not in mapping_data:
        mapping_data["team_names"] = {}

    # Update mapping
    added_count = 0
    updated_count = 0
    
    print("Updating manual_mapping.json...")
    
    for item in data.get('response', []):
        team = item['team']
        name = team['name']
        slug = slugify(name)
        
        # Logic: 
        # Key = slug (e.g. "mancity")
        # Value = Display Name (e.g. "Man City")
        
        if slug not in mapping_data["team_names"]:
            mapping_data["team_names"][slug] = name
            added_count += 1
            # print(f"Added: {slug} -> {name}")
        else:
            if mapping_data["team_names"][slug] != name:
                # Optional: Update if the name is different? 
                # Usually we might want to keep existing manual overrides, 
                # but the user said "nama tim dari fetch_teams.py akan menjadi nama display"
                # implying the API is the source of truth for the display name.
                old_name = mapping_data["team_names"][slug]
                mapping_data["team_names"][slug] = name
                updated_count += 1
                # print(f"Updated: {slug} -> {name} (was {old_name})")

    # Save the updated JSON temporarily (raw dump)
    try:
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error writing to mapping file: {e}")
        return

    print(f"Done. Added {added_count} new teams, updated {updated_count} existing teams.")

    # Now apply the sorting and formatting
    print("Applying sorting and formatting...")
    sort_and_format_mapping(MAPPING_FILE)

def main():
    if len(sys.argv) < 2:
        print("Usage: python update_teams.py <league_id> [season]")
        print("Example: python update_teams.py 39 2023")
        return

    league_id = sys.argv[1]
    season = sys.argv[2] if len(sys.argv) > 2 else "2024"
    
    if not league_id.isdigit():
        print("Error: League ID must be a number.")
        return

    update_mapping_with_teams(int(league_id), season)

if __name__ == "__main__":
    main()
