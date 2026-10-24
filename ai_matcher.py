"""
AI-Powered Team & League Name Matcher
Uses an OpenAI-compatible chat completions API (sumopod proxy -> GLM models)
to resolve unmatched team/league names and auto-update manual_mapping.json.
"""
import json
import os
import sys
import time
import re
import unicodedata
from difflib import SequenceMatcher
import requests


# Fix Windows console encoding for emoji/unicode
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass


# ============================================
# CONFIGURATION
# ============================================
# OpenAI-compatible chat completions endpoint (sumopod proxy -> GLM models).
# Override via env vars for portability; sane defaults baked in for the VPS.
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://ai.sumopod.com").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "glm-5.3-flash")
# Backwards-compatible name kept for any code/scripts referencing the old var.
DEEPSEEK_API_KEY = os.environ.get(
    "AI_API_KEY",
    os.environ.get("DEEPSEEK_API_KEY", ""),
)
# Historical alias — the model now comes from AI_MODEL (GLM via sumopod).
DEEPSEEK_MODEL = AI_MODEL
# GLM flash is a reasoning model: it spends tokens "thinking" before emitting
# the answer, so max_tokens must be generous or the JSON comes back empty.
AI_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "4096"))
BATCH_SIZE = 30  # Names per AI request
MAX_REF_NAMES = 200  # Limit reference names sent to AI (saves tokens)
AI_CACHE_FILE = "ai_mapping_cache.json"
MANUAL_MAPPING_FILE = "manual_mapping.json"



# ============================================
# NORMALIZATION (duplicated from sch.py for standalone use)
# ============================================
def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = text.lower()
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

# ============================================
# AI CACHE MANAGEMENT
# ============================================
def load_ai_cache():
    """Load previously resolved AI mappings"""
    if os.path.exists(AI_CACHE_FILE):
        try:
            with open(AI_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"team_names": {}, "league_names": {}, "_stats": {"total_resolved": 0, "last_run": ""}}

