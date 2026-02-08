from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import time
import base64
from datetime import datetime

def scrape_ikotv():
    print("Starting ikotv.com scraper...")
    base_url = "https://ikotv.com"
    list_url = "https://ikotv.com/default/filter-match?type=now&bigmatch=false"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://ikotv.com/",
        "Origin": "https://ikotv.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache"
    }

    all_matches = []

    try:
        print(f"Fetching match list from {list_url}...")
        print(f"Fetching match list from {list_url}...")
        response = requests.get(list_url, headers=headers, timeout=15, impersonate="chrome110")
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        match_items = soup.find_all('div', class_='match-item')
        
        print(f"Found {len(match_items)} live matches.")

        for item in match_items:
            try:
                # League
                league_elem = item.find('p', class_='type')
                league_name = league_elem.text.strip() if league_elem else "Unknown League"

                # Teams
                teams_container = item.find('h3')
                if teams_container:
                    spans = teams_container.find_all('span')
                    # Usually: [Home Team] [vs] [Away Team]
                    # Filter out "vs"
                    team_names = [s.text.strip() for s in spans if s.text.strip().lower() != 'vs']
                    if len(team_names) >= 2:
                        home_team = team_names[0]
                        away_team = team_names[1]
                    else:
                        home_team = "Unknown"
                        away_team = "Unknown"
                else:
                    home_team = "Unknown"
                    away_team = "Unknown"

                # Time parsing
                # Format example: "08 Feb 2026 | 18:15"
                date_elem = item.find('div', class_='date')
                kickoff_date = ""
                kickoff_time = ""
                
                if date_elem:
                    time_span = date_elem.find('span')
                    if time_span:
                        raw_time = time_span.text.strip()
                        try:
                            # Parse format "08 Feb 2026 | 18:15"
                            # If year is present
                            dt_obj = datetime.strptime(raw_time, "%d %b %Y | %H:%M")
                            kickoff_date = dt_obj.strftime("%Y-%m-%d")
                            kickoff_time = dt_obj.strftime("%H:%M")
                        except ValueError:
                            # Try without year or other formats if needed, or just leave empty
                            try:
                                # Sometimes it might just be time if today? But example shows full date.
                                pass
                            except:
                                pass
                            print(f"  Could not parse time: {raw_time}")

                # Logo
                home_logo = ""
                away_logo = ""
                imgs = item.find_all('img')
                if len(imgs) >= 2:
                    home_logo = imgs[0].get('src', '')
                    away_logo = imgs[1].get('src', '')

                # Match Link
                link_elem = item.find('a', class_='btn-view')
                match_url = link_elem['href'] if link_elem else ""

                if not match_url:
                    continue

                print(f"Processing: {home_team} vs {away_team} ({league_name})")

                # Fetch Match Page to get Stream Link
                # Fetch Match Page to get Stream Link
                try:
                    match_page_response = requests.get(match_url, headers=headers, timeout=10, impersonate="chrome110")
                    match_soup = BeautifulSoup(match_page_response.text, 'html.parser')
                    
                    # Look for stream links
                    raw_streams = []
                    
                    # Priority 1: .sv-link elements
                    sv_links = match_soup.find_all('a', class_='sv-link')
                    for sv in sv_links:
                        s_url = sv.get('data-url')
                        s_name = sv.get('data-name') or sv.text.strip() or "Server"
                        if s_url:
                            raw_streams.append({"name": s_name, "url": s_url})

                    # Priority 2: iframe #stream src
                    if not raw_streams:
                        iframe = match_soup.find('iframe', id='stream')
                        if iframe:
                           src = iframe.get('src')
                           if src:
                               raw_streams.append({"name": "Iframe", "url": src})

                    # Format streams for output (adstrim style)
                    servers = []
                    
                    # Deduplicate by URL
                    seen_urls = set()
                    
                    for s in raw_streams:
                        url_to_encode = s['url']
                        if url_to_encode in seen_urls:
                            continue
                        seen_urls.add(url_to_encode)

                        # Encode to base64
                        b64_url = base64.b64encode(url_to_encode.encode('utf-8')).decode('utf-8')
                        final_url = f"https://multi.govoet.cc/?hls={b64_url}"
                        
                        label = "CH-NA"

                        servers.append({
                            "url": final_url,
                            "label": label
                        })

                    if not servers:
                         print(f"  No streams found for {home_team} vs {away_team}")
                         # Continue or skip? User usually only wants matches with links.
                         # let's include if you want to see matches even without links, or skip.
                         # adstrim usually implies playable.
                         continue

                    # Construct final object
                    match_data = {
                        "id": f"{home_team}-{away_team}".replace(" ", ""),
                        "sport": "Football", # ikotv seems mostly football in "Live Now", need to check category if mixed
                        "league": league_name,
                        "team1": {
                            "name": home_team,
                            "logo": home_logo
                        },
                        "team2": {
                            "name": away_team,
                            "logo": away_logo
                        },
                        "kickoff_date": kickoff_date,
                        "kickoff_time": kickoff_time,
                        "match_date": kickoff_date,
                        "match_time": kickoff_time,
                        "duration": "3.5",
                        "servers": servers
                    }
                    
                    all_matches.append(match_data)

                except Exception as e:
                    print(f"  Error scraping match page {match_url}: {e}")

            except Exception as e:
                print(f"Error processing match item: {e}")
                continue

    except Exception as e:
        print(f"Error fetching match list: {e}")

    return all_matches

def save_json(data, filename="ikotv.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Saved {len(data)} matches to {filename}")

if __name__ == "__main__":
    data = scrape_ikotv()
    save_json(data)
