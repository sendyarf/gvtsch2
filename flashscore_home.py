import json
import time
import sys
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def scrape_flashscore_home():
    print("Starting Flashscore Homepage scraper...")
    
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    all_matches = []

    sports_config = [
        {
            "name": "Football",
            "url": "https://www.flashscore.com/",
            "container_class": "sportName soccer",
            "type": "Football"
        },
        {
            "name": "basketball",
            "url": "https://www.flashscore.com/basketball/",
            "container_class": "sportName basketball",
            "type": "basketball"
        }
    ]

    try:
        for sport in sports_config:
            print(f"Scraping {sport['name']} from {sport['url']}...")
            driver.get(sport['url'])

            # Wait for matches to load
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "event__match"))
                )
                print("Page loaded, parsing content...")
            except Exception as e:
                print(f"Timeout waiting for content for {sport['name']}: {e}")
                continue
            
            # Wait a bit more for dynamic content
            time.sleep(3)
            
            # Scroll down to load more matches
            last_height = driver.execute_script("return document.body.scrollHeight")
            for i in range(5):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Find all sport containers
            containers = soup.find_all('div', class_=sport['container_class'])
            
            if not containers:
                print(f"Could not find any main container for {sport['name']}")
                continue

            print(f"Found {len(containers)} match containers for {sport['name']}.")

            for container in containers:
                current_league = ""
                current_country = ""
                
                # Iterate through all children to get league headers and matches
                for child in container.find_all(['div'], recursive=False):
                    classes = child.get('class', [])
                    class_str = ' '.join(classes)
                    
                    # Check for league header
                    if 'headerLeague__wrapper' in classes:
                        try:
                            # Get country from category text
                            category_elem = child.find('span', class_='headerLeague__category-text')
                            # Get league name from title text
                            title_elem = child.find('span', class_='headerLeague__title-text')
                            
                            if category_elem:
                                current_country = category_elem.text.strip()
                            if title_elem:
                                league_name = title_elem.text.strip()
                            else:
                                league_name = ""
                            
                            # Format: "Country - League" (e.g., "ENGLAND - Premier League")
                            if current_country and league_name:
                                # Capitalize country properly
                                current_country_formatted = current_country.title()
                                current_league = f"{current_country_formatted} - {league_name}"
                            elif league_name:
                                current_league = league_name
                            else:
                                current_league = "Unknown League"
                                
                            print(f"  Found league: {current_league}")
                                
                        except Exception as e:
                            print(f"Error parsing league header: {e}")
                            current_league = "Unknown"

                    # Check for match row
                    elif 'event__match' in classes:
                        try:
                            if not current_league:
                                continue

                            match_item = {}
                            
                            # Get match time
                            time_elem = child.find('div', class_='event__time')
                            stage_elem = child.find('div', class_='event__stage')
                            
                            if time_elem:
                                match_time = time_elem.text.strip()
                            elif stage_elem:
                                match_time = stage_elem.get_text(strip=True)
                            else:
                                match_time = ""
                            
                            # Get home team
                            home_part = child.find('div', class_='event__homeParticipant')
                            if not home_part:
                                continue
                            
                            home_name_elem = home_part.find('span', class_=lambda x: x and 'wcl-name' in x)
                            home_name = home_name_elem.text.strip() if home_name_elem else "Unknown"
                            
                            home_img = home_part.find('img', class_=lambda x: x and 'wcl-logo' in x)
                            home_logo = home_img.get('src', '') if home_img else ""

                            # Get away team
                            away_part = child.find('div', class_='event__awayParticipant')
                            if not away_part:
                                continue
                            
                            away_name_elem = away_part.find('span', class_=lambda x: x and 'wcl-name' in x)
                            away_name = away_name_elem.text.strip() if away_name_elem else "Unknown"
                            
                            away_img = away_part.find('img', class_=lambda x: x and 'wcl-logo' in x)
                            away_logo = away_img.get('src', '') if away_img else ""

                            # Construct ID
                            match_id = f"{home_name}-{away_name}"
                            
                            match_item = {
                                "id": match_id,
                                "league": current_league,
                                "sport": sport['name'],
                                "team1": {
                                    "name": home_name,
                                    "logo": home_logo
                                },
                                "team2": {
                                    "name": away_name,
                                    "logo": away_logo
                                },
                                "kickoff_time": match_time
                            }
                            
                            all_matches.append(match_item)
                            
                        except Exception as e:
                            print(f"Error parsing match: {e}")
                            continue

            # Alternative parsing: iterate through all elements in order
            # This handles nested structures better
            if len(all_matches) == 0:
                print("Trying alternative parsing method...")
                current_league = ""
                
                # Find all league headers
                league_headers = soup.find_all('div', class_='headerLeague__wrapper')
                
                for header in league_headers:
                    category_elem = header.find('span', class_='headerLeague__category-text')
                    title_elem = header.find('span', class_='headerLeague__title-text')
                    
                    if category_elem and title_elem:
                        country = category_elem.text.strip().title()
                        league = title_elem.text.strip()
                        current_league = f"{country} - {league}"
                    elif title_elem:
                        current_league = title_elem.text.strip()
                    
                    # Find matches that follow this header
                    parent = header.find_parent('div', class_=sport['container_class'])
                    if not parent:
                        continue
                    
                    # Get all siblings after this header until next header
                    sibling = header.find_next_sibling()
                    while sibling:
                        sibling_classes = sibling.get('class', [])
                        
                        if 'headerLeague__wrapper' in sibling_classes:
                            break  # Next league header found
                        
                        if 'event__match' in sibling_classes:
                            try:
                                time_elem = sibling.find('div', class_='event__time')
                                stage_elem = sibling.find('div', class_='event__stage')
                                
                                if time_elem:
                                    match_time = time_elem.text.strip()
                                elif stage_elem:
                                    match_time = stage_elem.get_text(strip=True)
                                else:
                                    match_time = ""
                                
                                home_part = sibling.find('div', class_='event__homeParticipant')
                                away_part = sibling.find('div', class_='event__awayParticipant')
                                
                                if home_part and away_part:
                                    home_name_elem = home_part.find('span', class_=lambda x: x and 'wcl-name' in x)
                                    away_name_elem = away_part.find('span', class_=lambda x: x and 'wcl-name' in x)
                                    
                                    home_name = home_name_elem.text.strip() if home_name_elem else "Unknown"
                                    away_name = away_name_elem.text.strip() if away_name_elem else "Unknown"
                                    
                                    home_img = home_part.find('img', class_=lambda x: x and 'wcl-logo' in x)
                                    away_img = away_part.find('img', class_=lambda x: x and 'wcl-logo' in x)
                                    
                                    home_logo = home_img.get('src', '') if home_img else ""
                                    away_logo = away_img.get('src', '') if away_img else ""
                                    
                                    match_item = {
                                        "id": f"{home_name}-{away_name}",
                                        "league": current_league,
                                        "sport": sport['name'],
                                        "team1": {
                                            "name": home_name,
                                            "logo": home_logo
                                        },
                                        "team2": {
                                            "name": away_name,
                                            "logo": away_logo
                                        },
                                        "kickoff_time": match_time
                                    }
                                    
                                    all_matches.append(match_item)
                            except Exception as e:
                                print(f"Error in alternative parsing: {e}")
                        
                        sibling = sibling.find_next_sibling()

        print(f"\nTotal scraped {len(all_matches)} matches.")
        return all_matches

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        driver.quit()

def save_data(data, filename='flashscore_home.json'):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Data saved to {filename}")

if __name__ == "__main__":
    data = scrape_flashscore_home()
    save_data(data)
