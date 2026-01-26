from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
import requests
import random
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from GitHub Pages

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
    Identify tenant from the current request.
    Priority: API key header > subdomain > default tenant
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

    # Check for tenant_id in query params (useful for testing)
    tenant_id = request.args.get('tenant_id')
    if tenant_id:
        tenant = get_tenant_by_id(tenant_id)
        if tenant:
            return tenant

    # Default to your personal tenant (backward compatibility)
    return get_tenant_by_id(DEFAULT_TENANT_ID)


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

    return {
        'bingo': db[f'tenant_{subdomain}_bingo'],
        'history': db[f'tenant_{subdomain}_history'],
        'deaths': db[f'tenant_{subdomain}_deaths'],
        'rank_history': db[f'tenant_{subdomain}_rank_history'],
        'kc': db[f'tenant_{subdomain}_kc']
    }


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
ADMIN_PASSWORD = os.environ.get('BINGO_ADMIN_PASSWORD', 'bingo2025')
DROP_API_KEY = os.environ.get('DROP_API_KEY', 'your_secret_drop_key_here')

print(
    f"🔐 Admin password is set {'from environment variable' if os.environ.get('BINGO_ADMIN_PASSWORD') else 'to default (change this!)'}")
print(
    f"🔑 Drop API key is set {'from environment variable' if os.environ.get('DROP_API_KEY') else 'to default (change this!)'}")
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

        # WiseOldMan uses different keys for bosses - map them to our format
        boss_mapping = {
            'abyssal_sire': 'Abyssal Sire',
            'alchemical_hydra': 'Alchemical Hydra',
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
            'skotizo': 'Skotizo',
            'spindel': 'Spindel',
            'tempoross': 'Tempoross',
            'the_gauntlet': 'The Gauntlet',
            'the_corrupted_gauntlet': 'The Corrupted Gauntlet',
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
            'zalcano': 'Zalcano',
            'zulrah': 'Zulrah'
        }

        # Extract KC from snapshot
        for wom_key, display_name in boss_mapping.items():
            if wom_key in bosses_data:
                kc = bosses_data[wom_key].get('kills', 0)
                if kc and kc > 0:
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
def fetch_player_kc(player_name):
    """Fetch and store a player's current KC"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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

        all_kc = {}
        for result in results:
            player = result['_id']
            snapshot = result['latest_snapshot']
            all_kc[player] = {
                'bosses': snapshot['bosses'],
                'timestamp': snapshot['timestamp'].isoformat(),
                'snapshot_type': snapshot['snapshot_type']
            }

        return jsonify(all_kc)
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

            effort = {}
            for boss, current_kc in current_bosses.items():
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
def save_kc():
    """Save KC data (called from browser)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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
        # Parse timestamp if it's a string
        if isinstance(message_timestamp, str):
            msg_time = datetime.fromisoformat(message_timestamp.replace('Z', '+00:00'))
        else:
            msg_time = message_timestamp

        # Calculate time window around the message timestamp
        time_start = msg_time - timedelta(seconds=seconds)
        time_end = msg_time + timedelta(seconds=seconds)

        # Check for duplicate within the time window
        duplicate = history_collection.find_one({
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
                # Remove MongoDB _id field
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
        'tiles': [{'items': [], 'value': 10, 'completedBy': [], 'displayTitle': ''} for _ in range(25)],
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


@app.route('/tenant', methods=['GET'])
def get_tenant_info():
    """Get current tenant information"""
    tenant = get_tenant_from_request()

    if not tenant:
        return jsonify({
            'error': 'No tenant found',
            'using_default': True
        }), 404

    # Return safe tenant info (no API key)
    return jsonify({
        'tenant_id': tenant['tenant_id'],
        'name': tenant['name'],
        'subdomain': tenant['subdomain'],
        'plan': tenant['plan'],
        'features': tenant.get('settings', {}).get('features', []),
        'is_founder': tenant.get('is_founder', False)
    })


@app.route('/login', methods=['POST'])
def admin_login():
    """Authenticate admin user"""
    data = request.json
    password = data.get('password')

    if password == ADMIN_PASSWORD:
        return jsonify({'success': True, 'message': 'Login successful'})
    else:
        return jsonify({'success': False, 'message': 'Incorrect password'}), 401


@app.route('/drop', methods=['POST'])
def record_drop():
    """Receive drop from Discord bot - checks tiles AND saves to history"""
    data = request.json
    player_name = data.get('player')
    item_name = data.get('item')
    drop_type = data.get('drop_type', 'loot')  # 'loot' or 'collection_log'
    source = data.get('source')
    value = data.get('value', 0)  #Get value from bot
    value_string = data.get('value_string', '')  #Original value text (e.g., "2.95M")
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())

    # Get tenant from request
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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
                'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                    str) else timestamp
            })
            print(f"[OK] Saved to history collection (type: {drop_type})")
        except Exception as e:
            print(f"[X] Error saving to history: {e}")

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
def manual_drop():
    """Manually add a drop to history ONLY (does NOT check tiles)"""
    data = request.json
    password = data.get('password')

    # Verify admin password
    if password != ADMIN_PASSWORD:
        print(f"[X] Unauthorized manual drop attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    # Get tenant collections
    tenant = get_tenant_from_request()
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

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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


@app.route('/death', methods=['POST'])
def record_death():
    """Record player death"""
    data = request.json
    player_name = data.get('player')
    npc = data.get('npc')
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())

    # Get tenant from request
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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
def cleanup_death_markdown():
    """Clean markdown links from existing death data (admin only)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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
def save_rank_snapshot():
    """Save current rank data (called from frontend)"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Get tenant collections
    tenant = get_tenant_from_request()
    tenant_id = tenant['tenant_id'] if tenant else DEFAULT_TENANT_ID
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


@app.route('/update', methods=['POST'])
def update_board():
    """Update entire board (for syncing from website)"""
    data = request.json
    save_bingo_data(data)
    return jsonify({'success': True})


@app.route('/shuffle-board', methods=['POST'])
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
        if password != ADMIN_PASSWORD:
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
        if password != ADMIN_PASSWORD:
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


@app.route('/manual-override', methods=['POST'])
def manual_override():
    """Manual tile completion override (admin only)"""
    data = request.json
    password = data.get('password')

    # Verify admin password
    if password != ADMIN_PASSWORD:
        print(f"[X] Unauthorized manual override attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    # Get tenant
    tenant = get_tenant_from_request()
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Bingo API Server running on port {port}")
    print(f"Discord bot will send drops to: /drop endpoint")
    print(f"History imports to: /history-only endpoint")
    print(f"Deaths tracked at: /death endpoint")
    print(f"Website can fetch data from: /bingo, /history, /deaths, /deaths/by-npc endpoints")
    print()
    app.run(host='0.0.0.0', port=port, debug=False)