"""
colatv55.live scraper - clean, reliable Vietnamese source (separate backend).

Unlike soco (flaky livingRoom index), colatv exposes a public API that returns
each match's playable HLS (`videoUrl`) DIRECTLY:

    GET https://api.cltvlv.com/api/matches
    headers: X-Domain: colatv55.live , Referer: https://colatv55.live/

Response: { "data": { "<slug>": { matchId, sportId, matchTime, matchStatus,
  homeTeamName, awayTeamName, competitionName, videoUrl, anchorAppointmentVoList,
  ... } } }

There are two kinds of playable stream:

  1. `videoUrl` - for matches that have a direct/original feed this is a signed
     m3u8 on the current CDN (e.g. …/live/<id>_<hash>_autoChange.m3u8?auth_key=…).
     This is the ORIGINAL commentator feed and is used as the primary server.
  2. `anchorAppointmentVoList` - one entry per BLV/commentator channel, holding
     mirror feeds, used as alternative servers, mirroring the site's own player:
         streamUrl = anchor.playStreamAddress2 || anchor.playStreamAddress
     Each anchor's `servers` list is folded in as additional alternatives.

For matches without an original feed `videoUrl` is the literal string "https"
(or empty), so those matches only have anchor mirrors.

We do not hardcode CDN hosts: whatever host the API returns is used as-is, so a
host rotation needs no code change. Only the volatile signed query (`auth_key`)
is dropped, keeping player URLs stable across scrape cycles. Streams are stored
the same way as the other sources (multi.govoet.cc/?hls=<b64>).

Live metadata from the same response is surfaced too: `status`
(scheduled/inprogress/finished), a phase `status_desc`, the `score` and the
half-time `ht_score`. The score arrays mean different things per `sportId`:

  - football (1)  : `[goals, half_time_goals, red_cards, yellow_cards, corners, …]`
                    -> `status_desc` is the half + elapsed minute, plus a `stats`
                    block (corners/cards from the array; shots/possession from
                    /api/match/detail_live).
  - basketball (2): `[Q1, Q2, Q3, Q4, OT]` -> score is the sum, plus
                    `period_scores`. detail_live does not cover basketball and
                    the API exposes no period/clock for it, so `status_desc` is
                    left empty rather than guessing a quarter.

For football the live phase/minute and kickoff come from /api/match/detail_live
(`score[1]` and `score[4]`): `node_api_data.status_id` lags and `matchTime` can be
far from the real kickoff, which would make the displayed minute wrong.

Output: colatv.json (shared schema).
"""
import base64
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from http_client import http_get

API = "https://api.cltvlv.com"
DOMAIN = "colatv55.live"
PLAYER_PREFIX = "https://multi.govoet.cc/?hls="

