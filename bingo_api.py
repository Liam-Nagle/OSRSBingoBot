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
    Priority: API key header > `board` query param > subdomain > default tenant

    Trusts a `?board=<slug>` query param (matched against each tenant's
    `subdomain` field, reused here as its public URL slug - see Phase 1,
    board routing without real subdomains). This is safe for the same reason
    reads are already public: `board` only picks WHICH tenant's already-public
    data a read returns, or which tenant's password a write endpoint checks
    a submitted password against - it can't skip or weaken any auth check
    itself. That's different from the still-deliberately-unhonored
    `?tenant_id=` param below: pure impersonation with no auth of its own,
    not "which public tenant am I looking at".

    Deliberately does NOT trust a `?tenant_id=` query param: that's an
    unauthenticated field anyone can set to any value, so honoring it here
    let any request impersonate any tenant on every endpoint that used this
    for its identity. Reads are public data by design, so browsers/scripts
    without a matching `board` param, Origin, or API key just fall through
    to the default tenant. Endpoints that actually change data must not rely
    on this function alone - see get_authenticated_tenant_by_api_key/
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

    # Public board URL: yoursite.com/?board=<slug> - the no-subdomain routing path.
    # Accepts either the query param directly (shareable links) or an
    # X-Board-Slug header (what the frontend actually sends on every fetch,
    # once it's parsed `board` out of its own page URL once at load) - same
    # trust level either way, see docstring above.
    board_slug = request.args.get('board') or request.headers.get('X-Board-Slug')
    if board_slug:
        tenant = get_tenant_by_subdomain(board_slug)
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
        'archive': db[f'tenant_{subdomain}_archive']
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

    # Owner and paid plans have every feature - no need to also list every
    # feature in settings.features for them.
    if tenant.get('plan') in PREMIUM_PLANS:
        return True

    # Check settings (the escape hatch for one-off grants on an otherwise-free tenant)
    settings = tenant.get('settings', {})
    features = settings.get('features', [])

    return 'all' in features or feature in features


def require_premium_feature(tenant, feature):
    """
    Gate for a route that's entirely premium (personal bests, death tracking,
    boss KC, rank history, data export). Returns a (response, 403) tuple to
    `return` straight out of the route when the tenant doesn't have the
    feature, or None when it's fine to continue:

        blocked = require_premium_feature(tenant, 'boss_kc')
        if blocked:
            return blocked
    """
    if check_tenant_feature(tenant, feature):
        return None
    return jsonify({
        'error': 'premium_feature_required',
        'feature': feature,
        'message': f"'{feature}' requires a Premium plan."
    }), 403


# Plan -> default limits. A tenant's own settings.max_players/max_board_size
# (set explicitly at signup, or by the Stripe webhook on upgrade) take
# precedence over these; this is just the fallback for tenants that predate
# a given field, or that never got settings written at all.
PREMIUM_PLANS = {'premium_small', 'premium_large', 'owner'}
PLAN_LIMITS = {
    'free': {'max_players': 3, 'max_board_size': 5},
    'premium_small': {'max_players': 5, 'max_board_size': 9},
    'premium_large': {'max_players': None, 'max_board_size': 9},
    'owner': {'max_players': None, 'max_board_size': None},
}


def get_tenant_limits(tenant):
    """Resolve the effective {max_players, max_board_size} for a tenant. None means unlimited."""
    if not tenant:
        return PLAN_LIMITS['free']
    plan_defaults = PLAN_LIMITS.get(tenant.get('plan'), PLAN_LIMITS['free'])
    settings = tenant.get('settings') or {}
    return {
        'max_players': settings['max_players'] if 'max_players' in settings else plan_defaults['max_players'],
        'max_board_size': settings['max_board_size'] if 'max_board_size' in settings else plan_defaults['max_board_size'],
    }


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

print(
    f"🔐 Fallback admin password is set {'from environment variable' if os.environ.get('BINGO_ADMIN_PASSWORD') else 'to default (change this!)'} (only used by tenants without their own admin_password_hash)")
print(
    f"🔑 Legacy drop API key env var is set {'from environment variable' if os.environ.get('DROP_API_KEY') else 'to default (change this!)'} (only relevant as the seed value for tenants' own api_key)")
