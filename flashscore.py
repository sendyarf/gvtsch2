import json
import time
from datetime import datetime, timedelta
from dateutil.parser import parse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import re

def scrape_flashscore():
    # List of URLs to scrape
    urls = [
        {"url": "https://www.flashscore.com/football/england/premier-league/fixtures/", "league": "England - Premier League"},
        {"url": "https://www.flashscore.com/football/netherlands/eredivisie/fixtures/", "league": "Netherlands - Eredivisie"},
        {"url": "https://www.flashscore.com/football/france/ligue-1/fixtures/", "league": "France - Ligue 1"},
        {"url": "https://www.flashscore.com/football/germany/bundesliga/fixtures/", "league": "Germany - Bundesliga"},
        {"url": "https://www.flashscore.com/football/italy/serie-a/fixtures/", "league": "Italy - Serie A"},
        {"url": "https://www.flashscore.com/football/spain/laliga/fixtures/", "league": "Spain - Laliga"},
        {"url": "https://www.flashscore.com/football/indonesia/super-league/fixtures/", "league": "Indonesia - Super League"},
        #{"url": "https://www.flashscore.com/basketball/usa/nba/fixtures/", "league": "USA - NBA"},
    ]

    # Set up Chrome options for headless mode
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # Run in headless mode
    chrome_options.add_argument("--disable-gpu")  # Disable GPU for compatibility
    chrome_options.add_argument("--no-sandbox")  # Bypass OS security model
    chrome_options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

    # Print initial notification
    print("Starting to scrape football schedules from Flashscore...")

    # Initialize the WebDriver with headless options
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    except Exception as e:
        print(f"Error initializing driver: {e}")
        return []

    data = []
    # Get current date dynamically
    current_date = datetime.now()
    # Set current_date to start of day for accurate date comparison
    current_date = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
    current_year = current_date.year
    current_month = current_date.month

    try:
        # Iterate over each URL
        for league_info in urls:
            url = league_info["url"]
            league_name = league_info["league"]
            print(f"Navigating to {league_name} fixtures page: {url}")

            # Navigate to the URL
            driver.get(url)

            # Wait for the page to load with reduced timeout
            print(f"Waiting for {league_name} page to load...")
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".event__match--twoLine, .event__match--static"))
                )
            except TimeoutException:
                print(f"Timeout waiting for {league_name} page to load. Skipping.")
                continue

            # Handle "Show more matches" if present with reduced sleep
            print(f"Checking for 'Show more matches' button for {league_name}...")
            while True:
                try:
                    show_more = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "a.wclButtonLink"))
                    )
                    print(f"Clicking 'Show more matches' to load additional {league_name} fixtures...")
                    show_more.click()
                    time.sleep(1)  # Reduced from 2 seconds
                except:
                    print(f"No more matches to load for {league_name}.")
                    break

            # Find all match elements
            print(f"Collecting match data for {league_name}...")
            match_elements = driver.find_elements(By.CSS_SELECTOR, ".event__match--twoLine, .event__match--static")

            for match in match_elements:
                try:
                    # Home team
                    home_participant = match.find_element(By.CLASS_NAME, "event__homeParticipant")
                    home_name = home_participant.find_element(By.CSS_SELECTOR, "span.wcl-name_jjfMf").text

                    # Away team
                    away_participant = match.find_element(By.CLASS_NAME, "event__awayParticipant")
                    away_name = away_participant.find_element(By.CSS_SELECTOR, "span.wcl-name_jjfMf").text

                    # Time and date
                    time_div = match.find_element(By.CLASS_NAME, "event__time")
                    time_text = time_div.text.split("\n")[0]  # Get the time line, ignore preview if present

                    # Robust date parsing with fallback
                    date_time_part = time_text.split(" ")[0].rstrip(".")
                    try:
                        if "." in date_time_part:
                            date_parts = date_time_part.split(".")
                            day = date_parts[0].zfill(2)
                            month = date_parts[1].zfill(2)
                        else:
                            parsed_date = parse(date_time_part, dayfirst=True)
                            day = str(parsed_date.day).zfill(2)
                            month = str(parsed_date.month).zfill(2)
                    except (IndexError, ValueError):
                        day = str(current_date.day).zfill(2)
                        month = str(current_date.month).zfill(2)
                        print(f"Warning: Invalid date format for {league_name} match {home_name} vs {away_name}, using current date: {time_text}")

                    kickoff_time = time_text.split(" ")[1] if len(time_text.split(" ")) > 1 else time_text

                    # Determine the year dynamically
                    match_month = int(month)
                    # If current month is August or later, matches in January or early months belong to next year
                    if current_month >= 8 and match_month <= 3:
                        match_year = current_year + 1
                    else:
                        match_year = current_year

                    # Construct date
                    kickoff_date = f"{match_year}-{month}-{day}"

                    # Validate and filter date
                    try:
                        match_date = datetime.strptime(kickoff_date, "%Y-%m-%d")
                        # Only include matches from today and next 2 days (total 3 days)
                        end_date = current_date + timedelta(days=2)
                        if current_date <= match_date <= end_date:
                            # ID generation consistent with other scrapers
                            def clean_name(name):
                                return re.sub(r'[^a-zA-Z0-9]', '', name)
                            
                            match_id = f"{clean_name(home_name)}-{clean_name(away_name)}"

                            # Build the item
                            item = {
                                "id": match_id,
                                "league": league_name,
                                "team1": {
                                    "name": home_name
                                },
                                "team2": {
                                    "name": away_name
                                },
                                "kickoff_date": kickoff_date,
                                "kickoff_time": kickoff_time,
                                "match_date": kickoff_date,  # Same format as kickoff_date (YYYY-MM-DD)
                                "match_time": kickoff_time,  # Use the same time as kickoff_time
                                "duration": "3.5",
                                "servers": []
                            }

                            data.append(item)
                    except ValueError:
                        # If invalid date, skip
                        print(f"Skipping {league_name} match {home_name} vs {away_name} due to invalid date: {kickoff_date}")
                        continue

                except NoSuchElementException:
                    # Skip if elements not found
                    # print(f"Skipping a {league_name} match due to missing elements.")
                    continue
    finally:
        # Close the driver
        driver.quit()

    # Save to flashscore.json
    print(f"Saving {len(data)} matches to flashscore.json...")
    with open("flashscore.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("Scraping completed successfully! Data saved to flashscore.json.")
    return data

if __name__ == "__main__":
    scrape_flashscore()
