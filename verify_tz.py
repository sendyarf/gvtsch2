"""
Timezone drift verifier for gvtsch2.

sch.json merges many sources into one GMT+7 (Asia/Jakarta) feed. All non-flashscore
sources output GMT+7 already, so any match whose kickoff differs by ~1-2h from the
same teams in another source indicates a timezone mismatch (classic symptom: VPS in
Seoul KST feeding flashscore before the GMT+7 conversion fix).

Method: for every match in sch.json, find the same team-pair in each source JSON and
compare kickoff wall-times (minute diff). Report matches whose times disagree by more
than DRIFT_THRESHOLD_MIN minutes.

Run after a fresh merge on the VPS:
    ./venv/bin/python verify_tz.py
Exit code 0 = no drift found.
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))

# Sources produced in GMT+7 (used as the ground truth for comparison).
GMT7_SOURCES = ['bolaloca.json', 'soco.json', 'sportsonline.json', 'timstreams.json']
# flashscore is also GMT+7 after the conversion fix; include it too.
GMT7_SOURCES += ['flashscore.json']

DRIFT_THRESHOLD_MIN = 45  # >= 45 min apart is treated as a drift indicator


def norm(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def wall_minutes(date, time_):
    """(YYYY-MM-DD, HH:MM) -> naive epoch minutes, or None."""
    if not date or not time_:
        return None
    try:
        dt = datetime.strptime(f"{date} {time_}", "%Y-%m-%d %H:%M")
        return int(dt.timestamp() / 60)
    except (ValueError, TypeError):
        return None


def load(name):
    p = os.path.join(BASE, name)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[warn] cannot load {name}: {e}")
        return []


def main():
    # Build source index: teams_key -> list of kickoff-minutes (GMT+7).
    src_index = {}  # 'name' -> { key: [minutes...] }
    for fname in GMT7_SOURCES:
        idx = {}
        for m in load(fname):
            t1 = norm(m.get('team1', {}).get('name', ''))
            t2 = norm(m.get('team2', {}).get('name', ''))
            if not t1 and not t2:
                continue
            key = '-'.join(sorted([t1, t2]))
            cm = wall_minutes(m.get('kickoff_date'), m.get('kickoff_time'))
            if cm is not None:
                idx.setdefault(key, set()).add(cm)
        if idx:
            src_index[fname] = idx

    sch = load('sch.json')
    print(f"checking {len(sch)} matches across {len(src_index)} GMT+7 sources...")

    issues = []
    cross_checked = 0
    for m in sch:
        t1 = norm(m.get('team1', {}).get('name', ''))
        t2 = norm(m.get('team2', {}).get('name', ''))
        if not t1 or not t2:
            continue
        key = '-'.join(sorted([t1, t2]))
        scm = wall_minutes(m.get('kickoff_date'), m.get('kickoff_time'))
        if scm is None:
            continue

        found_any = False
        diffs = []
        for fname, idx in src_index.items():
            if key in idx:
                found_any = True
                base = min(idx[key])
                d = abs(scm - base)
                if d >= DRIFT_THRESHOLD_MIN:
                    diffs.append((fname, d))
        if found_any:
            cross_checked += 1
        if diffs:
            team = f"{m.get('team1', {}).get('name')} vs {m.get('team2', {}).get('name')}"
            det = ", ".join(f"{f} (+{d}min)" for f, d in diffs)
            issues.append((team, m.get('kickoff_date'), m.get('kickoff_time'), det))

    print(f"cross-checked: {cross_checked} matches (present in at least one GMT+7 source)")
    if not issues:
        print("✅ No timezone drift detected — all GMT+7 sources agree with sch.json.")
        return 0

    print(f"\n❌ {len(issues)} match(es) with suspected timezone drift:\n")
    for team, date, time_, det in issues:
        print(f"  • {team}  [{date} {time_}]  vs sources: {det}")
    print("\n(Likely a source feeding a non-GMT+7 kickoff — recheck that scraper.)")
    return 1


if __name__ == "__main__":
    sys.exit(main())