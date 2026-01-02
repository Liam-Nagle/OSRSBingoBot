from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from GitHub Pages

# MongoDB Configuration
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client['osrs_bingo']

# Collections
bingo_collection = db['bingo_board']
history_collection = db['drop_history']
deaths_collection = db['deaths']

# Fallback to file-based storage if MongoDB not available
USE_MONGODB = True
try:
    # Test MongoDB connection
    mongo_client.admin.command('ping')
    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"⚠️  MongoDB not available, falling back to file storage: {e}")
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

# OSRS Highscores fetcher
def fetch_osrs_highscores(player_name):
    """Fetch player's KC from OSRS highscores"""
    try:
        url = f"https://secure.runescape.com/m=hiscore_oldschool/index_lite.php?player={player_name}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            print(f"Failed to fetch highscores for {player_name}: HTTP {response.status_code}")
            return None

        # Parse CSV response
        lines = response.text.strip().split('\n')

        # Boss/Activity names in the order they appear in highscores (after skills)
        # First 24 lines are skills, lines 24+ are bosses/activities
        boss_names = [
            "Bounty Hunter - Hunter",
            "Bounty Hunter - Rogue",
            "Bounty Hunter (Legacy) - Hunter",
            "Bounty Hunter (Legacy) - Rogue",
            "Clue Scrolls (all)",
            "Clue Scrolls (beginner)",
            "Clue Scrolls (easy)",
            "Clue Scrolls (medium)",
            "Clue Scrolls (hard)",
            "Clue Scrolls (elite)",
            "Clue Scrolls (master)",
            "LMS - Rank",
            "PvP Arena - Rank",
            "Soul Wars Zeal",
            "Rifts closed",
            "Abyssal Sire",
            "Alchemical Hydra",
            "Artio",
            "Barrows Chests",
            "Bryophyta",
            "Callisto",
            "Cal'varion",
            "Cerberus",
            "Chambers of Xeric",
            "Chambers of Xeric: Challenge Mode",
            "Chaos Elemental",
            "Chaos Fanatic",
            "Commander Zilyana",
            "Corporeal Beast",
            "Crazy Archaeologist",
            "Dagannoth Prime",
            "Dagannoth Rex",
            "Dagannoth Supreme",
            "Deranged Archaeologist",
            "Duke Sucellus",
            "General Graardor",
            "Giant Mole",
            "Grotesque Guardians",
            "Hespori",
            "Kalphite Queen",
            "King Black Dragon",
            "Kraken",
            "Kree'Arra",
            "K'ril Tsutsaroth",
            "Mimic",
            "Nex",
            "Nightmare",
            "Phosani's Nightmare",
            "Obor",
            "Phantom Muspah",
            "Sarachnis",
            "Scorpia",
            "Skotizo",
            "Spindel",
            "Tempoross",
            "The Gauntlet",
            "The Corrupted Gauntlet",
            "The Leviathan",
            "The Whisperer",
            "Theatre of Blood",
            "Theatre of Blood: Hard Mode",
            "Thermonuclear Smoke Devil",
            "Tombs of Amascut",
            "Tombs of Amascut: Expert Mode",
            "TzKal-Zuk",
            "TzTok-Jad",
            "Vardorvis",
            "Venenatis",
            "Vet'ion",
            "Vorkath",
            "Wintertodt",
            "Zalcano",
            "Zulrah"
        ]

        boss_data = {}

        # Skip first 24 lines (skills), then parse bosses
        boss_lines = lines[24:]

        for i, line in enumerate(boss_lines):
            if i >= len(boss_names):
                break

            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    # parts[0] = rank, parts[1] = score (KC)
                    kc = int(parts[1])
                    if kc > 0:  # Only include bosses with KC
                        boss_data[boss_names[i]] = kc
                except (ValueError, IndexError):
                    pass

        print(f"Fetched {len(boss_data)} boss KCs for {player_name}")
        return boss_data if boss_data else None

    except Exception as e:
        print(f"Error fetching highscores for {player_name}: {e}")
        return None


