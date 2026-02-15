from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
import json
import time
import base64
import random

# User Agents list for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", 
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0"
]

def setup_driver():
    """Setup Chrome driver with headless options"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    
    # Anti-detection
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Random User-Agent
    user_agent = random.choice(USER_AGENTS)
    chrome_options.add_argument(f'user-agent={user_agent}')
    print(f"Using User-Agent: {user_agent}")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # Execute CDP command to override user agent and properties
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    
    return driver

def scrape_ikotv():
    print("Starting ikotv.com scraper...")
    list_url = "https://ikotv.com/default/filter-match?type=now&bigmatch=false"
    
    all_matches = []
    driver = None

    try:
        driver = setup_driver()
        
        # Visit homepage first to pass Cloudflare
        print("Visiting homepage to pass Cloudflare check...")
        driver.get("https://ikotv.com")
        
        # Wait for Cloudflare/Challenge to pass
        for i in range(10):
            title = driver.title
            print(f"Page title (attempt {i+1}): {title}")
            if "Just a moment" not in title and title != "":
                print("Cloudflare challenge passed!")
                break
            time.sleep(3)
        
        time.sleep(2)
        
        # Now fetch the match list
        print(f"Fetching match list from {list_url}...")
        driver.get(list_url)
        time.sleep(2)
        
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
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
                date_elem = item.find('div', class_='date')
                kickoff_date = ""
                kickoff_time = ""
                
                if date_elem:
                    time_span = date_elem.find('span')
                    if time_span:
                        raw_time = time_span.text.strip()
                        try:
                            dt_obj = datetime.strptime(raw_time, "%d %b %Y | %H:%M")
                            kickoff_date = dt_obj.strftime("%Y-%m-%d")
                            kickoff_time = dt_obj.strftime("%H:%M")
                        except ValueError:
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

                # Fetch Match Page to get Stream Links
                try:
                    driver.get(match_url)
                    time.sleep(2)
                    
                    match_page_source = driver.page_source
                    match_soup = BeautifulSoup(match_page_source, 'html.parser')
                    
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

                    # Format streams for output
                    servers = []
                    seen_urls = set()
                    
                    for s in raw_streams:
                        url_to_encode = s['url']
                        if url_to_encode in seen_urls:
                            continue
                        seen_urls.add(url_to_encode)

                        b64_url = base64.b64encode(url_to_encode.encode('utf-8')).decode('utf-8')
                        final_url = f"https://multi.govoet.cc/?hls={b64_url}"
                        
                        label = "CH-NA"

                        servers.append({
                            "url": final_url,
                            "label": label
                        })

                    if not servers:
                         print(f"  No streams found for {home_team} vs {away_team}")
                         continue

                    # Construct final object
                    match_data = {
                        "id": f"{home_team}-{away_team}".replace(" ", ""),
                        "sport": "Football",
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
    
    finally:
        if driver:
            driver.quit()

    return all_matches

def save_json(data, filename="ikotv.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Saved {len(data)} matches to {filename}")

if __name__ == "__main__":
    data = scrape_ikotv()
    save_json(data)
