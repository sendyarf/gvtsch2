"""
[DRAFT - NOT WIRED into run_all.py]

Browser-based signed HLS capture for camel1.tv with clean ad dismissal.
Kept as a reference only. camel1.tv signs with an obfuscated client-side
transform (`requestLayout`) and the embed/proxy rejects out-of-context origins,
so this is NOT a reliable source for a server-side daemon. Not registered in
run_all.py; do not enable unless the browser capture is validated on a clean IP.

Why this is needed (context):
Camel1.tv uses Tencent Cloud Live anti-leech stream signing. The playable m3u8 URL
requires:
  ?txSecret=<md5>&txTime=<hex_time>&lat=9000&auth=<md5>

This signed URL is generated dynamically inside the browser when the video player
mounts and initializes.
"""
import argparse
import base64
import json
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from playwright.sync_api import sync_playwright
from http_client import http_get

HOME = "https://www.camel1.tv/"
PLAYER_PREFIX = "https://multi.govoet.cc/?hls="


def _b64encode(url):
    return base64.b64encode(url.encode()).decode()


def _clean_team(name):
    return " ".join(p.capitalize() for p in re.split(r"[-+&]", name) if p)


def _jkt_now():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Jakarta"))


def get_live_matches():
    html = http_get(HOME, timeout=30, retries=2, verify=False).text
    out, seen = [], set()
    for m in re.finditer(r'href="(/football/([^"]+)/live/([^"/]+))"', html):
        path, slug, mid = m.group(1), m.group(2), m.group(3)
        if mid in seen:
            continue
        seen.add(mid)
        if "-vs-" in slug:
            a, b = slug.split("-vs-", 1)
            team1, team2 = _clean_team(a), _clean_team(b)
        else:
            team1 = team2 = _clean_team(slug)
        out.append({
            "path": path,
            "match_id": mid,
            "team1": {"name": team1, "logo": ""},
            "team2": {"name": team2, "logo": ""},
            "league": "Football",
        })
    return out


def _capture_signed_m3u8(page, url, total_seconds=25):
    found_signed = []

    def on_req(req):
        u = req.url
        if ".m3u8" in u.lower() and "txSecret" in u:
            print(f"      🎯 CAPTURED SIGNED HLS: {u[:110]}...", flush=True)
            found_signed.append(u)

    page.on("request", on_req)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
    except Exception as e:
        print(f"      [WARN] goto: {e}", flush=True)

    start = time.time()
    while time.time() - start < total_seconds:
        page.wait_for_timeout(2000)

        # In-page clicker: dismiss ad (class AND text based), switch to Video tab,
        # and force the player to start.
        try:
            page.evaluate("""() => {
                const CLOSE_TXT = ['close','x','×','✕','✖','✘','skip','tutup','ok','ad'];
                // 1. Remove login modal overlays
                document.querySelectorAll('div').forEach(el => {
                    if ((el.innerText || '').includes('Log in to Camel to watch')) el.style.display = 'none';
                });
                // 2. Click ALL close/skip elements (class-based)
                document.querySelectorAll('[class*="close"],[class*="skip"],[class*="dismiss"],[class*="btn-close"],[class*="mask-close"]').forEach(b => {
                    try { b.click(); } catch(e) {}
                });
                // 3. Click text-based CLOSE (the ad overlay uses <div>CLOSE</div>, no 'close' class)
                document.querySelectorAll('div,button,a,span').forEach(el => {
                    if (el.children.length > 0) return;
                    const t = (el.innerText || '').trim().toLowerCase();
                    if (CLOSE_TXT.includes(t)) { try { el.click(); } catch(e) {} }
                });
                // 4. Switch to the Video tab
                [...document.querySelectorAll('a,button,div,span')].filter(e => /^video$/i.test((e.textContent||'').trim())).slice(0,4).forEach(e => { try { e.click(); } catch(x) {} });
                // 5. Click the room play button + server options
                const playBtn = document.querySelector('#roomLiveVideo_streams_play') ||
                                document.querySelector('.roomLiveVideo-streams-play') ||
                                document.querySelector('.vjs-big-play-button') || document.querySelector('.roomLiveVideo');
                if (playBtn) { try { playBtn.click(); } catch(e) {} }
                document.querySelectorAll('[class*="roomLiveVideo-streams"] *, [class*="streams-play"]').forEach(e => { try { e.click(); } catch(x) {} });
                // 6. Force play the underlying video (it sits behind the ad)
                const v = document.querySelector('video');
                if (v) {
                    v.muted = true; try { v.play().catch(()=>{}); } catch(e) {}
                    const r = v.getBoundingClientRect();
                    const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
                    if (el) { try { el.click(); } catch(x) {} }
                }
            }""")
        except Exception:
            pass

        if found_signed:
            break

    return list(dict.fromkeys(found_signed))


