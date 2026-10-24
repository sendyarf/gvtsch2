from http_client import http_get
import json
import re
import argparse
import sys
from datetime import datetime, timedelta
import pytz
import random
import time

# Console output must survive Vietnamese/emoji on Windows (cp1252 would crash).
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def clean_name(name):
    """Remove non-alphanumeric characters for ID generation."""
    return re.sub(r'[^a-zA-Z0-9]', '', name)

# ------------------------------------------------------------------
# API config
# ------------------------------------------------------------------
# The community mirror 'api.sofascore1.com' currently only serves some endpoints
# (team detail, manager, `events/live`, ...). The old
# `/sport/{sport}/scheduled-events/{date}` feed returns 404 there, and the
# official `www.sofascore.com` API is behind a WAF. To keep the source useful we
# fetch the date feed first and fall back to the live feed when the date feed is
# unavailable (USE_LIVE_FALLBACK).
SOFASCORE_HOST = "api.sofascore1.com"
USE_LIVE_FALLBACK = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Accept": "application/json",
}


def _get_json(url):
    """GET url expecting a JSON object; returns dict or {} on any failure."""
    try:
        resp = http_get(url, headers=HEADERS, timeout=15, retries=2)
        if resp.status_code == 200:
            try:
                data = resp.json()
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        print(f"  -> HTTP {resp.status_code}")
    except Exception as e:
        print(f"  -> fetch error: {e}")
    return {}


def parse_event(event, sport):
    """Convert one SofaScore event dict into the shared match schema."""
    try:
        jakarta_tz = pytz.timezone('Asia/Jakarta')

        # Tournament / League info
        tournament = event.get("tournament", {})
        tournament_name = tournament.get("name", "")
        category = tournament.get("category", {})
        category_name = category.get("name", "")

        if category_name and tournament_name:
            league = f"{category_name} - {tournament_name}"
        elif tournament_name:
            league = tournament_name
        else:
            league = ""

        # Season & Round
        season = event.get("season", {})
        season_name = season.get("name", "")
        round_info = event.get("roundInfo", {})
        round_num = round_info.get("round", "")

        # Status
        status_info = event.get("status", {})
        status_type = status_info.get("type", "")
        status_desc = status_info.get("description", "")

        # Teams
        home_team = event.get("homeTeam", {})
        away_team = event.get("awayTeam", {})

        home_name = home_team.get("shortName", "") or home_team.get("name", "")
        away_name = away_team.get("shortName", "") or away_team.get("name", "")
        home_full = home_team.get("name", home_name)
        away_full = away_team.get("name", away_name)

        # Gender check - append " W" for women's teams if not present
        home_gender = home_team.get("gender", "")
        away_gender = away_team.get("gender", "")

        if home_gender == "F" and not home_full.endswith(" W") and not home_full.endswith(" Women"):
            home_full += " W"
        if away_gender == "F" and not away_full.endswith(" W") and not away_full.endswith(" Women"):
            away_full += " W"

        # Team logos
        home_id = home_team.get("id", "")
        away_id = away_team.get("id", "")
        home_logo = f"https://{SOFASCORE_HOST}/api/v1/team/{home_id}/image" if home_id else ""
        away_logo = f"https://{SOFASCORE_HOST}/api/v1/team/{away_id}/image" if away_id else ""

        # Scores
        home_score = event.get("homeScore", {})
        away_score = event.get("awayScore", {})
        score = ""
        if status_type in ("finished", "inprogress"):
            h = home_score.get("current", "")
            a = away_score.get("current", "")
            if h != "" and a != "":
                score = f"{h} - {a}"

        # Kickoff time - convert UNIX timestamp to GMT+7
        start_ts = event.get("startTimestamp", 0)
        if start_ts:
            dt_utc = datetime.fromtimestamp(start_ts, pytz.utc)
            dt_jakarta = dt_utc.astimezone(jakarta_tz)
            kickoff_date = dt_jakarta.strftime("%Y-%m-%d")
            kickoff_time = dt_jakarta.strftime("%H:%M")
        else:
            kickoff_date = ""
            kickoff_time = ""

        # ID generation
        id_str = f"{clean_name(home_full)}-{clean_name(away_full)}"

        # Sport type from category
        sport_info = category.get("sport", {})
        sport_name = sport_info.get("name", sport.capitalize())

        return {
            "id": id_str,
            "league": league,
            "team1": {"name": home_full, "logo": home_logo},
            "team2": {"name": away_full, "logo": away_logo},
            "kickoff_date": kickoff_date,
            "kickoff_time": kickoff_time,
            "match_date": kickoff_date,
            "match_time": kickoff_time,
            "status": status_type,
            "status_desc": status_desc,
            "score": score,
            "round": round_num,
            "season": season_name,
            "sport": sport_name,
            "gender": home_gender,
            "duration": "3.5",
            "servers": [],
        }
    except Exception:
        return None


