from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash
import json
import os
import re
import csv
import io
from datetime import datetime, timedelta
from pymongo import MongoClient
import requests
import random
from datetime import datetime
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from GitHub Pages

# Rate limiting - currently only applied to the /export/* endpoints (see below),
# since those run the heaviest, uncapped queries in the app. In-memory storage
# is fine as long as this runs as a single Render instance; if it's ever scaled
# to multiple instances this stops being per-app-wide and would need a shared
# backend (e.g. Redis) to stay accurate.
limiter = Limiter(get_remote_address, app=app, default_limits=[])

# MongoDB Configuration
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client['osrs_bingo']

# ============================================
# MULTI-TENANT SYSTEM
# ============================================

# Tenants collection
tenants_collection = db['tenants']

# Default tenant (your personal board - backward compatibility)
DEFAULT_TENANT_ID = 'unsociables_001'

# Legacy collections (kept for backward compatibility during transition)
bingo_collection = db['bingo_board']
history_collection = db['drop_history']
deaths_collection = db['deaths']
rank_history_collection = db['rank_history']


def get_tenant_by_id(tenant_id):
    """Get tenant document by ID"""
    return tenants_collection.find_one({'tenant_id': tenant_id})


def get_tenant_by_api_key(api_key):
    """Get tenant by API key"""
    return tenants_collection.find_one({'api_key': api_key})


def get_tenant_by_subdomain(subdomain):
    """Get tenant by subdomain"""
    return tenants_collection.find_one({'subdomain': subdomain.lower()})


def get_tenant_from_request():
    """
    Identify tenant from the current request, for read access and as the
    "which tenant is this browser talking to" starting point for admin
    actions (see verify_admin_password below).
    Priority: API key header > subdomain > default tenant

    Deliberately does NOT trust a `?tenant_id=` query param: that's an
    unauthenticated field anyone can set to any value, so honoring it here
    let any request impersonate any tenant on every endpoint that used this
    for its identity. Reads are public data by design, so browsers/scripts
    without a matching Origin or API key just fall through to the default
    tenant. Endpoints that actually change data must not rely on this
    function alone - see get_authenticated_tenant_by_api_key/
    get_authenticated_tenant/verify_admin_password for the write path.
    """
    # Check for API key in header
    api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization')
    if api_key:
        if api_key.startswith('Bearer '):
            api_key = api_key[7:]
        tenant = get_tenant_by_api_key(api_key)
        if tenant:
            return tenant

    # Check for subdomain in Origin/Referer header
    origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
    if origin:
        # Extract subdomain from origin (e.g., "https://unsociables.osrsbingo.com")
        import re
        match = re.search(r'https?://([^.]+)\.', origin)
        if match:
            subdomain = match.group(1)
            if subdomain not in ['www', 'api']:
                tenant = get_tenant_by_subdomain(subdomain)
                if tenant:
                    return tenant

    # Default to your personal tenant (backward compatibility)
    return get_tenant_by_id(DEFAULT_TENANT_ID)


def verify_admin_password(tenant, password):
    """
    Check a submitted admin password against the given tenant's own
    credential. A tenant gets its own hashed password once one is set via
    manage_tenant_credentials.py; until then this falls back to the single
    global ADMIN_PASSWORD env var, so the existing deployment keeps working
    without a forced migration step. Once every tenant has its own hash,
    the global fallback stops being reachable.
    """
    if not tenant or not password:
        return False
    pw_hash = tenant.get('admin_password_hash')
    if pw_hash:
        return check_password_hash(pw_hash, password)
    return password == ADMIN_PASSWORD


def get_authenticated_tenant_by_api_key():
    """
    Strict tenant resolution for bot/automation writes: the tenant is
    identified ONLY by a valid X-API-Key/Authorization header matching that
    tenant's own stored api_key - never by an Origin header or a tenant_id
    query param, both of which a non-browser client can set to anything.
    Returns the tenant dict, or None if no valid key was supplied (caller
    should respond 401).
    """
    api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization')
    if not api_key:
        return None
    if api_key.startswith('Bearer '):
        api_key = api_key[7:]
    if not api_key:
        return None
    return get_tenant_by_api_key(api_key)


def get_authenticated_tenant():
    """
    Combined auth for endpoints triggered by BOTH automation (a valid
    tenant API key) and the admin UI (a valid admin password) - e.g. the
    "fetch KC now" button, which a scheduled GitHub Action also hits.
    Tries the API key first, then falls back to a password checked against
    the tenant resolved from the request (Origin subdomain, or default).
    """
    tenant = get_authenticated_tenant_by_api_key()
    if tenant:
        return tenant
    data = request.get_json(silent=True) or {}
    password = data.get('password') or request.args.get('password')
    candidate = get_tenant_from_request()
    if verify_admin_password(candidate, password):
        return candidate
    return None


# Collections are queried with .sort('timestamp', ...) (and sometimes filtered
# by player) all over this file - without an index that's a full collection
# scan plus an in-memory sort on every request, which gets slow (and on
# Atlas's free M0 tier, can hit its 32MB in-memory sort limit) as history grows.
# Indexes are created lazily, once per tenant per process, the first time that
# tenant's collections are touched - avoids a separate migration step while
# keeping these queries fast. create_index() is a no-op if the index already
# exists, so this is safe to (rarely) call more than once.
_indexed_tenant_subdomains = set()


def _ensure_tenant_indexes(collections, subdomain):
    if subdomain in _indexed_tenant_subdomains:
        return
    try:
        collections['history'].create_index([('timestamp', -1)])
        collections['history'].create_index([('player', 1)])
        collections['deaths'].create_index([('timestamp', -1)])
        collections['deaths'].create_index([('player', 1)])
        collections['rank_history'].create_index([('timestamp', -1)])
        collections['kc'].create_index([('player', 1), ('timestamp', -1)])
        collections['personal_bests'].create_index([('player', 1), ('boss', 1)])
        collections['personal_bests'].create_index([('time_seconds', 1)])
        _indexed_tenant_subdomains.add(subdomain)
    except Exception as e:
        print(f"[!] Failed to create indexes for tenant '{subdomain}': {e}")


def get_tenant_collections(tenant_id=None):
    """
    Get MongoDB collections for a specific tenant.
    Returns dict with all tenant-specific collections.
    """
    if tenant_id is None:
        tenant = get_tenant_from_request()
        tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID

    # Get tenant subdomain for collection naming
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        # Fallback to default tenant
        tenant = get_tenant_by_id(DEFAULT_TENANT_ID)

    subdomain = tenant['subdomain'] if tenant else 'unsociables'

    collections = {
        'bingo': db[f'tenant_{subdomain}_bingo'],
        'history': db[f'tenant_{subdomain}_history'],
        'deaths': db[f'tenant_{subdomain}_deaths'],
        'rank_history': db[f'tenant_{subdomain}_rank_history'],
        'kc': db[f'tenant_{subdomain}_kc'],
        'personal_bests': db[f'tenant_{subdomain}_personal_bests'],
        'archive': db[f'tenant_{subdomain}_archive'],
        'gained_cache': db[f'tenant_{subdomain}_gained_cache'],
        'collection_log_cache': db[f'tenant_{subdomain}_collection_log_cache']
    }
    _ensure_tenant_indexes(collections, subdomain)
    return collections


