"""
Real-time live-score poller for gvtsch2.

`run_all.py` refreshes fixtures/servers every few minutes, which is fine for the
schedule but far too slow for a live scoreboard. This service is the real-time
companion: it polls the colatv API on a short interval and writes a small
`live.json` that the frontend can fetch every few seconds and overlay onto
`sch.json`.

Data sources (both polled every cycle):
  - `/api/matches`        : ALL live matches, any sport. Carries `sportId` and the
                            per-sport score arrays. This is the only source that
                            covers non-football sports.
  - `/api/match/detail_live`: football only. Fresher phase/kickoff and the extra
                            stats (shots/possession). Used to enrich football.

Score semantics differ per sport (`sportId`):
  - football (1)  : `[goals, half_time_goals, red, yellow, corners]`
  - basketball (2): `[Q1, Q2, Q3, Q4, OT]` -> total is the sum, `status_desc` is
                    the current quarter (the API exposes no clock/period for it)
  - other         : index 0 as the running value

`live.json`:
    {
      "updated_at": "2026-09-12T17:40:00+07:00",
      "interval": 10,
      "count": 5,
      "matches": [
        {
          "id": "<colatv matchId>",
          "join_key": "2026-09-12|acmilan-sslazio",
          "sch_id": "<id in sch.json, if a matching fixture is found>",
          "node_match_id": "<id in detail_live, football only>",
          "team1": "...", "team2": "...",
          "league": "...", "sport": "Football",
          "match_date": "2026-09-12",
          "status": "inprogress",
          "status_desc": "2nd half 65'",
          "score": "2 - 0",
          "ht_score": "2 - 0",
          # football only:
          "phase": 4, "live_kickoff": 1789232715,
          "stats": { "corners": {"home": 2, "away": 5}, ... },
          # basketball only:
          "period_scores": { "home": [26,20,22,7,0], "away": [12,15,18,9,0] }
        }
      ]
    }

For football, `live_kickoff` + `phase` let the frontend tick the minute locally
every second (the site itself polls every 5s), so this service only needs to
deliver score/phase changes. `matches` only contains currently in-play games, so
the frontend should clear the overlay for ids that are no longer present.

Joining live.json to sch.json
-----------------------------
Do NOT join by `id`: live.json's `id` is colatv's matchId while sch.json's `id`
comes from whichever source created the entry (e.g. flashscore's "Home-Away"),
so they never match. Join by `join_key` instead, which sch.py emits identically:

    join_key = "<kickoff_date>|<normalized-team-a>-<normalized-team-b>"

Team names are normalized through manual_mapping.json and sorted, so the key is
order-independent and source-independent. `sch_id` is also provided as a
resolved shortcut, but it is null when sch.json has not been merged yet; the
frontend should fall back to `join_key`.

    // frontend
    const byKey = new Map(sch.map(m => [m.join_key, m]));
    const schMatch = byKey.get(liveMatch.join_key);

Run under PM2 as `gvtsch2-live` (see ecosystem.config.js), or:
    python live.py                    # poll forever (10s)
    python live.py --interval 5
    python live.py --once             # write live.json once and exit
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from difflib import SequenceMatcher
import unicodedata
import re

from http_client import http_get
from colatv import (API, HEADERS, VI_LEAGUE_MAP, _SPORT_BY_ID, _live_data,
                    _phase_desc, _ts_wib, clean_team_name, half_score_text, period_scores,
                    score_text, sport_of, SPORT_BASKETBALL, SPORT_FOOTBALL)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

OUTPUT = "live.json"
SCH_FILE = "sch.json"

try:
    import sch as sch_matcher
except Exception:  # pragma: no cover - sch.py should always be importable
    sch_matcher = None

AFFIX_WORDS = {
    'clb', 'fc', 'cf', 'sc', 'ac', 'as', 'ss', 'ssc', 'rc', 'ud', 'cd', 'sv', 'fk', 'bk', 'sk',
    'afc', 'csd', 'ca', 'vfb', 'vfl', 'tsg', 'bsc', 'fsv', '1fc'
}


def _clean_team_for_matching(text):
    """Strip common club noise words (CLB, UD, FC, etc.) from team name."""
    if not text:
        return ""
    t = unicodedata.normalize('NFD', text)
    t = ''.join(char for char in t if unicodedata.category(char) != 'Mn').lower()
    t = re.sub(r'^(?:cau lac bo bong da|cau lac bo|clb)\s+', '', t)
    t = re.sub(r'[.\-_/]', ' ', t)
    tokens = t.split()
    if not tokens:
        return ""
    while tokens and tokens[0] in AFFIX_WORDS:
        tokens.pop(0)
    while tokens and (tokens[-1] in AFFIX_WORDS or re.match(r'^\d{4}$', tokens[-1])):
        tokens.pop()
    return ''.join(re.sub(r'[^a-z0-9]', '', tok) for tok in (tokens or t.split()))


def _clean_join_key(team1, team2, kickoff_date):
    c1 = _clean_team_for_matching(team1)
    c2 = _clean_team_for_matching(team2)
    teams = "-".join(sorted([c1, c2]))
    return f"{kickoff_date}|{teams}" if kickoff_date else teams


def _join_key(team1, team2, kickoff_date):
    """Same key sch.py emits, so the frontend can join by it (ids differ)."""
    if sch_matcher is not None and hasattr(sch_matcher, "make_join_key"):
        return sch_matcher.make_join_key(team1, team2, kickoff_date)
    return f"{kickoff_date}|{'-'.join(sorted([team1, team2]))}"


def _now_wib():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S+07:00")


def _fetch_live_matches():
    """Raw live match dicts for ALL sports from /api/matches.

    /api/matches is the only source carrying non-football live matches and the
    per-sport score arrays, so it is fetched every cycle. `_slug` is attached for
    the id fallback.
    """
    r = http_get(f"{API}/api/matches", headers=HEADERS, timeout=20, retries=2, verify=False)
    data = r.json().get("data") or {}
    out = []
    for slug, m in data.items():
        if isinstance(m, dict) and m.get("matchStatus") == 2:
            m = dict(m)
            m["_slug"] = slug
            out.append(m)
    return out


def _load_sch_index():
    """Lightweight view of sch.json for fast matching."""
    try:
        with open(SCH_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    out = []
    for m in data:
        try:
            t1 = m["team1"]["name"]
            t2 = m["team2"]["name"]
            kd = m.get("kickoff_date") or m.get("match_date") or ""
            out.append({
                "id": m.get("id"),
                "colatv_id": m.get("colatv_id"),
                "key": m.get("join_key") or _join_key(t1, t2, kd),
                "clean_key": _clean_join_key(t1, t2, kd),
                "t1": t1,
                "t2": t2,
                "date": kd,
            })
        except Exception:
            continue
    return out


def _find_sch_match(index, live_id, team1, team2, kickoff_date):
    """Resolve a live match to its sch.json entry using a multi-layer strategy:
    1. Direct match by Colatv match ID or colatv_id (100% exact & fast).
    2. Exact join_key match.
    3. Clean join_key match (club noise words CLB/UD/FC stripped).
    4. Adaptive fuzzy match on the same date (threshold >= 70%).
    """
    if not index:
        return None

    # Layer 1: Match by ID / colatv_id
    for m in index:
        if live_id and (m["id"] == live_id or m.get("colatv_id") == live_id):
            return m

    # Layer 2: Match by exact join_key
    target_key = _join_key(team1, team2, kickoff_date)
    for m in index:
        if m["key"] == target_key:
            return m

    # Layer 3: Match by clean_key (club affixes stripped)
    target_clean_key = _clean_join_key(team1, team2, kickoff_date)
    for m in index:
        if m.get("clean_key") == target_clean_key:
            return m

    # Layer 4: Adaptive fuzzy match (same date)
    c1_live = _clean_team_for_matching(team1)
    c2_live = _clean_team_for_matching(team2)
    for m in index:
        if kickoff_date and m["date"] and kickoff_date != m["date"]:
            continue
        c1_sch = _clean_team_for_matching(m["t1"])
        c2_sch = _clean_team_for_matching(m["t2"])
        sim_dir = (SequenceMatcher(None, c1_live, c1_sch).ratio() + SequenceMatcher(None, c2_live, c2_sch).ratio()) / 2
        sim_rev = (SequenceMatcher(None, c1_live, c2_sch).ratio() + SequenceMatcher(None, c2_live, c1_sch).ratio()) / 2
        if max(sim_dir, sim_rev) >= 0.70:
            return m

    return None


def build_snapshot(live_matches, live_detail, sch_index, now):
    """Turn live /api/matches entries into the live.json payload (all sports)."""
    matches = []
    for m in live_matches:
        try:
            slug = m.get("_slug")
            sport_id = sport_of(m)
            node_id = (m.get("node_api_data") or {}).get("match_id") or m.get("match_id")
            detail = live_detail.get(node_id) or {}

            team1 = clean_team_name(m.get("homeTeamName") or "Home")
            team2 = clean_team_name(m.get("awayTeamName") or "Away")
            comp = (m.get("competitionName") or "").strip()
            # Real kickoff date (sch.json's match_date is shifted -5 min and can
            # cross midnight); this is what the join key must use.
            kickoff_date = _ts_wib(m.get("matchTime") or 0).strftime("%Y-%m-%d")

            match_id = m.get("matchId") or slug
            sch_match = _find_sch_match(sch_index, match_id, team1, team2, kickoff_date)

            entry = {
                "id": match_id,
                # Synchronize join_key with sch.json so frontend lookup byKey ALWAYS matches!
                "join_key": sch_match["key"] if sch_match else _join_key(team1, team2, kickoff_date),
                "sch_id": sch_match["id"] if sch_match else None,
                "node_match_id": node_id,
                "team1": team1,
                "team2": team2,
                "league": VI_LEAGUE_MAP.get(comp, comp),
                "sport": _SPORT_BY_ID.get(sport_id, ""),
                "match_date": kickoff_date,
                "status": "inprogress",
                "status_desc": _phase_desc(m, detail, now),
                "score": score_text(m, sport_id, detail),
                "ht_score": half_score_text(m, sport_id, detail),
            }

            if sport_id == SPORT_BASKETBALL:
                hs, as_ = period_scores(m)
                entry["period_scores"] = {"home": hs, "away": as_}
            elif sport_id in (SPORT_FOOTBALL, 0):
                entry["phase"] = detail.get("phase", 0)
                entry["live_kickoff"] = detail.get("kickoff", 0)
                if detail.get("stats"):
                    entry["stats"] = detail["stats"]

            matches.append(entry)
        except Exception:
            continue

    matches.sort(key=lambda e: (e.get("sport") or "", e["league"], e["team1"]))
    return {
        "updated_at": _now_wib(),
        "count": len(matches),
        "matches": matches,
    }


def write_snapshot(snapshot):
    tmp = OUTPUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT)


def run_once(interval):
    now = time.time()
    live_matches = _fetch_live_matches()
    # detail_live is football-only; skip it when no football match is in play.
    has_football = any(sport_of(m) in (SPORT_FOOTBALL, 0) for m in live_matches)
    live_detail = _live_data() if has_football else {}
    sch_index = _load_sch_index()
    snapshot = build_snapshot(live_matches, live_detail, sch_index, now)
    snapshot["interval"] = interval
    write_snapshot(snapshot)
    return snapshot


def main():
    ap = argparse.ArgumentParser(description="gvtsch2 real-time live-score poller")
    ap.add_argument("--interval", type=int,
                    default=int(os.environ.get("LIVE_INTERVAL", "10")),
                    help="seconds between polls (default 10)")
    ap.add_argument("--once", action="store_true", help="write live.json once and exit")
    args = ap.parse_args()

    if args.once:
        snap = run_once(args.interval)
        print(f"[live] {snap['count']} live match(es) -> {OUTPUT}")
        return 0

    print(f"[live] polling every {args.interval}s -> {OUTPUT}", flush=True)
    while True:
        try:
            snap = run_once(args.interval)
            print(f"[live] {_now_wib()} {snap['count']} live match(es)", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[live] error: {type(e).__name__}: {e}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Stopped.")
