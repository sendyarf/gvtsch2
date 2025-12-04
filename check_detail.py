import json

# Check flashscore_home for Monaco-Paris
with open('flashscore_home.json', 'r', encoding='utf-8') as f:
    home = json.load(f)

monaco_paris = [m for m in home if ('Monaco' in m['team1']['name'] and 'Paris' in m['team2']['name']) or ('Paris' in m['team1']['name'] and 'Monaco' in m['team2']['name'])]
print("=== Monaco-Paris in flashscore_home.json ===")
for m in monaco_paris:
    print(json.dumps(m, indent=2, ensure_ascii=False))
    
# Check sch.json for Monaco-Paris
with open('sch.json', 'r', encoding='utf-8') as f:
    sch = json.load(f)

monaco_paris_sch = [m for m in sch if 'Monaco' in str(m) and 'Paris' in str(m)]
print("\n=== Monaco-Paris in sch.json ===")
for m in monaco_paris_sch:
    print(json.dumps(m, indent=2, ensure_ascii=False))

# Check matches without logos
no_logo = [m for m in sch if not m['team1'].get('logo') or not m['team2'].get('logo')]
print(f"\n=== Matches without logos: {len(no_logo)} ===")
for m in no_logo[:5]:
    print(f"- {m['team1']['name']} vs {m['team2']['name']} ({m.get('league', 'N/A')})")