# colatv returns competition names in Vietnamese; map the common ones to the
# canonical English names used by the rest of the pipeline. Anything not listed
# is kept as-is (the AI matcher can translate the long tail later).
VI_LEAGUE_MAP = {
    "Giải bóng đá Hạng nhất Brasil": "Brazil - Serie A",
    "Giải bóng đá Hạng nhì Brasil": "Brazil - Serie B",
    "Giải bóng đá Hạng nhì Argentina": "Argentina - Primera Nacional",
    "Giải bóng đá Hạng nhì Hoa Kỳ": "USA - USL Championship",
    "Cúp Argentina": "Argentina - Copa Argentina",
    "Cúp Brasil": "Brazil - Copa do Brasil",
    "Giải vô địch quốc gia Chile": "Chile - Primera División",
    "Cúp Liên đoàn": "League Cup",
    "Giải vô địch quốc gia Colombia": "Colombia - Primera A",
    "Cúp Bóng đá Châu Á U20": "AFC U-20 Asian Cup",
    "Giải vô địch quốc gia Qatar": "Qatar - Stars League",
    "Giải Vô địch quốc gia Ả-rập Xê-út": "Saudi Arabia - Saudi Pro League",
    "Cúp Ý": "Italy - Coppa Italia",
    "cúp Nga": "Russia - Russian Cup",
    "Giải Vô địch Quốc gia Thụy Điển": "Sweden - Allsvenskan",
    "Giải Ngoại hạng Đan Mạch": "Denmark - Superliga",
    "Giải vô địch quốc gia Bỉ": "Belgium - Pro League",
    "Ligue 1": "France - Ligue 1",
    "Giải Bóng đá Vô địch Quốc gia Tây Ban Nha": "Spain - LaLiga",
    "Giải vô địch quốc gia Ecuador": "Ecuador - LigaPro Serie A",
    "Giải hạng hai Mexico": "Mexico - Liga de Expansión",
    "Giải bóng đá Liga 1 Indonesia": "Indonesia - Liga 1",
    "World Cup Bóng rổ Nữ": "FIBA Women's World Cup",
    "Giải K1 Hàn Quốc": "South Korea - K League 1",
    "Giải K2 Hàn Quốc": "South Korea - K League 2",
    "Giải vô địch quốc gia Việt Nam": "Vietnam - V.League 1",
    "Asean Club Championship Shopee Cup": "AFC - ASEAN Club Championship",
    "Thái League 1": "Thailand - Thai League 1",
    "Giải vô địch Malaysia": "Malaysia - Super League",
    "UAE League": "UAE - Pro League",
    "Giải vô địch quốc gia Uzbekistan": "Uzbekistan - Super League",
    "Giải bóng đá Hạng hai Đức": "Germany - 2. Bundesliga",
    "AFC Giải vô địch Champions 2": "Asia - AFC Champions League Two",
    "AFC Giải vô địch Champions Elite": "Asia - AFC Champions League Elite",
    "Cúp bóng đá của Hiệp hội Bóng đá Úc": "Australia - Australia Cup",
    "Giải Bóng đá Vô địch Quốc gia Argentina": "Argentina - Primera División",
    "Giải Bóng đá Vô địch Quốc gia Bồ Đào Nha": "Portugal - Primeira Liga",
    "Giải Bóng đá Vô địch Quốc gia Hà Lan": "Netherlands - Eredivisie",
    "Giải Bóng đá Vô địch Quốc gia Phần Lan": "Finland - Veikkausliiga",
    "Giải Ngoại hạng Ai Cập": "Egypt - Premier League",
    "Giải Ngoại hạng Thổ Nhĩ Kỳ": "Turkey - Süper Lig",
    "Giải Vô địch Bóng đá Quốc gia Mexico": "Mexico - Liga MX",
    "Giải Vô địch Quốc gia Georgia": "Georgia - Erovnuli Liga",
    "Giải Vô địch quốc gia Romania": "Romania - Liga I",
    "Giải bóng đá Hạng nhất Thủ đô Canberra của Úc": "Australia - ACT Premier League",
    "Giải bóng đá Ngoại hạng Anh": "England - Premier League",
    "Giải bóng đá Serie A Italia": "Italy - Serie A",
    "Giải bóng đá vô địch quốc gia Đức": "Germany - Bundesliga",
    "Giải vô địch quốc gia Nhật Bản": "Japan - J1 League",
    "Major League Soccer": "USA - MLS",
    "Đại hội Thể thao Châu Á": "Asia - Asian Games",
    "Đại hội Thể thao Nữ Châu Á": "Asia - Asian Women's Games",
    "Giải Bóng đá Dự bị Nữ Hoa Kỳ": "USA - MLS Next Pro",
}

# sportId -> display name (matches the site's own map: 1 football, 2 basketball,
# 3 tennis, 4 volleyball).
_SPORT_BY_ID = {1: "Football", 2: "Basketball", 3: "Tennis", 4: "Volleyball",
                5: "Ice Hockey", 6: "Baseball"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "X-Domain": DOMAIN,
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}/",
}


