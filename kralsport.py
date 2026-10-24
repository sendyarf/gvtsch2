"""
kralsportshd.com scraper ("Andro Stream" altyapisi).

Situs ini TIDAK butuh Selenium/Playwright. Semua jadwal pertandingan sudah
ter-embed sebagai JSON di dalam file JavaScript statis `script4.js` yang dimuat
homepage. Alur datanya:

    homepage (index) -> <script src="scriptX.js"> -> scriptX.js
    scriptX.js berisi variabel JS (JSON valid):
        karsilasmalar      : semua pertandingan (punya 'tarih' + 'time')
        futbolMatches      : sepak bola      (punya 'sport_key')
        basketbolMatches   : basket
        voleybolMatches    : voli
        tenisMatches       : tenis
        channels           : kanal TV 7/24   (format JS object literal)

Setiap pertandingan punya 'url' -> "event.html?id=androstreamliveXXX".
Dari analisis event.html, URL stream m3u8 dibentuk statis:

    STREAM = <base>/checklist/<stream_path>
    stream_path:
        id == "androstreamlivebs1" atau "facebooklivebs1" -> "androstreamlivekral.m3u8"
        id startswith "facebooklive"                      -> "<id>.m3u8"
        id startswith "androstreamlive"                   -> "<id>.m3u8"
        selain itu                                        -> (tidak didukung, di-skip)

<base> adalah salah satu dari beberapa domain mirror (dipakai bergantian oleh
player sebagai fallback). Semuanya sudah diverifikasi mengembalikan HTTP 200
(live HLS). Kita pilih mirror pertama yang hidup (sekali, di-cache).

Output: kralsport.json (schema sama dengan scraper lain di repo ini):
    id, league, team1{name,logo}, team2{name,logo},
    kickoff_date, kickoff_time, match_date, match_time,
    status, score, sport, duration, servers[{url,label}]

Server URL dibungkus ke player bersama: https://multi.govoet.cc/?hls=<b64>
(pola yang sama dengan soco.py / 90phut.py / colatv.py).

Zona waktu: waktu di situs adalah waktu Turki (Europe/Istanbul, UTC+3). Semua
waktu dikonversi ke Asia/Jakarta (UTC+7) agar konsisten dengan sumber lain.
"""
import argparse
import base64
import json
import re
import sys
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, parse_qs

try:
    import pytz
except ImportError:  # pragma: no cover
    print("[WARN] pytz not available - timezone conversion disabled")
    pytz = None

from http_client import http_get

# Optional POST backend (untuk streamsport365 cinema API). Samakan dengan
# backend yang dipakai http_client (curl_cffi bila ada, else requests).
try:
    from curl_cffi import requests as _cffi_req
    _HAS_CFFI = True
except Exception:  # pragma: no cover
    _cffi_req = None
    _HAS_CFFI = False

try:
    import requests as _plain_req
except Exception:  # pragma: no cover
    _plain_req = None


def http_post_json(url, payload, *, headers=None, timeout=20, retries=1):
    """POST JSON ke url; kembalikan dict hasil response atau None bila gagal.

    Dipakai khusus untuk streamsport365 cinema API. Backend mengikuti
    http_client (curl_cffi impersonasi dulu, fallback requests biasa).
    """
    body = json.dumps(payload).encode()
    hdrs = dict(headers or {})
    hdrs.setdefault("Content-Type", "application/json")

    attempt = 0
    while attempt <= retries:
        try:
            if _HAS_CFFI:
                resp = _cffi_req.post(url, data=body, headers=hdrs, timeout=timeout,
                                      impersonate="chrome")
            elif _plain_req is not None:
                resp = _plain_req.post(url, data=body, headers=hdrs, timeout=timeout)
            else:
                print("  [warn] no HTTP POST backend available", flush=True)
                return None
            if resp.status_code == 200:
                return resp.json()
            print(f"  [warn] POST {url} -> HTTP {resp.status_code}", flush=True)
        except Exception as e:
            print(f"  [warn] POST {url} error: {e}", flush=True)
        attempt += 1
        if attempt <= retries:
            time.sleep(0.6 * attempt)
    return None

