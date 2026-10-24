"""
90phut.net scraper - same backend family as socolive (soco).

Both sites share the `biz.vnres.co/api/live/livingRoom` index that returns the
playable signed HLS on `pull.niur.live` (txSecret). We reuse the proven soco
helpers (base64/percent-encode player URL, host filter) and only parse this
site's homepage (classes are identical: .match-item, .blv-item-scl, .link-match).

Output: 90phut.json (same schema as other scrapers).
"""
import base64
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse, parse_qs

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from http_client import http_get

# Reuse the proven, commit-tested helpers from soco.py.
from soco import build_player_url, variant_stream_urls, _flv_to_m3u8, _is_playable_host, resolve_kickoff

HOME_CANDIDATES = ["https://www.90phut.net/", "https://90phut.net/"]
INDEX_URL = "https://biz.vnres.co/api/live/livingRoom"
PLAYER_PREFIX = "https://multi.govoet.cc/?hls="


def _find_base():
    for cand in HOME_CANDIDATES:
        try:
            r = http_get(cand, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, retries=1, verify=False)
            if r.status_code == 200 and len(r.text) > 5000:
                return cand
        except Exception:
            continue
    return None


def fetch_stream_index():
    """{blv_id: playable pull.niur.live m3u8 url} for currently-online channels."""
    try:
        r = http_get(INDEX_URL, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                     timeout=20, retries=2)
        rows = r.json()
        rows = rows if isinstance(rows, list) else (rows.get("data", []) if isinstance(rows, dict) else [])
        index = {}
        for x in rows:
            bid = str(x.get("id") or "").strip()
            stream = str(x.get("stream") or "").strip()
            if not (bid and stream.startswith("http")):
                continue
            stream = _flv_to_m3u8(stream)
            if _is_playable_host(stream):
                index[bid] = stream
        print(f"  [ok] stream index: {len(index)} playable channel(s)", flush=True)
        return index
    except Exception as e:
        print(f"  [warn] stream index unavailable: {e}", flush=True)
        return {}


def parse_matches(html, base):
    """Reuse soco's DOM selectors (identical structure on 90phut)."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        soup = None

    matches = []
    if soup is None:
        return matches

    for match_elem in soup.select(".match-item"):
        try:
            comp_el = match_elem.select_one(".match-item__comp")
            league = comp_el.get_text(strip=True) if comp_el else ""
            time_el = match_elem.select_one(".match-item__time span")
            time_text = time_el.get_text(strip=True) if time_el else ""

            home_el = match_elem.select_one(".name-home span") or match_elem.select_one(".name-home")
            away_el = match_elem.select_one(".name-away span") or match_elem.select_one(".name-away")
            home = home_el.get_text(strip=True) if home_el else "Unknown"
            away = away_el.get_text(strip=True) if away_el else "Unknown"

            link_el = match_elem.select_one("a.link-match")
            match_url = urljoin(base, link_el.get("href", "")) if link_el else ""

            blv_ids, blv_names = [], []
            for blv_elem in match_elem.select(".blv-item-scl"):
                a = blv_elem.select_one("a.dropdown-item")
                if a is None:
                    continue
                href = urljoin(base, a.get("href", ""))
                q = parse_qs(urlparse(href).query)
                if "blv" not in q:
                    continue
                span = a.select_one("span")
                blv_ids.append(q["blv"][0])
                blv_names.append(span.get_text(strip=True) if span else "")

            if not blv_ids:
                continue

            if re.match(r"^\d{2}:\d{2} \d{2}/\d{2}$", time_text):
                kickoff = resolve_kickoff(time_text)
                if kickoff:
                    match_date = kickoff.strftime("%Y-%m-%d")
                    match_time = kickoff.strftime("%H:%M")
                else:
                    match_date = match_time = ""
            else:
                match_date = match_time = ""

            matches.append({
                "match_url": match_url,
                "league": league,
                "home": home,
                "away": away,
                "match_date": match_date,
                "match_time": match_time,
                "blv_ids": blv_ids,
                "blv_names": blv_names,
            })
        except Exception:
            continue
    return matches


def scrape(base, max_matches=20):
    index = fetch_stream_index()
    print(f"[90phut] fetching {base} ...", flush=True)
    try:
        r = http_get(base, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, retries=2, verify=False)
        html = r.text
    except Exception as e:
        print(f"  [ERR] homepage: {e}", flush=True)
        return []

    matches_meta = parse_matches(html, base)
    print(f"  parsed {len(matches_meta)} match(es)", flush=True)

    out = []
    for m in matches_meta[:max_matches]:
        servers = []
        for bid, bname in zip(m["blv_ids"], m["blv_names"]):
            stream = index.get(bid)
            if not stream or not _is_playable_host(stream):
                continue
            for vurl in variant_stream_urls(stream):
                servers.append({"url": build_player_url(vurl), "label": "CH-VN"})

        if not servers:
            print(f"  {m['home']} vs {m['away']}: no stream", flush=True)
        else:
            print(f"  {m['home']} vs {m['away']}: {len(servers)} stream(s)", flush=True)

        out.append({
            "id": f"{m['home']}-{m['away']}",
            "league": m["league"],
            "team1": {"name": m["home"], "logo": ""},
            "team2": {"name": m["away"], "logo": ""},
            "kickoff_date": m["match_date"],
            "kickoff_time": m["match_time"],
            "match_date": m["match_date"],
            "match_time": m["match_time"],
            "status": "inprogress" if servers else "scheduled",
            "score": "",
            "sport": "Football",
            "duration": "3.5",
            "servers": servers,
        })
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="90phut.net scraper")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--output", default="90phut.json")
    args = ap.parse_args()

    base = _find_base()
    if not base:
        print("[90phut] no working base domain")
        return 1

    matches = scrape(base, max_matches=args.max)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)
    print(f"[90phut] {len(matches)} match(es) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())