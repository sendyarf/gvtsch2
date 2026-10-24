"""
mapping_loader.py — pembacaan manual_mapping.json yang mendukung DUA format.

Format LAMA (flat):
    {
      "team_names":   { "Canonical": ["alias1", "alias2"], ... },
      "league_names": { "Canonical": ["alias1", ...], ... }
    }

Format BARU (per-negara, hasil clean_mapping.py):
    {
      "Spain":        { "team_names": {...}, "league_names": {...} },
      "Azerbaijan":   { ... },
      "International": { ... }
    }

Semua scraper (sch.py, ai_matcher.py, soco.py, colatv.py) memakai helper di sini
supaya migrasi ke format per-negara TIDAK merusak pipeline. Deteksi format
otomatis: jika root tidak punya 'team_names'/'league_names' tapi punya blok
berisi 'team_names'/'league_names' di dalamnya -> dianggap format per-negara.

Catatan: format per-negara memisahkan klub bernama sama lintas negara. Tapi
karena pipeline saat ini mencocokkan HANYA berdasarkan nama (tanpa konteks
negara per-match), helper ini tetap mengembalikan peta datar normalized->canonical.
Bila ada nama klub yang sama di 2 negara, entri yang TIDAK 'International' dan
negara-spesifik diutamakan; kalau benar-benar bentrok, yang terakhir menang
(sama seperti perilaku lama). Ini kompromi aman agar tidak ada mapping hilang.
"""
import json
import re
import unicodedata


def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.lower()
    return re.sub(r'[^a-z0-9]', '', text)


def _flatten(mapping_data):
    """Kembalikan (raw_teams, raw_leagues) dari format flat ATAU per-negara."""
    if not isinstance(mapping_data, dict):
        return {}, {}

    # Format flat (lama): ada key ini di root.
    if 'team_names' in mapping_data or 'league_names' in mapping_data:
        return (mapping_data.get('team_names', {}) or {},
                mapping_data.get('league_names', {}) or {})

    # Format per-negara (baru): gabungkan semua blok negara.
    raw_teams, raw_leagues = {}, {}
    for country, block in mapping_data.items():
        if not isinstance(block, dict):
            continue
        tn = block.get('team_names', {}) or {}
        ln = block.get('league_names', {}) or {}
        # negara spesifik diutamakan daripada International (jika bentrok nama)
        for canon, aliases in tn.items():
            if canon not in raw_teams or country != 'International':
                raw_teams[canon] = aliases
        for canon, aliases in ln.items():
            if canon not in raw_leagues or country != 'International':
                raw_leagues[canon] = aliases
    return raw_teams, raw_leagues


def build_lookups(mapping_data):
    """Bangun (norm_teams, norm_leagues): normalized_alias -> canonical.

    Mendukung nilai list ("Canonical": [aliases]) maupun string ("Alias": "Canonical").
    """
    raw_teams, raw_leagues = _flatten(mapping_data)

    def build(raw):
        out = {}
        for k, v in raw.items():
            if not k:
                continue
            if isinstance(v, list):
                canonical = k.strip()
                for alias in v:
                    if alias:
                        out[normalize_text(alias)] = canonical
            else:
                out[normalize_text(k)] = (v or '').strip()
        return out

    return build(raw_teams), build(raw_leagues)


def load_manual_mapping(path='manual_mapping.json'):
    """Muat file -> (norm_teams, norm_leagues, raw_data).

    norm_teams/norm_leagues: normalized_alias -> canonical.
    raw_data: isi JSON apa adanya (untuk keperluan lain, mis. simpan).
    File tidak ada / rusak -> ({}, {}, {"team_names": {}, "league_names": {}}).
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, {}, {"team_names": {}, "league_names": {}}
    except Exception:
        return {}, {}, {"team_names": {}, "league_names": {}}

    norm_teams, norm_leagues = build_lookups(data)
    return norm_teams, norm_leagues, data


def is_country_structure(data):
    """True bila data berformat per-negara (bukan flat)."""
    if not isinstance(data, dict):
        return False
    if 'team_names' in data or 'league_names' in data:
        return False
    # per-negara: ada minimal satu blok dict yang memuat team/league_names
    for v in data.values():
        if isinstance(v, dict) and ('team_names' in v or 'league_names' in v):
            return True
    return False


def add_alias(data, kind, canonical, alias, country="International"):
    """Tambahkan alias->canonical ke data, sesuai formatnya (idempotent).

    kind: 'team_names' atau 'league_names'.
    - Format flat: mapping[kind][canonical] = [aliases...].
    - Format per-negara: mapping[country][kind][canonical] = [aliases...].
    Mengembalikan True jika benar-benar menambah (belum ada).
    """
    if is_country_structure(data):
        block = data.setdefault(country, {}).setdefault(kind, {})
    else:
        block = data.setdefault(kind, {})

    existing = block.get(canonical)
    if isinstance(existing, list):
        if alias in existing:
            return False
        existing.append(alias)
        return True
    if isinstance(existing, str):
        if existing == alias:
            return False
        block[canonical] = [existing, alias]
        return True
    block[canonical] = [alias]
    return True


def alias_exists(data, kind, alias):
    """True bila alias sudah terpetakan (di format apa pun)."""
    raw = _flatten(data)[0] if kind == 'team_names' else _flatten(data)[1]
    for canon, aliases in raw.items():
        alist = aliases if isinstance(aliases, list) else [aliases]
        if alias in alist or alias == canon:
            return True
    return False