# Console output must survive Turkish chars/emoji on Windows (cp1252 would crash).
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
HOME_CANDIDATES = [
    "https://kralsportshd.com/",
    "http://kralsportshd.com/",
]
# Fallback direct script path bila homepage tidak mengungkap nama file JS-nya.
SCRIPT_FALLBACK = "script4.js"

# Mirror base URLs (dipakai bergantian oleh player asli sebagai fallback).
BASE_URLS = [
    "https://andro.evrenesoglu149.click/checklist/",
    "https://andro.evrenesoglu153.click/checklist/",
    "https://andro.evrenesoglu151.click/checklist/",
    "https://andro.evrenesoglu141.click/checklist/",
]

# Stream id kanal 24/7 yang andal untuk mem-probe apakah sebuah base hidup.
PROBE_STREAM_ID = "androstreamlivebs2"

PLAYER_PREFIX = "https://multi.govoet.cc/?hls="

SRC_TZ = "Europe/Istanbul"   # waktu situs (Turki)
DST_TZ = "Asia/Jakarta"      # output (konsisten dgn scraper lain)

# sport_key di kategori -> nama sport schema bersama
SPORT_KEY_MAP = {
    "futbol": "Football",
    "basketbol": "Basketball",
    "voleybol": "Volleyball",
    "tenis": "Tennis",
}

# Keyword liga -> sport (untuk 'karsilasmalar' yang tak punya sport_key)
LEAGUE_SPORT_HINTS = [
    ("Basketball", ["nba", "basket", "euroliga", "euroleague", "eurocup", "bsl",
                    "basketbol", "wnba", "fiba"]),
    ("Volleyball", ["voleybol", "volleyball", "cev", "volley"]),
    ("Tennis",     ["wta", "atp", "tenis", "tennis", "itf", "us open", "wimbledon",
                    "roland", "davis cup"]),
    ("Football",   ["nfl"]),  # American football, tetap dikelompokkan Football
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "tr,en-US;q=0.9,en;q=0.8",
}

_active_base_cache = {"base": None, "ts": 0.0}

# --- Resolusi stream untuk id "androstreamlivech<videoId>" (match per-event) ---
# Ditemukan di favorisentv1o6.xyz/event_kral.html (host tujuan redirect untuk id
# ber-prefix "androstreamlivech"). Dua jalur:
#  1) videoId cocok ^[34]\d{7}$  -> halaman player pph.player-us.xyz yang memuat
#     <source src="https://<host>/<videoId>.m3u8">. Kita ambil m3u8-nya.
#  2) selain itu -> POST ke streamsport365.com/cinema (body AppId/VideoId/...)
#     yang membalas JSON {"URL": "<m3u8>"} (URL bertanda tangan, berumur pendek).
PPH_PLAYER_URL = "https://pph.player-us.xyz/tv/?stream_id={vid}"
SS365_ENDPOINT = "https://streamsport365.com/cinema"
SS365_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://streamsport365.com",
    "Referer": "https://streamsport365.com/",
}
_CH_VIDEOID_RE = re.compile(r'^[34]\d{7}$')




# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def clean_name(name):
    """Remove non-alphanumeric characters for ID generation."""
    return re.sub(r'[^a-zA-Z0-9]', '', name or "")


def build_player_url(stream_url):
    """Wrap a raw m3u8 URL into the shared multi.govoet.cc player (?hls=<b64>).

    Percent-encode every base64 char so URLSearchParams on the player side
    decodes it back to the exact base64 (avoids the '+' -> space bug), then
    atob() succeeds. Same approach as soco.build_player_url.
    """
    encoded = quote(base64.b64encode(stream_url.encode()).decode(), safe='')
    return f"{PLAYER_PREFIX}{encoded}"


