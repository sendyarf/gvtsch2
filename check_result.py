import json

with open('sch.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=== First 10 matches ===")
for i, match in enumerate(data[:10]):
    print(f"{i+1}. ID: {match.get('id', 'N/A')}")
    print(f"   League: {match.get('league', 'N/A')}")
    t1_logo = "YES" if match['team1'].get('logo') else "NO"
    t2_logo = "YES" if match['team2'].get('logo') else "NO"
    print(f"   Team1: {match['team1']['name']} - Logo: {t1_logo}")
    print(f"   Team2: {match['team2']['name']} - Logo: {t2_logo}")
    print()

# Count stats
total = len(data)
with_both_logos = sum(1 for m in data if m['team1'].get('logo') and m['team2'].get('logo'))
with_league = sum(1 for m in data if m.get('league'))

print(f"=== Statistics ===")
print(f"Total matches: {total}")
print(f"With both logos: {with_both_logos} ({100*with_both_logos/total:.1f}%)")
print(f"With league name: {with_league} ({100*with_league/total:.1f}%)")
