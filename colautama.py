"""
colatv77.live scraper - clean, reliable Vietnamese source (separate backend).

Unlike soco (flaky livingRoom index), colatv exposes a public API that returns
each match's playable HLS (`videoUrl`) DIRECTLY:

    GET https://api.cltvlv.com/api/matches
    headers: X-Domain: colatv77.live , Referer: https://colatv77.live/

Response: { "data": { "<slug>": { matchId, sportId, matchTime, matchStatus,
  homeTeamName, awayTeamName, competitionName, videoUrl, ... } } }

The stream is a signed m3u8 (auth_key) on live.ftlcbx.com / live1.ftlcbx.com.
We store it the same way as the other sources (multi.govoet.cc/?hls=<b64>) and
generate host variants so a rotated CDN host still plays.

Output: colatv.json (shared schema).
"""
import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from http_client import http_get

API = "https://api.cltvlv.com"
DOMAIN = "colatv77.live"
PLAYER_PREFIX = "https://multi.govoet.cc/?hls="

# The CDN rotates between these; the auth_key is per-stream, so the same signed
# URL is replayed across hosts as a fallback band.
STREAM_HOSTS = ["https://live.ftlcbx.com", "https://live1.ftlcbx.com"]

# colatv returns competition names in Vietnamese; map the common ones to the
# canonical English names used by the rest of the pipeline. Anything not listed
# is kept as-is (the AI matcher can translate the long tail later).
VI_LEAGUE_MAP = {
    "Giải bóng đá Hạng nhất Brasil": "Brazil - Serie B",
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
    "Giải K2 Hàn Quốc": "South Korea - K League 2",
    "Giải vô địch quốc gia Việt Nam": "Vietnam - V.League 1",
    "Asean Club Championship Shopee Cup": "AFC - ASEAN Club Championship",
    "Thái League 1": "Thailand - Thai League 1",
    "Giải vô địch Malaysia": "Malaysia - Super League",
    "UAE League": "UAE - Pro League",
    "Giải vô địch quốc gia Uzbekistan": "Uzbekistan - Super League",
    "Giải bóng đá Hạng hai Đức": "Germany - 2. Bundesliga",
}

# sportId (approx): 1 = football, basketball uses one of the higher ids.
_SPORT_BY_ID = {1: "Football", 2: "Basketball", 3: "Basketball", 4: "Tennis", 5: "Ice Hockey", 6: "Baseball", 7: "Volleyball"}

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
    """Strip auth_key to produce stable, consistent HLS URLs across known CDN hosts.

    The CDN plays the m3u8 and ts segments fine without auth_key. Stripping it
    prevents player URLs from churning on every scrape cycle.
    """
    try:
        u = urlparse(stream_url)
        if not (u.scheme in ("http", "https") and u.netloc and u.path and u.path.startswith("/live/")):
            return [stream_url.split("?")[0]]
        out = []
        orig_host = f"{u.scheme}://{u.netloc}"
        out.append(f"{orig_host}{u.path}")
        for host in STREAM_HOSTS:
            v = f"{host}{u.path}"
            if v not in out:
                out.append(v)
        return out[:2]
    except Exception:
        return [stream_url.split("?")[0]]


def _score(score_val):
    if isinstance(score_val, list) and score_val:
        return f"{score_val[0]} - {score_val[1]}" if len(score_val) > 1 else str(score_val[0])
    return ""


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

    out = []
    for slug, m in data.items():
        try:
            dt = _ts_wib(m.get("matchTime") or 0)
            status_p = "inprogress" if m.get("matchStatus") == 2 else "scheduled"
            video = (m.get("videoUrl") or "").strip()
            servers = []
            if video.startswith("http") and ".m3u8" in video:
                for vurl in variant_stream_urls(video):
                    servers.append({"url": build_player_url(vurl), "label": "CH-NA"})

            comp = (m.get("competitionName") or "Football").strip()
            league = VI_LEAGUE_MAP.get(comp, comp)
            sport = _SPORT_BY_ID.get(m.get("sportId"), "Football")

            out.append({
                "id": m.get("matchId") or slug,
                "league": league,
                "team1": {"name": m.get("homeTeamName") or "Home", "logo": m.get("homeTeamLogo") or ""},
                "team2": {"name": m.get("awayTeamName") or "Away", "logo": m.get("awayTeamLogo") or ""},
                "kickoff_date": dt.strftime("%Y-%m-%d"),
                "kickoff_time": dt.strftime("%H:%M"),
                "match_date": dt.strftime("%Y-%m-%d"),
                "match_time": dt.strftime("%H:%M"),
                "status": status_p,
                "score": _score(m.get("homeScore")) + " - " + _score(m.get("awayScore")) if m.get("homeScore") and m.get("awayScore") else "",
                "sport": sport,
                "duration": "3.5",
                "servers": servers,
            })
        except Exception:
            continue
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="colatv77.live scraper")
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