def extract_id(url):
    """Ambil nilai query 'id' dari url event (mis. '/event.html?id=androstreamliveXX')."""
    if not url:
        return ""
    q = url.split("?", 1)[1] if "?" in url else ""
    if not q:
        return ""
    try:
        return parse_qs(q).get("id", [""])[0]
    except Exception:
        return ""


def stream_kind(stream_id):
    """Kategorikan id stream:
      'direct' -> kanal TV androstreamlive (bs/tb/...) & facebooklive: URL statis.
      'ch'     -> match per-event 'androstreamlivech<videoId>': butuh resolusi.
      None     -> tidak didukung.
    """
    if not stream_id:
        return None
    if stream_id.startswith("androstreamlivech"):
        return "ch"
    if stream_id.startswith("androstreamlive") or stream_id.startswith("facebooklive"):
        return "direct"
    return None


def stream_path_for_id(stream_id):
    """Path m3u8 statis untuk id 'direct' (replikasi getStreamPath() event.html).

    Untuk id 'ch' (match per-event) kembalikan None — URL-nya harus di-resolve
    lewat resolve_ch_stream() karena host-nya berbeda & butuh POST/parse.
    """
    if not stream_id:
        return None
    if stream_id in ("androstreamlivebs1", "facebooklivebs1"):
        return "androstreamlivekral.m3u8"
    if stream_id.startswith("facebooklive"):
        return stream_id + ".m3u8"
    if stream_id.startswith("androstreamlive") and not stream_id.startswith("androstreamlivech"):
        return stream_id + ".m3u8"
    return None


def _ch_video_id(stream_id):
    """Ekstrak videoId dari 'androstreamlivech<videoId>' / '...chstream<videoId>'."""
    return re.sub(r'^androstreamlivech(?:stream)?', '', stream_id)


def resolve_ch_stream(stream_id, timeout=20):
    """Resolve URL m3u8 untuk match 'androstreamlivech<videoId>'.

    Dua jalur (dari favorisentv1o6.xyz/event_kral.html):
      * videoId ^[34]\\d{7}$ -> ambil m3u8 dari halaman player pph.player-us.xyz.
      * selain itu           -> POST streamsport365.com/cinema, ambil data.URL.
    Mengembalikan URL m3u8 (str) atau None bila gagal.
    """
    vid = _ch_video_id(stream_id)
    if not vid:
        return None

    # Jalur 1: pola angka panjang -> player pph memuat <source src=...m3u8>
    if _CH_VIDEOID_RE.match(vid):
        try:
            r = http_get(PPH_PLAYER_URL.format(vid=vid), headers=HEADERS,
                         timeout=timeout, retries=1)
            m = re.search(r'<source[^>]+src=["\']([^"\']+\.m3u8[^"\']*)["\']',
                          r.text or "", re.I)
            if m:
                return m.group(1).strip()
        except Exception as e:
            print(f"    [ch] pph resolve gagal ({vid}): {e}", flush=True)
        # jatuh ke jalur 2 bila pph tak mengungkap m3u8
    # Jalur 2: POST ke streamsport365 cinema API
    try:
        payload = {
            "AppId": "5000", "AppVer": "1", "VpcVer": "1.0.12",
            "Language": "en", "Token": "", "VideoId": vid,
        }
        r = http_post_json(SS365_ENDPOINT, payload, headers=SS365_HEADERS,
                           timeout=timeout, retries=1)
        if r is not None:
            data = r if isinstance(r, dict) else {}
            url = (data.get("URL") or "").strip()
            if url.startswith("http"):
                return url
    except Exception as e:
        print(f"    [ch] ss365 resolve gagal ({vid}): {e}", flush=True)
    return None



