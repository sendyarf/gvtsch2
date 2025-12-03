import requests
import json
import base64
from datetime import datetime
import pytz
import re
import urllib3

def parse_streamcenter():
    # Fetch categories first
    categories_url = "https://backendstreamcenter.youshop.pro:488/api/Categories"
    category_map = {}
    
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        cat_response = requests.get(categories_url, verify=False, timeout=15)
        cat_response.raise_for_status()
        categories = cat_response.json()
        
        # Build category id -> name mapping
        if isinstance(categories, list):
            for cat in categories:
                cat_id = cat.get('id')
                cat_name = cat.get('name', '')
                if cat_id:
                    category_map[cat_id] = cat_name
        print(f"Loaded {len(category_map)} categories from StreamCenter API")
    except Exception as e:
        print(f"Error fetching categories: {e}")
    
    # Fetch parties/matches
    url = "https://backendstreamcenter.youshop.pro:488/api/Parties?pageNumber=1&pageSize=500"
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(url, verify=False, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

    if isinstance(data, dict) and 'items' in data:
        items = data['items']
    elif isinstance(data, list):
        items = data
    else:
        items = []

    matches = []
    # Using Paris time based on cross-referencing with other sources
    source_tz = pytz.timezone('Europe/London') 
    jakarta_tz = pytz.timezone('Asia/Jakarta')

    for item in items:
        name = item.get('name', '')
        video_url_raw = item.get('videoUrl', '')
        begin_partie = item.get('beginPartie', '')
        category_id = item.get('categoryId')
        
        if not name or not video_url_raw:
            continue
            
        video_url = video_url_raw.split('<')[0]
        
        # Get league name from category
        league = category_map.get(category_id, '') if category_id else ''
        
        try:
            dt_obj = datetime.strptime(begin_partie, "%Y-%m-%dT%H:%M:%S")
            dt_obj = source_tz.localize(dt_obj)
            dt_jakarta = dt_obj.astimezone(jakarta_tz)
            
            kickoff_date = dt_jakarta.strftime("%Y-%m-%d")
            kickoff_time = dt_jakarta.strftime("%H:%M")
        except ValueError:
            continue
            
        if ' vs ' in name:
            teams = name.split(' vs ')
            team1 = teams[0].strip()
            team2 = teams[1].strip()
        else:
            team1 = name.strip()
            team2 = ""
            
        def clean_name(n):
            return re.sub(r'[^a-zA-Z0-9]', '', n)
        
        id_str = f"{clean_name(team1)}-{clean_name(team2)}" if team2 else clean_name(team1)
        
        encoded_url = base64.b64encode(video_url.encode('utf-8')).decode('utf-8')
        final_url = f"https://multi.govoet.my.id/?iframe={encoded_url}"
        
        server_data = {
            "url": final_url,
            "label": "CH-EN"
        }
        
        match_data = {
            "id": id_str,
            "league": league, 
            "team1": {"name": team1, "logo": item.get('logoTeam2', '')},
            "team2": {"name": team2, "logo": item.get('logoTeam1', '')},
            "kickoff_date": kickoff_date,
            "kickoff_time": kickoff_time,
            "match_date": kickoff_date,
            "match_time": kickoff_time,
            "duration": "3.5",
            "servers": [server_data]
        }
        matches.append(match_data)
        
    return matches

if __name__ == "__main__":
    data = parse_streamcenter()
    with open('streamcenter.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} matches to streamcenter.json")