def _ts_wib(ts):
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)
    except Exception:
        return datetime.now(timezone.utc) + timedelta(hours=7)


def _b64(url):
    return base64.b64encode(url.encode()).decode()


def build_player_url(stream_url):
    return f"{PLAYER_PREFIX}{quote(_b64(stream_url), safe='')}"


def variant_stream_urls(stream_url):
    """Return the stream URL without its volatile signed query string.

    We deliberately do NOT rewrite the CDN host: the API already returns
    whichever host is current, so a host rotation needs no code change here.
    Only the volatile query (`auth_key`) is dropped, which keeps the player URL
    stable across scrape cycles so merged output does not accumulate stale
    servers. The CDN serves the m3u8 and its segments without it.
    """
    return [stream_url.split("?")[0]]


def _flv_to_m3u8(url):
    """Convert a .flv stream URL to .m3u8, keeping any query params."""
    return re.sub(r"\.flv(?=([?#]|$))", ".m3u8", url, flags=re.IGNORECASE)


def clean_team_name(name):
    """Strip Vietnamese club prefixes (e.g. 'CLB ', 'Câu lạc bộ bóng đá ')."""
    if not name or not isinstance(name, str):
        return ""
    name = name.strip()
    name = re.sub(r'^(?:Câu lạc bộ bóng đá|Câu lạc bộ|CLB)\s+', '', name, flags=re.IGNORECASE)
    return name.strip()


def _anchor_stream_urls(match):
    """Playable mirror HLS URLs for a match, taken from its anchor (BLV) list.

    Mirrors the site's own player:
        streamUrl = anchor.playStreamAddress2 || anchor.playStreamAddress
    The pinned anchor (`pin_hot_anchor` / `house_id`) is preferred, then the
    remaining anchors. Each anchor's `servers` mirrors are folded in too.
    """
    anchors = match.get("anchorAppointmentVoList") or []
    if not isinstance(anchors, list):
        anchors = []
    pinned = str(match.get("pin_hot_anchor") or match.get("house_id") or "")
    if pinned:
        anchors = sorted(anchors, key=lambda a: 0 if str(a.get("houseId") or "") == pinned else 1)

    urls = []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        candidates = [a.get("playStreamAddress2"), a.get("playStreamAddress")]
        mirrors = a.get("servers")
        if isinstance(mirrors, list):
            candidates.extend(mirrors)
        for raw in candidates:
            if not isinstance(raw, str):
                continue
            u = _flv_to_m3u8(raw.strip())
            if u.startswith("http") and ".m3u8" in u and u not in urls:
                urls.append(u)
    return urls


# Top-level `matchStatus` -> the pipeline's status vocabulary.
_STATUS_BY_MATCH_STATUS = {1: "scheduled", 2: "inprogress", 3: "finished"}

# sportId values seen in the API (the site's own map).
SPORT_FOOTBALL = 1
SPORT_BASKETBALL = 2
SPORT_TENNIS = 3
SPORT_VOLLEYBALL = 4

# `node_api_data.status_id` is the detailed phase (mirrors the site's own
# mapping). Used only to describe a live match's phase.
_PHASE_DESC = {
    2: "1st half",
    3: "Halftime",
    4: "2nd half",
    5: "Extra Time 1",
    6: "Extra Time 2",
    7: "Penalties",
    8: "Finished",
}

# detail_live `stats[].type` -> our stat name. Corners and cards are taken from
# the score arrays (always present); these are the extra stats only detail_live
# exposes. Codes mirror the site's own map. Note: type 23/24 are attacks /
# dangerous attacks, not shots, so they are intentionally not mapped.
_STAT_TYPE = {
    "shots_on_target": 21,
    "shots_off_target": 22,
    "possession": 25,
}


def sport_of(match):
    """sportId as int (1 football, 2 basketball, 3 tennis, 4 volleyball)."""
    try:
        return int(match.get("sportId") or match.get("sport_id") or 0)
    except (TypeError, ValueError):
        return 0