def resolve_active_base():
    """Pilih mirror base pertama yang hidup (probe sekali, di-cache ~10 menit).

    Mengembalikan base string yang diakhiri '/'. Fallback ke BASE_URLS[0].
    """
    now = time.time()
    if _active_base_cache["base"] and (now - _active_base_cache["ts"]) < 600:
        return _active_base_cache["base"]

    probe_path = stream_path_for_id(PROBE_STREAM_ID)
    for base in BASE_URLS:
        try:
            r = http_get(base + probe_path, headers=HEADERS, timeout=12, retries=1)
            if r.status_code == 200 and "#EXTM3U" in (r.text or "")[:200]:
                _active_base_cache["base"] = base
                _active_base_cache["ts"] = now
                print(f"  [ok] active base: {base}", flush=True)
                return base
            print(f"  [warn] base {base} -> HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"  [warn] base {base} unreachable: {e}", flush=True)

    _active_base_cache["base"] = BASE_URLS[0]
    _active_base_cache["ts"] = now
    print(f"  [warn] no base verified, defaulting to {BASE_URLS[0]}", flush=True)
    return BASE_URLS[0]


def _split_teams(title):
    """Best-effort split judul jadi (team1, team2). Mendukung berbagai pemisah."""
    if not title:
        return "", ""
    s = title.replace("\u2013", "-").replace("\u2014", "-")
    for sep in (" -- ", " - ", " vs ", " VS ", " @ "):
        if sep in s:
            parts = s.split(sep, 1)
            t1 = parts[0].strip(" -")
            t2 = parts[1].strip(" -") if len(parts) > 1 else ""
            return t1, t2
    if "--" in s:
        parts = s.split("--", 1)
        return parts[0].strip(), parts[1].strip()
    return s.strip(), ""


def _detect_sport(league, sport_key=""):
    """Tentukan sport dari sport_key (prioritas) atau keyword liga."""
    if sport_key and sport_key in SPORT_KEY_MAP:
        return SPORT_KEY_MAP[sport_key]
    lg = (league or "").lower()
    for sport, words in LEAGUE_SPORT_HINTS:
        for w in words:
            if w in lg:
                return sport
    if "basket" in lg:
        return "Basketball"
    if "tenis" in lg or "tennis" in lg:
        return "Tennis"
    if "voley" in lg or "volley" in lg:
        return "Volleyball"
    return "Football"


def _now_src():
    """Waktu sekarang di zona sumber (Turki). Fallback naive bila pytz absen."""
    if pytz is not None:
        return datetime.now(pytz.timezone(SRC_TZ))
    return datetime.utcnow() + timedelta(hours=3)


def _to_jakarta(date_str, time_str):
    """Konversi (tanggal 'YYYY-M-D', jam 'HH:MM') zona Turki -> (date,time) Jakarta.

    Mengembalikan (kickoff_date, kickoff_time) string, atau ("", "") bila gagal.
    """
    if not time_str:
        return "", ""
    try:
        if date_str:
            y, mo, d = (int(x) for x in date_str.split("-"))
        else:
            nd = _now_src()
            y, mo, d = nd.year, nd.month, nd.day
        hh, mm = (int(x) for x in time_str.split(":"))
    except Exception:
        return "", ""

    if pytz is None:
        return _shift_naive(y, mo, d, hh, mm, hours=4)

    try:
        src = pytz.timezone(SRC_TZ)
        dst = pytz.timezone(DST_TZ)
        dt_src = src.localize(datetime(y, mo, d, hh, mm))
        dt_dst = dt_src.astimezone(dst)
        return dt_dst.strftime("%Y-%m-%d"), dt_dst.strftime("%H:%M")
    except Exception:
        return "", ""


def _shift_naive(y, mo, d, hh, mm, hours):
    """Fallback tanpa pytz: geser waktu naive sejumlah jam (handle rollover hari)."""
    dt = datetime(y, mo, d, hh, mm) + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _parse_sort_key(sort_key):
    """Ambil (date,time) dari '_sort_key' seperti '2026-10-13 00:00'."""
    if not sort_key:
        return "", ""
    m = re.match(r"(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}:\d{2})", sort_key.strip())
    if m:
        return m.group(1), m.group(2)
    return "", ""



# ------------------------------------------------------------------
# Fetch & parse
# ------------------------------------------------------------------
def fetch_home():
    """Ambil homepage yang hidup (butuh body besar sbg bukti bukan halaman blokir)."""
    for url in HOME_CANDIDATES:
        try:
            r = http_get(url, headers=HEADERS, timeout=20, retries=2)
            if r.status_code == 200 and len(r.text or "") > 3000:
                return url, r.text
        except Exception as e:
            print(f"  [warn] home {url}: {e}", flush=True)
    return None, None


def discover_script_url(home_url, home_html):
    """Temukan file JS data dari homepage (yang mengandung 'karsilasmalar').

    Homepage merujuk beberapa <script src>. Kita uji kandidat dan pilih yang
    pertama benar-benar memuat variabel 'karsilasmalar'. Fallback ke path
    statis bila tidak ada yang cocok.
    """
    candidates = []
    for m in re.finditer(r'<script[^>]+src=["\']([^"\']+\.js)["\']', home_html, re.I):
        src = m.group(1).strip()
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(home_url, src)
        elif not re.match(r'^https?://', src, re.I):
            # path relatif biasa (mis. 'script4.js') -> jadikan absolut
            src = urljoin(home_url, src)
        low = src.lower()
        # Buang yang jelas bukan data (CDN/analitik/tema)
        if any(b in low for b in ("cdn.", "waust.at", "googletagmanager",
                                  "cloudflare", "jquery", "font-awesome",
                                  "/theme.js", "email-decode")):
            continue
        if src not in candidates:
            candidates.append(src)

    for src in candidates:
        try:
            r = http_get(src, headers=HEADERS, timeout=20, retries=1)
            if r.status_code == 200 and "karsilasmalar" in (r.text or ""):
                print(f"  [ok] data script: {src} ({len(r.text)} bytes)", flush=True)
                return r.text
            print(f"  [skip] {src} (no karsilasmalar)", flush=True)
        except Exception as e:
            print(f"  [skip] {src}: {e}", flush=True)

    # Fallback: coba path statis relatif ke homepage
    fb = urljoin(home_url, SCRIPT_FALLBACK)
    try:
        r = http_get(fb, headers=HEADERS, timeout=20, retries=1)
        if r.status_code == 200 and "karsilasmalar" in (r.text or ""):
            print(f"  [ok] data script (fallback): {fb}", flush=True)
            return r.text
    except Exception as e:
        print(f"  [warn] fallback {fb}: {e}", flush=True)
    return None


def _extract_array(text, name):
    """Ekstrak isi array JS `const|var|let <name> = [ ... ]` -> string body.

    Bracket-matching yang menghormati string (agar ']' di dalam string tak
    menghentikan pencarian terlalu awal).
    """
    m = re.search(r'(?:const|var|let)\s+' + re.escape(name) + r'\s*=\s*\[', text)
    if not m:
        return None
    start = m.end() - 1  # posisi '['
    depth = 0
    in_str = False
    str_ch = ""
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == str_ch:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            str_ch = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_js_array(text, name):
    """Parse array JSON-valid (karsilasmalar/kategori) -> list of dict."""
    body = _extract_array(text, name)
    if not body:
        return []
    try:
        data = json.loads(body)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [warn] parse '{name}' gagal: {e}", flush=True)
        return []


def parse_channels(text):
    """Parse 'channels' yang berupa JS object literal (key tanpa tanda kutip)."""
    body = _extract_array(text, "channels")
    if not body:
        return []
    out = []
    for m in re.finditer(r'\{\s*title:\s*"([^"]*)"\s*,\s*url:\s*"([^"]*)"\s*\}', body):
        out.append({"title": m.group(1), "url": m.group(2)})
    return out



# ------------------------------------------------------------------
# Build matches
# ------------------------------------------------------------------
def _build_match(entry):
    """Ubah satu entri mentah jadi objek match schema bersama (atau None).

    Stream id & jenisnya disimpan sementara di field '_stream_*' untuk dibentuk
    menjadi server URL di scrape() (butuh akses jaringan untuk tipe 'ch').
    """
    title = (entry.get("title") or "").strip()
    league = (entry.get("league") or "").strip()
    url = (entry.get("url") or "").strip()

    stream_id = extract_id(url)
    kind = stream_kind(stream_id)
    if not kind:
        return None  # id tak didukung -> tak ada stream
    # untuk 'direct', hitung path statis sekarang; 'ch' di-resolve nanti.
    stream_path = stream_path_for_id(stream_id) if kind == "direct" else None
    if kind == "direct" and not stream_path:
        return None

    team1, team2 = _split_teams(title)

    # Tanggal & jam sumber (zona Turki)
    if entry.get("tarih"):
        src_date, src_time = entry.get("tarih"), entry.get("time", "")
    elif entry.get("_sort_key"):
        src_date, src_time = _parse_sort_key(entry.get("_sort_key"))
    else:
        nd = _now_src()
        src_date, src_time = nd.strftime("%Y-%m-%d"), entry.get("time", "")

    kd, kt = _to_jakarta(src_date, src_time)

    sport = _detect_sport(league, entry.get("sport_key", ""))
    is_live = bool(entry.get("live"))

    base_id = f"{clean_name(team1)}-{clean_name(team2)}" if team2 else clean_name(team1)
    match_id = base_id or clean_name(stream_id)

    return {
        "id": match_id,
        "league": league,
        "team1": {"name": team1, "logo": ""},
        "team2": {"name": team2, "logo": ""},
        "kickoff_date": kd,
        "kickoff_time": kt,
        "match_date": kd,
        "match_time": kt,
        "status": "inprogress" if is_live else "scheduled",
        "status_desc": "CANLI" if is_live else "",
        "score": "",
        "sport": sport,
        "duration": "3.5",
        "_stream_id": stream_id,     # sementara
        "_stream_kind": kind,        # sementara
        "_stream_path": stream_path,  # sementara (hanya untuk 'direct')
    }


def _dedup(matches):
    """Buang duplikat berdasarkan (team1,team2,kickoff_date,kickoff_time)."""
    seen = {}
    for m in matches:
        key = (
            m["team1"]["name"].lower(), m["team2"]["name"].lower(),
            m["kickoff_date"], m["kickoff_time"],
        )
        if key not in seen:
            seen[key] = m
    return list(seen.values())


def scrape(include_channels=False, max_matches=None):
    home_url, home_html = fetch_home()
    if not home_html:
        print("[kralsport] gagal mengambil homepage", flush=True)
        return []

    script_text = discover_script_url(home_url, home_html)
    if not script_text:
        print("[kralsport] gagal menemukan/memuat data script", flush=True)
        return []

    # Kumpulkan entri: karsilasmalar (utama) + kategori (lengkapi sport)
    raw_entries = []
    raw_entries += parse_js_array(script_text, "karsilasmalar")
    for cat in ("futbolMatches", "basketbolMatches", "voleybolMatches", "tenisMatches"):
        raw_entries += parse_js_array(script_text, cat)

    print(f"  parsed {len(raw_entries)} raw entri", flush=True)

    matches = []
    for e in raw_entries:
        m = _build_match(e)
        if m:
            matches.append(m)

    # Kanal 7/24 (opsional) — semuanya id 'direct' (kanal TV).
    if include_channels:
        for ch in parse_channels(script_text):
            stream_id = extract_id(ch.get("url", ""))
            if stream_kind(stream_id) != "direct" or not stream_path_for_id(stream_id):
                continue
            matches.append({
                "id": f"channel-{clean_name(stream_id) or clean_name(ch.get('title'))}",
                "league": "TV / 7-24",
                "team1": {"name": ch.get("title", "Kanal"), "logo": ""},
                "team2": {"name": "", "logo": ""},
                "kickoff_date": "", "kickoff_time": "",
                "match_date": "", "match_time": "",
                "status": "inprogress", "status_desc": "7/24", "score": "",
                "sport": "TV", "duration": "24",
                "_stream_id": stream_id,
                "_stream_kind": "direct",
                "_stream_path": stream_path_for_id(stream_id),
            })

    matches = _dedup(matches)
    if max_matches:
        matches = matches[:max_matches]

    # Bentuk server URL:
    #   - 'direct' (kanal TV): statis <base>/<id>.m3u8 (base sudah diverifikasi).
    #   - 'ch' (match/event): resolve lewat pph / streamsport365 (butuh jaringan).
    # Resolusi 'ch' dijalankan paralel ringan agar tidak terlalu lambat.
    active_base = resolve_active_base()

    ch_jobs = [(i, m) for i, m in enumerate(matches)
               if m.get("_stream_kind") == "ch"]
    if ch_jobs:
        print(f"  me-resolve {len(ch_jobs)} stream 'ch' (per-event)...", flush=True)

        def _resolve_job(item):
            idx, m = item
            return idx, resolve_ch_stream(m["_stream_id"])

        with ThreadPoolExecutor(max_workers=6) as ex:
            for idx, stream_url in ex.map(_resolve_job, ch_jobs):
                matches[idx]["_resolved_url"] = stream_url

    dropped = 0
    for m in matches:
        kind = m.pop("_stream_kind", None)
        sid = m.pop("_stream_id", None)
        sp = m.pop("_stream_path", None)
        if kind == "direct":
            stream_url = active_base + sp
        else:  # 'ch'
            stream_url = m.pop("_resolved_url", None)
        if not stream_url:
            m["servers"] = []
            dropped += 1
            continue
        m["servers"] = [{"url": build_player_url(stream_url), "label": "CH-NA"}]

    # Buang match tanpa server (stream gagal di-resolve) agar sch.py tidak
    # menerima entri kosong; kecuali user meminta sertakan (tidak ada di sini).
    matches = [m for m in matches if m.get("servers")]
    if dropped:
        print(f"  {dropped} match tanpa stream (gagal resolve) dibuang", flush=True)

    # Urutkan berdasarkan tanggal & jam kickoff (yang tanpa tanggal di belakang)
    matches.sort(key=lambda x: (x["kickoff_date"] or "9999", x["kickoff_time"] or "99:99"))
    return matches


def main():
    ap = argparse.ArgumentParser(description="kralsportshd.com scraper (Andro Stream)")
    ap.add_argument("--include-channels", action="store_true",
                    help="Sertakan kanal TV 7/24 (default: hanya pertandingan)")
    ap.add_argument("--max", type=int, default=None,
                    help="Batasi jumlah match yang disimpan")
    ap.add_argument("--output", default="kralsport.json", help="Nama file output")
    args = ap.parse_args()

    print("=" * 60)
    print("KRALSPORTSHD (ANDRO STREAM) SCRAPER")
    print("=" * 60)

    matches = scrape(include_channels=args.include_channels, max_matches=args.max)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)

    print(f"\nTotal: {len(matches)} match -> {args.output}")

    if matches:
        by_sport = {}
        for m in matches:
            by_sport[m.get("sport", "?")] = by_sport.get(m.get("sport", "?"), 0) + 1
        print("\nRingkasan per sport:")
        for sp, c in sorted(by_sport.items(), key=lambda x: -x[1]):
            print(f"  {sp}: {c}")
        print("\nContoh match teratas:")
        for m in matches[:8]:
            t2 = m["team2"]["name"]
            label = f"{m['team1']['name']} vs {t2}" if t2 else m["team1"]["name"]
            live = " [CANLI]" if m["status"] == "inprogress" else ""
            print(f"  - {label} | {m['league']} | "
                  f"{m['kickoff_date']} {m['kickoff_time']}{live}")
    else:
        print("(tidak ada match - cek konektivitas/struktur situs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())