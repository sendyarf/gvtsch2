"""
xoilacz.vip (globaldispatchespodcast.com) scraper.

Lists upcoming/live matches on the home page, then resolves each match's
playable stream URLs by fetching its match page (which embeds a `list_stream`
array of per-channel AJAX player pages) and the per-channel AJAX endpoint
(which exposes `urlStream`).

Output: xoilac.json (shared schema).
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import base64
from urllib.parse import quote

from http_client import http_get

BASE = "https://globaldispatchespodcast.com"
HOME = f"{BASE}/"
REFERER = f"{BASE}/"

_SPORT_MAP = {
    "football": "Football",
    "basketball": "Basketball",
    "tennis": "Tennis",
    "volleyball": "Volleyball",
    "lol": "Esports",
    "csgo": "Esports",
}


def _text(el):
    return el.get_text(strip=True) if el is not None else ""


def _img_src(img):
    if img is None:
        return ""
    src = img.get("data-src") or img.get("src") or ""
    if not src or src.startswith("data:"):
        return ""
    return src.strip()


def _full_url(href):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return BASE + (href if href.startswith("/") else "/" + href)


def _parse_kickoff(item):
    runtime = item.get("data-runtime")
    if runtime:
        try:
            dt = datetime.fromtimestamp(int(runtime), tz=timezone.utc) + timedelta(hours=7)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except (ValueError, TypeError, OSError):
            pass
    date_el = item.select_one(".grid-match__date")
    txt = _text(date_el)  # e.g. "08:00 - 18.10"
    m = re.match(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2})\.(\d{1,2})", txt)
    if m:
        hh, mm, dd, mo = m.groups()
        year = datetime.now().year
        try:
            dt = datetime(year, int(mo), int(dd), int(hh), int(mm))
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except ValueError:
            pass
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), "00:00"


def _extract_list_stream(html):
    m = re.search(r"var list_stream = (.*?);\s*\n\s*var stream_active_link", html, re.S)
    if not m:
        m = re.search(r"var list_stream = (.*?);", html, re.S)
    if not m:
        return []
    raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except Exception:
        # Try to fix common JS-isms (none expected, but be safe).
        try:
            data = json.loads(raw.replace("\\/", "/"))
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    return data


def _fetch_stream_url(ajax_url):
    """Fetch one per-channel AJAX player page and return its urlStream (or '')."""
    try:
        r = http_get(ajax_url, headers={"Referer": REFERER, "Accept": "text/html"}, timeout=25, retries=2)
    except Exception as e:
        print(f"    [warn] ajax fetch failed: {e}")
        return ""
    m = re.search(r'var urlStream = "(.*?)"', r.text)
    if not m:
        return ""
    return m.group(1).strip()


def build_player_url(stream_url):
    b64 = base64.b64encode(stream_url.encode()).decode()
    enc = quote(b64, safe="")
    low = stream_url.lower()
    if ".m3u8" in low or "m3u8" in low:
        return f"https://multi.govoet.cc/?hls={enc}"
    return f"https://multi.govoet.cc/?flv={enc}"


def build_iframe_url(page_url):
    """Wrap an AJAX player page URL into multi.govoet.cc iframe mode.

    Used only as a last resort: the AJAX page is protected by Cloudflare
    (X-Frame-Options/challenge), so an iframe may still fail in the browser.
    """
    b64 = base64.b64encode(page_url.encode()).decode()
    enc = quote(b64, safe="")
    return f"https://multi.govoet.cc/?iframe={enc}"


# The AJAX channel URL encodes which CDN serves the FLV stream:
#   /ajax/chanel/type/8/link/<channel> -> live2.jorvakstreamcache.com/live/<channel>.flv
#   /ajax/chanel/type/7/link/<channel> -> live1.quickscoreboardz.com/live/<channel>.flv
#   /ajax/chanel/type/5/link/<channel> -> live2.domaincdn.cc/livecdn/<channel>.flv?auth_key=...
# Type 5 needs a signed auth_key that is only exposed by the AJAX page. When
# the AJAX page is blocked by Cloudflare we cannot build that URL. Type 5
# channels are mirrored on (at least) two public CDNs, so we emit both
# candidates and let the player pick the one that works.
_FLV_CDN_BY_TYPE = {
    "8": ["https://live2.jorvakstreamcache.com/live/{channel}.flv"],
    "7": ["https://live1.quickscoreboardz.com/live/{channel}.flv"],
    "5": [
        "https://live1.quickscoreboardz.com/live/{channel}.flv",
        "https://live2.jorvakstreamcache.com/live/{channel}.flv",
    ],
}


def _derive_flv_urls(ajax_url):
    """Build candidate direct FLV URLs from an AJAX channel URL."""
    m = re.search(r"/type/(\d+)/link/([^/?#]+)", ajax_url)
    if not m:
        return []
    tmpls = _FLV_CDN_BY_TYPE.get(m.group(1))
    if not tmpls:
        return []
    channel = m.group(2).replace("-", "")
    return [t.format(channel=channel) for t in tmpls]


def fetch_streams(match_url):
    """Return list of server dicts for a match."""
    url = _full_url(match_url)
    try:
        r = http_get(url, headers={"Referer": REFERER}, timeout=30, retries=2)
    except Exception as e:
        print(f"  [warn] match page fetch failed: {e}")
        return []
    channels = _extract_list_stream(r.text)
    servers = []
    seen = set()
    for idx, channel in enumerate(channels):
        if not isinstance(channel, list) or not channel:
            continue
        ajax_url = channel[0]
        if not isinstance(ajax_url, str) or not ajax_url.startswith("http"):
            continue
        stream_url = _fetch_stream_url(ajax_url)
        derived_urls = []
        if not (stream_url and stream_url.startswith("http") and stream_url != ajax_url):
            # AJAX page blocked/unreachable -> derive FLV URLs from the
            # channel type without hitting Cloudflare.
            derived_urls = _derive_flv_urls(ajax_url)
        if derived_urls:
            for su in derived_urls:
                final_url = build_player_url(su)
                if final_url in seen:
                    continue
                seen.add(final_url)
                servers.append({"url": final_url, "label": "CH-NA"})
        elif stream_url and stream_url.startswith("http") and stream_url != ajax_url:
            # Direct media URL -> wrap as playable stream (?flv= / ?hls=).
            final_url = build_player_url(stream_url)
            if final_url not in seen:
                seen.add(final_url)
                servers.append({"url": final_url, "label": "CH-NA"})
        else:
            # Last resort: embed the AJAX player page itself.
            final_url = build_iframe_url(ajax_url)
            if final_url not in seen:
                seen.add(final_url)
                servers.append({"url": final_url, "label": "CH-NA"})
        # Be polite / avoid hammering.
        time.sleep(0.2)
    return servers


def fetch_matches():
    try:
        r = http_get(HOME, headers={"Referer": REFERER}, timeout=30, retries=2)
    except Exception as e:
        print(f"[xoilac] home fetch failed: {e}")
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select(".grid-matches__item-match")
    print(f"[xoilac] found {len(items)} match items on home page")

    out = []
    for item in items:
        try:
            sport_raw = (item.get("data-sport") or "").strip().lower()
            sport = _SPORT_MAP.get(sport_raw, sport_raw.capitalize() or "Football")

            league_el = item.select_one(".grid-match__league span")
            league = _text(league_el)

            home_el = item.select_one(".grid-match__team--home-name")
            away_el = item.select_one(".grid-match__team--away-name")
            home_team = _text(home_el) or "Home"
            away_team = _text(away_el) or "Away"

            home_logo = ""
            away_logo = ""
            home_img = item.select_one(".grid-match__team-home img")
            away_img = item.select_one(".grid-match__team-away img")
            if home_img is None:
                home_img = item.select_one(".team-logo-group-home-logo img")
            if away_img is None:
                away_img = item.select_one(".team-logo-group-away-logo img")
            home_logo = _img_src(home_img)
            away_logo = _img_src(away_img)

            kickoff_date, kickoff_time = _parse_kickoff(item)

            link_el = item.select_one("a.redirectPopup")
            match_url = link_el.get("href", "") if link_el else ""
            match_id = item.get("data-fid") or ""

            print(f"  Match: {home_team} vs {away_team} ({sport})")

            servers = fetch_streams(match_url) if match_url else []

            team1 = {"name": home_team}
            if home_logo:
                team1["logo"] = home_logo
            team2 = {"name": away_team}
            if away_logo:
                team2["logo"] = away_logo

            out.append({
                "id": match_id or match_url.strip("/").split("/")[-1],
                "league": league,
                "team1": team1,
                "team2": team2,
                "kickoff_date": kickoff_date,
                "kickoff_time": kickoff_time,
                "match_date": kickoff_date,
                "match_time": kickoff_time,
                "sport": sport,
                "duration": "3.5",
                "servers": servers,
            })
        except Exception as e:
            print(f"  [err] processing match: {e}")
            continue
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="xoilacz.vip scraper")
    ap.add_argument("--output", default="xoilac.json")
    args = ap.parse_args()

    print("=" * 60)
    print("XOILAC MATCH SCRAPER")
    print("=" * 60)

    matches = fetch_matches()

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    live = sum(1 for m in matches if m["servers"])
    total_srv = sum(len(m["servers"]) for m in matches)
    print(f"\n✅ Saved {len(matches)} matches to {args.output}")
    print(f"   {live} with streams, {total_srv} server(s) total")


if __name__ == "__main__":
    main()
