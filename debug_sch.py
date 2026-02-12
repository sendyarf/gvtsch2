import json

data = json.load(open('sch.json', encoding='utf-8'))
matches = [m for m in data if 'bahia' in str(m).lower()]

for m in matches:
    print(f"Match: {m.get('team1').get('name')} vs {m.get('team2').get('name')}")
    print(f"Date: {m.get('kickoff_date')}")
    print(f"Time: {m.get('kickoff_time')}")
    print(f"League: {m.get('league')}")
    print("-" * 20)
