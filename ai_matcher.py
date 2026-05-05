"""
AI-Powered Team & League Name Matcher
Uses Groq API (free tier) with Llama models to resolve unmatched team/league names
and auto-update manual_mapping.json
"""
import json
import os
import sys
import time
import re
import unicodedata
from difflib import SequenceMatcher
from groq import Groq

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
# Automatically use environment variable if available (for GitHub Actions)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# Model priority: try smaller/faster models first to conserve token limits
GROQ_MODELS = [
    "llama-3.1-8b-instant",        # Fast, low token usage
    "llama-3.3-70b-versatile",     # Fallback: more accurate
]
BATCH_SIZE = 30  # Names per AI request
MAX_REF_NAMES = 200  # Limit reference names sent to AI (saves tokens)
AI_CACHE_FILE = "ai_mapping_cache.json"
MANUAL_MAPPING_FILE = "manual_mapping.json"

client = Groq(api_key=GROQ_API_KEY)


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
    """Load current manual_mapping.json to know what's already mapped"""
    try:
        with open(MANUAL_MAPPING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Build flat lookup: normalized_alias -> canonical_name
        team_lookup = {}
        raw_teams = data.get('team_names', {})
        for canonical, aliases in raw_teams.items():
            team_lookup[normalize_text(canonical)] = canonical
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias:
                        team_lookup[normalize_text(alias)] = canonical
            elif isinstance(aliases, str):
                team_lookup[normalize_text(aliases)] = canonical
        
        league_lookup = {}
        raw_leagues = data.get('league_names', {})
        for canonical, aliases in raw_leagues.items():
            league_lookup[normalize_text(canonical)] = canonical
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias:
                        league_lookup[normalize_text(alias)] = canonical
            elif isinstance(aliases, str):
                league_lookup[normalize_text(aliases)] = canonical
        
        return team_lookup, league_lookup, data
    except:
        return {}, {}, {"team_names": {}, "league_names": {}}

# ============================================
# FIND UNMATCHED NAMES
# ============================================
def collect_all_names_from_sources():
    """Collect all unique team and league names from all source JSON files"""
    source_files = [
        'bolaloca.json', 'streamcenter.json', 'sportsonline.json',
        'soco.json', 'manual_sch.json'
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
def _call_groq(prompt, max_tokens=4096):
    """Call Groq API with model fallback on rate limits"""
    for model in GROQ_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content.strip(), model
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str:
                print(f"    Rate limited on {model}, trying next model...")
                continue
            raise e
    return None, None

def resolve_team_names_with_ai(unmatched_teams, reference_teams):
    """Use Groq AI to match unmatched team names to reference (SofaScore) names"""
    if not unmatched_teams:
        return {}
    
    # Sort reference teams for consistent context - limit to save tokens
    ref_list = sorted(list(reference_teams))[:MAX_REF_NAMES]
    
    results = {}
    batches = [unmatched_teams[i:i+BATCH_SIZE] for i in range(0, len(unmatched_teams), BATCH_SIZE)]
    
    print(f"\n[AI] Resolving {len(unmatched_teams)} unmatched team names in {len(batches)} batch(es)...")
    
    for batch_idx, batch in enumerate(batches):
        print(f"  Batch {batch_idx+1}/{len(batches)} ({len(batch)} names)...")
        
        prompt = f"""I have team names from streaming sites. Match each to its SofaScore/Flashscore canonical name.
- Handle abbreviations, languages (FR/ES/PT/VI/ID), different spellings
- Country names -> standard English
- Non-team names (F1, AEW, tennis players) -> "SKIP"

Names to match: {json.dumps(batch, ensure_ascii=False)}

Known teams (partial): {json.dumps(ref_list, ensure_ascii=False)}

Respond with ONLY a JSON object. Example: {{"Gérone": "Girona", "F1 GP": "SKIP"}}"""

        try:
            answer, model_used = _call_groq(prompt)
            if answer:
                json_match = re.search(r'\{.*\}', answer, re.DOTALL)
                if json_match:
                    batch_results = json.loads(json_match.group())
                    count = 0
                    for unmatched, canonical in batch_results.items():
                        if (canonical and canonical != "SKIP" and canonical != unmatched
                                and unmatched.lower() not in ('alias', 'canonical', 'example')):
                            results[unmatched] = canonical
                            count += 1
                    print(f"    [OK] Resolved {count}/{len(batch)} ({model_used})")
                else:
                    print(f"    [WARN] Could not parse AI response")
            else:
                print(f"    [SKIP] All models rate limited")
                break  # Stop trying if all models are rate limited
                
        except Exception as e:
            print(f"    [ERR] batch {batch_idx+1}: {e}")
        
        # Rate limiting
        if batch_idx < len(batches) - 1:
            time.sleep(1)
    
    return results

def resolve_league_names_with_ai(unmatched_leagues, reference_leagues):
    """Use Groq AI to match unmatched league names to canonical names"""
    if not unmatched_leagues:
        return {}
    
    ref_list = sorted(list(reference_leagues))[:MAX_REF_NAMES]
    
    results = {}
    batches = [unmatched_leagues[i:i+BATCH_SIZE] for i in range(0, len(unmatched_leagues), BATCH_SIZE)]
    
    print(f"\n[AI] Resolving {len(unmatched_leagues)} unmatched league names in {len(batches)} batch(es)...")
    
    for batch_idx, batch in enumerate(batches):
        print(f"  Batch {batch_idx+1}/{len(batches)} ({len(batch)} names)...")
        
        prompt = f"""I have league names from streaming sites. Match each to standard "Country - Competition" format.
- Handle multi-language (FR/ES/PT)
- NBA -> "USA - NBA", NFL -> "USA - NFL", etc.
- Non-league names -> "SKIP"

Names to match: {json.dumps(batch, ensure_ascii=False)}

Known leagues (partial): {json.dumps(ref_list, ensure_ascii=False)}

Respond with ONLY a JSON object. Example: {{"Laliga": "Spain - LaLiga", "Random": "SKIP"}}"""

        try:
            answer, model_used = _call_groq(prompt)
            if answer:
                json_match = re.search(r'\{.*\}', answer, re.DOTALL)
                if json_match:
                    batch_results = json.loads(json_match.group())
                    count = 0
                    for unmatched, canonical in batch_results.items():
                        if (canonical and canonical != "SKIP" and canonical != unmatched
                                and unmatched.lower() not in ('alias', 'canonical', 'example')):
                            results[unmatched] = canonical
                            count += 1
                    print(f"    [OK] Resolved {count}/{len(batch)} ({model_used})")
                else:
                    print(f"    [WARN] Could not parse AI response")
            else:
                print(f"    [SKIP] All models rate limited")
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
    Format: "Canonical Name": ["Alias1", "Alias2"]
    """
    try:
        with open(MANUAL_MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
    except:
        mapping = {"team_names": {}, "league_names": {}}
    
    team_names = mapping.get('team_names', {})
    league_names = mapping.get('league_names', {})
    
    teams_added = 0
    leagues_added = 0
    
    # Process team resolutions
    for alias, canonical in team_resolutions.items():
        # Check if alias is already mapped
        already_mapped = False
        for can_name, aliases in team_names.items():
            if isinstance(aliases, list):
                if alias in aliases:
                    already_mapped = True
                    break
            elif isinstance(aliases, str) and aliases == alias:
                already_mapped = True
                break
        
        if already_mapped:
            continue
        
        # Check if canonical name already exists as a key
        if canonical in team_names:
            # Add alias to existing canonical entry
            if isinstance(team_names[canonical], list):
                if alias not in team_names[canonical]:
                    team_names[canonical].append(alias)
                    teams_added += 1
            else:
                # Convert string to list
                existing = team_names[canonical]
                team_names[canonical] = [existing, alias]
                teams_added += 1
        else:
            # Create new canonical entry
            team_names[canonical] = [alias]
            teams_added += 1
    
    # Process league resolutions
    for alias, canonical in league_resolutions.items():
        # Check if alias is already mapped
        already_mapped = False
        for can_name, aliases in league_names.items():
            if isinstance(aliases, list):
                if alias in aliases:
                    already_mapped = True
                    break
            elif isinstance(aliases, str) and aliases == alias:
                already_mapped = True
                break
        
        if already_mapped:
            continue
            
        # Check if canonical name already exists as a key
        if canonical in league_names:
            if isinstance(league_names[canonical], list):
                if alias not in league_names[canonical]:
                    league_names[canonical].append(alias)
                    leagues_added += 1
            else:
                existing = league_names[canonical]
                league_names[canonical] = [existing, alias]
                leagues_added += 1
        else:
            league_names[canonical] = [alias]
            leagues_added += 1
    
    if not dry_run and (teams_added > 0 or leagues_added > 0):
        # Sort both dictionaries alphabetically by key
        sorted_teams = dict(sorted(team_names.items(), key=lambda x: x[0].lower()))
        sorted_leagues = dict(sorted(league_names.items(), key=lambda x: x[0].lower()))
        mapping['team_names'] = sorted_teams
        mapping['league_names'] = sorted_leagues
        
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