def save_ai_cache(cache):
    """Save AI cache"""
    from datetime import datetime
    cache["_stats"]["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AI_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

# ============================================
# LOAD EXISTING MAPPING
# ============================================
def load_manual_mapping():
    """Load current manual_mapping.json to know what's already mapped.

    Mendukung format flat LAMA maupun per-negara BARU (deteksi otomatis).
    Returns: (team_lookup, league_lookup, raw_data) di mana *_lookup adalah
    dict normalized_alias -> canonical_name.
    """
    try:
        from mapping_loader import load_manual_mapping as _load
        team_lookup, league_lookup, data = _load(MANUAL_MAPPING_FILE)
        # _load sudah memetakan alias->canonical; pastikan canonical juga
        # memetakan ke dirinya sendiri (perilaku lama ai_matcher).
        return team_lookup, league_lookup, data
    except Exception:
        return {}, {}, {"team_names": {}, "league_names": {}}

# ============================================
# FIND UNMATCHED NAMES
# ============================================
def collect_all_names_from_sources():
    """Collect all unique team and league names from all source JSON files"""
    source_files = [
        'bolaloca.json', 'sportsonline.json',
        'soco.json', '90phut.json', 'colatv.json', 'manual_sch.json'
    ]
    
    teams = set()
    leagues = set()
    
    for fname in source_files:
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                continue
            for match in data:
                t1 = match.get('team1', {}).get('name', '').strip()
                t2 = match.get('team2', {}).get('name', '').strip()
                lg = match.get('league', '').strip()
                if t1: teams.add(t1)
                if t2: teams.add(t2)
                if lg: leagues.add(lg)
        except:
            continue
    
    return teams, leagues

def collect_reference_names():
    """Collect canonical names from sofascore/flashscore (the 'truth' sources)"""
    ref_teams = set()
    ref_leagues = set()
    
    for fname in ['sofascore.json', 'flashscore.json']:
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                continue
            for match in data:
                t1 = match.get('team1', {}).get('name', '').strip()
                t2 = match.get('team2', {}).get('name', '').strip()
                lg = match.get('league', '').strip()
                if t1: ref_teams.add(t1)
                if t2: ref_teams.add(t2)
                if lg: ref_leagues.add(lg)
        except:
            continue
    
    return ref_teams, ref_leagues

def _make_bigrams(s):
    """Create a set of character bigrams for fast similarity pre-filtering."""
    if len(s) < 2:
        return set(s) if s else set()
    return {s[i:i+2] for i in range(len(s) - 1)}

def _bigram_similarity(bg1, bg2):
    """Fast Jaccard similarity on pre-computed bigram sets (0-100)."""
    if not bg1 or not bg2:
        return 0
    intersection = len(bg1 & bg2)
    union = len(bg1 | bg2)
    return (intersection / union) * 100

def find_unmatched_names(source_names, reference_names, existing_lookup, threshold=85):
    """
    Find names from sources that don't match any reference name 
    (either exact or via existing mapping).
    Uses bigram pre-filter for performance.
    """
    # Pre-compute normalized reference set for O(1) exact matching
    ref_normalized = {}  # norm -> original
    ref_bigrams = []  # [(norm, bigrams)]
    for ref_name in reference_names:
        norm = normalize_text(ref_name)
        if norm:
            ref_normalized[norm] = ref_name
            ref_bigrams.append((norm, _make_bigrams(norm)))
    
    unmatched = []
    
    for name in source_names:
        if not name or len(name) < 2:
            continue
        
        norm_name = normalize_text(name)
        if not norm_name:
            continue
        
        # Already in mapping?
        if norm_name in existing_lookup:
            continue
        
        # Exact match with normalized reference? (O(1))
        if norm_name in ref_normalized:
            continue
        
        # Fuzzy match with bigram pre-filter
        matched = False
        name_bigrams = _make_bigrams(norm_name)
        
        for ref_norm, ref_bg in ref_bigrams:
            # Quick length check
            if abs(len(norm_name) - len(ref_norm)) > 0.4 * max(len(norm_name), len(ref_norm)):
                continue
            # Bigram pre-filter (very fast, eliminates ~95% of candidates)
            if _bigram_similarity(name_bigrams, ref_bg) < 40:
                continue
            # Expensive SequenceMatcher only for candidates that passed pre-filter
            similarity = SequenceMatcher(None, norm_name, ref_norm).ratio() * 100
            if similarity >= threshold:
                matched = True
                break
        
        if not matched:
            unmatched.append(name)
    
    return sorted(set(unmatched))


# ============================================
# AI RESOLUTION
# ============================================
def _call_deepseek(prompt, max_tokens=None):
    """Call the OpenAI-compatible chat completions API (sumopod -> GLM).

    Kept the historical name `_call_deepseek` so callers elsewhere don't break,
    but it now targets AI_BASE_URL / AI_MODEL. Uses AI_MAX_TOKENS by default so
    the reasoning model has room to emit its final JSON answer.
    """
    if max_tokens is None:
        max_tokens = AI_MAX_TOKENS
    url = f"{AI_BASE_URL}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            res_json = response.json()
            message = res_json["choices"][0]["message"]
            content = (message.get("content") or "").strip()
            # Reasoning models may leave content empty and put text in
            # reasoning_content; fall back to it if so.
            if not content:
                content = (message.get("reasoning_content") or "").strip()
            return content, AI_MODEL
        else:
            print(f"    [ERR] AI API returned status code {response.status_code}: {response.text}")
            return None, None
    except Exception as e:
        print(f"    [ERR] AI API call failed: {e}")
        return None, None

def resolve_team_names_with_ai(unmatched_teams, reference_teams):
    """Use the AI to match unmatched team names to reference (SofaScore) names"""
    if not unmatched_teams:
        return {}
    
    # Sort reference teams for consistent context - limit to save tokens
    ref_list = sorted(list(reference_teams))[:MAX_REF_NAMES]
    
    results = {}
    batches = [unmatched_teams[i:i+BATCH_SIZE] for i in range(0, len(unmatched_teams), BATCH_SIZE)]
    
    print(f"\n[AI] Resolving {len(unmatched_teams)} unmatched team names in {len(batches)} batch(es)...")
    
    for batch_idx, batch in enumerate(batches):
        print(f"  Batch {batch_idx+1}/{len(batches)} ({len(batch)} names)...")
        
        prompt = f"""You are a sports data expert. Translate/normalize these team and sports event names to standard English.

RULES:
1. Always output in English only
2. Handle abbreviations and multi-language names (FR/ES/PT/VI/ID) and translate to English
3. Country names: translate to English (e.g. "Corée du Sud" → "South Korea", "Espagne" → "Spain")
4. For Formula 1, MotoGP, tennis tournaments, UFC and single-player events NOT in the known list: translate to clean English (e.g. "Grand Prix de Barcelone Essais libres 1" → "Spanish Grand Prix - Practice 1", "Roland Garros Double Hommes" → "French Open - Men's Doubles")
5. If the name is completely invalid or spam → "SKIP"
6. If the name matches a known team closely, return the known team name exactly

Names to match: {json.dumps(batch, ensure_ascii=False)}

Known teams (partial): {json.dumps(ref_list, ensure_ascii=False)}

Respond with ONLY a raw JSON object (no markdown). Example: {{"Gérone": "Girona", "Grand Prix de Barcelone Essais libres 1": "Spanish Grand Prix - Practice 1", "RandomSpamText": "SKIP"}}"""

        try:
            answer, model_used = _call_deepseek(prompt)
            if answer:
                # Remove code blocks if present
                clean_answer = answer.strip()
                if clean_answer.startswith("```"):
                    # Remove starting ```json or ```
                    clean_answer = re.sub(r'^```[a-zA-Z]*\s*', '', clean_answer)
                    # Remove ending ```
                    clean_answer = re.sub(r'\s*```$', '', clean_answer)
                
                json_match = re.search(r'\{.*\}', clean_answer, re.DOTALL)
                if json_match:
                    try:
                        batch_results = json.loads(json_match.group())
                        count = 0
                        for unmatched, canonical in batch_results.items():
                            if (canonical and canonical != "SKIP" and canonical != unmatched
                                    and unmatched.lower() not in ('alias', 'canonical', 'example')):
                                results[unmatched] = canonical
                                count += 1
                        print(f"    [OK] Resolved {count}/{len(batch)} ({model_used})")
                    except Exception as je:
                        print(f"    [WARN] Failed to load JSON: {je}. Raw response was:\n{answer}")
                else:
                    print(f"    [WARN] Could not parse AI response. Raw response was:\n{answer}")
            else:
                print(f"    [SKIP] AI API call failed or returned empty response")
                break  # Stop trying if API failed
                
        except Exception as e:
            print(f"    [ERR] batch {batch_idx+1}: {e}")
        
        # Rate limiting / polite delay
        if batch_idx < len(batches) - 1:
            time.sleep(1)
    
    return results

def resolve_league_names_with_ai(unmatched_leagues, reference_leagues):
    """Use the AI to match unmatched league names to canonical names"""
    if not unmatched_leagues:
        return {}
    
    ref_list = sorted(list(reference_leagues))[:MAX_REF_NAMES]
    
    results = {}
    batches = [unmatched_leagues[i:i+BATCH_SIZE] for i in range(0, len(unmatched_leagues), BATCH_SIZE)]
    
    print(f"\n[AI] Resolving {len(unmatched_leagues)} unmatched league names in {len(batches)} batch(es)...")
    
    for batch_idx, batch in enumerate(batches):
        print(f"  Batch {batch_idx+1}/{len(batches)} ({len(batch)} names)...")
        
        prompt = f"""You are a sports data expert. Translate these league/competition names to standard English format.

RULES:
1. Always output in English only — NO other language allowed in your response
2. Club league format: "Country - Competition Name" (e.g. "France - Ligue 1", "Brazil - Serie A", "Ecuador - Primera A")
3. International competitions: "World - FIFA World Cup", "Europe - UEFA Champions League", "South America - Copa Libertadores", "South America - Copa Sudamericana"
4. Friendly matches: ALWAYS use exactly "Club Friendly" (NOT "Amical club", NOT "Amistoso", NOT "Friendly Match", NOT "International Friendly", NOT "Amical")
5. Vietnamese names: translate fully ("Giải bóng đá vô địch Ecuador" → "Ecuador - Primera A", "Giải bóng đá đội tuyển dự bị nhà nghề Mỹ" → "USA - MLS Next Pro", "Giải VDQG" → translate the country)
6. French names: "Amical club" → "Club Friendly", "Amical équipes nationales" → "International Friendly"
7. Abbreviations: "BRA D1" → "Brazil - Serie A", "USA MLS" → "USA - MLS", "CON CSA" → "South America - Copa Sudamericana", "CON LIB" → "South America - Copa Libertadores", "UEFA CL" → "Europe - UEFA Champions League", "UEFA EL" → "Europe - UEFA Europa League"
8. NBA → "USA - NBA", NFL → "USA - NFL", etc.
9. Non-league/invalid/spam names → "SKIP"

Names to translate: {json.dumps(batch, ensure_ascii=False)}

Known leagues for reference: {json.dumps(ref_list, ensure_ascii=False)}

Respond with ONLY a raw JSON object (no markdown, no explanation). Example: {{"Laliga": "Spain - LaLiga", "Amical club": "Club Friendly", "Random": "SKIP"}}"""

        try:
            answer, model_used = _call_deepseek(prompt)
            if answer:
                # Remove code blocks if present
                clean_answer = answer.strip()
                if clean_answer.startswith("```"):
                    clean_answer = re.sub(r'^```[a-zA-Z]*\s*', '', clean_answer)
                    clean_answer = re.sub(r'\s*```$', '', clean_answer)
                
                json_match = re.search(r'\{.*\}', clean_answer, re.DOTALL)
                if json_match:
                    try:
                        batch_results = json.loads(json_match.group())
                        count = 0
                        for unmatched, canonical in batch_results.items():
                            if (canonical and canonical != "SKIP" and canonical != unmatched
                                    and unmatched.lower() not in ('alias', 'canonical', 'example')):
                                results[unmatched] = canonical
                                count += 1
                        print(f"    [OK] Resolved {count}/{len(batch)} ({model_used})")
                    except Exception as je:
                        print(f"    [WARN] Failed to load JSON: {je}. Raw response was:\n{answer}")
                else:
                    print(f"    [WARN] Could not parse AI response. Raw response was:\n{answer}")
            else:
                print(f"    [SKIP] AI API call failed or returned empty response")
                break
                
        except Exception as e:
            print(f"    [ERR] batch {batch_idx+1}: {e}")
        
        if batch_idx < len(batches) - 1:
            time.sleep(1)
    
    return results



# ============================================
# UPDATE MANUAL MAPPING
# ============================================
def update_manual_mapping(team_resolutions, league_resolutions, dry_run=False):
    """
    Update manual_mapping.json with AI-resolved names.
    Format-aware: mendukung file FLAT lama maupun PER-NEGARA baru (via
    mapping_loader.add_alias). Entri baru untuk tim/liga yang tak jelas
    negaranya ditaruh di grup 'International' pada format per-negara.
    """
    try:
        with open(MANUAL_MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
    except Exception:
        mapping = {"team_names": {}, "league_names": {}}

    from mapping_loader import alias_exists, add_alias

    teams_added = 0
    leagues_added = 0

    for alias, canonical in team_resolutions.items():
        if not alias or not canonical:
            continue
        if alias_exists(mapping, 'team_names', alias):
            continue
        if add_alias(mapping, 'team_names', canonical, alias):
            teams_added += 1

    for alias, canonical in league_resolutions.items():
        if not alias or not canonical:
            continue
        if alias_exists(mapping, 'league_names', alias):
            continue
        if add_alias(mapping, 'league_names', canonical, alias):
            leagues_added += 1

    if not dry_run and (teams_added > 0 or leagues_added > 0):
        with open(MANUAL_MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
            f.write('\n')
    
    return teams_added, leagues_added

# ============================================
# MAIN ENTRY POINT
# ============================================
def run_ai_matcher(dry_run=False):
    """
    Main function: find unmatched names and resolve them with AI.
    Returns tuple (team_resolutions, league_resolutions)
    """
    print("=" * 60)
    print("🤖 AI TEAM & LEAGUE NAME MATCHER")
    print("=" * 60)
    
    if not DEEPSEEK_API_KEY:
        print("⚠️  DEEPSEEK_API_KEY/AI_API_KEY not set. Skipping AI matcher.")
        return {}, {}

    # 1. Load existing mapping
    team_lookup, league_lookup, _ = load_manual_mapping()
    ai_cache = load_ai_cache()
    
    # Merge AI cache into lookup
    for alias, canonical in ai_cache.get("team_names", {}).items():
        team_lookup[normalize_text(alias)] = canonical
    for alias, canonical in ai_cache.get("league_names", {}).items():
        league_lookup[normalize_text(alias)] = canonical
    
    print(f"📋 Existing mapping: {len(team_lookup)} team aliases, {len(league_lookup)} league aliases")
    
    # 2. Collect names from sources
    source_teams, source_leagues = collect_all_names_from_sources()
    ref_teams, ref_leagues = collect_reference_names()
    
    print(f"📥 Source names: {len(source_teams)} teams, {len(source_leagues)} leagues")
    print(f"📊 Reference names: {len(ref_teams)} teams, {len(ref_leagues)} leagues")
    
    # 3. Find unmatched
    unmatched_teams = find_unmatched_names(source_teams, ref_teams, team_lookup, threshold=85)
    unmatched_leagues = find_unmatched_names(source_leagues, ref_leagues, league_lookup, threshold=85)
    
    print(f"\n❓ Unmatched: {len(unmatched_teams)} teams, {len(unmatched_leagues)} leagues")
    
    if not unmatched_teams and not unmatched_leagues:
        print("✅ All names are already matched! No AI resolution needed.")
        return {}, {}
    
    if unmatched_teams:
        print(f"\n  Unmatched teams (sample): {unmatched_teams[:10]}")
    if unmatched_leagues:
        print(f"\n  Unmatched leagues (sample): {unmatched_leagues[:10]}")
    
    # 4. Resolve with AI
    team_resolutions = resolve_team_names_with_ai(unmatched_teams, ref_teams)
    league_resolutions = resolve_league_names_with_ai(unmatched_leagues, ref_leagues)
    
    print(f"\n🎯 AI Resolved: {len(team_resolutions)} teams, {len(league_resolutions)} leagues")
    
    # 5. Show results
    if team_resolutions:
        print("\n  Team resolutions:")
        for alias, canonical in sorted(team_resolutions.items()):
            print(f"    {alias:40s} → {canonical}")
    
    if league_resolutions:
        print("\n  League resolutions:")
        for alias, canonical in sorted(league_resolutions.items()):
            print(f"    {alias:40s} → {canonical}")
    
    # 6. Update manual_mapping.json
    if not dry_run:
        teams_added, leagues_added = update_manual_mapping(team_resolutions, league_resolutions)
        print(f"\n📝 Updated manual_mapping.json: +{teams_added} team aliases, +{leagues_added} league aliases")
        
        # Update AI cache
        for alias, canonical in team_resolutions.items():
            ai_cache["team_names"][alias] = canonical
        for alias, canonical in league_resolutions.items():
            ai_cache["league_names"][alias] = canonical
        ai_cache["_stats"]["total_resolved"] += len(team_resolutions) + len(league_resolutions)
        save_ai_cache(ai_cache)
    else:
        print("\n🔍 DRY RUN - no files modified")
    
    print("\n" + "=" * 60)
    return team_resolutions, league_resolutions

# ============================================
# CLI
# ============================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI-powered team & league name matcher")
    parser.add_argument("--dry-run", action="store_true", help="Show results without updating files")
    args = parser.parse_args()
    
    run_ai_matcher(dry_run=args.dry_run)