def fetch_scheduled_events(sport, date_str):
    """Fetch scheduled events for one sport + date via the classic endpoint."""
    url = f"https://{SOFASCORE_HOST}/api/v1/sport/{sport}/scheduled-events/{date_str}"
    print(f"Fetching {sport} scheduled events for {date_str}...")
    data = _get_json(url)
    events = data.get("events", []) if isinstance(data.get("events"), list) else []
    print(f"  -> Found {len(events)} scheduled events")
    return [m for m in (parse_event(e, sport) for e in events) if m]


def fetch_live_events(sport):
    """Fallback: fetch currently live events for one sport."""
    url = f"https://{SOFASCORE_HOST}/api/v1/sport/{sport}/events/live"
    print(f"[fallback] Fetching {sport} live events (scheduled endpoint unavailable)...")
    data = _get_json(url)
    events = data.get("events", []) if isinstance(data.get("events"), list) else []
    print(f"  -> Found {len(events)} live events")
    return [m for m in (parse_event(e, sport) for e in events) if m]


def fetch_sofascore(sport="football", date_str=None):
    """Fetch events for one sport/date. Kept for CLI/backward-compat."""
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    if not date_str:
        date_str = datetime.now(jakarta_tz).strftime("%Y-%m-%d")
    matches = fetch_scheduled_events(sport, date_str)
    if not matches and USE_LIVE_FALLBACK:
        matches = fetch_live_events(sport)
    return matches


def main():
    parser = argparse.ArgumentParser(description="Scrape scheduled events from SofaScore API")
    parser.add_argument("--sport", default="football,basketball,baseball,ice-hockey", help="Sport slugs, comma-separated (default: football,basketball,baseball,ice-hockey)")
    parser.add_argument("--date", default=None, help="Single date in YYYY-MM-DD format (overrides auto 3-day mode)")
    parser.add_argument("--days", type=int, default=3, help="Number of days to fetch (default: 3, starting from today)")
    parser.add_argument("--output", default="sofascore.json", help="Output filename (default: sofascore.json)")
    args = parser.parse_args()

    jakarta_tz = pytz.timezone('Asia/Jakarta')
    all_matches = []

    sports = [s.strip() for s in args.sport.split(",")]

    if args.date:
        dates = [args.date]
    else:
        today = datetime.now(jakarta_tz).date()
        dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    print(f"{'='*60}")
    print(f"SofaScore Scraper")
    print(f"Sports: {', '.join(s.upper() for s in sports)}")
    print(f"Dates:  {', '.join(dates)}")
    print(f"{'='*60}\n")

    for sport in sports:
        scheduled_any = False
        for date_str in dates:
            matches = fetch_scheduled_events(sport=sport, date_str=date_str)
            if matches:
                scheduled_any = True
            all_matches.extend(matches)
            # Add small sleep between requests to avoid rate limiting
            time.sleep(random.uniform(0.5, 1.5))

        # If no date-based feed is available for this sport, use the live feed.
        if not scheduled_any and not args.date and USE_LIVE_FALLBACK:
            all_matches.extend(fetch_live_events(sport))

    # Sort by kickoff_date then kickoff_time
    all_matches.sort(key=lambda x: (x.get("kickoff_date", ""), x.get("kickoff_time", "")))

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Total: {len(all_matches)} matches saved to {args.output}")
    print(f"{'='*60}")

    # Print summary per sport & date
    if all_matches:
        by_sport = {}
        for m in all_matches:
            s = m.get("sport", "Unknown")
            d = m.get("kickoff_date", "Unknown")
            key = (s, d)
            by_sport[key] = by_sport.get(key, 0) + 1

        for (s, d) in sorted(by_sport.keys()):
            print(f"  📅 {d} | {s}: {by_sport[(s, d)]} matches")
    else:
        print("  (no matches fetched — check sofascore host availability)")


if __name__ == "__main__":
    main()