def scrape_camel(matches_meta, max_matches=10, headless=True, per_match=25):
    matches = []
    now = _jkt_now()

    # Stealth flags: bypass camel1.tv's "Anonymous Proxy detected" block
    # (WebRTC IP leak) and hide Playwright's automation fingerprint.
    STEALTH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-web-security",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--use-fake-ui-for-media-stream",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--autoplay-policy=no-user-gesture-required",
        "--mute-audio",
    ]
    STEALTH_INIT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {};
    Object.defineProperty(window, 'outerWidth', { get: () => 1440 });
    Object.defineProperty(window, 'outerHeight', { get: () => 900 });
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=STEALTH_ARGS)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en",
            viewport={"width": 1440, "height": 900},
        )
        ctx.add_init_script(STEALTH_INIT)

        # Anonymous login cookie
        try:
            resp = ctx.request.post(
                "https://api.cameltv.live/account-service/login/anonymous/web?appCode=D04B29D6B957CD44DC5F9894189380B8",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data="",
            )
            det = resp.json().get("detail") or {}
            k, v = det.get("key"), det.get("value")
            if k and v:
                ctx.add_cookies([
                    {"name": k, "value": v, "domain": "api.cameltv.live", "path": "/"},
                    {"name": k, "value": v, "domain": ".cameltv.live", "path": "/"},
                ])
        except Exception:
            pass

        for idx, m in enumerate(matches_meta[:max_matches], 1):
            display = f"{m['team1']['name']} vs {m['team2']['name']}"
            print(f"\n[{idx}/{min(len(matches_meta), max_matches)}] {display} ...", flush=True)

            page = ctx.new_page()
            # Close popups on this page
            page.on("popup", lambda popup: popup.close())

            match_url = urljoin(HOME, m["path"])

            try:
                signed_hls = _capture_signed_m3u8(page, match_url, total_seconds=per_match)
            except Exception as e:
                print(f"   [ERR] capture: {e}", flush=True)
                signed_hls = []
            finally:
                try:
                    page.close()
                except Exception:
                    pass

            servers = []
            for i, hls_url in enumerate(signed_hls, 1):
                label = "CH-CAMEL-HD" if "hd" in hls_url.lower() else f"CH-CAMEL-{i}"
                servers.append({
                    "url": PLAYER_PREFIX + _b64encode(hls_url),
                    "label": label,
                })

            if servers:
                print(f"   ✅ {len(servers)} signed stream(s) captured", flush=True)
            else:
                print(f"   ⚠️  no signed stream captured", flush=True)

            matches.append({
                "id": m["match_id"],
                "league": m["league"],
                "team1": m["team1"],
                "team2": m["team2"],
                "kickoff_date": now.strftime("%Y-%m-%d"),
                "kickoff_time": now.strftime("%H:%M"),
                "match_date": now.strftime("%Y-%m-%d"),
                "match_time": now.strftime("%H:%M"),
                "status": "inprogress" if servers else "scheduled",
                "score": "",
                "sport": "Football",
                "duration": "3.5",
                "servers": servers,
            })

        browser.close()

    return matches


def main():
    ap = argparse.ArgumentParser(description="camel1.tv signed stream scraper")
    ap.add_argument("--url", default=None, help="single match URL")
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--per-match", type=int, default=25)
    ap.add_argument("--output", default="camel.json")
    args = ap.parse_args()

    print("=" * 60)
    print("CAMEL1.TV SIGNED STREAM SCRAPER")
    print("=" * 60)

    if args.url:
        m = re.match(r".*/football/([^/]+)/live/([^/?]+)", args.url)
        if not m:
            print("Invalid URL")
            return 1
        slug, mid = m.group(1), m.group(2)
        if "-vs-" in slug:
            t1, t2 = slug.split("-vs-", 1)
            t1, t2 = _clean_team(t1), _clean_team(t2)
        else:
            t1 = t2 = _clean_team(slug)
        urls = [{
            "path": f"/football/{slug}/live/{mid}",
            "match_id": mid,
            "team1": {"name": t1, "logo": ""},
            "team2": {"name": t2, "logo": ""},
            "league": "Football"
        }]
    else:
        urls = get_live_matches()
        print(f"Found {len(urls)} live match(es) on homepage\n")

    matches = scrape_camel(urls, max_matches=args.max, headless=not args.headed, per_match=args.per_match)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(matches)} match(es) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())