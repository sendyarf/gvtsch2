import requests
import json
from datetime import datetime, timedelta

r = requests.get('https://beta.adstrim.ru/api/events')
data = r.json()
events = data.get('data', [])

# Find Bahia vs Fluminense
bahia = [e for e in events if 'bahia' in str(e).lower() and 'fluminense' in str(e).lower()]

if bahia:
    match = bahia[0]
    print(f"Match: {match.get('home_team')} vs {match.get('away_team')}")
    print(f"Timestamp: {match.get('timestamp')}")
    print(f"Unix Timestamp: {match.get('unix_timestamp')}")
    
    ts = match.get('timestamp')
    if ts:
        dt_utc = datetime.utcfromtimestamp(ts)
        print(f"UTC from timestamp: {dt_utc}")
        print(f"GMT+7 from timestamp: {dt_utc + timedelta(hours=7)}")
    
    uts = match.get('unix_timestamp')
    if uts and uts != ts:
        dt_utc_uts = datetime.utcfromtimestamp(uts)
        print(f"UTC from unix_timestamp: {dt_utc_uts}")
        print(f"GMT+7 from unix_timestamp: {dt_utc_uts + timedelta(hours=7)}")
else:
    print("Bahia vs Fluminense not found")