@app.route('/kc/fetch/<player_name>', methods=['POST'])
def fetch_player_kc(player_name):
    """Fetch and store a player's current KC"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    # Fetch from OSRS
    kc_data = fetch_osrs_highscores(player_name)

    if not kc_data:
        return jsonify({'error': f'Could not fetch KC for {player_name}'}), 404

    # Store snapshot
    try:
        kc_collection.insert_one({
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
    print("🚀 FUNCTION STARTED!")  # ADD THIS LINE
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    data = request.json
    snapshot_type = data.get('type', 'manual')  # 'start', 'current', 'manual'

    # Get all unique players from history
    players = history_collection.distinct('player')

    results = []
    print(f"\n{'=' * 60}")
    print(f"🔍 Fetching KC for {len(players)} players: {players}")
    print(f"{'=' * 60}")

    for player in players:
        print(f"\n📥 Trying to fetch: {player}")
        kc_data = fetch_osrs_highscores(player)

        if kc_data:
            print(f"✅ Got {len(kc_data)} bosses")
            try:
                result = kc_collection.insert_one({
                    'player': player,
                    'timestamp': datetime.utcnow(),
                    'snapshot_type': snapshot_type,
                    'bosses': kc_data
                })
                print(f"💾 Saved! MongoDB ID: {result.inserted_id}")
                results.append({'player': player, 'success': True})
            except Exception as e:
                print(f"❌ Save failed: {e}")
                results.append({'player': player, 'success': False})
        else:
            print(f"❌ No KC data (player might have 0 bosses or doesn't exist)")
            results.append({'player': player, 'success': False})

    return jsonify({
        'success': True,
        'snapshots': len(results),
        'results': results
    })


@app.route('/kc/player/<player_name>', methods=['GET'])
def get_player_kc(player_name):
    """Get a player's KC history"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    try:
        # Get all snapshots for this player
        snapshots = list(kc_collection.find(
            {'player': player_name},
            sort=[('timestamp', -1)]
        ))

        # Convert ObjectId to string
        for snapshot in snapshots:
            snapshot['_id'] = str(snapshot['_id'])
            snapshot['timestamp'] = snapshot['timestamp'].isoformat()

        # Get starting snapshot
        start_snapshot = kc_collection.find_one(
            {'player': player_name, 'snapshot_type': 'start'},
            sort=[('timestamp', 1)]
        )

        # Get current snapshot
        current_snapshot = kc_collection.find_one(
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

        results = list(kc_collection.aggregate(pipeline))

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

    try:
        # Get latest snapshot for each player
        pipeline = [
            {'$sort': {'timestamp': -1}},
            {'$group': {
                '_id': '$player',
                'latest_snapshot': {'$first': '$$ROOT'}
            }}
        ]

        results = list(kc_collection.aggregate(pipeline))

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


# Initialize KC collection
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


def load_bingo_data():
    """Load bingo board data from MongoDB or file"""
    if USE_MONGODB:
        try:
            board = bingo_collection.find_one({'type': 'current_board'})
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


def save_bingo_data(data):
    """Save bingo board data to MongoDB or file"""
    if USE_MONGODB:
        try:
            data['type'] = 'current_board'
            bingo_collection.replace_one(
                {'type': 'current_board'},
                data,
                upsert=True
            )
            print("✅ Saved to MongoDB")
            return
        except Exception as e:
            print(f"Error saving to MongoDB: {e}")

    # Fallback to file storage
    with open(BINGO_FILE, 'w') as f:
        json.dump(data, f, indent=2)


@app.route('/bingo', methods=['GET'])
def get_bingo():
    """Get current bingo board state"""
    return jsonify(load_bingo_data())


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

    print(f"\n{'=' * 60}")
    print(f"📥 Received drop from Discord bot:")
    print(f"   Player: {player_name}")
    print(f"   Item: {item_name}")
    print(f"   Type: {drop_type}")
    print(f"   Value: {value_string} ({value:,.0f} gp)")  #Show value
    print(f"{'=' * 60}")

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    # Save to history (no deduplication - track both separately)
    if USE_MONGODB:
        try:
            history_collection.insert_one({
                'player': player_name,
                'item': item_name,
                'drop_type': drop_type,
                'source': source,
                'value': value,
                'value_string': value_string,
                'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                    str) else timestamp
            })
            print(f"💾 Saved to history collection (type: {drop_type})")
        except Exception as e:
            print(f"❌ Error saving to history: {e}")

    # Check tiles for completion
    bingo_data = load_bingo_data()
    updated = False
    completed_tiles = []

    print(f"🔍 Checking {len(bingo_data['tiles'])} tiles...")

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

                if tile_item_clean == item_name_clean or tile_item_clean in item_name_clean or item_name_clean in tile_item_clean:
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
        save_bingo_data(bingo_data)
        print(f"✅ Saved updated board data")
        print(f"{'=' * 60}\n")
        return jsonify({
            'success': True,
            'message': f'{player_name} completed {len(completed_tiles)} tile(s)!',
            'completedTiles': completed_tiles,
            'duplicate': False
        })

    print(f"❌ No matching tiles found or already completed")
    print(f"{'=' * 60}\n")
    return jsonify({
        'success': False,
        'message': 'No matching tiles found or already completed',
        'duplicate': False
    })


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

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    # Save to history (no deduplication - track both Collection Log and Loot Drop)
    if USE_MONGODB:
        try:
            history_collection.insert_one({
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

    npc_text = f" to {npc}" if npc else ""
    print(f"\n💀 Death recorded: {player_name}{npc_text}")

    if not player_name:
        return jsonify({'error': 'Missing player name'}), 400

    if USE_MONGODB:
        try:
            deaths_collection.insert_one({
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

@app.route('/deaths', methods=['GET'])
def get_deaths():
    """Get death statistics"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    try:
        # ⭐ FIX: Sort by timestamp BEFORE grouping
        pipeline = [
            {
                '$sort': {'timestamp': -1}  # ← Sort newest first
            },
            {
                '$group': {
                    '_id': '$player',
                    'deaths': {'$sum': 1},
                    'last_death': {'$first': '$timestamp'},  # ← First = most recent
                    'last_npc': {'$first': '$npc'}  # ← Get NPC from most recent death
                }
            },
            {
                '$sort': {'deaths': -1}  # Sort by death count
            }
        ]

        results = list(deaths_collection.aggregate(pipeline))

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
        
        results = list(deaths_collection.aggregate(pipeline))
        
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


@app.route('/history', methods=['GET'])
def get_history():
    """Get drop history with optional filters"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

    try:
        # Get query parameters
        player = request.args.get('player')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        drop_type = request.args.get('type')  # NEW: 'loot' or 'collection_log'
        min_value = request.args.get('minValue')  # NEW: minimum value filter
        search = request.args.get('search')  # NEW: item name search
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

        # NEW: Drop type filter
        if drop_type:
            query['drop_type'] = drop_type

        # NEW: Minimum value filter
        if min_value:
            query['value'] = {'$gte': int(min_value)}

        # NEW: Item search filter (case-insensitive)
        if search:
            query['item'] = {'$regex': search, '$options': 'i'}

        # Fetch history
        history = list(history_collection.find(query).sort('timestamp', -1).limit(limit))

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


@app.route('/deaths/by-player-npc', methods=['GET'])
def get_deaths_by_player_npc():
    """Get detailed death statistics: how many times each player died to each NPC"""
    if not USE_MONGODB:
        return jsonify({'error': 'MongoDB not available'}), 503

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

        results = list(deaths_collection.aggregate(pipeline))

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
        print(f"❌ Unauthorized manual override attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    tile_index = data.get('tileIndex')
    player_name = data.get('playerName')
    action = data.get('action')  # 'add' or 'remove'

    if tile_index is None or not player_name or not action:
        return jsonify({'error': 'Missing required fields'}), 400

    bingo_data = load_bingo_data()

    if tile_index < 0 or tile_index >= len(bingo_data['tiles']):
        return jsonify({'error': 'Invalid tile index'}), 400

    tile = bingo_data['tiles'][tile_index]

    if action == 'add':
        if player_name not in tile['completedBy']:
            tile['completedBy'].append(player_name)
            save_bingo_data(bingo_data)
            print(f"✅ Manual override: Added {player_name} to tile {tile_index + 1}")
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
            save_bingo_data(bingo_data)
            print(f"✅ Manual override: Removed {player_name} from tile {tile_index + 1}")
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