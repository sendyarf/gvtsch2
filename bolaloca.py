import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
import pytz

def parse_bolaloca():
    url = "https://bolaloca.my/"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find the textarea with the schedule
    # Based on plan.txt: <textarea style="width:100%;height:14000px;resize: yes;background: #121212; font-family: Verdana,sans-serif; font-size: 16px; color: #eee;">
    # We can try to find the textarea that contains "partners" or just the first large textarea.
    textarea = None
    for ta in soup.find_all('textarea'):
        if 'background: #121212' in ta.get('style', '') or 'width:100%' in ta.get('style', ''):
             # Check if it looks like the schedule
             if 'CH' in ta.text:
                 textarea = ta
                 break
    
    if not textarea:
        print("Could not find schedule textarea")
        return []

    content = textarea.text
    lines = content.split('\n')
    
    matches = []
    
    # Timezones
    paris_tz = pytz.timezone('Europe/Paris')
    jakarta_tz = pytz.timezone('Asia/Jakarta')

    # Regex for the line structure
    # 30-11-2025 (21:00) Laliga : Gérone - Real Madrid  (CH1fr) (CH49es) (CH71es) (CH88es)
    # Group 1: Date, Group 2: Time, Group 3: League, Group 4: Match info (Teams), Group 5: Servers part
    line_regex = re.compile(r'^(\d{2}-\d{2}-\d{4})\s*\((\d{2}:\d{2})\)\s*(.*?)\s*:\s*(.*?)\s+(\(CH.*)$')
    
    # Regex for servers: (CH1fr)
    server_regex = re.compile(r'\(CH(\d+)([a-z]+)\)')

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        match = line_regex.match(line)
        if match:
            date_str, time_str, league, match_info, servers_str = match.groups()
            
            # Parse Date and Time
            try:
                dt_str = f"{date_str} {time_str}"
                dt_obj = datetime.strptime(dt_str, "%d-%m-%Y %H:%M")
                dt_obj = paris_tz.localize(dt_obj)
                dt_jakarta = dt_obj.astimezone(jakarta_tz)
                
                kickoff_date = dt_jakarta.strftime("%Y-%m-%d")
                kickoff_time = dt_jakarta.strftime("%H:%M")
            except ValueError:
                continue

            # Parse Teams
            # "Gérone - Real Madrid" or "Qatar F1 Grand Prix -"
            if ' - ' in match_info:
                parts = match_info.split(' - ')
                team1_name = parts[0].strip()
                team2_name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else ""
            else:
                team1_name = match_info.strip()
                team2_name = ""

            # Generate ID
            # Remove spaces and special chars for ID
            def clean_name(name):
                return re.sub(r'[^a-zA-Z0-9]', '', name)
            
            id_str = f"{clean_name(team1_name)}-{clean_name(team2_name)}" if team2_name else clean_name(team1_name)

            # Parse Servers
            servers = []
            server_matches = server_regex.findall(servers_str)
            for s_num, s_country in server_matches:
                servers.append({
                    "url": f"https://multi.govoet.cc/?envivo={s_num}",
                    "label": f"CH-{s_country.upper()}"
                })

            match_data = {
                "id": id_str,
                "league": league.strip(),
                "team1": {
                    "name": team1_name,
                    "logo": ""
                },
                "team2": {
                    "name": team2_name,
                    "logo": ""
                },
                "kickoff_date": kickoff_date,
                "kickoff_time": kickoff_time,
                "match_date": kickoff_date,
                "match_time": kickoff_time,
                "duration": "3.5",
                "servers": servers
            }
            matches.append(match_data)

    return matches

if __name__ == "__main__":
    data = parse_bolaloca()
    with open('bolaloca.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} matches to bolaloca.json")