def parse_rarity_denominator(raw):
    """
    Extract the numeric denominator from Dink's "Item Rarity"/"Rank" field text,
    e.g. '```\\n1 in 12.8 (7.81%)\\n```' -> 12.8. Returns None if unparseable/absent.
    Higher value = rarer.
    """
    if not raw:
        return None
    match = re.search(r'1\s*in\s*([\d,]+(?:\.\d+)?)', raw, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', ''))
    except ValueError:
        return None


def check_tenant_feature(tenant, feature):
    """Check if tenant has access to a specific feature"""
    if not tenant:
        return False

    # Owner plan has all features
    if tenant.get('plan') == 'owner':
        return True

    # Check settings
    settings = tenant.get('settings', {})
    features = settings.get('features', [])

    return 'all' in features or feature in features


# ============================================
# END MULTI-TENANT SYSTEM
# ============================================

# Fallback to file-based storage if MongoDB not available
USE_MONGODB = True
try:
    # Test MongoDB connection
    mongo_client.admin.command('ping')
    print("[OK] Connected to MongoDB")

    # Check if default tenant exists
    default_tenant = get_tenant_by_id(DEFAULT_TENANT_ID)
    if default_tenant:
        print(f"[OK] Default tenant: {default_tenant['name']} ({DEFAULT_TENANT_ID})")
    else:
        print(f"[!] Default tenant not found - run migrate_to_tenant.py first!")

except Exception as e:
    print(f"[!] MongoDB not available, falling back to file storage: {e}")
    USE_MONGODB = False
    BINGO_FILE = '/data/bingo_data.json' if os.path.exists('/data') else 'bingo_data.json'

# Configuration
# ADMIN_PASSWORD is the legacy global fallback verify_admin_password() uses
# for any tenant that hasn't been given its own admin_password_hash yet (see
# manage_tenant_credentials.py). DROP_API_KEY is no longer checked directly
# anywhere - each tenant's own 'api_key' field is what get_tenant_by_api_key
# matches against - but it's kept here because it's still the value
# migrate_to_tenant.py seeds new/legacy tenants' api_key with, and the value
# DinkParser.py/fetch_gim_data.py send as X-API-Key.
ADMIN_PASSWORD = os.environ.get('BINGO_ADMIN_PASSWORD', 'bingo2025')
DROP_API_KEY = os.environ.get('DROP_API_KEY', 'your_secret_drop_key_here')

# groupiron.men (the group's own GIM tracker, fed by the Collection Log
# RuneLite plugin) - see fetch_groupironmen_collection_log. Not tenant-aware
# like the rest of this file; only used to supplement the All Time luck calc
# for this one deployment's group, so a single global credential is enough.
GROUPIRONMEN_TOKEN = os.environ.get('GROUPIRONMEN_TOKEN', '')
GROUPIRONMEN_GROUP_NAME = os.environ.get('GROUPIRONMEN_GROUP_NAME', 'Unsociables')

print(
    f"🔐 Fallback admin password is set {'from environment variable' if os.environ.get('BINGO_ADMIN_PASSWORD') else 'to default (change this!)'} (only used by tenants without their own admin_password_hash)")
print(
    f"🔑 Legacy drop API key env var is set {'from environment variable' if os.environ.get('DROP_API_KEY') else 'to default (change this!)'} (only relevant as the seed value for tenants' own api_key)")
print()


# Bosses excluded from all tracking and display
WOM_EXCLUDED_BOSSES = {'Brutus'}

# WiseOldMan uses different keys for bosses - map them to our display format.
# Shared between fetch_osrs_highscores (current KC) and fetch_wom_gained
# (KC gained over a date range) so both resolve the same metric to the same
# display name.
WOM_BOSS_MAPPING = {
    'abyssal_sire': 'Abyssal Sire',
    'alchemical_hydra': 'Alchemical Hydra',
    'amoxliatl': 'Amoxliatl',
    'araxxor': 'Araxxor',
    'artio': 'Artio',
    'barrows_chests': 'Barrows Chests',
    'bryophyta': 'Bryophyta',
    'callisto': 'Callisto',
    'calvarion': "Cal'varion",
    'cerberus': 'Cerberus',
    'chambers_of_xeric': 'Chambers of Xeric',
    'chambers_of_xeric_challenge_mode': 'Chambers of Xeric: Challenge Mode',
    'chaos_elemental': 'Chaos Elemental',
    'chaos_fanatic': 'Chaos Fanatic',
    'commander_zilyana': 'Commander Zilyana',
    'corporeal_beast': 'Corporeal Beast',
    'crazy_archaeologist': 'Crazy Archaeologist',
    'dagannoth_prime': 'Dagannoth Prime',
    'dagannoth_rex': 'Dagannoth Rex',
    'dagannoth_supreme': 'Dagannoth Supreme',
    'deranged_archaeologist': 'Deranged Archaeologist',
    'doom_of_mokhaiotl': 'Doom of Mokhaiotl',
    'duke_sucellus': 'Duke Sucellus',
    'general_graardor': 'General Graardor',
    'giant_mole': 'Giant Mole',
    'grotesque_guardians': 'Grotesque Guardians',
    'hespori': 'Hespori',
    'kalphite_queen': 'Kalphite Queen',
    'king_black_dragon': 'King Black Dragon',
    'kraken': 'Kraken',
    'kreearra': "Kree'Arra",
    'kril_tsutsaroth': "K'ril Tsutsaroth",
    'lunar_chests': "Moons",
    'mimic': 'Mimic',
    'nex': 'Nex',
    'nightmare': 'Nightmare',
    'phosanis_nightmare': "Phosani's Nightmare",
    'obor': 'Obor',
    'phantom_muspah': 'Phantom Muspah',
    'sarachnis': 'Sarachnis',
    'scorpia': 'Scorpia',
    'scurrius': 'Scurrius',
    'skotizo': 'Skotizo',
    'shellbane_gryphon': 'Shellbane Gryphon',
    'sol_heredit': 'Sol Heredit',
    'spindel': 'Spindel',
    'tempoross': 'Tempoross',
    'the_gauntlet': 'The Gauntlet',
    'the_corrupted_gauntlet': 'The Corrupted Gauntlet',
    'the_hueycoatl': 'The Hueycoatl',
    'the_leviathan': 'The Leviathan',
    'the_whisperer': 'The Whisperer',
    'the_royal_titans': 'Royal Titans',
    'theatre_of_blood': 'Theatre of Blood',
    'theatre_of_blood_hard_mode': 'Theatre of Blood: Hard Mode',
    'thermonuclear_smoke_devil': 'Thermonuclear Smoke Devil',
    'tombs_of_amascut': 'Tombs of Amascut',
    'tombs_of_amascut_expert': 'Tombs of Amascut: Expert Mode',
    'tzkal_zuk': 'TzKal-Zuk',
    'tztok_jad': 'TzTok-Jad',
    'vardorvis': 'Vardorvis',
    'venenatis': 'Venenatis',
    'vetion': "Vet'ion",
    'vorkath': 'Vorkath',
    'wintertodt': 'Wintertodt',
    'yama': 'Yama',
    'zalcano': 'Zalcano',
    'zulrah': 'Zulrah'
}


def fetch_osrs_highscores(player_name):
    """Fetch player's KC from WiseOldMan API - returns (kc_data, debug_log)"""
    debug = []

    try:
        # WiseOldMan API endpoint
        url = f"https://api.wiseoldman.net/v2/players/{player_name.replace(' ', '_')}"
        debug.append(f"🌐 Fetching from WiseOldMan: {url}")

        headers = {
            'User-Agent': 'OSRS-Bingo-Tracker/1.0'
        }

        response = requests.get(url, headers=headers, timeout=10)
        debug.append(f"📡 HTTP Status: {response.status_code}")

        if response.status_code == 404:
            debug.append(f"⚠️ Player not tracked on WiseOldMan yet")
            debug.append(f"💡 Players need to be added to WiseOldMan first")
            return None, debug

        if response.status_code != 200:
            debug.append(f"❌ Error: {response.text[:200]}")
            return None, debug

        data = response.json()
        debug.append(f"✅ Got player data")

        # DEBUG: Log what keys we actually got
        debug.append(f"🔍 Response keys: {list(data.keys())[:10]}")

        # Extract boss KC from latestSnapshot
        if 'latestSnapshot' not in data:
            debug.append(f"⚠️ No 'latestSnapshot' key in response")
            debug.append(f"Available keys: {list(data.keys())}")
            return None, debug

        if 'data' not in data['latestSnapshot']:
            debug.append(f"⚠️ No 'data' key in latestSnapshot")
            debug.append(f"latestSnapshot keys: {list(data['latestSnapshot'].keys())}")
            return None, debug

        snapshot_data = data['latestSnapshot']['data']
        debug.append(f"🔍 Snapshot data keys: {list(snapshot_data.keys())}")

        # Boss data is inside the 'bosses' key!
        if 'bosses' not in snapshot_data:
            debug.append(f"⚠️ No 'bosses' key in snapshot data")
            return None, debug

        bosses_data = snapshot_data['bosses']
        debug.append(f"🔍 Bosses data keys (first 10): {list(bosses_data.keys())[:10]}")

        # DEBUG: Check what one boss entry looks like
        if 'zulrah' in bosses_data:
            debug.append(f"🔍 Sample (zulrah): {bosses_data['zulrah']}")
        elif len(bosses_data) > 0:
            first_key = list(bosses_data.keys())[0]
            debug.append(f"🔍 Sample ({first_key}): {bosses_data[first_key]}")

        boss_data = {}

        # Extract KC from snapshot - iterate WiseOldMan's full response so new bosses
        # are picked up automatically without needing a code change.
        # The mapping overrides display names for special cases (apostrophes, abbreviations);
        # anything not in the mapping gets an auto-derived name (underscores → title case).
        for wom_key, boss_value in bosses_data.items():
            kc = boss_value.get('kills', 0)
            if not kc or kc <= 0:
                continue
            display_name = WOM_BOSS_MAPPING.get(wom_key) or wom_key.replace('_', ' ').title()
            if display_name in WOM_EXCLUDED_BOSSES:
                continue
            boss_data[display_name] = kc

        debug.append(f"✅ Found {len(boss_data)} bosses with KC > 0")
        if boss_data:
            sample = list(boss_data.items())[:3]
            debug.append(f"Sample: {sample}")

        return (boss_data if boss_data else None), debug

    except Exception as e:
        debug.append(f"💥 Exception: {type(e).__name__}: {str(e)}")
        return None, debug


def fetch_wom_gained(player_name, start_date, end_date):
    """
    Fetch a player's KC gained per boss over an exact date range, straight
    from WiseOldMan's own /gained endpoint - which computes the delta from
    WOM's own historical snapshot data, not from two single snapshots we
    captured ourselves.

    This replaces diffing our own 'start' vs 'current' KC snapshots, which
    turned out to be unreliable in multiple ways: a boss can be missing
    from our 'start' snapshot entirely (defaulting the gain to the
    player's whole lifetime KC instead of 0), or our 'start' snapshot can
    simply have been captured later than intended (showing 0 gained when
    real gains happened before it was taken). WOM's own numbers aren't
    subject to either failure mode.

    Returns {display_name: {'start': int, 'end': int, 'gained': int}, ...},
    or (None, debug_log) on failure. A boss WOM reports as unranked (its
    "-1" sentinel for kills it doesn't track a leaderboard rank for) is
    skipped rather than guessed at.
    """
    debug = []
    try:
        url = f"https://api.wiseoldman.net/v2/players/{player_name.replace(' ', '_')}/gained"
        debug.append(f"🌐 Fetching gained KC from WiseOldMan: {url}")

        response = requests.get(url, headers={'User-Agent': 'OSRS-Bingo-Tracker/1.0'},
                                 params={'startDate': start_date, 'endDate': end_date}, timeout=15)
        debug.append(f"📡 HTTP Status: {response.status_code}")

        if response.status_code != 200:
            debug.append(f"❌ Error: {response.text[:200]}")
            return None, debug

        boss_data = response.json().get('data', {}).get('bosses', {})
        gained_by_boss = {}
        for wom_key, entry in boss_data.items():
            kills = entry.get('kills', {})
            # Trust WOM's own precomputed "gained" directly rather than
            # recomputing end-start ourselves - it stays correct even when
            # start or end individually show WOM's -1 "unranked" sentinel
            # (e.g. a player who wasn't on that boss's leaderboard yet at
            # the start date still has a perfectly valid gained count).
            gained = kills.get('gained', 0)
            if gained <= 0:
                continue
            start_kc = kills.get('start', -1)
            end_kc = kills.get('end', -1)
            display_name = WOM_BOSS_MAPPING.get(wom_key) or wom_key.replace('_', ' ').title()
            if display_name in WOM_EXCLUDED_BOSSES:
                continue
            gained_by_boss[display_name] = {'start': start_kc, 'end': end_kc, 'gained': gained}

        debug.append(f"✅ Found {len(gained_by_boss)} bosses with KC gained > 0")
        return gained_by_boss, debug

    except Exception as e:
        debug.append(f"💥 Exception: {type(e).__name__}: {str(e)}")
        return None, debug


@app.route('/kc/fetch/<player_name>', methods=['POST'])
@limiter.limit("20 per minute")
def fetch_player_kc(player_name):
    """Fetch and store a player's current KC"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_authenticated_tenant()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    # Fetch from OSRS
    kc_data, _ = fetch_osrs_highscores(player_name)

    if not kc_data:
        return jsonify({'error': f'Could not fetch KC for {player_name}'}), 404

    # Store snapshot in tenant's KC collection
    try:
        collections['kc'].insert_one({
            'player': player_name,
            'timestamp': datetime.utcnow(),
            'snapshot_type': 'current',
            'bosses': kc_data
        })

        return jsonify({
            'success': True,
            'player': player_name,
            'kc_count': len(kc_data),
            'bosses': kc_data
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/kc/snapshot', methods=['POST'])
@limiter.limit("10 per minute")
def create_kc_snapshot():
    """Create KC snapshot for all players"""
    debug_log = []
    debug_log.append("[*] KC Snapshot endpoint called")

    if not USE_MONGODB:
        return jsonify({
            'success': False,
            'error': 'MongoDB not available',
            'debug': debug_log
        }), 503

    tenant = get_authenticated_tenant()
    if not tenant:
        return jsonify({'success': False, 'error': 'Unauthorized', 'debug': debug_log}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    data = request.json
    snapshot_type = data.get('type', 'manual')
    debug_log.append(f"[*] Snapshot type: {snapshot_type}")

    # Get all unique players from tenant's history
    try:
        players = collections['history'].distinct('player')
        debug_log.append(f"[OK] Found {len(players)} players: {players}")
    except Exception as e:
        debug_log.append(f"[X] Error getting players: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'debug': debug_log
        }), 500

    if not players:
        debug_log.append("[!] No players in history!")
        return jsonify({
            'success': False,
            'message': 'No players found in drop history',
            'snapshots': 0,
            'results': [],
            'debug': debug_log
        })

    results = []

    for player in players:
        player_debug = []
        player_debug.append(f"[*] Fetching KC for: {player}")

        kc_data, fetch_debug = fetch_osrs_highscores(player)  # Returns tuple
        player_debug.extend(fetch_debug)  # Add all fetch debug info

        if kc_data:
            player_debug.append(f"[OK] Got {len(kc_data)} boss KCs")

            try:
                result = collections['kc'].insert_one({
                    'player': player,
                    'timestamp': datetime.utcnow(),
                    'snapshot_type': snapshot_type,
                    'bosses': kc_data
                })
                player_debug.append(f"[OK] SAVED to MongoDB! ID: {result.inserted_id}")
                results.append({
                    'player': player,
                    'success': True,
                    'kc_count': len(kc_data),
                    'debug': player_debug
                })
            except Exception as e:
                player_debug.append(f"[X] MongoDB save failed: {str(e)}")
                results.append({
                    'player': player,
                    'success': False,
                    'error': str(e),
                    'debug': player_debug
                })
        else:
            player_debug.append(f"[X] No KC data")
            results.append({
                'player': player,
                'success': False,
                'error': 'No KC data',
                'debug': player_debug
            })

        debug_log.extend(player_debug)

    successful = sum(1 for r in results if r.get('success'))
    debug_log.append(f"[*] FINAL: {successful}/{len(results)} succeeded")

    return jsonify({
        'success': True,
        'snapshots': len(results),
        'successful': successful,
        'results': results,
        'debug': debug_log
    })


@app.route('/kc/refresh-gained', methods=['POST'])
@limiter.limit("10 per minute")
def refresh_kc_gained():
    """
    Refreshes the WOM-authoritative "KC gained per boss" cache for every
    tracked player, for the current event's date window. Replaces diffing
    our own 'start'/'current' KC snapshots (see fetch_wom_gained for why
    that was unreliable) as the source for KC-gained everywhere it's used
    (recap/luck badges, /kc/player, /kc/effort). Triggered periodically by
    a GitHub Action (same pattern as /kc/snapshot), not on every page
    view - WOM's API has rate limits, and this data only needs to be as
    fresh as the last few hours.
    """
    debug_log = []
    if not USE_MONGODB:
        return jsonify({'success': False, 'error': 'MongoDB not available', 'debug': debug_log}), 503

    tenant = get_authenticated_tenant()
    if not tenant:
        return jsonify({'success': False, 'error': 'Unauthorized', 'debug': debug_log}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    event_config = collections['bingo'].find_one({'_id': 'event_config'})
    if not event_config or not event_config.get('enabled'):
        return jsonify({'success': False, 'error': 'No event is currently configured', 'debug': debug_log}), 404

    start_date = event_config.get('startDate')
    configured_end = event_config.get('endDate')
    now_iso = datetime.utcnow().isoformat() + 'Z'
    # Don't ask WOM to compute "gained" up to a date in the future - cap the
    # window at now for an event that's still ongoing.
    end_date = min(configured_end, now_iso) if configured_end else now_iso
    if not start_date:
        return jsonify({'success': False, 'error': 'Event has no startDate configured', 'debug': debug_log}), 400
    debug_log.append(f"[*] Refreshing KC gained from {start_date} to {end_date}")

    try:
        players = collections['history'].distinct('player')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'debug': debug_log}), 500
    debug_log.append(f"[*] Found {len(players)} players: {players}")

    results = []
    for player in players:
        gained_by_boss, fetch_debug = fetch_wom_gained(player, start_date, end_date)
        if gained_by_boss is not None:
            try:
                collections['gained_cache'].update_one(
                    {'player': player},
                    {'$set': {
                        'player': player,
                        'event_start': start_date,
                        'event_end': end_date,
                        'bosses': gained_by_boss,
                        'fetched_at': datetime.utcnow()
                    }},
                    upsert=True
                )
                results.append({'player': player, 'success': True, 'boss_count': len(gained_by_boss)})
            except Exception as e:
                results.append({'player': player, 'success': False, 'error': str(e)})
        else:
            results.append({'player': player, 'success': False, 'error': 'fetch failed', 'debug': fetch_debug})

    successful = sum(1 for r in results if r.get('success'))
    debug_log.append(f"[*] FINAL: {successful}/{len(results)} succeeded")

    return jsonify({
        'success': True,
        'players_processed': len(results),
        'successful': successful,
        'results': results,
        'debug': debug_log
    })


def fetch_groupironmen_collection_log():
    """
    Pulls each player's real collection log - item name -> quantity ever
    obtained - from groupiron.men, the group's own GIM tracker site, fed by
    the Collection Log RuneLite plugin.

    Why this exists: Dink's own drop history only goes back to whenever
    Dink was actually installed, so a player's All Time luck score was
    being computed against a badly incomplete "actual" count - missing
    every real drop from before then. The in-game Collection Log has no
    such gap; groupiron.men already has it synced for this group.

    This is ONLY ever used as a supplemental source for the All Time luck
    calc (see compute_luck_breakdown) - never stored into or merged with
    drop history, and never used for anything date-based (Drop History,
    Analytics, Recap, Current Bingo luck), because collection log entries
    carry no timestamp and no per-drop source at all, just a running total.

    Returns {player: {item_name_lower: quantity}}, or None if not
    configured (no GROUPIRONMEN_TOKEN) or the request failed.
    """
    if not GROUPIRONMEN_TOKEN:
        return None
    try:
        group_resp = requests.get(
            f'https://groupiron.men/api/group/{GROUPIRONMEN_GROUP_NAME}/get-group-data',
            params={'from_time': '1970-01-01T00:00:00.000Z'},
            headers={'Authorization': GROUPIRONMEN_TOKEN},
            timeout=20
        )
        if group_resp.status_code != 200:
            print(f"[!] groupiron.men group-data request failed: HTTP {group_resp.status_code}")
            return None

        items_resp = requests.get('https://groupiron.men/data/item_data.json', timeout=20)
        if items_resp.status_code != 200:
            print(f"[!] groupiron.men item_data.json request failed: HTTP {items_resp.status_code}")
            return None
        item_names = {k: v.get('name', '') for k, v in items_resp.json().items()}

        result = {}
        for player_doc in group_resp.json():
            player = player_doc.get('name')
            cl = player_doc.get('collection_log_v2') or []
            if not player or not cl:
                continue
            # Flat [itemId, qty, itemId, qty, ...] list (see
            # CollectionLogV2Manager.java's List<Integer> - it's a JSON
            # array, not an object, even though it happens to also respond
            # to string-indexed/Object.keys() access in JS).
            owned = {}
            for i in range(0, len(cl) - 1, 2):
                item_id = str(cl[i])
                qty = cl[i + 1]
                name = item_names.get(item_id)
                if name and qty:
                    name = name.lower()
                    owned[name] = owned.get(name, 0) + qty
            if owned:
                result[player] = owned
        return result
    except Exception as e:
        print(f"[!] groupiron.men fetch failed: {e}")
        return None


@app.route('/kc/refresh-collection-log', methods=['POST'])
@limiter.limit("10 per minute")
def refresh_collection_log():
    """
    Refreshes the collection_log_cache from groupiron.men (see
    fetch_groupironmen_collection_log). Triggered periodically by a GitHub
    Action, not fetched live per request - groupiron.men is an external
    service we don't control the availability/rate limits of, and this
    data (a lifetime total) doesn't need to be fresher than a few hours.
    """
    if not USE_MONGODB:
        return jsonify({'success': False, 'error': 'MongoDB not available'}), 503

    tenant = get_authenticated_tenant()
    if not tenant:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    data = fetch_groupironmen_collection_log()
    if data is None:
        return jsonify({'success': False, 'error': 'Fetch from groupiron.men failed (not configured, or request failed) - see server logs'}), 502

    for player, items in data.items():
        collections['collection_log_cache'].update_one(
            {'player': player},
            {'$set': {'player': player, 'items': items, 'fetched_at': datetime.utcnow()}},
            upsert=True
        )

    return jsonify({'success': True, 'players_updated': len(data)})


@app.route('/kc/player/<player_name>', methods=['GET'])
def get_player_kc(player_name):
    """Get a player's KC history"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get all snapshots for this player
        snapshots = list(collections['kc'].find(
            {'player': player_name},
            sort=[('timestamp', -1)]
        ))

        # Convert ObjectId to string
        for snapshot in snapshots:
            snapshot['_id'] = str(snapshot['_id'])
            snapshot['timestamp'] = snapshot['timestamp'].isoformat()

        # Get starting snapshot (still used for has_start/UI purposes, but no
        # longer for the effort calculation below)
        start_snapshot = collections['kc'].find_one(
            {'player': player_name, 'snapshot_type': 'start'},
            sort=[('timestamp', 1)]
        )

        # KC gained per boss comes from the WOM-authoritative gained_cache
        # (refreshed periodically by /kc/refresh-gained), not from diffing
        # our own 'start' vs 'current' snapshots - that diff was unreliable
        # (a boss missing from 'start' entirely credited a player's whole
        # lifetime KC as "gained", and a late-captured 'start' snapshot
        # could show 0 gained when real gains happened first).
        cached = collections['gained_cache'].find_one({'player': player_name})
        effort = {}
        if cached:
            for boss, boss_gained in cached.get('bosses', {}).items():
                effort[boss] = {
                    'start': boss_gained['start'],
                    'current': boss_gained['end'],
                    'gained': boss_gained['gained']
                }

        return jsonify({
            'player': player_name,
            'snapshots': snapshots,
            'effort': effort,
            'has_start': start_snapshot is not None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/kc/leaderboard/<boss_name>', methods=['GET'])
def get_boss_leaderboard(boss_name):
    """Get KC leaderboard for a specific boss"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get latest snapshot for each player
        pipeline = [
            {'$sort': {'timestamp': -1}},
            {'$group': {
                '_id': '$player',
                'latest_snapshot': {'$first': '$$ROOT'}
            }},
            {'$project': {
                'player': '$_id',
                'kc': f'$latest_snapshot.bosses.{boss_name}',
                'timestamp': '$latest_snapshot.timestamp'
            }},
            {'$match': {'kc': {'$exists': True, '$ne': None}}},
            {'$sort': {'kc': -1}}
        ]

        results = list(collections['kc'].aggregate(pipeline))

        # Convert to simple format
        leaderboard = []
        for result in results:
            leaderboard.append({
                'player': result['player'],
                'kc': result['kc'],
                'timestamp': result['timestamp'].isoformat()
            })

        return jsonify({
            'boss': boss_name,
            'leaderboard': leaderboard
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/kc/all', methods=['GET'])
def get_all_kc():
    """Get current KC for all players"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get latest snapshot for each player
        pipeline = [
            {'$sort': {'timestamp': -1}},
            {'$group': {
                '_id': '$player',
                'latest_snapshot': {'$first': '$$ROOT'}
            }}
        ]

        results = list(collections['kc'].aggregate(pipeline))

        _excluded = {'Brutus'}
        all_kc = {}
        for result in results:
            player = result['_id']
            snapshot = result['latest_snapshot']
            all_kc[player] = {
                'bosses': {k: v for k, v in snapshot['bosses'].items() if k not in _excluded},
                'timestamp': snapshot['timestamp'].isoformat(),
                'snapshot_type': snapshot['snapshot_type']
            }

        return jsonify(all_kc)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def count_unique_drops(docs, window_seconds=60):
    """
    Count real drop events from history docs, collapsing paired 'loot' + 'collection_log'
    entries that Dink can send for the same physical item pickup (one item, two Discord
    messages) into a single count. Docs are NOT modified or removed - this only affects
    how many "actual drops" we report, not what's stored in history.

    window_seconds default is 60, not 5 - checking real history showed loot/collection_log
    pairs for the same pickup arriving anywhere from under a second up to ~47 seconds apart
    (notable/rare drops seem to take longer), so 5s was under-collapsing some of them and
    inflating counts. An independent second drop of the same item within 60s of the first
    would require another full kill that fast, which isn't realistic, so this is safe in the
    other direction too. Matches js/app.js's dedupeDropsForAnalytics, which had the same bug.
    """
    # Group by player so timestamps are only compared within the same player's drops
    by_player = {}
    for doc in docs:
        by_player.setdefault(doc['player'], []).append(doc['timestamp'])

    total = 0
    for timestamps in by_player.values():
        timestamps.sort()
        last_counted = None
        for ts in timestamps:
            if last_counted is not None and (ts - last_counted).total_seconds() <= window_seconds:
                continue  # same physical drop as the previous one we counted (loot + collection_log pair)
            total += 1
            last_counted = ts

    return total


@app.route('/kc/notable-drops', methods=['GET'])
def get_notable_drops():
    """Count actual drops of a notable item (e.g. Enhanced crystal weapon seed) from drop history"""
    item_name = request.args.get('item', '')
    if not item_name:
        return jsonify({'error': 'Missing item parameter'}), 400

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        docs = list(collections['history'].find(
            {'item': {'$regex': f'^{item_name}$', '$options': 'i'}},
            {'player': 1, 'timestamp': 1}
        ))
        count = count_unique_drops(docs)
        return jsonify({'item': item_name, 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/kc/effort', methods=['GET'])
def get_kc_effort():
    """Calculate KC effort (gains since bingo start)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get all players
        players = collections['kc'].distinct('player')

        effort_results = []

        # KC gained per boss comes from the WOM-authoritative gained_cache
        # (refreshed periodically by /kc/refresh-gained) rather than diffing
        # our own 'start'/'current' KC snapshots - see fetch_wom_gained for
        # why that diff was unreliable (missing bosses, late-captured starts).
        for player in players:
            cached = collections['gained_cache'].find_one({'player': player})
            if not cached or not cached.get('bosses'):
                continue  # Skip if no gained data cached yet for this player

            effort = {boss: data['gained'] for boss, data in cached['bosses'].items()}

            effort_results.append({
                'player': player,
                'effort': effort,
                'start_timestamp': cached.get('event_start'),
                'current_timestamp': cached.get('fetched_at').isoformat() if cached.get('fetched_at') else None
            })

        if not effort_results:
            return jsonify({
                'success': False,
                'message': 'No KC gained data cached yet. Trigger /kc/refresh-gained to populate it.',
                'players': []
            })

        return jsonify({
            'success': True,
            'players': effort_results
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/players', methods=['GET'])
def get_players():
    """Get list of all players from history"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        players = collections['history'].distinct('player')
        return jsonify({'players': players})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/kc/save', methods=['POST'])
@limiter.limit("60 per minute")
def save_kc():
    """Save KC data (called from browser)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_authenticated_tenant()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    data = request.json
    player = data.get('player')
    bosses = data.get('bosses')
    snapshot_type = data.get('snapshot_type', 'current')

    if not player or not bosses:
        return jsonify({'success': False, 'error': 'Missing player or bosses'}), 400

    try:
        result = collections['kc'].insert_one({
            'player': player,
            'timestamp': datetime.utcnow(),
            'snapshot_type': snapshot_type,
            'bosses': bosses
        })

        return jsonify({
            'success': True,
            'id': str(result.inserted_id)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Legacy KC collection reference (kept for backward compatibility)
if USE_MONGODB:
    kc_collection = db['kc_snapshots']


def check_duplicate_in_history(player, item, message_timestamp, seconds=5):
    """Check if this drop already exists in history (within N seconds of the message timestamp)"""
    if not USE_MONGODB:
        return False  # Skip deduplication for file storage

    try:
        tenant = get_tenant_from_request()
        tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
        collections = get_tenant_collections(tenant_id)

        # Parse timestamp if it's a string
        if isinstance(message_timestamp, str):
            msg_time = datetime.fromisoformat(message_timestamp.replace('Z', '+00:00'))
        else:
            msg_time = message_timestamp

        # Calculate time window around the message timestamp
        time_start = msg_time - timedelta(seconds=seconds)
        time_end = msg_time + timedelta(seconds=seconds)

        # CHANGE THIS LINE: history_collection → collections['history']
        duplicate = collections['history'].find_one({
            'player': player,
            'item': item,
            'timestamp': {
                '$gte': time_start,
                '$lte': time_end
            }
        })

        return duplicate is not None
    except Exception as e:
        print(f"Error checking duplicate: {e}")
        return False


def load_bingo_data(tenant_id=None):
    """Load bingo board data from MongoDB or file"""
    if USE_MONGODB:
        try:
            # Get tenant-specific collection
            collections = get_tenant_collections(tenant_id)
            bingo_coll = collections['bingo']

            board = bingo_coll.find_one({'type': 'current_board'})
            if board:
                board.pop('_id', None)
                board.pop('type', None)
                return board
        except Exception as e:
            print(f"Error loading from MongoDB: {e}")

    # Fallback to file storage
    if os.path.exists(BINGO_FILE):
        with open(BINGO_FILE, 'r') as f:
            data = json.load(f)
            if 'boardSize' not in data:
                data['boardSize'] = 5
            if 'adminPassword' in data:
                del data['adminPassword']
            if 'lineBonuses' not in data:
                size = data['boardSize']
                data['lineBonuses'] = {
                    'rows': [50] * size,
                    'cols': [50] * size,
                    'diags': [100, 100]
                }
            return data

    # Return default empty board
    return {
        'boardSize': 5,
        'tiles': [{'items': [], 'value': 10, 'completedBy': [], 'completedAt': {}, 'displayTitle': ''} for _ in range(25)],
        'completions': {},
        'lineBonuses': {
            'rows': [50, 50, 50, 50, 50],
            'cols': [50, 50, 50, 50, 50],
            'diags': [100, 100]
        }
    }


def save_bingo_data(data, tenant_id=None):
    """Save bingo board data to MongoDB or file"""
    if USE_MONGODB:
        try:
            # Get tenant-specific collection
            collections = get_tenant_collections(tenant_id)
            bingo_coll = collections['bingo']

            data['type'] = 'current_board'
            bingo_coll.replace_one(
                {'type': 'current_board'},
                data,
                upsert=True
            )
            print("[OK] Saved to MongoDB")
            return
        except Exception as e:
            print(f"Error saving to MongoDB: {e}")

    # Fallback to file storage
    with open(BINGO_FILE, 'w') as f:
        json.dump(data, f, indent=2)


@app.route('/bingo', methods=['GET'])
def get_bingo():
    """Get current bingo board state"""
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    return jsonify(load_bingo_data(tenant_id))

@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def admin_login():
    """Authenticate admin user"""
    data = request.json
    password = data.get('password')
    tenant = get_tenant_from_request()

    if verify_admin_password(tenant, password):
        return jsonify({'success': True, 'message': 'Login successful'})
    else:
        return jsonify({'success': False, 'message': 'Incorrect password'}), 401


@app.route('/drop', methods=['POST'])
@limiter.limit("300 per minute")
def record_drop():
    """Receive drop from Discord bot - checks tiles AND saves to history"""
    data = request.json
    player_name = data.get('player')
    item_name = data.get('item')
    drop_type = data.get('drop_type', 'loot')  # 'loot' or 'collection_log'
    source = data.get('source')
    value = data.get('value', 0)  #Get value from bot
    value_string = data.get('value_string', '')  #Original value text (e.g., "2.95M")
    rarity = data.get('rarity')  # Raw "1 in X" text from Dink, when known (single-item drops only)
    rarity_1_in = parse_rarity_denominator(rarity)
    quantity = data.get('quantity', 1)  # How many of the item this single drop event was for
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())

    tenant = get_authenticated_tenant_by_api_key()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    # Check if within event window
    if not is_within_event_window(tenant_id=tenant_id):
        event_config = collections['bingo'].find_one({'_id': 'event_config'})
        event_name = event_config.get('eventName', 'Event') if event_config else 'Event'
        print(f"[!] Drop rejected: Outside event window ({event_name})")
        return jsonify({
            'success': False,
            'message': f'Drop rejected: Outside {event_name} event window'
        })

    print(f"\n{'=' * 60}")
    print(f"[DROP] Received from Discord bot:")
    print(f"   Tenant: {tenant['name'] if tenant else 'default'}")
    print(f"   Player: {player_name}")
    print(f"   Item: {item_name}")
    print(f"   Type: {drop_type}")
    print(f"   Value: {value_string} ({value:,.0f} gp)")
    print(f"{'=' * 60}")

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    # Save to tenant's history collection
    if USE_MONGODB:
        try:
            collections['history'].insert_one({
                'player': player_name,
                'item': item_name,
                'drop_type': drop_type,
                'source': source,
                'value': value,
                'value_string': value_string,
                'rarity': rarity,
                'rarity_1_in': rarity_1_in,
                'quantity': quantity,
                'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                    str) else timestamp
            })
            print(f"[OK] Saved to history collection (type: {drop_type})")
        except Exception as e:
            print(f"[X] Error saving to history: {e}")

    # Normalize the drop timestamp once so it can be stamped onto any tile
    # this drop completes (see completedAt below).
    try:
        completed_at_iso = (datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                             if isinstance(timestamp, str) else timestamp).isoformat()
    except (ValueError, AttributeError):
        completed_at_iso = datetime.utcnow().isoformat()

    # Check tiles for completion (using tenant's bingo data)
    bingo_data = load_bingo_data(tenant_id)
    updated = False
    completed_tiles = []

    print(f"[*] Checking {len(bingo_data['tiles'])} tiles...")

    for index, tile in enumerate(bingo_data['tiles']):
        if not tile['items']:
            continue

        # Check if this is a multi-item requirement tile
        if tile.get('requiredItems') and len(tile['requiredItems']) > 1:
            # Multi-item tile - track progress
            if 'itemProgress' not in tile:
                tile['itemProgress'] = {}

            if player_name not in tile['itemProgress']:
                tile['itemProgress'][player_name] = []

            player_items = tile['itemProgress'][player_name]

            # Check if this item is required and not yet collected
            for req_item in tile['requiredItems']:
                req_item_clean = req_item.strip().lower()
                item_name_clean = item_name.strip().lower()

                if (req_item_clean == item_name_clean or
                        req_item_clean in item_name_clean or
                        item_name_clean in req_item_clean):

                    # Add to progress if not already there
                    if item_name not in player_items:
                        player_items.append(item_name)
                        print(
                            f"   Tile {index + 1}: Added {item_name} to {player_name}'s progress ({len(player_items)}/{len(tile['requiredItems'])})")
                        updated = True

                    # Check if all items collected
                    has_all = all(
                        any(req_item.strip().lower() == pi.strip().lower() for pi in player_items)
                        for req_item in tile['requiredItems']
                    )

                    if has_all and player_name not in tile['completedBy']:
                        tile['completedBy'].append(player_name)
                        tile.setdefault('completedAt', {})[player_name] = completed_at_iso
                        completed_tiles.append({
                            'tile': index + 1,
                            'items': tile['items'],
                            'value': tile['value']
                        })
                        print(f"   ✅ Tile {index + 1} COMPLETED by {player_name} (all items collected)!")

                    break
        else:
            # Regular tile - any matching item completes it
            for tile_item in tile['items']:
                tile_item_clean = tile_item.strip().lower()
                item_name_clean = item_name.strip().lower()

                if tile_item_clean == item_name_clean:
                    print(f"      ✓ MATCH: '{item_name}' matches '{tile_item}'")

                    if player_name not in tile['completedBy']:
                        tile['completedBy'].append(player_name)
                        tile.setdefault('completedAt', {})[player_name] = completed_at_iso
                        completed_tiles.append({
                            'tile': index + 1,
                            'items': tile['items'],
                            'value': tile['value']
                        })
                        updated = True
                        print(f"      → Added {player_name} to completedBy list")
                    else:
                        print(f"      → {player_name} already completed this tile")
                    break

    if updated:
        save_bingo_data(bingo_data, tenant_id)
        print(f"[OK] Saved updated board data")
        print(f"{'=' * 60}\n")
        return jsonify({
            'success': True,
            'message': f'{player_name} completed {len(completed_tiles)} tile(s)!',
            'completedTiles': completed_tiles,
            'duplicate': False
        })

    print(f"[X] No matching tiles found or already completed")
    print(f"{'=' * 60}\n")
    return jsonify({
        'success': False,
        'message': 'No matching tiles found or already completed',
        'duplicate': False
    })


@app.route('/manual-drop', methods=['POST'])
@limiter.limit("30 per minute")
def manual_drop():
    """Manually add a drop to history ONLY (does NOT check tiles)"""
    data = request.json
    password = data.get('password')
    tenant = get_tenant_from_request()

    # Verify admin password
    if not verify_admin_password(tenant, password):
        print(f"[X] Unauthorized manual drop attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    # Get tenant collections
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    player_name = data.get('playerName')  # Note: playerName, not player
    item_name = data.get('itemName')  # Note: itemName, not item

    if not player_name or not item_name:
        print(f"[X] Missing data. Received: {data}")
        return jsonify({'error': 'Missing player or item'}), 400

    print(f"\n{'=' * 60}")
    print(f"[MANUAL DROP]")
    print(f"   Player: {player_name}")
    print(f"   Item: {item_name}")
    print(f"{'=' * 60}")

    # Save to tenant's history collection (no tile checking)
    if USE_MONGODB:
        try:
            collections['history'].insert_one({
                'player': player_name,
                'item': item_name,
                'drop_type': 'loot',
                'source': 'Manual Entry',
                'value': 0,
                'value_string': '',
                'timestamp': datetime.utcnow()
            })
            print(f"[OK] Saved to history collection")
            print(f"{'=' * 60}\n")
            return jsonify({
                'success': True,
                'message': f'Added {item_name} to {player_name}\'s history'
            })
        except Exception as e:
            print(f"[X] Error saving to history: {e}")
            return jsonify({'error': f'Failed to save: {str(e)}'}), 500
    else:
        return jsonify({'error': 'MongoDB not available'}), 503

@app.route('/history-only', methods=['POST'])
@limiter.limit("600 per minute")
def record_history_only():
    """Save drop to history ONLY (no tile checking) - for historical imports"""
    data = request.json
    player_name = data.get('player')
    item_name = data.get('item')
    drop_type = data.get('drop_type', 'loot')
    source = data.get('source')
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())
    value = data.get('value', 0)
    value_string = data.get('value_string', '')
    rarity = data.get('rarity')
    rarity_1_in = parse_rarity_denominator(rarity)
    quantity = data.get('quantity', 1)

    tenant = get_authenticated_tenant_by_api_key()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    # Save to tenant's history collection
    if USE_MONGODB:
        try:
            collections['history'].insert_one({
                'player': player_name,
                'item': item_name,
                'drop_type': drop_type,
                'source': source,
                'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                    str) else timestamp,
                'value': value,
                'value_string': value_string,
                'rarity': rarity,
                'rarity_1_in': rarity_1_in,
                'quantity': quantity,
            })
            return jsonify({
                'success': True,
                'message': f'Saved {player_name} - {item_name} to history (type: {drop_type})',
                'duplicate': False
            })
        except Exception as e:
            return jsonify({'error': f'Failed to save: {str(e)}'}), 500
    else:
        return jsonify({'error': 'MongoDB not available'}), 503


@app.route('/history/backfill-rarity', methods=['POST'])
@limiter.limit("60 per minute")
def backfill_rarity():
    """
    Enrich already-saved history documents with rarity/value/quantity/source
    data re-scraped from old Discord messages (see DinkParser.py's
    !backfill_rarity command). This never inserts new history entries and
    never overwrites a document that already has a field set - it only
    fills gaps left by drops logged before that field existed, or (for
    source) logged before Loot Drop embeds' "From:" line - which lives in
    the description, not a dedicated field - was parsed at all.

    Each candidate is matched to an existing history doc by player + item +
    closest timestamp within a short window (drops predating rarity tracking
    were saved with the API-receipt time, not the exact Discord message time,
    so an exact timestamp match isn't expected).

    Auth: same X-API-Key the bot already sends on every drop post — this is
    a bot-driven data-correction pass, not an admin-panel action.
    """
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_authenticated_tenant_by_api_key()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    drops = data.get('drops', [])
    if not isinstance(drops, list):
        return jsonify({'error': 'drops must be a list'}), 400

    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    MATCH_WINDOW_SECONDS = 120

    matched = 0
    updated = 0
    unmatched = 0

    for candidate in drops:
        player = candidate.get('player')
        item = candidate.get('item')
        ts_raw = candidate.get('timestamp')
        if not player or not item or not ts_raw:
            unmatched += 1
            continue

        try:
            ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
            # Discord timestamps parse as timezone-aware (they carry a +00:00
            # offset), but MongoClient() here isn't configured with tz_aware=True,
            # so every timestamp read back from history is naive UTC. Subtracting
            # a naive datetime from an aware one below (docs.sort()) raises
            # TypeError and crashes the whole request with an unhandled 500 -
            # normalize to naive UTC here so it matches what history actually
            # stores, for both that subtraction and the query bounds below.
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except (ValueError, AttributeError):
            unmatched += 1
            continue

        # One bad/unexpected candidate (or a transient Mongo hiccup) shouldn't
        # take down the other ~199 in this same batch with an unhandled 500 -
        # count it as unmatched and move on, same as any other "couldn't
        # confidently match this one" case above.
        try:
            rarity = candidate.get('rarity')
            rarity_1_in = parse_rarity_denominator(rarity)
            total_value_numeric = candidate.get('total_value_numeric')
            total_value = candidate.get('total_value')
            quantity = candidate.get('quantity')
            source = candidate.get('source')

            query = {
                'player': player,
                'item': item,
                'timestamp': {
                    '$gte': ts - timedelta(seconds=MATCH_WINDOW_SECONDS),
                    '$lte': ts + timedelta(seconds=MATCH_WINDOW_SECONDS)
                },
                '$or': [
                    {'rarity': {'$in': [None, '']}},
                    {'value': {'$in': [0, None]}},
                    {'quantity': {'$exists': False}},
                    {'source': {'$in': [None, '']}}
                ]
            }

            docs = list(collections['history'].find(query))
            if not docs:
                unmatched += 1
                continue

            # Multiple candidates near the same time (e.g. repeat drops of a common
            # item) — take the closest match so we don't guess wrong on an unrelated one.
            docs.sort(key=lambda d: abs((d['timestamp'] - ts).total_seconds()))
            target_doc = docs[0]
            matched += 1

            update_fields = {}
            if rarity and not target_doc.get('rarity'):
                update_fields['rarity'] = rarity
                update_fields['rarity_1_in'] = rarity_1_in
            if total_value_numeric and not target_doc.get('value'):
                update_fields['value'] = total_value_numeric
                if total_value:
                    update_fields['value_string'] = total_value
            if quantity and 'quantity' not in target_doc:
                update_fields['quantity'] = quantity
            if source and not target_doc.get('source'):
                update_fields['source'] = source

            if update_fields:
                collections['history'].update_one({'_id': target_doc['_id']}, {'$set': update_fields})
                updated += 1
        except Exception as e:
            print(f"[!] backfill_rarity: skipping one candidate after an error: {e}")
            unmatched += 1

    return jsonify({
        'success': True,
        'received': len(drops),
        'matched': matched,
        'updated': updated,
        'unmatched': unmatched
    })


@app.route('/death', methods=['POST'])
@limiter.limit("300 per minute")
def record_death():
    """Record player death"""
    data = request.json
    player_name = data.get('player')
    npc = data.get('npc')
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())

    tenant = get_authenticated_tenant_by_api_key()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    npc_text = f" to {npc}" if npc else ""
    print(f"\n[DEATH] {player_name}{npc_text}")

    if not player_name:
        return jsonify({'error': 'Missing player name'}), 400

    # Check if within event window
    if not is_within_event_window(tenant_id=tenant_id):
        event_config = collections['bingo'].find_one({'_id': 'event_config'})
        event_name = event_config.get('eventName', 'Event') if event_config else 'Event'
        print(f"[!] Death rejected: Outside event window ({event_name})")
        return jsonify({
            'success': False,
            'message': f'Death rejected: Outside {event_name} event window'
        })

    if USE_MONGODB:
        try:
            collections['deaths'].insert_one({
                'player': player_name,
                'npc': npc,
                'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                    str) else timestamp
            })
            return jsonify({
                'success': True,
                'message': f'{player_name} death recorded'
            })
        except Exception as e:
            return jsonify({'error': f'Failed to save death: {str(e)}'}), 500
    else:
        return jsonify({'error': 'MongoDB not available'}), 503


@app.route('/deaths/cleanup-markdown', methods=['POST'])
@limiter.limit("5 per minute")
def cleanup_death_markdown():
    """Clean markdown links from existing death data (admin only)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    data = request.json or {}
    tenant = get_tenant_from_request()
    if not verify_admin_password(tenant, data.get('password')):
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    try:
        import re

        # Get all deaths with NPC names
        deaths = list(collections['deaths'].find({'npc': {'$exists': True, '$ne': None}}))

        updated_count = 0

        for death in deaths:
            npc_name = death['npc']
            original_npc = npc_name

            # Step 1: Remove complete markdown links [text](url)
            cleaned_npc = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', npc_name)

            # Step 2: Remove incomplete markdown [text](
            cleaned_npc = re.sub(r'\[([^\]]+)\]\(', r'\1', cleaned_npc)

            # Step 3: Remove just brackets [text]
            cleaned_npc = re.sub(r'\[([^\]]+)\]', r'\1', cleaned_npc)

            # Step 4: Remove any remaining brackets or parentheses
            cleaned_npc = cleaned_npc.replace('[', '').replace(']', '')
            cleaned_npc = cleaned_npc.replace('(', '').replace(')', '')

            # Step 5: Remove any URLs
            cleaned_npc = re.sub(r'https?://[^\s]+', '', cleaned_npc)

            # Step 6: Clean up whitespace
            cleaned_npc = cleaned_npc.strip()

            # Only update if it changed and result is not empty
            if cleaned_npc != original_npc and cleaned_npc:
                collections['deaths'].update_one(
                    {'_id': death['_id']},
                    {'$set': {'npc': cleaned_npc}}
                )
                updated_count += 1
                print(f"Cleaned: '{original_npc}' → '{cleaned_npc}'")

        return jsonify({
            'success': True,
            'message': f'Cleaned {updated_count} death records',
            'updated': updated_count,
            'total_checked': len(deaths)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/deaths', methods=['GET'])
def get_deaths():
    """Get death statistics"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Sort by timestamp BEFORE grouping
        pipeline = [
            {
                '$sort': {'timestamp': -1}  # Sort newest first
            },
            {
                '$group': {
                    '_id': '$player',
                    'deaths': {'$sum': 1},
                    'last_death': {'$first': '$timestamp'},  # First = most recent
                    'last_npc': {'$first': '$npc'}  # Get NPC from most recent death
                }
            },
            {
                '$sort': {'deaths': -1}  # Sort by death count
            }
        ]

        results = list(collections['deaths'].aggregate(pipeline))

        # Format results
        death_stats = []
        total_deaths = 0

        for result in results:
            deaths = result['deaths']
            total_deaths += deaths
            death_stats.append({
                'player': result['_id'],
                'deaths': deaths,
                'last_death': result['last_death'].isoformat() if result.get('last_death') else None,
                'last_npc': result.get('last_npc')
            })

        return jsonify({
            'total_deaths': total_deaths,
            'player_stats': death_stats
        })

    except Exception as e:
        return jsonify({'error': f'Failed to get deaths: {str(e)}'}), 500


@app.route('/deaths/by-npc', methods=['GET'])
def get_deaths_by_npc():
    """Get death statistics grouped by NPC/location"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Aggregate deaths by NPC
        pipeline = [
            {
                '$match': {'npc': {'$ne': None}}  # Only include deaths with NPC
            },
            {
                '$sort': {'timestamp': -1}  # Sort by timestamp descending (newest first)
            },
            {
                '$group': {
                    '_id': '$npc',
                    'deaths': {'$sum': 1},
                    'players': {'$addToSet': '$player'},
                    'last_victim': {'$first': '$player'},  # First player (most recent)
                    'last_death_time': {'$first': '$timestamp'}  # First timestamp (most recent)
                }
            },
            {
                '$sort': {'deaths': -1}
            },
            {
                '$limit': 50  # Top 50 most deadly NPCs
            }
        ]

        results = list(collections['deaths'].aggregate(pipeline))
        
        # Format results
        npc_stats = []
        for result in results:
            npc_stats.append({
                'npc': result['_id'],
                'deaths': result['deaths'],
                'unique_players': len(result['players']),
                'players': result['players'],
                'last_victim': result.get('last_victim'),
                'last_death_time': result['last_death_time'].isoformat() if result.get('last_death_time') else None
            })
        
        return jsonify({
            'npc_stats': npc_stats,
            'count': len(npc_stats)
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get NPC deaths: {str(e)}'}), 500


@app.route('/rank/history', methods=['GET'])
def get_rank_history():
    """Get historical rank data"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get all rank snapshots, sorted by date
        history = list(collections['rank_history'].find(
            {},
            {'_id': 0}  # Exclude MongoDB ID
        ).sort('timestamp', -1).limit(100))  # Last 100 snapshots

        return jsonify({
            'success': True,
            'history': history
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/rank/snapshot', methods=['POST'])
@limiter.limit("10 per minute")
def save_rank_snapshot():
    """Save current rank data (called by fetch_gim_data.py)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_authenticated_tenant_by_api_key()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    try:
        data = request.json

        # Validate data
        required_fields = ['rank', 'prestigeRank', 'totalXp']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        # Create snapshot
        snapshot = {
            'timestamp': datetime.utcnow(),
            'rank': data['rank'],
            'prestigeRank': data['prestigeRank'],
            'totalXp': data['totalXp'],
            'rankChange': data.get('rankChange', 0),
            'prestigeRankChange': data.get('prestigeRankChange', 0),
            'xpChange': data.get('xpChange', 0)
        }

        # Check if we already have a snapshot from today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        existing = collections['rank_history'].find_one({
            'timestamp': {'$gte': today_start}
        })

        if existing:
            # Update today's snapshot
            collections['rank_history'].update_one(
                {'_id': existing['_id']},
                {'$set': snapshot}
            )
            print(f"[OK] Updated today's rank snapshot")
        else:
            # Insert new snapshot
            collections['rank_history'].insert_one(snapshot)
            print(f"[OK] Saved new rank snapshot")

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/history', methods=['GET'])
def get_history():
    """Get drop history with optional filters"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get query parameters
        player = request.args.get('player')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        drop_type = request.args.get('type')  # 'loot' or 'collection_log'
        min_value = request.args.get('minValue')  # minimum value filter
        max_value = request.args.get('maxValue')  # maximum value filter
        search = request.args.get('search')  # item name search
        limit = int(request.args.get('limit', 100))

        # Build query
        query = {}
        if player:
            query['player'] = player
        if start_date or end_date:
            query['timestamp'] = {}
            if start_date:
                query['timestamp']['$gte'] = datetime.fromisoformat(start_date)
            if end_date:
                query['timestamp']['$lte'] = datetime.fromisoformat(end_date)

        # Drop type filter
        if drop_type:
            query['drop_type'] = drop_type

        # Value range filter (either bound optional, combined into one $gte/$lte dict
        # so both can be supplied together - e.g. the History page's "100k-1m" range
        # filter, or its "=500k" filter translated to a ±10% band)
        if min_value or max_value:
            query['value'] = {}
            if min_value:
                query['value']['$gte'] = float(min_value)
            if max_value:
                query['value']['$lte'] = float(max_value)

        # Item search filter (case-insensitive)
        if search:
            query['item'] = {'$regex': search, '$options': 'i'}

        # skip supports the History page's lazy-loading - it fetches page after
        # page (newest first) rather than everything at once, so this is how it
        # asks for "the next batch after what I've already got".
        skip = int(request.args.get('skip', 0))

        # Total documents matching the filters (NOT capped by limit) - the
        # frontend needs this to know when it's reached the end and to show an
        # accurate "X of Y" count while only a subset has actually been loaded.
        total = collections['history'].count_documents(query)

        # Fetch history from tenant collection
        history = list(collections['history'].find(query).sort('timestamp', -1).skip(skip).limit(limit))

        # Format results (remove MongoDB _id)
        for item in history:
            item['_id'] = str(item['_id'])
            if isinstance(item['timestamp'], datetime):
                item['timestamp'] = item['timestamp'].isoformat()

        return jsonify({
            'history': history,
            'count': len(history),
            'total': total
        })

    except Exception as e:
        return jsonify({'error': f'Failed to get history: {str(e)}'}), 500


@app.route('/history/total-value', methods=['GET'])
def get_total_value_looted():
    """
    Sum of GP value looted, for the main board's quick-glance widget.
    Scoped to the current event (since its startDate) by default; pass
    ?all_time=true to sum across all history instead.
    """
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        all_time = request.args.get('all_time', 'false').lower() == 'true'

        match_query = {}
        since = None
        if not all_time:
            event_config = collections['bingo'].find_one({'_id': 'event_config'})
            if event_config and event_config.get('enabled') and event_config.get('startDate'):
                since = event_config['startDate']
                match_query['timestamp'] = {'$gte': datetime.fromisoformat(since.replace('Z', '+00:00'))}

        result = list(collections['history'].aggregate([
            {'$match': match_query},
            {'$group': {'_id': None, 'total': {'$sum': '$value'}}}
        ]))

        total = result[0]['total'] if result else 0
        return jsonify({'total_value': total, 'since': since})

    except Exception as e:
        return jsonify({'error': f'Failed to get total value: {str(e)}'}), 500


@app.route('/update', methods=['POST'])
@limiter.limit("60 per minute")
def update_board():
    """Update entire board (admin only)"""
    data = request.json
    tenant = get_tenant_from_request()
    if not data or not verify_admin_password(tenant, data.get('password')):
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    save_bingo_data(data, tenant_id=tenant_id)
    return jsonify({'success': True})


@app.route('/shuffle-board', methods=['POST'])
@limiter.limit("20 per minute")
def shuffle_board():
    """Shuffle board tiles randomly (admin only)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        data = request.json
        password = data.get('password')

        # Verify admin password
        if not verify_admin_password(tenant, password):
            print(f"[X] Unauthorized shuffle attempt")
            return jsonify({'error': 'Unauthorized'}), 401

        # Get current board from tenant collection
        bingo_doc = collections['bingo'].find_one({'type': 'current_board'})
        if not bingo_doc:
            return jsonify({'error': 'No board found'}), 404

        # Get tiles and shuffle them
        tiles = bingo_doc.get('tiles', [])

        if not tiles:
            return jsonify({'error': 'No tiles to shuffle'}), 400

        # Shuffle the tiles array
        import random
        random.shuffle(tiles)

        # Update the board with shuffled tiles
        collections['bingo'].update_one(
            {'type': 'current_board'},
            {'$set': {'tiles': tiles}}
        )

        print(f"[OK] Board shuffled successfully - {len(tiles)} tiles reordered")

        return jsonify({
            'success': True,
            'message': f'Board shuffled! {len(tiles)} tiles reordered',
            'tiles': tiles
        })

    except Exception as e:
        print(f"[X] Error shuffling board: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================
# EVENT TIMER CONFIGURATION
# ============================================

@app.route('/event/config', methods=['GET'])
def get_event_config():
    """Get current event configuration"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get event config from tenant's bingo collection
        event_config = collections['bingo'].find_one({'_id': 'event_config'})

        if not event_config:
            # No event configured - return empty config
            return jsonify({
                'enabled': False,
                'startDate': None,
                'endDate': None
            })

        return jsonify({
            'enabled': event_config.get('enabled', False),
            'startDate': event_config.get('startDate'),
            'endDate': event_config.get('endDate'),
            'eventName': event_config.get('eventName', 'Bingo Event')
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/event/config', methods=['POST'])
@limiter.limit("20 per minute")
def set_event_config():
    """Set event configuration (admin only)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        data = request.json
        password = data.get('password')

        # Verify admin password
        if not verify_admin_password(tenant, password):
            print(f"[X] Unauthorized event config attempt")
            return jsonify({'error': 'Unauthorized'}), 401

        enabled = data.get('enabled', False)
        start_date = data.get('startDate')
        end_date = data.get('endDate')
        event_name = data.get('eventName', 'Bingo Event')

        # Validate dates if enabled
        if enabled:
            if not start_date or not end_date:
                return jsonify({'error': 'Start and end dates required when enabled'}), 400

            # Parse dates to ensure they're valid
            from datetime import datetime
            try:
                start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))

                if end <= start:
                    return jsonify({'error': 'End date must be after start date'}), 400
            except Exception as e:
                return jsonify({'error': f'Invalid date format: {str(e)}'}), 400

        # Save event config to tenant's bingo collection
        event_config = {
            '_id': 'event_config',
            'enabled': enabled,
            'startDate': start_date,
            'endDate': end_date,
            'eventName': event_name
        }

        collections['bingo'].replace_one(
            {'_id': 'event_config'},
            event_config,
            upsert=True
        )

        print(f"[OK] Event config updated: {event_name} ({start_date} to {end_date}, enabled={enabled})")

        return jsonify({
            'success': True,
            'message': 'Event configuration saved',
            'config': event_config
        })

    except Exception as e:
        print(f"[X] Error setting event config: {e}")
        return jsonify({'error': str(e)}), 500


def is_within_event_window(timestamp=None, tenant_id=None):
    """Check if a timestamp is within the current event window"""
    try:
        # Get tenant's bingo collection for event config
        collections = get_tenant_collections(tenant_id)
        event_config = collections['bingo'].find_one({'_id': 'event_config'})

        # If no event or event disabled, allow all
        if not event_config or not event_config.get('enabled', False):
            return True

        # Use provided timestamp or current time
        if timestamp is None:
            check_time = datetime.utcnow()
        else:
            # Convert timestamp to datetime if it's a string
            if isinstance(timestamp, str):
                check_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif isinstance(timestamp, datetime):
                check_time = timestamp
            else:
                check_time = datetime.utcnow()

        # Get event dates
        start_date = event_config.get('startDate')
        end_date = event_config.get('endDate')

        if not start_date or not end_date:
            return True

        # Parse dates
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))

        # Check if within window
        return start <= check_time <= end

    except Exception as e:
        print(f"[!] Error checking event window: {e}")
        # On error, allow the action (fail open)
        return True


# ============================================
# EVENT RECAP + ARCHIVE
# ============================================

# A handful of Dink's NPC source names don't reduce to their WiseOldMan boss
# key under the generic normalization below (WOM drops a leading "Barrows
# Chest(s)" down to "barrows_chests" but Dink's source text varies) — mapped
# by hand rather than guessed, since a wrong guess would attribute KC to the
# wrong boss instead of just skipping it.
BOSS_NAME_ALIASES = {
    'barrows': 'barrows_chests',
    'barrows_chest': 'barrows_chests',
    'hydra': 'alchemical_hydra',
}


def _load_notable_item_names():
    """
    Item names (lowercase) from gear-data/boss-unique-items.json - the
    curated "is this actually the chase drop" list also used by gear
    tracking. A drop having a droprate Dink will show (e.g. Muspah's Frozen
    cache, Duke's Frozen tablet) doesn't mean it's the item people grind the
    boss for, so the luck badges only count items on this list rather than
    anything with a rarity_1_in.
    """
    path = os.path.join(os.path.dirname(__file__), 'gear-data', 'boss-unique-items.json')
    try:
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
        return {name for name, info in items.items() if info.get('_notable', True)}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Could not load boss-unique-items.json for luck badges: {e}")
        return set()


NOTABLE_ITEM_NAMES = _load_notable_item_names()


def _load_notable_item_sources():
    """
    item_name (lowercase) -> curated boss/source string from
    boss-unique-items.json. Collection Log embeds don't always carry a
    Source field (Dink omits it when it can't resolve the kill itself, e.g.
    BigNumLock's Araxyte fang/venom sack), leaving that history doc's
    source blank even though the item is only ever droppable by one boss.
    Used as a fallback boss lookup so a genuinely notable drop isn't
    silently excluded from the luck badges just because Dink's message
    happened to omit the field.
    """
    path = os.path.join(os.path.dirname(__file__), 'gear-data', 'boss-unique-items.json')
    try:
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
        return {name: info['source'] for name, info in items.items() if info.get('source')}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Could not load boss-unique-items.json for source fallback: {e}")
        return {}


def _load_ambiguous_source_items():
    """
    Item names (lowercase) flagged _ambiguous_source: true - a curated
    "source" boss that's real for live Dink drops (which carry their own
    verified per-drop source) but not safe to trust blind for the All Time
    collection-log boost, which has no per-drop source at all. e.g. Granite
    maul's curated source is Grotesque Guardians, but it's also dropped by
    ordinary Gargoyles - a collection log total can't tell which one a copy
    came from, so compute_luck_breakdown excludes these from that boost
    specifically rather than silently crediting the wrong boss.
    """
    path = os.path.join(os.path.dirname(__file__), 'gear-data', 'boss-unique-items.json')
    try:
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
        return {name for name, info in items.items() if info.get('_ambiguous_source')}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Could not load boss-unique-items.json for ambiguous-source list: {e}")
        return set()


NOTABLE_ITEM_SOURCES = _load_notable_item_sources()
AMBIGUOUS_SOURCE_ITEMS = _load_ambiguous_source_items()


def _boss_key_for_drop(d, item_name):
    """
    Resolve a history doc to a boss key. Dink's own per-drop source field
    is always tried first and wins when present (it reports the specific
    NPC actually killed, e.g. "Dagannoth Rex") - the curated item source
    in NOTABLE_ITEM_SOURCES is only a fallback for when that field is
    blank. A curated source naming a group rather than one specific boss
    (uncommon - NOTABLE_ITEM_SOURCES is kept scoped to single bosses where
    possible) still won't resolve to a single WOM boss key in that case.
    """
    boss_key = normalize_boss_name(d.get('source'))
    if boss_key:
        return boss_key
    return normalize_boss_name(NOTABLE_ITEM_SOURCES.get(item_name.lower()))


def _load_boss_drop_rates():
    """
    Per-boss real droprates scraped from the OSRS Wiki (see
    scrape_boss_drop_rates.py) - {boss_key: {item_lower: rarity_1_in}}.
    Used as the preferred source for the luck badges' "expected" baseline,
    since it covers a boss even when nobody on the team has pulled its
    notable item live through Dink yet. Not auto-refreshed; re-run the
    scraper by hand when boss-unique-items.json changes.
    """
    path = os.path.join(os.path.dirname(__file__), 'gear-data', 'boss-drop-rates.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Could not load boss-drop-rates.json for luck badges: {e}")
        return {}


BOSS_DROP_RATES = _load_boss_drop_rates()


def normalize_boss_name(name):
    """
    Best-effort reduction of a free-text NPC/source name (as Dink sends it,
    e.g. "K'ril Tsutsaroth", "The Nightmare") to the snake_case boss key
    WiseOldMan uses (e.g. "kril_tsutsaroth", "nightmare"). Used only to join
    drop history to KC-gained-per-boss for the recap's luck badges — a name
    that doesn't resolve to a known boss key just fails the lookup later and
    is excluded from that calculation, rather than being misattributed.
    """
    if not name:
        return None
    slug = name.strip().lower()
    slug = slug.replace("'", '')
    slug = re.sub(r'^the\s+', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    return BOSS_NAME_ALIASES.get(slug, slug)


def _dedupe_drops_for_recap(docs, window_seconds=60):
    """
    Loot Drop and Collection Log are two separate Discord messages - and two
    separate history documents - for the same real pickup, arriving up to
    ~60s apart. Ports js/app.js's dedupeDropsForAnalytics so the recap's own
    server-side stats (drop counts, GP totals, rarest drop, luck badges)
    don't double-count a drop just because it exists in both forms, merging
    together whichever fields each twin happens to carry.
    """
    by_player = {}
    for d in docs:
        by_player.setdefault(d.get('player'), []).append(d)

    result = []
    for player_docs in by_player.values():
        player_docs.sort(key=lambda d: d.get('timestamp') or datetime.min)
        kept = []
        for d in player_docs:
            match = next((
                k for k in kept
                if k.get('item') == d.get('item') and k.get('timestamp') and d.get('timestamp')
                and abs((k['timestamp'] - d['timestamp']).total_seconds()) <= window_seconds
            ), None)
            if match:
                if not match.get('value') and d.get('value'):
                    match['value'] = d['value']
                    match['value_string'] = d.get('value_string')
                if not match.get('quantity') and d.get('quantity'):
                    match['quantity'] = d['quantity']
                if not match.get('source') and d.get('source'):
                    match['source'] = d['source']
                if not match.get('rarity_1_in') and d.get('rarity_1_in'):
                    match['rarity_1_in'] = d['rarity_1_in']
                    match['rarity'] = d.get('rarity')
            else:
                kept.append(dict(d))
        result.extend(kept)
    return result


def compute_luck_breakdown(collections, start_date, end_date, all_time=False):
    """
    Expected-vs-actual notable drops per player per boss. Backs both the
    Event Recap's tiny_violin/silver_spoon badges (compute_event_recap below
    just needs the final luck_score) and the live Luck tab (which also needs
    the full per-boss expected/actual/diff rows).

    By default this is scoped to the given event window: KC from the
    WOM-authoritative gained_cache, actual drops from history between
    start_date/end_date. With all_time=True it instead compares each
    player's TOTAL account KC per boss (same source as /kc/all) against
    ALL-TIME notable drops, ignoring start_date/end_date entirely - this
    backs the Luck tab's "All Time" toggle, mirroring how Effort/Boss
    Contribution already have their own Current Bingo vs. All Time modes.
    All Time's "actual" side also pulls from collection_log_cache (see
    fetch_groupironmen_collection_log) to cover real drops from before
    Dink was installed, which drop history alone can't have.

    Returns {player: {'luck_score': float, 'bosses': [
        {'boss': display name, 'kc_gained': int, 'expected': float, 'actual': int, 'diff': float}
    ]}} - a player only appears if they have KC at a boss the team also has
    a known droprate for; bosses with no usable droprate are simply omitted
    rather than guessed at.
    """
    match_query = {}
    if not all_time:
        if start_date:
            match_query.setdefault('timestamp', {})['$gte'] = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if end_date:
            match_query.setdefault('timestamp', {})['$lte'] = datetime.fromisoformat(end_date.replace('Z', '+00:00'))

    # Per-boss droprates, built from ALL-TIME history (see compute_event_recap
    # for why) - wiki-scraped rates first, Dink-observed all-time rates fill gaps.
    boss_item_rarity = {boss_key: dict(items) for boss_key, items in BOSS_DROP_RATES.items()}
    for d in _dedupe_drops_for_recap(list(collections['history'].find({}))):
        r1 = d.get('rarity_1_in')
        item_name = (d.get('item') or '').strip()
        if not r1 or item_name.lower() not in NOTABLE_ITEM_NAMES:
            continue
        boss_key = _boss_key_for_drop(d, item_name)
        if not boss_key:
            continue
        rates = boss_item_rarity.setdefault(boss_key, {})
        if item_name.lower() not in {k.lower() for k in rates}:
            rates[item_name] = r1

    # KC per player per boss - WOM-authoritative "gained since event start"
    # from gained_cache, or each player's latest total-KC snapshot (same
    # aggregation /kc/all uses) when all_time. Computed before the actual-
    # drops section below because the All Time collection-log supplement
    # needs it to disambiguate an item shared between two specific bosses.
    kc_by_boss = {}
    boss_display_names = {}  # boss_key -> the display name WOM/the snapshot uses
    if all_time:
        pipeline = [
            {'$sort': {'timestamp': -1}},
            {'$group': {'_id': '$player', 'latest_snapshot': {'$first': '$$ROOT'}}}
        ]
        for result in collections['kc'].aggregate(pipeline):
            snap_player = result['_id']
            boss_kcs = (result.get('latest_snapshot') or {}).get('bosses', {})
            player_bosses = {}
            for boss, kc in boss_kcs.items():
                if boss in WOM_EXCLUDED_BOSSES or not kc:
                    continue
                boss_key = normalize_boss_name(boss)
                if boss_key:
                    player_bosses[boss_key] = player_bosses.get(boss_key, 0) + kc
                    boss_display_names.setdefault(boss_key, boss)
            if player_bosses:
                kc_by_boss[snap_player] = player_bosses
    else:
        for cached in collections['gained_cache'].find({}):
            snap_player = cached.get('player')
            boss_gains = cached.get('bosses', {})
            if not snap_player or not boss_gains:
                continue
            player_bosses = {}
            for boss, boss_gained in boss_gains.items():
                gained = boss_gained.get('gained', 0)
                if gained > 0:
                    boss_key = normalize_boss_name(boss)
                    if boss_key:
                        player_bosses[boss_key] = player_bosses.get(boss_key, 0) + gained
                        boss_display_names.setdefault(boss_key, boss)
            if player_bosses:
                kc_by_boss[snap_player] = player_bosses

    # Actual notable drops, per player per boss per item - event-windowed,
    # or every drop on record when all_time (match_query is {} in that
    # case). Tracked per item rather than summed straight to a boss total
    # so the All Time collection-log supplement below can raise one item's
    # count without clobbering a different notable item at the same boss.
    player_boss_item_notable = {}  # player -> {boss_key: {item_name_lower: count}}
    for d in _dedupe_drops_for_recap(list(collections['history'].find(match_query))):
        player = d.get('player')
        if not player:
            continue
        item_name = (d.get('item') or '').strip()
        item_key = item_name.lower()
        if item_key not in NOTABLE_ITEM_NAMES:
            continue
        boss_key = _boss_key_for_drop(d, item_name)
        if not boss_key:
            continue
        per_boss = player_boss_item_notable.setdefault(player, {}).setdefault(boss_key, {})
        per_boss[item_key] = per_boss.get(item_key, 0) + 1

    # All Time only: groupiron.men's collection log (see
    # fetch_groupironmen_collection_log) covers real drops from before Dink
    # was installed, which Dink's own history can never have. It carries no
    # timestamp or per-drop source though, so attribution falls back to the
    # curated source: a single-boss source resolves directly; a source
    # naming several bosses (e.g. "The Gauntlet / Corrupted Gauntlet") goes
    # to whichever of those specific bosses this player has more KC at -
    # people who split time close to evenly between two such modes are
    # rare, so this is a reasonable signal, not a guess from nothing. An
    # item flagged _ambiguous_source (shared with a monster outside this
    # set entirely, e.g. Granite maul/Gargoyles) is skipped rather than
    # guessed at either way. This only ever RAISES an item's count to what's
    # actually logged - it can't lower a count Dink already captured, and
    # never double-counts since it's a max() against the same per-item slot.
    if all_time:
        for cl_doc in collections['collection_log_cache'].find({}):
            player = cl_doc.get('player')
            owned = cl_doc.get('items', {})
            if not player or not owned:
                continue
            player_kc = kc_by_boss.get(player, {})
            for item_name, qty in owned.items():
                item_key = item_name.lower()
                if item_key not in NOTABLE_ITEM_NAMES or not qty or item_key in AMBIGUOUS_SOURCE_ITEMS:
                    continue
                source = NOTABLE_ITEM_SOURCES.get(item_key) or ''
                if '/' in source:
                    # Covers both "A / B" (Gauntlet pair) and "A/B" (the
                    # Wilderness boss twins, e.g. "Callisto/Artio") - the
                    # curated file isn't consistent about the spacing.
                    candidates = [c for c in (normalize_boss_name(p) for p in re.split(r'\s*/\s*', source)) if c]
                    boss_key = max(candidates, key=lambda c: player_kc.get(c, 0)) if candidates else None
                    if boss_key and player_kc.get(boss_key, 0) <= 0:
                        boss_key = None  # no KC at any candidate - nothing to disambiguate with
                else:
                    boss_key = normalize_boss_name(source)
                if not boss_key:
                    continue
                per_boss = player_boss_item_notable.setdefault(player, {}).setdefault(boss_key, {})
                if qty > per_boss.get(item_key, 0):
                    per_boss[item_key] = qty

    player_boss_notable = {}
    for player, bosses in player_boss_item_notable.items():
        for boss_key, items in bosses.items():
            player_boss_notable.setdefault(player, {})[boss_key] = sum(items.values())

    breakdown = {}
    for player, boss_kc in kc_by_boss.items():
        total = 0.0
        bosses_out = []
        for boss_key, kc in boss_kc.items():
            rates = boss_item_rarity.get(boss_key)
            if not rates:
                continue
            expected = kc * sum(1.0 / r for r in rates.values())
            actual = player_boss_notable.get(player, {}).get(boss_key, 0)
            diff = actual - expected
            total += diff
            bosses_out.append({
                'boss': boss_display_names.get(boss_key, boss_key.replace('_', ' ').title()),
                'kc_gained': kc,
                'expected': round(expected, 3),
                'actual': actual,
                'diff': round(diff, 3),
            })
        if bosses_out:
            bosses_out.sort(key=lambda b: b['diff'])
            breakdown[player] = {'luck_score': round(total, 2), 'bosses': bosses_out}

    return breakdown


def compute_event_recap(collections, start_date, end_date, board_doc=None):
    """
    Compute per-player recap stats + team-wide superlative badges for the given
    event window. Mirrors the client-side scoring in js/app.js's
    updatePlayerStats()/checkLineCompletion() (tile value + line bonuses) so
    "points"/MVP match the live leaderboard. Used for both the live
    /event/recap endpoint and frozen /event/archive snapshots.
    Returns {player_name: {...stats, badges: [...]}}.
    """
    board = board_doc if board_doc is not None else (collections['bingo'].find_one({'type': 'current_board'}) or {})
    tiles = board.get('tiles', [])
    board_size = board.get('boardSize', 5)
    line_bonuses = board.get('lineBonuses', {}) or {}

    def tile_at(row, col):
        idx = row * board_size + col
        return tiles[idx] if 0 <= idx < len(tiles) else {}

    # --- tile points (sum of completed tiles' value) ---
    player_scores = {}
    for tile in tiles:
        for player in tile.get('completedBy', []):
            entry = player_scores.setdefault(player, {'tiles': 0, 'points': 0})
            entry['tiles'] += 1
            entry['points'] += tile.get('value', 0)

    # --- line completion bonuses (rows/cols/diagonals), mirrors checkLineCompletion() ---
    for player in list(player_scores.keys()):
        bonus = 0
        rows_list = line_bonuses.get('rows', [])
        cols_list = line_bonuses.get('cols', [])
        diags_list = line_bonuses.get('diags', [])

        for row in range(board_size):
            if all(player in tile_at(row, col).get('completedBy', []) for col in range(board_size)):
                if row < len(rows_list):
                    bonus += rows_list[row]

        for col in range(board_size):
            if all(player in tile_at(row, col).get('completedBy', []) for row in range(board_size)):
                if col < len(cols_list):
                    bonus += cols_list[col]

        if all(player in tile_at(i, i).get('completedBy', []) for i in range(board_size)):
            if len(diags_list) > 0:
                bonus += diags_list[0]
        if all(player in tile_at(i, board_size - 1 - i).get('completedBy', []) for i in range(board_size)):
            if len(diags_list) > 1:
                bonus += diags_list[1]

        player_scores[player]['points'] += bonus

    # --- first/last tile completed per player + event-wide earliest/latest (First Blood/Closer) ---
    first_last = {}
    event_earliest = None  # (iso, player)
    event_latest = None
    for tile in tiles:
        title = tile.get('displayTitle') or (tile.get('items') or [{}])[0].get('name') or 'a tile'
        for player, iso in (tile.get('completedAt') or {}).items():
            entry = first_last.setdefault(player, {'first': iso, 'first_tile': title, 'last': iso, 'last_tile': title})
            if iso < entry['first']:
                entry['first'], entry['first_tile'] = iso, title
            if iso > entry['last']:
                entry['last'], entry['last_tile'] = iso, title
            if event_earliest is None or iso < event_earliest[0]:
                event_earliest = (iso, player)
            if event_latest is None or iso > event_latest[0]:
                event_latest = (iso, player)

    # --- drop history aggregation ---
    match_query = {}
    if start_date:
        match_query.setdefault('timestamp', {})['$gte'] = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    if end_date:
        match_query.setdefault('timestamp', {})['$lte'] = datetime.fromisoformat(end_date.replace('Z', '+00:00'))

    drop_stats = {}
    biggest_drop = None  # (value, player, item)
    for d in _dedupe_drops_for_recap(list(collections['history'].find(match_query))):
        player = d.get('player')
        if not player:
            continue
        stats = drop_stats.setdefault(player, {
            'drop_count': 0, 'gp_total': 0, 'days': set(), 'most_valuable': None, 'rarest_drop': None
        })
        stats['drop_count'] += 1
        value = d.get('value', 0) or 0
        stats['gp_total'] += value
        ts = d.get('timestamp')
        if isinstance(ts, datetime):
            stats['days'].add(ts.date().isoformat())
        if value > 0 and (stats['most_valuable'] is None or value > stats['most_valuable'][0]):
            stats['most_valuable'] = (value, d.get('item'))
        if value > 0 and (biggest_drop is None or value > biggest_drop[0]):
            biggest_drop = (value, player, d.get('item'))

        # A drop can carry a rarity_1_in Dink happens to show without being the
        # actual chase item for that boss (e.g. Muspah's Frozen cache, Duke's
        # Frozen tablet) - only count it as "notable" if it's on the curated
        # boss-unique-items list, so neither the Rarest Drop badge nor the luck
        # badges below can be swayed by a common item that happens to have odds.
        r1 = d.get('rarity_1_in')
        item_name = (d.get('item') or '').strip()
        is_curated_item = item_name.lower() in NOTABLE_ITEM_NAMES
        if is_curated_item and r1 and (stats['rarest_drop'] is None or r1 > stats['rarest_drop'][0]):
            stats['rarest_drop'] = (r1, item_name, d.get('rarity'))

    rarest_drop_overall = None  # (rarity_1_in, player)
    for player, stats in drop_stats.items():
        if stats['rarest_drop'] and (rarest_drop_overall is None or stats['rarest_drop'][0] > rarest_drop_overall[0]):
            rarest_drop_overall = (stats['rarest_drop'][0], player)

    # --- KC gained per player, from the WOM-authoritative gained_cache (see
    # fetch_wom_gained) rather than diffing our own 'start'/'current' KC
    # snapshots - that diff was unreliable (a boss missing from 'start'
    # entirely credited a player's whole lifetime KC as "gained", and a
    # late-captured 'start' snapshot could show 0 gained when real gains
    # happened before it was taken). ---
    kc_gained = {}
    for cached in collections['gained_cache'].find({}):
        snap_player = cached.get('player')
        boss_gains = cached.get('bosses', {})
        if not snap_player or not boss_gains:
            continue
        total_gained = sum(bg.get('gained', 0) for bg in boss_gains.values() if bg.get('gained', 0) > 0)
        if total_gained > 0:
            kc_gained[snap_player] = total_gained

    # --- luck score (tiny_violin/silver_spoon): expected-vs-actual notable
    # drops, per boss, summed per player. See compute_luck_breakdown, which
    # also backs the live Luck page's full per-boss breakdown.
    luck_breakdown = compute_luck_breakdown(collections, start_date, end_date)
    luck_score = {player: data['luck_score'] for player, data in luck_breakdown.items()}

    tiny_violin_player = None
    silver_spoon_player = None
    if len(luck_score) >= 2:
        tiny_violin_player = min(luck_score, key=luck_score.get)
        silver_spoon_player = max(luck_score, key=luck_score.get)

    roster = set(player_scores) | set(drop_stats) | set(kc_gained)

    # --- team-wide superlatives ---
    top_points = max((s['points'] for s in player_scores.values()), default=0)
    mvps = {p for p, s in player_scores.items() if top_points > 0 and s['points'] == top_points}

    top_days = max((len(s['days']) for s in drop_stats.values()), default=0)
    most_consistent = {p for p, s in drop_stats.items() if top_days > 0 and len(s['days']) == top_days}

    top_kc = max(kc_gained.values(), default=0)
    top_grinders = {p for p, v in kc_gained.items() if top_kc > 0 and v == top_kc}

    recap = {}
    for player in roster:
        badges = []
        if player in mvps:
            badges.append('mvp')
        if biggest_drop and biggest_drop[1] == player:
            badges.append('biggest_drop')
        if rarest_drop_overall and rarest_drop_overall[1] == player:
            badges.append('rarest_drop')
        if player in most_consistent:
            badges.append('most_consistent')
        if player in top_grinders:
            badges.append('top_grinder')
        if event_earliest and event_earliest[1] == player:
            badges.append('first_blood')
        if event_latest and event_latest[1] == player:
            badges.append('closer')
        if tiny_violin_player == player:
            badges.append('tiny_violin')
        if silver_spoon_player == player:
            badges.append('silver_spoon')

        stats = drop_stats.get(player, {})
        most_valuable = stats.get('most_valuable')
        rarest = stats.get('rarest_drop')
        tile_dates = first_last.get(player, {})

        recap[player] = {
            'points': player_scores.get(player, {}).get('points', 0),
            'tiles_completed': player_scores.get(player, {}).get('tiles', 0),
            'drop_count': stats.get('drop_count', 0),
            'gp_total': stats.get('gp_total', 0),
            'distinct_days': len(stats.get('days', set())),
            'most_valuable_drop': {'item': most_valuable[1], 'value': most_valuable[0]} if most_valuable else None,
            'rarest_drop': {'item': rarest[1], 'rarity': rarest[2]} if rarest else None,
            'kc_gained': kc_gained.get(player, 0),
            'luck_score': round(luck_score[player], 2) if player in luck_score else None,
            'first_tile': tile_dates.get('first_tile'),
            'first_tile_at': tile_dates.get('first'),
            'last_tile': tile_dates.get('last_tile'),
            'last_tile_at': tile_dates.get('last'),
            'badges': badges
        }

    return recap


@app.route('/event/luck', methods=['GET'])
def get_event_luck():
    """
    Live per-boss luck breakdown (expected vs. actual notable drops) for
    every player, for the Luck tab. Unlike /event/recap this is NOT gated
    behind the event ending - it's meant to be checked mid-event, same as
    the KC Effort/Boss Contribution pages.

    ?all_time=true switches to the same scope as /kc/all - total account KC
    per boss vs. ALL-TIME notable drops, independent of any event window -
    mirroring Effort/Boss Contribution's own Current Bingo vs. All Time
    toggle. That mode doesn't need an event configured at all.
    """
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)
    all_time = request.args.get('all_time', '').lower() == 'true'

    try:
        if all_time:
            breakdown = compute_luck_breakdown(collections, None, None, all_time=True)
            return jsonify({'players': breakdown})

        event_config = collections['bingo'].find_one({'_id': 'event_config'})
        if not event_config or not event_config.get('enabled'):
            return jsonify({'error': 'No event is currently configured'}), 404

        breakdown = compute_luck_breakdown(
            collections,
            event_config.get('startDate'),
            event_config.get('endDate')
        )

        return jsonify({
            'eventName': event_config.get('eventName', 'Bingo Event'),
            'startDate': event_config.get('startDate'),
            'endDate': event_config.get('endDate'),
            'players': breakdown
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/event/recap/<player_name>', methods=['GET'])
def get_event_recap(player_name):
    """
    Live per-player event recap, scoped to the current event_config window.
    Locked to admins only until the event's endDate has passed — players
    shouldn't see final-stats/badges (MVP, biggest drop, etc.) while the
    event is still in progress. Pass the admin password in an
    X-Admin-Password header to preview early — deliberately not a query
    param, since query strings end up in server logs, browser history, and
    the Referer header sent to any resource the recap page loads.
    """
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        event_config = collections['bingo'].find_one({'_id': 'event_config'})
        if not event_config or not event_config.get('enabled'):
            return jsonify({'error': 'No event is currently configured'}), 404

        end_date = event_config.get('endDate')
        event_over = False
        if end_date:
            # .replace(tzinfo=None): endDate is always stored as a UTC ISO string (JS
            # toISOString(), always 'Z'-suffixed) — strip the offset fromisoformat adds
            # so this compares safely against the naive datetime.utcnow() below.
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00')).replace(tzinfo=None)
            event_over = datetime.utcnow() > end_dt
        is_admin = verify_admin_password(tenant, request.headers.get('X-Admin-Password'))

        if not event_over and not is_admin:
            event_name = event_config.get('eventName', 'Bingo Event')
            return jsonify({'error': f'Recaps unlock once {event_name} ends'}), 403

        recap = compute_event_recap(
            collections,
            event_config.get('startDate'),
            event_config.get('endDate')
        )

        player_recap = recap.get(player_name)
        if not player_recap:
            return jsonify({'error': f'No recorded activity for {player_name} this event'}), 404

        return jsonify({
            'player': player_name,
            'eventName': event_config.get('eventName', 'Bingo Event'),
            'startDate': event_config.get('startDate'),
            'endDate': event_config.get('endDate'),
            **player_recap
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/event/archive', methods=['POST'])
@limiter.limit("10 per minute")
def archive_event():
    """Snapshot the current event's recap data + board tiles into the archive (admin only)."""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    data = request.json or {}
    tenant = get_tenant_from_request()
    if not verify_admin_password(tenant, data.get('password')):
        return jsonify({'error': 'Unauthorized'}), 401

    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        event_config = collections['bingo'].find_one({'_id': 'event_config'})
        if not event_config:
            return jsonify({'error': 'No event is currently configured'}), 404

        board = collections['bingo'].find_one({'type': 'current_board'}) or {}
        recap = compute_event_recap(
            collections,
            event_config.get('startDate'),
            event_config.get('endDate'),
            board_doc=board
        )

        archive_doc = {
            'event_name': event_config.get('eventName', 'Bingo Event'),
            'start_date': event_config.get('startDate'),
            'end_date': event_config.get('endDate'),
            'archived_at': datetime.utcnow().isoformat(),
            'players': recap,
            'player_names': sorted(recap.keys()),
            'tiles_snapshot': board.get('tiles', [])
        }
        result = collections['archive'].insert_one(archive_doc)

        print(f"[OK] Archived event '{archive_doc['event_name']}' ({len(recap)} players)")

        return jsonify({
            'success': True,
            'message': f"Archived '{archive_doc['event_name']}' with {len(recap)} players",
            'archive_id': str(result.inserted_id)
        })
    except Exception as e:
        print(f"[X] Error archiving event: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/event/archive/list', methods=['GET'])
def list_event_archives():
    """List past archived events, newest first."""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        archives = list(collections['archive'].find({}, {'players': 0, 'tiles_snapshot': 0}).sort('archived_at', -1))
        for a in archives:
            a['_id'] = str(a['_id'])
        return jsonify({'archives': archives})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/event/archive/<archive_id>/player/<player_name>', methods=['GET'])
def get_archived_player_recap(archive_id, player_name):
    """A single player's frozen recap from a past archived event."""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        from bson import ObjectId
        archive_doc = collections['archive'].find_one({'_id': ObjectId(archive_id)})
        if not archive_doc:
            return jsonify({'error': 'Archive not found'}), 404

        player_recap = archive_doc.get('players', {}).get(player_name)
        if not player_recap:
            return jsonify({'error': f'No recorded activity for {player_name} in this event'}), 404

        return jsonify({
            'player': player_name,
            'eventName': archive_doc.get('event_name', 'Bingo Event'),
            'startDate': archive_doc.get('start_date'),
            'endDate': archive_doc.get('end_date'),
            **player_recap
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/deaths/by-player-npc', methods=['GET'])
def get_deaths_by_player_npc():
    """Get detailed death statistics: how many times each player died to each NPC"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Aggregate to get death counts per player per NPC
        pipeline = [
            {
                '$match': {'npc': {'$ne': None}}  # Only deaths with NPC
            },
            {
                '$group': {
                    '_id': {
                        'player': '$player',
                        'npc': '$npc'
                    },
                    'deaths': {'$sum': 1}
                }
            },
            {
                '$sort': {'deaths': -1}
            }
        ]

        results = list(collections['deaths'].aggregate(pipeline))

        # Format as: {player: {npc: death_count}}
        player_npc_deaths = {}
        for result in results:
            player = result['_id']['player']
            npc = result['_id']['npc']
            deaths = result['deaths']

            if player not in player_npc_deaths:
                player_npc_deaths[player] = {}

            player_npc_deaths[player][npc] = deaths

        return jsonify({
            'player_npc_deaths': player_npc_deaths
        })

    except Exception as e:
        return jsonify({'error': f'Failed to get player-NPC deaths: {str(e)}'}), 500



@app.route('/pb', methods=['POST'])
@limiter.limit("300 per minute")
def record_pb():
    """Record a personal best from the Discord bot"""
    data = request.json
    player_name = data.get('player')
    boss_name = data.get('boss')
    time_seconds = data.get('time_seconds')
    time_string = data.get('time_string', '')
    party_size = data.get('party_size', 1)
    invocation_level = data.get('invocation_level')  # TOA only, None for other bosses
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())

    if not player_name or not boss_name or time_seconds is None:
        return jsonify({'error': 'Missing player, boss, or time'}), 400

    tenant = get_authenticated_tenant_by_api_key()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    tenant_id = tenant['tenant_id']
    collections = get_tenant_collections(tenant_id)

    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    try:
        ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp, str) else timestamp

        # Check for exact duplicate (same player, boss, time, party size, invocation, within 10s)
        existing = collections['personal_bests'].find_one({
            'player': player_name,
            'boss': boss_name,
            'time_seconds': time_seconds,
            'party_size': party_size,
            'invocation_level': invocation_level
        })
        if existing:
            return jsonify({'success': True, 'duplicate': True, 'message': 'PB already recorded'})

        collections['personal_bests'].insert_one({
            'player': player_name,
            'boss': boss_name,
            'time_seconds': time_seconds,
            'time_string': time_string,
            'party_size': party_size,
            'invocation_level': invocation_level,
            'timestamp': ts
        })

        print(f"[PB] {player_name} - {boss_name} in {time_string}"
              + (f" @ {invocation_level} invocations" if invocation_level else "")
              + f" (party: {party_size})")

        return jsonify({'success': True, 'message': f'PB recorded: {player_name} - {boss_name} {time_string}'})

    except Exception as e:
        return jsonify({'error': f'Failed to save PB: {str(e)}'}), 500


@app.route('/pbs', methods=['GET'])
def get_personal_bests():
    """
    Get personal bests.
    Query params: player, boss
    Returns the current best (fastest) time per (player, boss, party_size, invocation_level) group.
    """
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    player_filter = request.args.get('player')
    boss_filter = request.args.get('boss')

    try:
        query = {}
        if player_filter:
            query['player'] = {'$regex': f'^{re.escape(player_filter)}$', '$options': 'i'}
        if boss_filter:
            query['boss'] = {'$regex': boss_filter, '$options': 'i'}

        all_records = list(collections['personal_bests'].find(query, {'_id': 0}).sort('time_seconds', 1))

        # Keep the best time per (player, boss, party_size, invocation_level) group
        best = {}
        for rec in all_records:
            if not rec.get('boss') or not rec.get('player'):
                continue
            key = (
                rec['player'].lower(),
                rec['boss'].lower(),
                rec.get('party_size', 1),
                rec.get('invocation_level')
            )
            if key not in best or rec['time_seconds'] < best[key]['time_seconds']:
                # Convert timestamp to ISO string for JSON serialisation
                if hasattr(rec.get('timestamp'), 'isoformat'):
                    rec['timestamp'] = rec['timestamp'].isoformat()
                best[key] = rec

        result = sorted(best.values(), key=lambda x: (x['boss'].lower(), x.get('invocation_level') or 0, x['time_seconds']))

        return jsonify({'success': True, 'personal_bests': result})

    except Exception as e:
        return jsonify({'error': f'Failed to fetch PBs: {str(e)}'}), 500


@app.route('/manual-override', methods=['POST'])
@limiter.limit("60 per minute")
def manual_override():
    """Manual tile completion override (admin only)"""
    data = request.json
    password = data.get('password')
    tenant = get_tenant_from_request()

    # Verify admin password
    if not verify_admin_password(tenant, password):
        print(f"[X] Unauthorized manual override attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID

    tile_index = data.get('tileIndex')
    player_name = data.get('playerName')
    action = data.get('action')  # 'add' or 'remove'

    if tile_index is None or not player_name or not action:
        return jsonify({'error': 'Missing required fields'}), 400

    bingo_data = load_bingo_data(tenant_id)

    if tile_index < 0 or tile_index >= len(bingo_data['tiles']):
        return jsonify({'error': 'Invalid tile index'}), 400

    tile = bingo_data['tiles'][tile_index]

    if action == 'add':
        if player_name not in tile['completedBy']:
            tile['completedBy'].append(player_name)
            # No drop event backs a manual override, so stamp it with "now" rather
            # than leaving it unresolved on the Timeline.
            tile.setdefault('completedAt', {})[player_name] = datetime.utcnow().isoformat()
            save_bingo_data(bingo_data, tenant_id)
            print(f"[OK] Manual override: Added {player_name} to tile {tile_index + 1}")
            return jsonify({
                'success': True,
                'message': f'Added {player_name} to tile {tile_index + 1}'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'{player_name} already completed this tile'
            })

    elif action == 'remove':
        if player_name in tile['completedBy']:
            tile['completedBy'].remove(player_name)
            tile.get('completedAt', {}).pop(player_name, None)
            save_bingo_data(bingo_data, tenant_id)
            print(f"[OK] Manual override: Removed {player_name} from tile {tile_index + 1}")
            return jsonify({
                'success': True,
                'message': f'Removed {player_name} from tile {tile_index + 1}'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'{player_name} has not completed this tile'
            })

    return jsonify({'error': 'Invalid action'}), 400


@app.route('/api/tenant/info', methods=['GET'])
def get_tenant_info():
    """Get current tenant information and plan details"""
    tenant = get_tenant_from_request()

    if not tenant:
        return jsonify({
            'error': 'Tenant not found'
        }), 404

    # Get plan details
    plan = tenant.get('plan', 'free')
    settings = tenant.get('settings', {})
    features = settings.get('features', [])

    # Determine what features are available
    is_premium = plan in ['premium', 'owner']

    return jsonify({
        'success': True,
        'tenant': {
            'id': tenant.get('tenant_id'),
            'name': tenant.get('name'),
            'subdomain': tenant.get('subdomain'),
            'plan': plan
        },
        'features': {
            'analytics': is_premium or 'analytics' in features,
            'death_tracking': is_premium or 'death_tracking' in features,
            'boss_kc': is_premium or 'boss_kc' in features,
            'event_timer': is_premium or 'event_timer' in features,
            'export_data': is_premium or 'export_data' in features,
            'custom_colors': is_premium or 'custom_colors' in features,
            'view_history': is_premium or 'view_history' in features,  # NEW
            'rank_history': is_premium or 'rank_history' in features,  # NEW
            'unlimited_history': is_premium,
            'unlimited_board_size': is_premium
        },
        'limits': {
            'board_size': 9 if is_premium else 3,
            'drop_history': None if is_premium else 50,
            'admins': 10 if is_premium else 1
        }
    })


@app.route('/rank/latest', methods=['GET'])
def get_latest_rank():
    """Get the most recent rank snapshot (for quick widget loading)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get the most recent snapshot
        latest = collections['rank_history'].find_one(
            {},
            {'_id': 0},
            sort=[('timestamp', -1)]
        )

        if not latest:
            return jsonify({
                'error': 'No rank data available',
                'message': 'No rank snapshots found. Data will be available after first fetch.'
            }), 404

        return jsonify({
            'success': True,
            'data': {
                'overall_rank': latest.get('rank'),
                'prestige_rank': latest.get('prestigeRank'),
                'total_xp': latest.get('totalXp'),
                'last_updated': latest.get('timestamp').isoformat() if latest.get('timestamp') else None
            }
        })

    except Exception as e:
        return jsonify({
            'error': 'Failed to fetch latest rank',
            'message': str(e)
        }), 500


@app.route('/api/gim-proxy', methods=['GET'])
def gim_proxy():
    """
    Proxy endpoint for fetching GIM highscores.
    Bypasses CORS and Cloudflare protection by fetching server-side.
    """
    page = request.args.get('page', '1')
    group_size = request.args.get('groupSize', '5')

    url = f'https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/?groupSize={group_size}&page={page}'

    try:
        if HAS_CLOUDSCRAPER:
            # Use cloudscraper to bypass Cloudflare
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            response = scraper.get(url, timeout=10)
        else:
            # Fallback to requests with browser-like headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return response.text, 200, {'Content-Type': 'text/html'}
        else:
            print(f'❌ RuneScape returned {response.status_code} for page {page}')
            print(f'Response content: {response.text[:500]}')
            return jsonify({
                'error': f'Failed to fetch page {page}',
                'status': response.status_code,
                'using_cloudscraper': HAS_CLOUDSCRAPER
            }), response.status_code

    except Exception as e:
        print(f'❌ Exception in gim_proxy: {str(e)}')
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Request failed',
            'message': str(e),
            'using_cloudscraper': HAS_CLOUDSCRAPER
        }), 500


# ============================================
# DATA EXPORT (public CSV downloads)
# ============================================
# Lets anyone pull the raw data behind the board (drop history, boss KC,
# personal bests, rank history) as CSV, to build their own analytics in
# Excel/Sheets/etc. Read-only and unauthenticated, same as the other GET
# endpoints these datasets are drawn from (/history, /kc/all, /pbs, /rank/history).

EXPORT_DATASETS = {
    'history': 'Drop History',
    'kc': 'Boss Kill Counts',
    'personal_bests': 'Personal Bests',
    'rank_history': 'Rank History',
}


def _csv_response(rows, fieldnames, filename):
    """Build a Flask CSV file-download response from a list of dict rows."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return Response(
        buffer.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/export/meta', methods=['GET'])
@limiter.limit("20 per minute")
def export_meta():
    """Record counts per exportable dataset, so the UI can show what's available before downloading."""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        datasets = [
            {
                'key': 'history',
                'label': 'Drop History',
                'description': 'Every recorded drop and collection log entry.',
                'count': collections['history'].count_documents({})
            },
            {
                'key': 'kc',
                'label': 'Boss Kill Counts',
                'description': "Each player's latest kill count per boss.",
                'count': len(collections['kc'].distinct('player'))
            },
            {
                'key': 'personal_bests',
                'label': 'Personal Bests',
                'description': 'Fastest recorded time per player/boss.',
                'count': collections['personal_bests'].count_documents({})
            },
            {
                'key': 'rank_history',
                'label': 'Group Rank History',
                'description': 'GIM group rank/prestige/XP snapshots over time.',
                'count': collections['rank_history'].count_documents({})
            }
        ]
        return jsonify({'datasets': datasets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/export/<dataset>', methods=['GET'])
@limiter.limit("10 per minute")
def export_dataset(dataset):
    """Download a full dataset as CSV, for players who want to build their own analytics."""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    if dataset not in EXPORT_DATASETS:
        return jsonify({'error': f'Unknown dataset "{dataset}". Choose from: {", ".join(EXPORT_DATASETS)}'}), 404

    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        if dataset == 'history':
            docs = list(collections['history'].find({}, {'_id': 0}).sort('timestamp', -1))
            rows = []
            for d in docs:
                ts = d.get('timestamp')
                rows.append({
                    'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else ts,
                    'player': d.get('player'),
                    'item': d.get('item'),
                    'drop_type': d.get('drop_type'),
                    'value': d.get('value'),
                    'value_string': d.get('value_string'),
                    'rarity': d.get('rarity'),
                    'rarity_1_in': d.get('rarity_1_in'),
                    'source': d.get('source'),
                })
            fieldnames = ['timestamp', 'player', 'item', 'drop_type', 'value', 'value_string', 'rarity', 'rarity_1_in', 'source']

        elif dataset == 'kc':
            pipeline = [
                {'$sort': {'timestamp': -1}},
                {'$group': {'_id': '$player', 'latest_snapshot': {'$first': '$$ROOT'}}}
            ]
            results = list(collections['kc'].aggregate(pipeline))
            _excluded = {'Brutus'}
            rows = []
            for result in results:
                player = result['_id']
                snapshot = result['latest_snapshot']
                ts = snapshot.get('timestamp')
                ts_iso = ts.isoformat() if hasattr(ts, 'isoformat') else ts
                for boss, kc in snapshot.get('bosses', {}).items():
                    if boss in _excluded:
                        continue
                    rows.append({
                        'player': player,
                        'boss': boss,
                        'kill_count': kc,
                        'snapshot_type': snapshot.get('snapshot_type'),
                        'snapshot_timestamp': ts_iso,
                    })
            rows.sort(key=lambda r: (r['player'].lower(), r['boss'].lower()))
            fieldnames = ['player', 'boss', 'kill_count', 'snapshot_type', 'snapshot_timestamp']

        elif dataset == 'personal_bests':
            all_records = list(collections['personal_bests'].find({}, {'_id': 0}).sort('time_seconds', 1))
            best = {}
            for rec in all_records:
                if not rec.get('boss') or not rec.get('player'):
                    continue
                key = (rec['player'].lower(), rec['boss'].lower(), rec.get('party_size', 1), rec.get('invocation_level'))
                if key not in best or rec['time_seconds'] < best[key]['time_seconds']:
                    best[key] = rec
            result = sorted(best.values(), key=lambda x: (x['boss'].lower(), x['player'].lower()))
            rows = []
            for rec in result:
                ts = rec.get('timestamp')
                rows.append({
                    'player': rec.get('player'),
                    'boss': rec.get('boss'),
                    'time_string': rec.get('time_string'),
                    'time_seconds': rec.get('time_seconds'),
                    'party_size': rec.get('party_size'),
                    'invocation_level': rec.get('invocation_level'),
                    'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else ts,
                })
            fieldnames = ['player', 'boss', 'time_string', 'time_seconds', 'party_size', 'invocation_level', 'timestamp']

        elif dataset == 'rank_history':
            docs = list(collections['rank_history'].find({}, {'_id': 0}).sort('timestamp', 1))
            rows = []
            for d in docs:
                ts = d.get('timestamp')
                rows.append({
                    'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else ts,
                    'rank': d.get('rank'),
                    'prestige_rank': d.get('prestigeRank'),
                    'total_xp': d.get('totalXp'),
                    'rank_change': d.get('rankChange'),
                    'prestige_rank_change': d.get('prestigeRankChange'),
                    'xp_change': d.get('xpChange'),
                })
            fieldnames = ['timestamp', 'rank', 'prestige_rank', 'total_xp', 'rank_change', 'prestige_rank_change', 'xp_change']

        filename = f'{dataset}_export_{datetime.utcnow().strftime("%Y%m%d")}.csv'
        return _csv_response(rows, fieldnames, filename)

    except Exception as e:
        return jsonify({'error': f'Failed to export {dataset}: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Bingo API Server running on port {port}")
    print(f"Discord bot will send drops to: /drop endpoint")
    print(f"History imports to: /history-only endpoint")
    print(f"Deaths tracked at: /death endpoint")
    print(f"Website can fetch data from: /bingo, /history, /deaths, /deaths/by-npc endpoints")
    print(f"GIM proxy available at: /api/gim-proxy")
    print()
    app.run(host='0.0.0.0', port=port, debug=False)