from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import json
import base64
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

def encode_url_to_base64(url):
    """Encode URL to base64"""
    return base64.b64encode(url.encode()).decode()

def setup_driver():
    """Setup Chrome driver with options"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Run in background
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def scrape_with_selenium():
    """Scrape Indonesia league matches using Selenium"""
    
    base_url = "https://socolive5.in/"
    driver = None
    
    try:
        print("Starting Chrome driver...")
        driver = setup_driver()
        
        print(f"Navigating to {base_url}...")
        driver.get(base_url)
        
        # Wait for page to load
        time.sleep(3)
        
        # Click on "Nay" (Today) tab if needed
        try:
            today_tab = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'li[data-value="tday"]'))
            )
            if not today_tab.get_attribute('class') or 'active' not in today_tab.get_attribute('class'):
                print("Clicking on 'Today' tab...")
                today_tab.click()
                time.sleep(2)
        except:
            print("Today tab already active or not found")
        
        # Wait for match items to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'match-item'))
        )
        
        # Find all match items
        match_elements = driver.find_elements(By.CLASS_NAME, 'match-item')
        
        print(f"\nFound {len(match_elements)} total matches")
        print("Filtering Indonesia league matches...\n")
        
        indonesia_matches = []
        
        for match_elem in match_elements:
            try:
                # Check league name
                league_elem = match_elem.find_element(By.CLASS_NAME, 'match-item__comp')
                league_name = league_elem.text.strip()
                
                # Filter only Indonesia league
                if "Giải bóng đá VĐQG Indonesia" not in league_name:
                    continue
                
                print(f"Processing: {league_name}")
                
                # Extract time
                try:
                    time_elem = match_elem.find_element(By.CSS_SELECTOR, '.match-item__time span')
                    time_text = time_elem.text.strip()
                except:
                    time_text = ""
                
                # Extract teams
                try:
                    home_team_elem = match_elem.find_element(By.CSS_SELECTOR, '.name-home span')
                    home_team = home_team_elem.text.strip()
                except:
                    home_team = "Unknown"
                
                try:
                    away_team_elem = match_elem.find_element(By.CSS_SELECTOR, '.name-away span')
                    away_team = away_team_elem.text.strip()
                except:
                    away_team = "Unknown"
                
                print(f"  Match: {home_team} vs {away_team}")
                print(f"  Time: {time_text}")
                
                # Extract match URL
                try:
                    link_elem = match_elem.find_element(By.CLASS_NAME, 'link-match')
                    match_url = link_elem.get_attribute('href')
                except:
                    match_url = ""
                
                # Extract BLV channels
                blv_elements = match_elem.find_elements(By.CLASS_NAME, 'blv-item-scl')
                
                if not blv_elements:
                    print(f"  No BLV channels found, skipping...")
                    continue
                
                servers = []
                
                for blv_elem in blv_elements:
                    try:
                        blv_link = blv_elem.find_element(By.CLASS_NAME, 'dropdown-item')
                        blv_url = blv_link.get_attribute('href')
                        blv_name_elem = blv_link.find_element(By.TAG_NAME, 'span')
                        blv_name = blv_name_elem.text.strip()
                        
                        # Extract blv parameter
                        parsed_url = urlparse(blv_url)
                        query_params = parse_qs(parsed_url.query)
                        
                        if 'blv' not in query_params:
                            continue
                        
                        blv_id = query_params['blv'][0]
                        
                        # Create stream URL
                        stream_url = f"https://live.inplyr.com/room/{blv_id}.m3u8"
                        encoded_url = encode_url_to_base64(stream_url)
                        player_url = f"https://multi.govoet.my.id/?hls={encoded_url}"
                        
                        servers.append({
                            "url": player_url,
                            "label": f"CH-VN"
                        })
                        
                        print(f"  Channel: {blv_name} (BLV ID: {blv_id})")
                    except Exception as e:
                        continue
                
                if not servers:
                    print(f"  No valid servers found, skipping...")
                    continue
                
                # Parse time
                try:
                    time_parts = time_text.split()
                    if len(time_parts) >= 2:
                        time_str = time_parts[0]
                        date_str = time_parts[1]
                        current_year = datetime.now().year
                        date_obj = datetime.strptime(f"{date_str}/{current_year} {time_str}", "%d/%m/%Y %H:%M")
                        match_date = date_obj.strftime("%Y-%m-%d")
                        match_time = date_obj.strftime("%H:%M")
                    else:
                        match_date = datetime.now().strftime("%Y-%m-%d")
                        match_time = "00:00"
                except:
                    match_date = datetime.now().strftime("%Y-%m-%d")
                    match_time = "00:00"
                
                # Create match ID
                match_id = urlparse(match_url).path.split('/')[-2] if match_url else ""
                
                # Create match object
                match_data = {
                    "id": match_id,
                    "league": league_name,
                    "team1": {
                        "name": home_team
                    },
                    "team2": {
                        "name": away_team
                    },
                    "kickoff_date": match_date,
                    "kickoff_time": match_time,
                    "match_date": match_date,
                    "match_time": match_time,
                    "duration": "3.0",
                    "servers": servers
                }
                
                indonesia_matches.append(match_data)
                print(f"  Added with {len(servers)} server(s)\n")
                
            except Exception as e:
                print(f"  Error processing match: {e}")
                continue
        
        return indonesia_matches
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    finally:
        if driver:
            driver.quit()
            print("Browser closed")

def save_to_json(matches, filename="soco.json"):
    """Save matches to JSON file"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Successfully saved {len(matches)} matches to {filename}")
        return True
    except Exception as e:
        print(f"❌ Error saving to file: {e}")
        return False

def main():
    print("=" * 60)
    print("SOCOLIVE INDONESIA LEAGUE SCRAPER (SELENIUM)")
    print("=" * 60)
    
    matches = scrape_with_selenium()
    
    if matches:
        save_to_json(matches, "soco.json")
        
        print("\n" + "=" * 60)
        print(f"SUMMARY: Found {len(matches)} Indonesia league match(es)")
        print("=" * 60)
        
        for i, match in enumerate(matches, 1):
            print(f"\n{i}. {match['team1']['name']} vs {match['team2']['name']}")
            print(f"   Date: {match['match_date']} {match['match_time']}")
            print(f"   Servers: {len(match['servers'])}")
    else:
        print("\n❌ No Indonesia league matches found")

if __name__ == "__main__":
    main()
