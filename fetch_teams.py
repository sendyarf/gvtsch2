import requests
import json
import sys

API_KEY = "fb5807151d1e10914760bc733c5bca97"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}

def get_teams_by_league(league_id, season):
    url = f"{BASE_URL}/teams"
    querystring = {"league": league_id, "season": season}
    response = requests.get(url, headers=HEADERS, params=querystring)
    return response.json()

def slugify(text):
    """
    Create a slug from the text by keeping only alphanumeric characters and converting to lowercase.
    This matches the style in manual_mapping.json (e.g., 'Man City' -> 'mancity').
    """
    return "".join(e for e in text if e.isalnum()).lower()

def main():
    # Common Leagues Dictionary for reference
    leagues = {
        "Premier League": 39,
        "La Liga": 140,
        "Bundesliga": 78,
        "Serie A": 135,
        "Ligue 1": 61,
        "Eredivisie": 88,
        "Primeira Liga": 94,
        "Super Lig": 203,
        "Indonesia Liga 1": 279,
        "Champions League": 2,
        "Europa League": 3
    }

    # Check for command line arguments
    # Usage: 
    #   python fetch_teams.py [league_id] [season] 
    #   python fetch_teams.py search [team_name]
    #   python fetch_teams.py search-league [league_name]
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode.lower() == "search":
            if len(sys.argv) < 3:
                print("Usage: python fetch_teams.py search <team_name>")
                return
            query = " ".join(sys.argv[2:])
            search_teams(query)
            return

        elif mode.lower() == "search-league":
            if len(sys.argv) < 3:
                print("Usage: python fetch_teams.py search-league <league_name>")
                return
            query = " ".join(sys.argv[2:])
            search_leagues(query)
            return

        elif mode.isdigit():
            league_id = int(mode)
            season = sys.argv[2] if len(sys.argv) > 2 else "2024"
            fetch_teams_by_league(league_id, season)
            return

    print("--- API-Football Team Fetcher ---")
    print("Available Common League IDs:")
    for name, lid in leagues.items():
        print(f"  {lid}: {name}")
    print("---------------------------------")
    print("Modes:")
    print("1. Enter League ID (e.g., '39') to fetch teams")
    print("2. Type 'search <name>' to search for a TEAM")
    print("3. Type 'league <name>' to search for a LEAGUE ID")
    
    user_input = input("\nEnter command: ").strip()
    
    if not user_input:
        print("No input provided. Exiting.")
        return

    try:
        if user_input.lower().startswith("search "):
            query = user_input.split(" ", 1)[1]
            search_teams(query)
        elif user_input.lower().startswith("league "):
            query = user_input.split(" ", 1)[1]
            search_leagues(query)
        elif user_input.isdigit():
            league_id = int(user_input)
            season = input("Enter Season (e.g., 2024): ").strip() or "2024"
            fetch_teams_by_league(league_id, season)
        else:
            print("Invalid input.")

    except Exception as e:
        print(f"An error occurred: {e}")

def search_teams(query):
    if len(query) < 3:
        print("Search query must be at least 3 characters.")
        return
        
    url = f"{BASE_URL}/teams"
    querystring = {"search": query}
    print(f"Searching for team '{query}'...")
    response = requests.get(url, headers=HEADERS, params=querystring)
    data = response.json()
    
    if not data.get('response'):
        print("No teams found.")
    else:
        print("\n--- Search Results (JSON format) ---")
        for item in data.get('response', []):
            team = item['team']
            name = team['name']
            country = team['country']
            slug = slugify(name)
            print(f'"{slug}": "{name}", // {country}')

def search_leagues(query):
    if len(query) < 3:
        print("Search query must be at least 3 characters.")
        return
        
    url = f"{BASE_URL}/leagues"
    querystring = {"search": query}
    print(f"Searching for league '{query}'...")
    response = requests.get(url, headers=HEADERS, params=querystring)
    data = response.json()
    
    if not data.get('response'):
        print("No leagues found.")
    else:
        print(f"\n--- League Search Results for '{query}' ---")
        print(f"{'ID':<6} | {'Name':<30} | {'Country':<15}")
        print("-" * 60)
        for item in data.get('response', []):
            league = item['league']
            country = item['country']
            lid = league['id']
            lname = league['name']
            cname = country['name'] if country['name'] else "World"
            print(f"{lid:<6} | {lname:<30} | {cname:<15}")

def fetch_teams_by_league(league_id, season):
    print(f"Fetching teams for League ID {league_id}, Season {season}...")
    data = get_teams_by_league(league_id, season)
    
    if not data.get('response'):
        print("No data found. Check League ID and Season.")
        if data.get('errors'):
            print("API Errors:", data['errors'])
    else:
        print("\n--- Generated Mapping (Copy to manual_mapping.json) ---")
        for item in data.get('response', []):
            team = item['team']
            name = team['name']
            slug = slugify(name)
            print(f'"{slug}": "{name}",')

if __name__ == "__main__":
    main()