def _int_list(value):
    if not isinstance(value, list):
        return []
    return [int(x) if isinstance(x, (int, float)) else 0 for x in value]


def period_scores(match):
    """Raw per-period score arrays (home, away).

    Meaning depends on the sport:
      - football : [goals, half_time_goals, red_cards, yellow_cards, corners, …]
      - basketball: [Q1, Q2, Q3, Q4, OT] (total = sum)
    """
    return _int_list(match.get("homeScore")), _int_list(match.get("awayScore"))


def football_components(match):
    """Per-team components from a FOOTBALL score array.

    Layout: `[goals, half_time_goals, red_cards, yellow_cards, corners, …]`.
    Returns a dict of (home, away) tuples, zero-filled for short arrays.
    """
    hs, as_ = period_scores(match)
    # The top-level `homeScore`/`awayScore` from /api/matches can be missing
    # (or left all-zero) for mlive-covered matches while the real values live in
    # the nested `node_api_data.home_scores`/`away_scores`, so fall back to it
    # when the top-level arrays are empty.
    if not hs or not as_:
        node = match.get("node_api_data") or {}
        nhs = _int_list(node.get("home_scores"))
        nas = _int_list(node.get("away_scores"))
        if nhs or nas:
            hs, as_ = nhs, nas

    def at(arr, i):
        return arr[i] if i < len(arr) else 0

    return {
        "goals": (at(hs, 0), at(as_, 0)),
        "ht": (at(hs, 1), at(as_, 1)),
        "red": (at(hs, 2), at(as_, 2)),
        "yellow": (at(hs, 3), at(as_, 3)),
        "corners": (at(hs, 4), at(as_, 4)),
    }


def score_text(match, sport, live=None):
    """Current score as "home - away", interpreted per sport.

    For football, `live` (a detail_live entry) is authoritative when present:
    the top-level /api/matches score array is often left all-zero for
    mlive-covered matches, while detail_live carries the freshest score inside
    score[2]/score[3]."""
    if sport == SPORT_BASKETBALL:
        hs, as_ = period_scores(match)
        return f"{sum(hs)} - {sum(as_)}"
    if sport == SPORT_FOOTBALL:
        if live and live.get("goals") is not None:
            gh, ga = live["goals"]
            return f"{gh} - {ga}"
        c = football_components(match)
        return f"{c['goals'][0]} - {c['goals'][1]}"
    # Other sports (tennis/volleyball): single running value per side.
    hs, as_ = period_scores(match)
    return f"{hs[0] if hs else 0} - {as_[0] if as_ else 0}"


def half_score_text(match, sport, live=None):
    """Half-time score: football HT, basketball first half (Q1+Q2), else "".

    For football, `live` (a detail_live entry) is preferred when it carries a
    half-time score; otherwise fall back to the /api/matches score array."""
    if sport == SPORT_BASKETBALL:
        hs, as_ = period_scores(match)
        return f"{sum(hs[:2])} - {sum(as_[:2])}"
    if sport == SPORT_FOOTBALL:
        if live and live.get("ht") is not None:
            hh, ha = live["ht"]
            return f"{hh} - {ha}"
        c = football_components(match)
        return f"{c['ht'][0]} - {c['ht'][1]}"
    return ""


