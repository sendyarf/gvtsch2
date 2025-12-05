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
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    all_matches = []

    sports_config = [
        {
            "name": "soccer",
            "url": "https://www.flashscore.com/",
            "container_class": "sportName soccer",
            "type": "soccer"
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
            
            # Scroll down
            last_height = driver.execute_script("return document.body.scrollHeight")
            for i in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Find containers
            containers = soup.find_all('div', class_=sport['container_class'])
            
            if not containers:
                print(f"Could not find any main container for {sport['name']}")
                continue

            print(f"Found {len(containers)} match containers for {sport['name']}.")

            for container in containers:
                current_league = ""
                current_country = ""
                
                for child in container.children:
                    if child.name != 'div':
                        continue
                    
                    classes = child.get('class', [])
                    
                    if 'headerLeague__wrapper' in classes:
                        try:
                            category_elem = child.find('span', class_='headerLeague__category-text')
                            title_elem = child.find('span', class_='headerLeague__title-text')
                            
                            if not title_elem:
                                 title_elem = child.find('strong', class_='headerLeague__title-text')

                            current_country = category_elem.text.strip() if category_elem else ""
                            current_league_name = title_elem.text.strip() if title_elem else ""
                            
                            if current_country and current_league_name:
                                current_league = f"{current_country} - {current_league_name}"
                            elif current_league_name:
                                current_league = current_league_name
                            else:
                                current_league = "Unknown League"
                                
                        except Exception as e:
                            print(f"Error parsing league header: {e}")
                            current_league = "Unknown"

                    elif 'event__match' in classes:
                        try:
                            if not current_league:
                                continue

                            match_item = {}
                            
                            if sport['type'] == 'soccer':
                                # Soccer Parsing Logic
                                time_elem = child.find('div', class_='event__time')
                                if time_elem:
                                    match_time = time_elem.text.strip().replace("Preview", "")
                                else:
                                    stage_elem = child.find('div', class_='event__stage')
                                    match_time = stage_elem.text.strip() if stage_elem else ""
                                
                                if not match_time:
                                    if child.find('span', {'data-state': 'final'}):
                                        match_time = "Finished"
                                
                                home_part = child.find('div', class_='event__homeParticipant')
                                if not home_part: continue
                                home_name_elem = home_part.find('span', class_='wcl-name_jjfMf')
                                if not home_name_elem: home_name_elem = home_part.find('strong', class_='wcl-name_jjfMf')
                                home_name = home_name_elem.text.strip() if home_name_elem else "Unknown"
                                
                                home_img = home_part.find('img', class_='wcl-logo_UrSpU')
                                home_logo = home_img.get('src') if home_img else ""

                                away_part = child.find('div', class_='event__awayParticipant')
                                if not away_part: continue
                                away_name_elem = away_part.find('span', class_='wcl-name_jjfMf')
                                if not away_name_elem: away_name_elem = away_part.find('strong', class_='wcl-name_jjfMf')
                                away_name = away_name_elem.text.strip() if away_name_elem else "Unknown"
                                
                                away_img = away_part.find('img', class_='wcl-logo_UrSpU')
                                away_logo = away_img.get('src') if away_img else ""

                            elif sport['type'] == 'basketball':
                                # Basketball Parsing Logic
                                time_elem = child.find('div', class_='event__time')
                                match_time = time_elem.text.strip() if time_elem else ""

                                # Home Team
                                home_name_elem = child.find('div', class_='event__participant--home')
                                home_name = home_name_elem.text.strip() if home_name_elem else "Unknown"
                                
                                home_img = child.find('img', class_='event__logo--home')
                                home_logo = home_img.get('src') if home_img else ""

                                # Away Team
                                away_name_elem = child.find('div', class_='event__participant--away')
                                away_name = away_name_elem.text.strip() if away_name_elem else "Unknown"
                                
                                away_img = child.find('img', class_='event__logo--away')
                                away_logo = away_img.get('src') if away_img else ""

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

        print(f"Total scraped {len(all_matches)} matches.")
        return all_matches

    except Exception as e:
        print(f"An error occurred: {e}")
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