print()


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

        # Bosses excluded from all tracking and display
        EXCLUDED_BOSSES = {'Brutus'}

        # WiseOldMan uses different keys for bosses - map them to our format
        boss_mapping = {
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

        # Extract KC from snapshot - iterate WiseOldMan's full response so new bosses
        # are picked up automatically without needing a code change.
        # The mapping overrides display names for special cases (apostrophes, abbreviations);
        # anything not in the mapping gets an auto-derived name (underscores → title case).
        for wom_key, boss_value in bosses_data.items():
            kc = boss_value.get('kills', 0)
            if not kc or kc <= 0:
                continue
            display_name = boss_mapping.get(wom_key) or wom_key.replace('_', ' ').title()
            if display_name in EXCLUDED_BOSSES:
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


@app.route('/kc/fetch/<player_name>', methods=['POST'])
@limiter.limit("20 per minute")
def fetch_player_kc(player_name):
    """Fetch and store a player's current KC"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    tenant = get_authenticated_tenant()
    if not tenant:
        return jsonify({'error': 'Unauthorized'}), 401
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
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


@app.route('/kc/player/<player_name>', methods=['GET'])
def get_player_kc(player_name):
    """Get a player's KC history"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
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

        # Get starting snapshot
        start_snapshot = collections['kc'].find_one(
            {'player': player_name, 'snapshot_type': 'start'},
            sort=[('timestamp', 1)]
        )

        # Get current snapshot
        current_snapshot = collections['kc'].find_one(
            {'player': player_name},
            sort=[('timestamp', -1)]
        )

        # Calculate effort (KC gained)
        effort = {}
        if start_snapshot and current_snapshot:
            for boss, current_kc in current_snapshot['bosses'].items():
                start_kc = start_snapshot['bosses'].get(boss, 0)
                gained = current_kc - start_kc
                if gained > 0:
                    effort[boss] = {
                        'start': start_kc,
                        'current': current_kc,
                        'gained': gained
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
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
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

def count_unique_drops(docs, window_seconds=5):
    """
    Count real drop events from history docs, collapsing paired 'loot' + 'collection_log'
    entries that Dink can send for the same physical item pickup (one item, two Discord
    messages) into a single count. Docs are NOT modified or removed - this only affects
    how many "actual drops" we report, not what's stored in history.
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
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
    collections = get_tenant_collections(tenant_id)

    try:
        # Get all players
        players = collections['kc'].distinct('player')

        effort_results = []

        for player in players:
            # Get bingo start snapshot
            start_snapshot = collections['kc'].find_one({
                'player': player,
                'snapshot_type': 'start'
            }, sort=[('timestamp', -1)])

            # Get latest current snapshot
            current_snapshot = collections['kc'].find_one({
                'player': player,
                'snapshot_type': 'current'
            }, sort=[('timestamp', -1)])

            if not start_snapshot or not current_snapshot:
                continue  # Skip if missing either snapshot

            # Calculate effort (current - start)
            start_bosses = start_snapshot.get('bosses', {})
            current_bosses = current_snapshot.get('bosses', {})

            _excluded = {'Brutus'}
            effort = {}
            for boss, current_kc in current_bosses.items():
                if boss in _excluded:
                    continue
                start_kc = start_bosses.get(boss, 0)
                gain = current_kc - start_kc
                if gain > 0:
                    effort[boss] = gain

            if effort:  # Only include if there are gains
                effort_results.append({
                    'player': player,
                    'effort': effort,
                    'start_timestamp': start_snapshot['timestamp'].isoformat(),
                    'current_timestamp': current_snapshot['timestamp'].isoformat()
                })

        if not effort_results:
            return jsonify({
                'success': False,
                'message': 'No bingo start snapshot found. Click "Mark as Bingo Start" to set baseline.',
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
    blocked = require_premium_feature(tenant, 'boss_kc')
    if blocked:
        return blocked
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

    # Enforce the plan's tracked-player cap: a brand new player only counts
    # against the cap once they're about to get their first drop recorded -
    # players already in history keep being tracked regardless of order.
    max_players = get_tenant_limits(tenant)['max_players']
    if max_players is not None and player_name:
        known_players = collections['history'].distinct('player')
        if player_name not in known_players and len(known_players) >= max_players:
            print(f"[!] Drop rejected: player cap reached ({len(known_players)}/{max_players})")
            return jsonify({
                'success': False,
                'message': f'Drop rejected: this board already tracks {max_players} players (plan limit). Upgrade to track more.'
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
    Enrich already-saved history documents with rarity/value data re-scraped
    from old Discord messages (see DinkParser.py's !backfill_rarity command).
    This never inserts new history entries and never overwrites a document
    that already has rarity set or a nonzero value — it only fills gaps left
    by drops logged before those fields existed.

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
        except (ValueError, AttributeError):
            unmatched += 1
            continue

        rarity = candidate.get('rarity')
        rarity_1_in = parse_rarity_denominator(rarity)
        total_value_numeric = candidate.get('total_value_numeric')
        total_value = candidate.get('total_value')

        query = {
            'player': player,
            'item': item,
            'timestamp': {
                '$gte': ts - timedelta(seconds=MATCH_WINDOW_SECONDS),
                '$lte': ts + timedelta(seconds=MATCH_WINDOW_SECONDS)
            },
            '$or': [
                {'rarity': {'$in': [None, '']}},
                {'value': {'$in': [0, None]}}
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

        if update_fields:
            collections['history'].update_one({'_id': target_doc['_id']}, {'$set': update_fields})
            updated += 1

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
    blocked = require_premium_feature(tenant, 'death_tracking')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'death_tracking')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'death_tracking')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'death_tracking')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'rank_history')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'rank_history')
    if blocked:
        return blocked
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

        # Minimum value filter
        if min_value:
            query['value'] = {'$gte': int(min_value)}

        # Item search filter (case-insensitive)
        if search:
            query['item'] = {'$regex': search, '$options': 'i'}

        # Fetch history from tenant collection
        history = list(collections['history'].find(query).sort('timestamp', -1).limit(limit))

        # Format results (remove MongoDB _id)
        for item in history:
            item['_id'] = str(item['_id'])
            if isinstance(item['timestamp'], datetime):
                item['timestamp'] = item['timestamp'].isoformat()

        return jsonify({
            'history': history,
            'count': len(history)
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

    max_board_size = get_tenant_limits(tenant)['max_board_size']
    board_size = data.get('boardSize')
    if max_board_size is not None and board_size and board_size > max_board_size:
        return jsonify({
            'error': 'board_size_limit',
            'message': f'Your plan is limited to {max_board_size}x{max_board_size} boards. Upgrade for bigger boards.',
            'limit': max_board_size
        }), 403

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
    for d in collections['history'].find(match_query):
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

        r1 = d.get('rarity_1_in')
        if r1 and (stats['rarest_drop'] is None or r1 > stats['rarest_drop'][0]):
            stats['rarest_drop'] = (r1, d.get('item'), d.get('rarity'))

    rarest_drop_overall = None  # (rarity_1_in, player)
    for player, stats in drop_stats.items():
        if stats['rarest_drop'] and (rarest_drop_overall is None or stats['rarest_drop'][0] > rarest_drop_overall[0]):
            rarest_drop_overall = (stats['rarest_drop'][0], player)

    # --- KC gained per player, reusing the same start-vs-latest snapshot diff as /kc/player/<name> ---
    kc_gained = {}
    for snap_player in collections['kc'].distinct('player'):
        start_snap = collections['kc'].find_one({'player': snap_player, 'snapshot_type': 'start'}, sort=[('timestamp', 1)])
        current_snap = collections['kc'].find_one({'player': snap_player}, sort=[('timestamp', -1)])
        if start_snap and current_snap:
            total_gained = 0
            for boss, current_kc in current_snap.get('bosses', {}).items():
                gained = current_kc - start_snap.get('bosses', {}).get(boss, 0)
                if gained > 0:
                    total_gained += gained
            if total_gained > 0:
                kc_gained[snap_player] = total_gained

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
            'first_tile': tile_dates.get('first_tile'),
            'first_tile_at': tile_dates.get('first'),
            'last_tile': tile_dates.get('last_tile'),
            'last_tile_at': tile_dates.get('last'),
            'badges': badges
        }

    return recap


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

        # Free tenants only keep the most recent archived event - prune the
        # rest right after inserting the new one, rather than blocking the
        # archive action itself.
        if not check_tenant_feature(tenant, 'unlimited_archive'):
            old_ids = [
                a['_id'] for a in
                collections['archive'].find({}, {'_id': 1}).sort('archived_at', -1).skip(1)
            ]
            if old_ids:
                collections['archive'].delete_many({'_id': {'$in': old_ids}})
                print(f"[*] Pruned {len(old_ids)} older archive(s) (free plan keeps only the latest)")

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
    blocked = require_premium_feature(tenant, 'death_tracking')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'personal_bests')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'personal_bests')
    if blocked:
        return blocked
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
    is_premium = plan in PREMIUM_PLANS
    limits = get_tenant_limits(tenant)

    return jsonify({
        'success': True,
        'tenant': {
            'id': tenant.get('tenant_id'),
            'name': tenant.get('name'),
            'subdomain': tenant.get('subdomain'),
            'plan': plan
        },
        'features': {
            'analytics': is_premium,
            'death_tracking': check_tenant_feature(tenant, 'death_tracking'),
            'boss_kc': check_tenant_feature(tenant, 'boss_kc'),
            'event_timer': is_premium,
            'export_data': check_tenant_feature(tenant, 'export_data'),
            'custom_colors': is_premium,
            'personal_bests': check_tenant_feature(tenant, 'personal_bests'),
            'rank_history': check_tenant_feature(tenant, 'rank_history'),
            'unlimited_events': check_tenant_feature(tenant, 'unlimited_archive'),
            'unlimited_board_size': limits['max_board_size'] is None or limits['max_board_size'] >= 9
        },
        'limits': {
            'board_size': limits['max_board_size'],
            'max_players': limits['max_players']
        }
    })


@app.route('/rank/latest', methods=['GET'])
def get_latest_rank():
    """Get the most recent rank snapshot (for quick widget loading)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    blocked = require_premium_feature(tenant, 'rank_history')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'export_data')
    if blocked:
        return blocked
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
    blocked = require_premium_feature(tenant, 'export_data')
    if blocked:
        return blocked
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