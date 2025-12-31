from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from datetime import datetime, timedelta
from pymongo import MongoClient

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
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())

    print(f"\n{'=' * 60}")
    print(f"📥 Received drop from Discord bot:")
    print(f"   Player: {player_name}")
    print(f"   Item: {item_name}")
    print(f"   Type: {drop_type}")
    print(f"{'=' * 60}")

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    # Check for duplicates in history (within last 5 seconds of the drop timestamp)
    is_duplicate = check_duplicate_in_history(player_name, item_name, timestamp, seconds=5)

    if is_duplicate:
        print(f"⚠️  Duplicate detected - skipping history save (likely Loot Drop + Collection Log)")
    else:
        # Save to history
        if USE_MONGODB:
            try:
                history_collection.insert_one({
                    'player': player_name,
                    'item': item_name,
                    'drop_type': drop_type,
                    'source': source,
                    'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                        str) else timestamp
                })
                print(f"💾 Saved to history collection")
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
            'duplicate': is_duplicate
        })

    print(f"❌ No matching tiles found or already completed")
    print(f"{'=' * 60}\n")
    return jsonify({
        'success': False,
        'message': 'No matching tiles found or already completed',
        'duplicate': is_duplicate
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

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    # Check for duplicates (within 5 seconds of the drop timestamp)
    is_duplicate = check_duplicate_in_history(player_name, item_name, timestamp, seconds=5)

    if is_duplicate:
        return jsonify({
            'success': False,
            'message': 'Duplicate detected - skipped',
            'duplicate': True
        })

    # Save to history
    if USE_MONGODB:
        try:
            history_collection.insert_one({
                'player': player_name,
                'item': item_name,
                'drop_type': drop_type,
                'source': source,
                'timestamp': datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if isinstance(timestamp,
                                                                                                    str) else timestamp
            })
            return jsonify({
                'success': True,
                'message': f'Saved {player_name} - {item_name} to history',
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