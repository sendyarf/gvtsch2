import requests
import json
import re
import argparse
from datetime import datetime, timedelta
import pytz

def clean_name(name):
    """Remove non-alphanumeric characters for ID generation."""
    return re.sub(r'[^a-zA-Z0-9]', '', name)

def fetch_sofascore(sport="football", date_str=None):
    """Fetch scheduled events from SofaScore API."""
    
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    
    # Default to today's date in GMT+7
    if not date_str:
        now = datetime.now(jakarta_tz)
        date_str = now.strftime("%Y-%m-%d")
    
    url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com",
    }
    
    print(f"Fetching {sport} events for {date_str}...")
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return []
    
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return []
    
    events = data.get("events", [])
    print(f"  -> Found {len(events)} events")
    
    matches = []
    
    for event in events:
        try:
            # Tournament / League info
            tournament = event.get("tournament", {})
            tournament_name = tournament.get("name", "")
            category = tournament.get("category", {})
            category_name = category.get("name", "")
            
            # Build league string: "Country - Tournament"
            if category_name and tournament_name:
                league = f"{category_name} - {tournament_name}"
            elif tournament_name:
                league = tournament_name
            else:
                league = ""
            
            # Season & Round
            season = event.get("season", {})
            season_name = season.get("name", "")
            round_info = event.get("roundInfo", {})
            round_num = round_info.get("round", "")
            
            # Status
            status_info = event.get("status", {})
            status_type = status_info.get("type", "")
            status_desc = status_info.get("description", "")
            
            # Teams
            home_team = event.get("homeTeam", {})
            away_team = event.get("awayTeam", {})
            
            home_name = home_team.get("shortName", "") or home_team.get("name", "")
            away_name = away_team.get("shortName", "") or away_team.get("name", "")
            home_full = home_team.get("name", home_name)
            away_full = away_team.get("name", away_name)
            
            # Team logos
            home_id = home_team.get("id", "")
            away_id = away_team.get("id", "")
            home_logo = f"https://img.sofascore.com/api/v1/team/{home_id}/image" if home_id else ""
            away_logo = f"https://img.sofascore.com/api/v1/team/{away_id}/image" if away_id else ""
            
            # Scores
            home_score = event.get("homeScore", {})
            away_score = event.get("awayScore", {})
            score = ""
            if status_type == "finished":
                h = home_score.get("current", "")
                a = away_score.get("current", "")
                if h != "" and a != "":
                    score = f"{h} - {a}"
            elif status_type == "inprogress":
                h = home_score.get("current", "")
                a = away_score.get("current", "")
                if h != "" and a != "":
                    score = f"{h} - {a}"
            
            # Kickoff time - convert UNIX timestamp to GMT+7
            start_ts = event.get("startTimestamp", 0)
            if start_ts:
                dt_utc = datetime.utcfromtimestamp(start_ts).replace(tzinfo=pytz.utc)
                dt_jakarta = dt_utc.astimezone(jakarta_tz)
                kickoff_date = dt_jakarta.strftime("%Y-%m-%d")
                kickoff_time = dt_jakarta.strftime("%H:%M")
            else:
                kickoff_date = ""
                kickoff_time = ""
            
            # ID generation
            id_str = f"{clean_name(home_full)}-{clean_name(away_full)}"
            
            # Sport type from category
            sport_info = category.get("sport", {})
            sport_name = sport_info.get("name", sport.capitalize())
            
            match_data = {
                "id": id_str,
                "league": league,
                "team1": {"name": home_full, "logo": home_logo},
                "team2": {"name": away_full, "logo": away_logo},
                "kickoff_date": kickoff_date,
                "kickoff_time": kickoff_time,
                "match_date": kickoff_date,
                "match_time": kickoff_time,
                "status": status_type,
                "status_desc": status_desc,
                "score": score,
                "round": round_num,
                "season": season_name,
                "sport": sport_name,
                "duration": "3.5",
                "servers": []
            }
            matches.append(match_data)
            
        except Exception as e:
            print(f"Error parsing event: {e}")
            continue
    
    return matches

def main():
    parser = argparse.ArgumentParser(description="Scrape scheduled events from SofaScore API")
    parser.add_argument("--sport", default="football,basketball", help="Sport slugs, comma-separated (default: football,basketball)")
    parser.add_argument("--date", default=None, help="Single date in YYYY-MM-DD format (overrides auto 3-day mode)")
    parser.add_argument("--days", type=int, default=3, help="Number of days to fetch (default: 3, starting from today)")
    parser.add_argument("--output", default="sofascore.json", help="Output filename (default: sofascore.json)")
    args = parser.parse_args()
    
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    all_matches = []
    
    sports = [s.strip() for s in args.sport.split(",")]
    
    if args.date:
        dates = [args.date]
    else:
        today = datetime.now(jakarta_tz).date()
        dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]
    
    print(f"{'='*60}")
    print(f"SofaScore Scraper")
    print(f"Sports: {', '.join(s.upper() for s in sports)}")
    print(f"Dates:  {', '.join(dates)}")
    print(f"{'='*60}\n")
    
    for sport in sports:
        for date_str in dates:
            matches = fetch_sofascore(sport=sport, date_str=date_str)
            all_matches.extend(matches)
    
    # Sort by kickoff_date then kickoff_time
    all_matches.sort(key=lambda x: (x.get("kickoff_date", ""), x.get("kickoff_time", "")))
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"Total: {len(all_matches)} matches saved to {args.output}")
    print(f"{'='*60}")
    
    # Print summary per sport & date
    if all_matches:
        by_sport = {}
        for m in all_matches:
            s = m.get("sport", "Unknown")
            d = m.get("kickoff_date", "Unknown")
            key = (s, d)
            by_sport[key] = by_sport.get(key, 0) + 1
        
        for (s, d) in sorted(by_sport.keys()):
            print(f"  📅 {d} | {s}: {by_sport[(s, d)]} matches")

if __name__ == "__main__":
    main()

