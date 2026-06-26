import requests
import re
import json
from datetime import datetime, timedelta
import pytz

def parse_sportsonline():
    url = "https://sportsonline.st/prog.txt"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        response.encoding = 'utf-8'  # Force UTF-8 encoding
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

    lines = response.text.split('\n')
    matches = []
    
    london_tz = pytz.timezone('Europe/London')
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    
    current_date_str = None
    
    # Days mapping
    days_map = {
        'MONDAY': 0, 'TUESDAY': 1, 'WEDNESDAY': 2, 'THURSDAY': 3, 
        'FRIDAY': 4, 'SATURDAY': 5, 'SUNDAY': 6
    }
    
    # Regex for match lines
    line_regex = re.compile(r'^(\d{2}:\d{2})\s+(.*?)\s+\|\s+(https?://.*)$')
    
    today = datetime.now(london_tz).date()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if line is a day
        if line.upper() in days_map:
            day_idx = days_map[line.upper()]
            today_idx = today.weekday()
            
            days_ahead = day_idx - today_idx
            if days_ahead < 0:
                days_ahead += 7
            
            current_date_obj = today + timedelta(days=days_ahead)
            current_date_str = current_date_obj.strftime("%Y-%m-%d")
            continue
            
        if not current_date_str:
            continue
            
        match = line_regex.match(line)
        if match:
            time_str, content, url = match.groups()
            
            league = ""
            team1 = ""
            team2 = ""
            
            if ':' in content:
                parts = content.split(':', 1)
                league = parts[0].strip()
                match_info = parts[1].strip()
            else:
                match_info = content
            
            if ' x ' in match_info:
                teams = match_info.split(' x ')
                team1 = teams[0].strip()
                team2 = teams[1].strip()
            elif ' @ ' in match_info:
                teams = match_info.split(' @ ')
                team1 = teams[0].strip()
                team2 = teams[1].strip()
            else:
                team1 = match_info.strip()
            
            # ID Generation
            def clean_name(name):
                return re.sub(r'[^a-zA-Z0-9]', '', name)
            
            id_str = f"{clean_name(team1)}-{clean_name(team2)}" if team2 else clean_name(team1)
            
            # Timezone Conversion
            try:
                dt_str = f"{current_date_str} {time_str}"
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                dt_obj = london_tz.localize(dt_obj)
                dt_jakarta = dt_obj.astimezone(jakarta_tz)
                
                kickoff_date = dt_jakarta.strftime("%Y-%m-%d")
                kickoff_time = dt_jakarta.strftime("%H:%M")
            except ValueError:
                continue
                
            # Server URL parsing
            ss_match = re.search(r'/([^/]+)\.php$', url)
            if ss_match:
                ss_val = ss_match.group(1)
                final_url = f"https://multi.govoet.cc/?ss={ss_val}"
            else:
                final_url = url
            
            server_data = {
                "url": final_url,
                "label": "CH-?" 
            }
            
            match_data = {
                "id": id_str,
                "league": league,
                "team1": {"name": team1, "logo": ""},
                "team2": {"name": team2, "logo": ""},
                "kickoff_date": "",
                "kickoff_time": kickoff_time,
                "match_date": "",
                "match_time": kickoff_time,
                "duration": "3.5",
                "servers": [server_data]
            }
            matches.append(match_data)

    # Post-processing to merge duplicate matches
    merged_matches = {}
    for m in matches:
        m_id = m['id']
        if m_id in merged_matches:
            merged_matches[m_id]['servers'].extend(m['servers'])
        else:
            merged_matches[m_id] = m
            
    final_list = []
    for m in merged_matches.values():
        for idx, srv in enumerate(m['servers']):
            srv['label'] = f"CH-{idx+1}"
        final_list.append(m)
        
    return final_list

if __name__ == "__main__":
    data = parse_sportsonline()
    with open('sportsonline.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} matches to sportsonline.json")
