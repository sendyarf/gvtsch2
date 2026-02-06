import json
import requests
import base64
from datetime import datetime, timedelta
import re
import pytz

def gmt_to_gmt7(timestamp):
    # Convert unix timestamp to UTC and then to GMT+7 using pytz
    utc_tz = pytz.utc
    gmt7_tz = pytz.timezone('Asia/Jakarta')
    
    dt_utc = datetime.fromtimestamp(timestamp, utc_tz)
    dt_gmt7 = dt_utc.astimezone(gmt7_tz)
    return dt_gmt7

def clean_name(name):
    return re.sub(r'[^a-zA-Z0-9]', '', name)

def encode_url(channel_name):
    url = f"https://dovkembed.pw/channel/{channel_name}"
    encoded = base64.b64encode(url.encode('utf-8')).decode('utf-8')
    return f"https://multi.govoet.cc/?iframex={encoded}"

def get_sport_duration(sport, league, duration_mapping):
    # Try exact match for league first
    if league in duration_mapping:
        minutes = duration_mapping[league]
    # Then try sport
    elif sport in duration_mapping:
        minutes = duration_mapping[sport]
    else:
        # Default for Football if not found (though it should be in mapping)
        if sport == 'Football':
            return "3.5"
        return "3.5"
    
    # Convert minutes to hours and format as string with 2 decimal places if not whole
    hours = minutes / 60.0
    if hours == int(hours):
        return str(int(hours))
    return f"{hours:.3g}"

def scrape_adstrim():
    api_url = "https://beta.adstrim.ru/api/events"
    output_file = "adstrim.json"
    duration_file = "duration.json"
    
    # Load duration mapping
    duration_mapping = {}
    try:
        with open(duration_file, 'r', encoding='utf-8') as f:
            duration_data = json.load(f)
            duration_mapping = duration_data.get('data', {})
    except Exception as e:
        print(f"Warning: Could not load {duration_file}: {e}")

    print(f"Fetching data from {api_url}...")
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        events_data = response.json()
        print(f"Response type: {type(events_data)}")
        
        if isinstance(events_data, dict):
            # Try to find the list in common keys
            if 'events' in events_data:
                events = events_data['events']
            elif 'data' in events_data:
                events = events_data['data']
            else:
                print("Dictionary response found but no 'events' or 'data' key.")
                events = []
        else:
            events = events_data
            
        print(f"Number of events to process: {len(events)}")
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    data = []
    for event in events:
        if not isinstance(event, dict):
            print(f"Skipping non-dict event: {event}")
            continue
        try:
            timestamp = event.get('unix_timestamp') or event.get('timestamp')
            if not timestamp:
                continue
                
            dt_gmt7 = gmt_to_gmt7(timestamp)
            kickoff_date = dt_gmt7.strftime("%Y-%m-%d")
            kickoff_time = dt_gmt7.strftime("%H:%M")
            
            home_team = event.get('home_team')
            away_team = event.get('away_team')
            title = event.get('title')
            
            if not home_team and not away_team and title:
                home_team = title
                away_team = ""
                match_id = clean_name(title)
            else:
                home_team = home_team or 'Unknown'
                away_team = away_team or 'Unknown'
                match_id = f"{clean_name(home_team)}-{clean_name(away_team)}"
            
            servers = []
            for channel in event.get('channels', []):
                name = channel.get('name', 'Server')
                # Determine label based on country tag in name
                label = "CH-NA"
                if "[UK]" in name:
                    label = "CH-UK"
                elif "[USA]" in name:
                    label = "CH-US"
                elif "[Spain]" in name:
                    label = "CH-ES"
                elif "[ID]" in name:
                    label = "CH-ID"
                
                servers.append({
                    "url": encode_url(name),
                    "label": label
                })
            
            item = {
                "id": match_id,
                "sport": event.get('sport', 'Other'),
                "league": event.get('league', 'Unknown'),
                "team1": {
                    "name": home_team,
                    "logo": event.get('home_team_image', '')
                },
                "team2": {
                    "name": away_team,
                    "logo": event.get('away_team_image', '')
                },
                "kickoff_date": kickoff_date,
                "kickoff_time": kickoff_time,
                "match_date": kickoff_date,
                "match_time": kickoff_time,
                "duration": get_sport_duration(event.get('sport', 'Other'), event.get('league', 'Unknown'), duration_mapping),
                "servers": servers
            }
            data.append(item)
        except Exception as e:
            print(f"Error processing event {event.get('id')}: {e}")
            continue

    print(f"Saving {len(data)} items to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("Scraping completed successfully!")

if __name__ == "__main__":
    scrape_adstrim()
