"""
clean_mapping.py — merapikan & menata ulang manual_mapping.json per negara.

Tujuan:
  1. Deduplikasi canonical yang normalized-nya identik (Alaves/Alaves, ...).
  2. Memperbaiki entri "chained" (alias yang sebenarnya canonical lain).
  3. Menata ulang ke struktur per-negara:
         {
           "Spain":   { "team_names": {...}, "league_names": {...} },
           "Azerbaijan": {...},
           "International": {...}   # tim nasional & kompetisi multilateral
         }
  4. Menggunakan AI (GLM via ai_matcher._call_deepseek) untuk:
         - menentukan negara tiap klub (termasuk beda nama sama lintas negara),
         - menandai tim nasional / kompetisi internasional sebagai "International",
         - mengusulkan nama canonical resmi bila perlu.

AMAN: default TIDAK menimpa manual_mapping.json. Hasil ditulis ke file output
terpisah (default manual_mapping.new.json) + laporan. Pakai --apply untuk
menimpa (setelah Anda review).

Backward-compat: fungsi load_* di sch.py/ai_matcher.py/soco.py/colatv.py tetap
membaca format FLAT lama; skrip ini menghasilkan format baru DAN tetap menyediakan
pembacaan keduanya (lihat README di bawah / catatan integrasi).
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

try:
    from ai_matcher import _call_deepseek
except Exception:
    _call_deepseek = None


# ------------------------------------------------------------------
# Normalisasi (identik dengan sch.py / ai_matcher.py)
# ------------------------------------------------------------------
def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.lower()
    return re.sub(r'[^a-z0-9]', '', text)


# Konfederasi / kata kunci kompetisi multilateral -> International
INTL_LEAGUE_HINTS = [
    "uefa", "afc", "fifa", "conmebol", "concacaf", "caf ", "caf-", "world cup",
    "international", "nations league", "champions league", "europa league",
    "conference league", "libertadores", "sudamericana", "copa america",
    "euro ", "eurobasket", "euroleague", "fiba", "olymp", "club world cup",
    "asean", "afc champions", "afc cup", "world -", "friendly", "club friendly",
]

# Negara yang umum jadi "head" liga tapi sebenarnya nama konfederasi/wilayah
REGION_NOT_COUNTRY = {"africa", "asia", "europe", "america", "world", "south america",
                      "north america", "central america", "international", "oceania"}

# Kode negara (FIFA/ISO3 & singkatan umum) -> nama negara Inggris standar.
# Dipakai membaca suffix "(KAZ)"/"(Esp)"/"(USA)" pada nama tim/liga TANPA AI.
# (definisi COUNTRY_CODES ada di bawah)

# Normalisasi nama negara hasil AI -> bentuk kanonik tunggal (hindari
# 'USA' vs 'United States', 'BRAZIL' vs 'Brazil', typo, dll).
COUNTRY_ALIASES = {
    "usa": "USA", "united states": "USA", "united states of america": "USA",
    "us": "USA", "america": "USA",
    "uk": "England", "united kingdom": "England", "great britain": "England",
    "brazil": "Brazil", "brasil": "Brazil",
    "ivory coast": "Ivory Coast", "cote d ivoire": "Ivory Coast", "cote divoire": "Ivory Coast",
    "civ": "Ivory Coast",
    "uae": "UAE", "united arab emirates": "UAE",
    "south korea": "South Korea", "korea": "South Korea", "korea republic": "South Korea",
    "republic of korea": "South Korea", "kr": "South Korea",
    "north korea": "North Korea",
    "russia": "Russia", "czech republic": "Czech Republic", "czechia": "Czech Republic",
    "eastonia": "Estonia", "estonia": "Estonia",
    "swiss": "Switzerland", "switzerland": "Switzerland",
    "macao": "Macau", "macau": "Macau",
    "turkey": "Turkey", "turkiye": "Turkey",
    "vietnam": "Vietnam", "viet nam": "Vietnam",
    "saudi arabia": "Saudi Arabia",
    "bosnia": "Bosnia and Herzegovina", "bosnia and herzegovina": "Bosnia and Herzegovina",
    "macedonia": "North Macedonia", "north macedonia": "North Macedonia",
    "holland": "Netherlands", "the netherlands": "Netherlands",
    "china": "China", "pr china": "China", "prc": "China",
    "chinese taipei": "Chinese Taipei", "taiwan": "Chinese Taipei",
    "republic of ireland": "Ireland",
    "congo dr": "DR Congo", "dr congo": "DR Congo",
    "cape verde": "Cape Verde",
    "trinidad": "Trinidad and Tobago",
    "st kitts": "Saint Kitts and Nevis", "saint kitts and nevis": "Saint Kitts and Nevis",
}


def canonical_country(name):
    """Normalkan nama negara hasil AI ke bentuk kanonik (hindari duplikat grup)."""
    if not name:
        return name
    key = name.strip().lower()
    return COUNTRY_ALIASES.get(key, name.strip())


COUNTRY_CODES = {
    "aus": "Australia", "austria": "Austria", "bel": "Belgium", "belgium": "Belgium",
    "bra": "Brazil", "brazil": "Brazil", "brasil": "Brazil", "cyp": "Cyprus",
    "cyprus": "Cyprus", "den": "Denmark", "denmark": "Denmark", "eng": "England",
    "england": "England", "esp": "Spain", "spain": "Spain", "espana": "Spain",
    "fra": "France", "france": "France", "ger": "Germany", "germany": "Germany",
    "ale": "Germany", "gre": "Greece", "greece": "Greece", "ita": "Italy",
    "italy": "Italy", "kaz": "Kazakhstan", "kazakhstan": "Kazakhstan",
    "ned": "Netherlands", "netherlands": "Netherlands", "por": "Portugal",
    "portugal": "Portugal", "rus": "Russia", "russia": "Russia", "sco": "Scotland",
    "scotland": "Scotland", "sui": "Switzerland", "switzerland": "Switzerland",
    "swe": "Sweden", "sweden": "Sweden", "tur": "Turkey", "turkey": "Turkey",
    "turkiye": "Turkey", "ukr": "Ukraine", "ukraine": "Ukraine", "usa": "USA",
    "us": "USA", "arg": "Argentina", "argentina": "Argentina", "mex": "Mexico",
    "mexico": "Mexico", "col": "Colombia", "colombia": "Colombia", "chi": "Chile",
    "chile": "Chile", "uru": "Uruguay", "uruguay": "Uruguay", "par": "Paraguay",
    "per": "Peru", "ecu": "Ecuador", "bol": "Bolivia", "ven": "Venezuela",
    "sau": "Saudi Arabia", "saudi arabia": "Saudi Arabia", "qat": "Qatar",
    "qatar": "Qatar", "uae": "UAE", "egy": "Egypt", "egypt": "Egypt",
    "mar": "Morocco", "morocco": "Morocco", "alg": "Algeria", "algeria": "Algeria",
    "tun": "Tunisia", "rsa": "South Africa", "nga": "Nigeria", "nigeria": "Nigeria",
    "gha": "Ghana", "sen": "Senegal", "cmr": "Cameroon", "civ": "Ivory Coast",
    "jpn": "Japan", "japan": "Japan", "kor": "South Korea", "chn": "China",
    "china": "China", "tha": "Thailand", "thailand": "Thailand", "vie": "Vietnam",
    "vietnam": "Vietnam", "idn": "Indonesia", "indonesia": "Indonesia",
    "mas": "Malaysia", "malaysia": "Malaysia", "sin": "Singapore", "ind": "India",
    "isl": "Iceland", "iceland": "Iceland", "nor": "Norway", "norway": "Norway",
    "fin": "Finland", "pol": "Poland", "poland": "Poland", "cze": "Czech Republic",
    "czech republic": "Czech Republic", "svk": "Slovakia", "slovakia": "Slovakia",
    "hun": "Hungary", "hungary": "Hungary", "rou": "Romania", "romania": "Romania",
    "bul": "Bulgaria", "srb": "Serbia", "serbia": "Serbia", "cro": "Croatia",
    "croatia": "Croatia", "svn": "Slovenia", "slovenia": "Slovenia",
    "alb": "Albania", "albania": "Albania", "arm": "Armenia", "armenia": "Armenia",
    "aze": "Azerbaijan", "azerbaijan": "Azerbaijan", "geo": "Georgia",
    "isr": "Israel", "israel": "Israel", "wal": "Wales", "wales": "Wales",
    "irl": "Ireland", "ireland": "Ireland", "nir": "Northern Ireland",
    "northern ireland": "Northern Ireland", "new zealand": "New Zealand",
    "nz": "New Zealand", "can": "Canada", "canada": "Canada",
}




# ------------------------------------------------------------------
# Negara dari nama liga (data-driven, tanpa AI)
# ------------------------------------------------------------------
def country_from_league(league):
    """Ekstrak negara dari 'Negara - Kompetisi' / 'Negara: Kompetisi'.

    Mengembalikan:
      - nama negara (str) bila head terlihat seperti negara,
      - "International" bila head/kompetisi jelas multilateral/tim nasional,
      - None bila tak bisa dipastikan (biar AI yang menangani).
    """
    if not league:
        return None
    head = None
    for sep in (" - ", ": "):
        if sep in league:
            head = league.split(sep, 1)[0].strip()
            break
    if not head:
        # tanpa pemisah: cek hint internasional di seluruh string
        low = league.lower()
        if any(h in low for h in INTL_LEAGUE_HINTS):
            return "International"
        return None
    low = head.lower()
    if low in REGION_NOT_COUNTRY or any(h in low for h in INTL_LEAGUE_HINTS):
        return "International"
    return head


# ------------------------------------------------------------------
# Deteksi masalah (untuk laporan)
# ------------------------------------------------------------------
def detect_issues(team_names, league_names):
    """Kumpulkan semua masalah kualitas data -> dict laporan."""
    report = {"dup_canonical": [], "team_alias_collision": [],
              "league_alias_collision": [], "chained_team": [], "chained_league": []}

    # 1) Canonical dengan normalized identik (duplikat sejati)
    def find_norm_dups(mapping):
        groups = defaultdict(list)
        for k in mapping:
            groups[normalize_text(k)].append(k)
        return {n: ks for n, ks in groups.items() if len(ks) > 1}

    report["dup_canonical"] = [
        {"normalized": n, "variants": ks}
        for n, ks in find_norm_dups(team_names).items()
    ]

    # 2) Alias yang menunjuk ke >1 canonical (collision)
    def alias_collisions(mapping):
        amap = defaultdict(set)
        for canon, aliases in mapping.items():
            alist = [canon] if isinstance(aliases, str) else (aliases or [])
            for a in alist:
                if a:
                    amap[normalize_text(a)].add(canon)
        return {a: sorted(cs) for a, cs in amap.items() if len(cs) > 1}

    report["team_alias_collision"] = [
        {"normalized_alias": a, "canonicals": cs}
        for a, cs in alias_collisions(team_names).items()
    ]
    report["league_alias_collision"] = [
        {"normalized_alias": a, "canonicals": cs}
        for a, cs in alias_collisions(league_names).items()
    ]

    # 3) Chained: alias yang normalized-nya sama dengan canonical lain
    def chained(mapping):
        canon_norm = {normalize_text(k): k for k in mapping}
        out = []
        for canon, aliases in mapping.items():
            alist = [canon] if isinstance(aliases, str) else (aliases or [])
            for a in alist:
                na = normalize_text(a)
                if na in canon_norm and canon_norm[na] != canon:
                    out.append({"alias": a, "in_entry": canon,
                                "but_is_canonical": canon_norm[na]})
        return out

    report["chained_team"] = chained(team_names)
    report["chained_league"] = chained(league_names)
    return report


def merge_norm_dups(mapping):
    """Gabungkan canonical yang normalized-nya identik jadi satu entri.

    Canonical "terbaik" = varian terpanjang yang mengandung huruf non-ASCII
    (mis. 'Alaves' -> pilih 'Alaves' yang beraksen) sebagai representasi;
    semua varian + semua alias digabung (unik, urut stabil).
    Mengembalikan (mapping_baru, daftar_penggabungan).
    """
    groups = defaultdict(list)
    for k in mapping:
        groups[normalize_text(k)].append(k)

    new_map = {}
    merges = []
    for nkey, variants in groups.items():
        if len(variants) == 1:
            k = variants[0]
            new_map[k] = mapping[k]
            continue
        # pilih canonical terbaik: yang punya karakter non-ascii diutamakan,
        # lalu yang terpanjang
        def score(v):
            has_accent = any(ord(ch) > 127 for ch in v)
            return (has_accent, len(v))
        best = sorted(variants, key=score, reverse=True)[0]
        # gabung semua alias dari semua varian + varian itu sendiri
        alias_set = []
        seen = set()
        for v in variants:
            alist = [v] if isinstance(mapping[v], str) else (mapping[v] or [])
            for a in [v] + alist:
                if a and normalize_text(a) != normalize_text(best) and a not in seen:
                    seen.add(a)
                    alias_set.append(a)
        new_map[best] = alias_set
        merges.append({"merged_into": best, "from": variants})
    return new_map, merges



# ------------------------------------------------------------------
# Klasifikasi negara via AI (batch)
# ------------------------------------------------------------------
def classify_countries_ai(names, batch_size=40, cache=None, cache_file=None):
    """Petakan setiap nama (tim/kompetisi) -> negara atau 'International'/'SKIP'.

    Menggunakan GLM via ai_matcher._call_deepseek. cache: dict opsional untuk
    menghindari memanggil AI berulang untuk nama yang sama. Bila cache_file
    diberikan, cache disimpan SETIAP batch (inkremental) supaya progres tidak
    hilang bila proses terhenti — dan bisa di-resume pada run berikutnya.
    Batch yang gagal parse akan dicoba ulang sekali.
    Mengembalikan dict {nama_asli: negara_atau_"International"_atau_"SKIP"}.
    """
    result = {}
    if _call_deepseek is None:
        print("  [WARN] AI tidak tersedia — semua tak terklasifikasi.")
        return result
    if cache is None:
        cache = {}

    todo = [n for n in names if n not in cache]
    print(f"  [AI] klasifikasi {len(todo)} nama (batch {batch_size}) ...",
          flush=True)

    def _ask(batch):
        prompt = (
            "You are a football/sports data expert. For EACH entry below, output "
            "the COUNTRY it belongs to (English common short form, e.g. Spain, "
            "Azerbaijan, Brazil, England, Indonesia).\n"
            "Rules:\n"
            "1. If the entry is a NATIONAL TEAM (e.g. Brazil, Germany, France U21), "
            "output \"International\".\n"
            "2. If the entry is a MULTI-COUNTRY competition/tournament (UEFA "
            "Champions League, AFC Champions League, Copa Libertadores, World Cup, "
            "Euro, friendly/international tournaments), output \"International\".\n"
            "3. A club always maps to the country where it is based (Sabah FC -> "
            "Malaysia, Sabah FK -> Azerbaijan).\n"
            "4. If the entry is not a real club/team/competition, output \"SKIP\".\n"
            "Reply ONLY with a raw JSON object mapping each input string to its "
            "value. No markdown, no explanation.\n\n"
            "Entries: " + json.dumps(batch, ensure_ascii=False)
        )
        ans, _ = _call_deepseek(prompt)
        if not ans:
            return {}
        try:
            m = re.search(r'\{.*\}', ans, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as e:
            print(f"    [AI] gagal parse: {e}", flush=True)
        return {}

    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        parsed = _ask(batch)
        # retry sekali bila hasil kosong / tidak lengkap (mis. parse gagal)
        if len(parsed) < len(batch):
            retry = _ask(batch)
            for k, v in retry.items():
                parsed.setdefault(k, v)
        for n in batch:
            val = parsed.get(n)
            if isinstance(val, str) and val.strip():
                v = val.strip()
                result[n] = v
                cache[n] = v
            else:
                result[n] = None  # tandai tak diketahui
        # simpan cache inkremental tiap batch
        if cache_file:
            try:
                save_country_cache(cache)
            except Exception:
                pass
        print(f"    batch {i // batch_size + 1}: {len(parsed)}/{len(batch)} terpetakan",
              flush=True)
    return result


# ------------------------------------------------------------------
# Negara dari nama tim (heuristic TANPA AI: suffix "(KAZ)" dll)
# ------------------------------------------------------------------
def country_from_team_name(name):
    """Coba tebak negara dari suffix '(KODE/NEGARA)' di akhir nama tim.

    Mengembalikan nama negara (str) atau None. Sengaja HANYA dari suffix kurung
    di ujung — hindar menebak dari kata dalam nama (bikin salah, mis. klub
    'International' bisa jadi nama biasa).
    """
    if not name:
        return None
    m = re.search(r'\(([^)]+)\)\s*$', name.strip())
    if not m:
        return None
    token = m.group(1).strip().lower()
    return COUNTRY_CODES.get(token)


# ------------------------------------------------------------------
# Bangun struktur per-negara
# ------------------------------------------------------------------
def build_country_structure(team_names, league_names, use_ai=True, ai_cache=None,
                            cache_file=None):
    """Susun ulang ke {negara: {team_names, league_names}}.

    Strategi negara:
      - LIGA: dari prefix 'Negara - ' bila ada; jika tak ada -> AI; fallback
        'International' bila tampak multilateral.
      - TIM  : 1) suffix '(KODE/Negara)' (tanpa AI); 2) sisanya -> AI.
    Semua yang AI beri 'International' atau tak jelas -> grup International.
    """
    # 1) Tentukan negara untuk tiap liga
    league_country = {}
    leagues_need_ai = []
    for lg in league_names:
        c = country_from_league(lg)
        if c:
            league_country[lg] = c
        else:
            leagues_need_ai.append(lg)

    if use_ai and leagues_need_ai:
        ai_lg = classify_countries_ai(leagues_need_ai, cache=ai_cache,
                                      cache_file=cache_file)
        for lg, c in ai_lg.items():
            league_country[lg] = c or "International"
    else:
        for lg in leagues_need_ai:
            league_country[lg] = "International"

    # 2) Tentukan negara untuk tiap tim
    team_country = {}
    teams_need_ai = []
    for t in team_names:
        c = country_from_team_name(t)  # heuristic tanpa AI dulu
        if c:
            team_country[t] = c
        else:
            teams_need_ai.append(t)

    if use_ai and teams_need_ai:
        ai_team = classify_countries_ai(teams_need_ai, cache=ai_cache,
                                        cache_file=cache_file)
        for t, c in ai_team.items():
            team_country[t] = (c if c and c != "SKIP" else "International")
    else:
        for t in teams_need_ai:
            team_country[t] = "International"

    # 3) Rakit struktur (negara dinormalkan ke bentuk kanonik)
    structure = defaultdict(lambda: {"team_names": {}, "league_names": {}})
    for canon, country in team_country.items():
        c = canonical_country(country)
        structure[c]["team_names"][canon] = team_names[canon]
    for canon, country in league_country.items():
        c = canonical_country(country)
        structure[c]["league_names"][canon] = league_names[canon]
    return dict(structure)




# ------------------------------------------------------------------
# Cache AI persisten (biar run ulang murah)
# ------------------------------------------------------------------
COUNTRY_CACHE_FILE = "country_cache.json"


def load_country_cache():
    try:
        with open(COUNTRY_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_country_cache(cache):
    with open(COUNTRY_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Rapikan & tata ulang manual_mapping.json per negara (aman: dry-run default).")
    ap.add_argument("--input", default="manual_mapping.json")
    ap.add_argument("--output", default="manual_mapping.new.json")
    ap.add_argument("--report", default="mapping_report.json")
    ap.add_argument("--apply", action="store_true",
                    help="Timpa --input dengan hasil (default: tidak).")
    ap.add_argument("--no-ai", action="store_true",
                    help="Jangan panggil AI; negara dari prefix liga saja, sisanya International.")
    ap.add_argument("--no-dedup", action="store_true",
                    help="Lewati penggabungan canonical duplikat.")
    ap.add_argument("--normalize-only", action="store_true",
                    help="Hanya normalkan nama negara (gabungkan grup alias) "
                         "pada file --input yang sudah berbentuk per-negara; "
                         "tanpa AI, tanpa dedup. Cepat.")
    args = ap.parse_args()

    print("=" * 60)
    print("CLEAN & RESTRUCTURE manual_mapping.json")
    print("=" * 60)

    # --- Mode cepat: normalkan negara pada struktur yang sudah ada ---
    if args.normalize_only:
        with open(args.input, encoding="utf-8") as f:
            structure = json.load(f)
        before = len(structure)
        merged = defaultdict(lambda: {"team_names": {}, "league_names": {}})
        combine_log = []
        for country, block in structure.items():
            canon = canonical_country(country)
            if canon != country:
                combine_log.append({"from": country, "to": canon})
            merged[canon]["team_names"].update(block.get("team_names", {}))
            merged[canon]["league_names"].update(block.get("league_names", {}))
        result = dict(merged)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Normalkan negara: {before} grup -> {len(result)} grup")
        print(f"Penggabungan negara: {len(combine_log)}")
        for x in combine_log:
            print(f"  {x['from']}  ->  {x['to']}")
        print(f"Hasil -> {args.output}")
        return 0

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    team_names = data.get("team_names", {}) or {}
    league_names = data.get("league_names", {}) or {}
    print(f"Input: {len(team_names)} team canonical, {len(league_names)} league canonical")

    # --- Deteksi & lapor masalah ---
    print("\n[1/4] Mendeteksi masalah kualitas data ...")
    report = detect_issues(team_names, league_names)
    print(f"  Duplikat canonical      : {len(report['dup_canonical'])}")
    print(f"  Alias collision (tim)   : {len(report['team_alias_collision'])}")
    print(f"  Alias collision (liga)  : {len(report['league_alias_collision'])}")
    print(f"  Chained (tim)           : {len(report['chained_team'])}")
    print(f"  Chained (liga)          : {len(report['chained_league'])}")

    # --- Dedup canonical ---
    merges_team, merges_league = [], []
    if not args.no_dedup:
        print("\n[2/4] Menggabungkan canonical duplikat ...")
        team_names, merges_team = merge_norm_dups(team_names)
        league_names, merges_league = merge_norm_dups(league_names)
        print(f"  Tim: {len(merges_team)} penggabungan -> {len(team_names)} canonical")
        print(f"  Liga: {len(merges_league)} penggabungan -> {len(league_names)} canonical")
    else:
        print("\n[2/4] Dedup dilewati (--no-dedup).")

    # --- Susun per negara (AI) ---
    print("\n[3/4] Menyusun struktur per-negara ...")
    ai_cache = load_country_cache()
    structure = build_country_structure(
        team_names, league_names, use_ai=not args.no_ai, ai_cache=ai_cache,
        cache_file=COUNTRY_CACHE_FILE)
    if not args.no_ai:
        save_country_cache(ai_cache)
    countries = sorted(structure.keys())
    print(f"  {len(countries)} negara/grup terbentuk")
    intl = structure.get("International", {})
    print(f"  International: {len(intl.get('team_names', {}))} tim, "
          f"{len(intl.get('league_names', {}))} liga")

    # --- Tulis output + laporan ---
    print("\n[4/4] Menulis output ...")
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)
    print(f"  Struktur baru -> {args.output}")

    full_report = {
        "issues": report,
        "team_merges": merges_team,
        "league_merges": merges_league,
        "countries": countries,
        "country_counts": {
            c: {"teams": len(v.get("team_names", {})),
                "leagues": len(v.get("league_names", {}))}
            for c, v in structure.items()
        },
    }
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)
    print(f"  Laporan review -> {args.report}")

    if args.apply:
        with open(args.input, "w", encoding="utf-8") as f:
            json.dump(structure, f, ensure_ascii=False, indent=2)
        print(f"\n  ✅ DITERAPKAN: {args.input} telah ditimpa.")
    else:
        print(f"\n  ℹ️  DRY-RUN: {args.input} TIDAK diubah. "
              f"Review {args.output} & {args.report}, lalu jalankan ulang dengan --apply.")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