def format_phase(phase, kickoff=0, now=None):
    """Format a phase code + kickoff into a label with the elapsed minute.

    e.g. "1st half 34'", "2nd half 67'", "45'+2", "Halftime", "Finished".
    `kickoff` is the real kickoff (unix); when it is missing only the phase
    label is returned.
    """
    label = _PHASE_DESC.get(phase, "")
    if not label:
        return ""
    if phase in (3, 7, 8):
        return label
    if not kickoff or kickoff <= 0:
        return label
    elapsed = int(max(0, (now if now is not None else time.time()) - kickoff) // 60) + 1
    if phase == 2:
        return f"45'+{elapsed - 45}" if elapsed > 45 else f"{label} {elapsed}'"
    if phase == 4:
        minute = 45 + elapsed
        return f"90'+{minute - 90}" if minute > 90 else f"{label} {minute}'"
    if phase == 5:
        return f"{label} {90 + elapsed}'"
    if phase == 6:
        return f"{label} {105 + elapsed}'"
    return label


def _phase_desc(match, live=None, now=None):
    """Phase label for a live match, interpreted per sport.

    Football gets the half + elapsed minute (from detail_live's fresher phase
    and kickoff; `node_api_data.status_id` lags and `matchTime` can be far off).
    Other sports return "": the API exposes no period/clock for them, and
    guessing a quarter from the score array would be unreliable.
    """
    match_status = match.get("matchStatus")
    if match_status == 3:
        return "Finished"
    if match_status != 2:
        return ""
    sport = sport_of(match)
    if sport not in (SPORT_FOOTBALL, 0):
        return ""
    live = live or {}
    node = match.get("node_api_data") or {}
    phase = live.get("phase")
    if phase not in _PHASE_DESC:
        phase = node.get("status_id")
    if phase not in _PHASE_DESC:
        phase = match_status
    kickoff = live.get("kickoff") or match.get("matchTime") or 0
    return format_phase(phase, kickoff, now)


def _live_data():
    """{match_id: {"phase", "kickoff", "stats"}} from /api/match/detail_live.

    detail_live returns every in-play FOOTBALL match at once, so one request
    covers all of them. It is the freshest source: `score[1]` is the phase and
    `score[4]` the real kickoff (both used for the live minute), while `stats`
    gives shots/possession (corners and cards come from the score arrays in
    /api/matches instead). Basketball is not covered here; its quarter/score are
    derived from the /api/matches score array.
    """
    try:
        r = http_get(f"{API}/api/match/detail_live?t={int(time.time())}",
                     headers=HEADERS, timeout=20, retries=2, verify=False)
        results = r.json().get("results") or []
    except Exception as e:
        print(f"[colatv] detail_live error: {e}")
        return {}
    if not isinstance(results, list):
        return {}

    out = {}
    for item in results:
        mid = item.get("id")
        if not mid:
            continue
        info = {}

        score = item.get("score")
        if isinstance(score, list) and len(score) > 4:
            try:
                phase = int(score[1])
                if phase:
                    info["phase"] = phase
            except (TypeError, ValueError):
                pass
            try:
                kickoff = int(score[4])
                if kickoff > 0:
                    info["kickoff"] = kickoff
            except (TypeError, ValueError):
                pass

            # detail_live carries the same football score layout inside
            # score[2]/score[3], so corners and cards come from there too.
            c = football_components({"homeScore": score[2], "awayScore": score[3]})
            # Expose the freshest live goals/HT for score_text(); the top-level
            # /api/matches array is unreliable (often all-zero) for these games.
            info["goals"] = c["goals"]
            info["ht"] = c["ht"]
            stats = {
                "corners": {"home": c["corners"][0], "away": c["corners"][1]},
                "yellow_cards": {"home": c["yellow"][0], "away": c["yellow"][1]},
                "red_cards": {"home": c["red"][0], "away": c["red"][1]},
            }
            for name, code in _STAT_TYPE.items():
                for row in (item.get("stats") or []):
                    if row.get("type") == code:
                        stats[name] = {"home": row.get("home", 0), "away": row.get("away", 0)}
                        break
            info["stats"] = stats

        if info:
            out[mid] = info
    return out


def fetch_matches():
    """Return list of normalized match dicts from the colatv API."""
    try:
        r = http_get(f"{API}/api/matches", headers=HEADERS, timeout=20, retries=2, verify=False)
        data = r.json().get("data") or {}
    except Exception as e:
        print(f"[colatv] API error: {e}")
        return []
    if not isinstance(data, dict):
        return []

    now = time.time()
    has_live = any(m.get("matchStatus") == 2 for m in data.values() if isinstance(m, dict))
    live_data = _live_data() if has_live else {}

    out = []
    for slug, m in data.items():
        try:
            dt = _ts_wib(m.get("matchTime") or 0)
            match_status = m.get("matchStatus")
            is_live = match_status == 2
            status_p = _STATUS_BY_MATCH_STATUS.get(match_status, "scheduled")
            sport_id = sport_of(m)

            # Servers in preference order: the original direct feed (`videoUrl`)
            # first, then the BLV mirror anchors. URLs are used as the API gives
            # them, so a CDN host rotation needs no change here.
            streams = []
            video = (m.get("videoUrl") or "").strip()
            if video.startswith("http") and ".m3u8" in video:
                streams.append(video)
            if is_live:
                streams.extend(_anchor_stream_urls(m))

            servers = []
            seen = set()
            for stream in streams:
                for vurl in variant_stream_urls(stream):
                    purl = build_player_url(vurl)
                    if purl not in seen:
                        seen.add(purl)
                        servers.append({"url": purl, "label": "CH-NA"})

            comp = (m.get("competitionName") or "Football").strip()
            league = VI_LEAGUE_MAP.get(comp, comp)
            sport = _SPORT_BY_ID.get(m.get("sportId"), "Football")

            node = m.get("node_api_data") or {}
            live = live_data.get(node.get("match_id") or "") or {}

            match_out = {
                "id": m.get("matchId") or slug,
                "league": league,
                "team1": {"name": clean_team_name(m.get("homeTeamName") or "Home"), "logo": m.get("homeTeamLogo") or ""},
                "team2": {"name": clean_team_name(m.get("awayTeamName") or "Away"), "logo": m.get("awayTeamLogo") or ""},
                "kickoff_date": dt.strftime("%Y-%m-%d"),
                "kickoff_time": dt.strftime("%H:%M"),
                "match_date": dt.strftime("%Y-%m-%d"),
                "match_time": dt.strftime("%H:%M"),
                "status": status_p,
                "status_desc": _phase_desc(m, live, now),
                "score": score_text(m, sport_id, live) if match_status in (2, 3) else "",
                "sport": sport,
                "duration": "3.5",
                "servers": servers,
            }

            # Live/finished extras, interpreted per sport.
            if match_status in (2, 3):
                match_out["ht_score"] = half_score_text(m, sport_id, live)
                if sport_id == SPORT_BASKETBALL:
                    # Per-quarter breakdown (the API exposes no clock/period).
                    hs, as_ = period_scores(m)
                    match_out["period_scores"] = {
                        "home": hs,
                        "away": as_,
                    }
                elif sport_id in (SPORT_FOOTBALL, 0):
                    # Real kickoff (unix) so the frontend can tick the minute
                    # itself instead of waiting for the next scrape.
                    if live.get("kickoff"):
                        match_out["live_kickoff"] = live["kickoff"]
                    stats = live.get("stats")
                    if not stats:
                        c = football_components(m)
                        stats = {
                            "corners": {"home": c["corners"][0], "away": c["corners"][1]},
                            "yellow_cards": {"home": c["yellow"][0], "away": c["yellow"][1]},
                            "red_cards": {"home": c["red"][0], "away": c["red"][1]},
                        }
                    match_out["stats"] = stats

            out.append(match_out)
        except Exception:
            continue
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="colatv55.live scraper")
    ap.add_argument("--output", default="colatv.json")
    args = ap.parse_args()

    print(f"[colatv] fetching {API}/api/matches ...", flush=True)
    matches = fetch_matches()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    live = sum(1 for m in matches if m["servers"])
    total_srv = sum(len(m["servers"]) for m in matches)
    print(f"[colatv] {len(matches)} match(es) | {live} with stream | {total_srv} server(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())