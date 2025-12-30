from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from GitHub Pages

# MongoDB Configuration
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = 'osrs_bingo'
COLLECTION_NAME = 'bingo_data'
HISTORY_COLLECTION_NAME = 'drop_history'

# Security
ADMIN_PASSWORD = os.environ.get('BINGO_ADMIN_PASSWORD', 'bingo2025')
DROP_API_KEY = os.environ.get('DROP_API_KEY', 'your_secret_drop_key_here')

print("=" * 60)
print("🎮 OSRS Bingo API Server with MongoDB")
print("=" * 60)
print(
    f"🔐 Admin password is set {'from environment variable' if os.environ.get('BINGO_ADMIN_PASSWORD') else 'to default (change this!)'}")
print(f"   To change: export BINGO_ADMIN_PASSWORD='your_password_here'")
print(
    f"🔑 Drop API key is set {'from environment variable' if os.environ.get('DROP_API_KEY') else 'to default (change this!)'}")
print(f"   To change: export DROP_API_KEY='your_secret_key_here'")
print(f"🗄️  MongoDB URI: {'Set from environment' if os.environ.get('MONGODB_URI') else 'Using default (localhost)'}")
print(f"   Database: {DATABASE_NAME}")
print(f"   Collection: {COLLECTION_NAME}")
print(f"   History Collection: {HISTORY_COLLECTION_NAME}")
print("=" * 60)
print()

# MongoDB connection
try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    # Test connection
    client.server_info()
    db = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]
    history_collection = db[HISTORY_COLLECTION_NAME]
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("⚠️  Server will start but data operations will fail!")
    client = None
    db = None
    collection = None
    history_collection = None


def get_default_bingo_data(board_size=5):
    """Create default bingo data structure"""
    total_tiles = board_size * board_size
    return {
        'boardSize': board_size,
        'tiles': [{'items': [], 'value': 10, 'completedBy': [], 'displayTitle': ''} for _ in range(total_tiles)],
        'completions': {},
        'lineBonuses': {
            'rows': [50] * board_size,
            'cols': [50] * board_size,
            'diags': [100, 100]
        },
        'lastUpdated': datetime.utcnow().isoformat()
    }


def load_bingo_data():
    """Load bingo data from MongoDB"""
    if collection is None:
        print("❌ MongoDB not connected, returning default data")
        return get_default_bingo_data()

    try:
        # Find the single bingo board document
        data = collection.find_one({'_id': 'bingo_board'})

        if data:
            # Remove MongoDB's _id field before returning
            data.pop('_id', None)

            # Ensure boardSize exists
            if 'boardSize' not in data:
                data['boardSize'] = 5

            # Ensure lineBonuses structure exists
            if 'lineBonuses' not in data:
                size = data['boardSize']
                data['lineBonuses'] = {
                    'rows': [50] * size,
                    'cols': [50] * size,
                    'diags': [100, 100]
                }

            # Ensure all tiles have displayTitle field (backwards compatibility)
            for tile in data.get('tiles', []):
                if 'displayTitle' not in tile:
                    tile['displayTitle'] = ''

            print("✅ Loaded bingo data from MongoDB")
            return data
        else:
            # No data exists, create default
            print("ℹ️  No existing data found, creating default board")
            default_data = get_default_bingo_data()
            save_bingo_data(default_data)
            return default_data

    except Exception as e:
        print(f"❌ Error loading from MongoDB: {e}")
        return get_default_bingo_data()


def save_bingo_data(data):
    """Save bingo data to MongoDB"""
    if collection is None:
        print("❌ MongoDB not connected, cannot save data")
        return False

    try:
        # Add timestamp
        data['lastUpdated'] = datetime.utcnow().isoformat()

        # Use upsert to either insert or update the single document
        result = collection.replace_one(
            {'_id': 'bingo_board'},
            {**data, '_id': 'bingo_board'},
            upsert=True
        )

        if result.modified_count > 0 or result.upserted_id:
            print("✅ Saved bingo data to MongoDB")
            return True
        else:
            print("ℹ️  No changes to save")
            return True

    except Exception as e:
        print(f"❌ Error saving to MongoDB: {e}")
        return False


def save_drop_to_history(player_name, item_name, tile_completed=False, tiles_info=None):
    """Save drop to history collection"""
    if history_collection is None:
        print("❌ MongoDB not connected, cannot save history")
        return False

    try:
        drop_record = {
            'timestamp': datetime.utcnow(),
            'player': player_name,
            'item': item_name,
            'tileCompleted': tile_completed,
            'tilesInfo': tiles_info or []
        }

        history_collection.insert_one(drop_record)
        print(f"✅ Saved drop to history: {player_name} - {item_name}")
        return True
    except Exception as e:
        print(f"❌ Error saving to history: {e}")
        return False


@app.route('/bingo', methods=['GET'])
def get_bingo():
    """Get current bingo board state"""
    return jsonify(load_bingo_data())


@app.route('/history', methods=['GET'])
def get_history():
    """Get drop history with date filtering"""
    if history_collection is None:
        return jsonify({'error': 'Database not available'}), 503

    try:
        # Get query parameters
        limit = int(request.args.get('limit', 1000))
        player = request.args.get('player', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)

        # Build query
        query = {}

        # Player filter
        if player:
            query['player'] = player

        # Date range filter
        if start_date or end_date:
            query['timestamp'] = {}

            if start_date:
                try:
                    # Parse ISO format date string
                    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    query['timestamp']['$gte'] = start_dt
                    print(f"🔍 Filtering from: {start_dt}")
                except ValueError as e:
                    print(f"⚠️  Invalid start_date format: {e}")

            if end_date:
                try:
                    # Parse ISO format date string and add 1 day to include the entire end date
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    # Add 23:59:59 to include the entire day
                    from datetime import timedelta
                    end_dt = end_dt + timedelta(days=1, seconds=-1)
                    query['timestamp']['$lte'] = end_dt
                    print(f"🔍 Filtering until: {end_dt}")
                except ValueError as e:
                    print(f"⚠️  Invalid end_date format: {e}")

        print(f"🔍 Query: {query}")

        # Fetch history sorted by most recent first
        history = list(history_collection.find(
            query,
            {'_id': 0}  # Exclude MongoDB _id field
        ).sort('timestamp', -1).limit(limit))

        # Convert datetime objects to ISO format strings
        for record in history:
            if 'timestamp' in record and isinstance(record['timestamp'], datetime):
                record['timestamp'] = record['timestamp'].isoformat()

        print(f"✅ Fetched {len(history)} history records")
        return jsonify({
            'success': True,
            'count': len(history),
            'history': history
        })

    except Exception as e:
        print(f"❌ Error fetching history: {e}")
        return jsonify({'error': str(e)}), 500


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
    """Receive drop from Discord bot"""
    # Check API key
    api_key = request.headers.get('X-API-Key')
    if api_key != DROP_API_KEY:
        print(f"❌ Unauthorized drop attempt - invalid API key")
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    player_name = data.get('player')
    item_name = data.get('item')

    print(f"\n{'=' * 60}")
    print(f"📥 Received drop from Discord bot:")
    print(f"   Player: {player_name}")
    print(f"   Item: {item_name}")
    print(f"{'=' * 60}")

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player or item'}), 400

    bingo_data = load_bingo_data()
    updated = False
    completed_tiles = []

    print(f"🔍 Checking {len(bingo_data['tiles'])} tiles...")

    for index, tile in enumerate(bingo_data['tiles']):
        if not tile['items']:
            continue

        display_name = tile['items'][0] if tile['items'] else 'Unknown'
        all_items = ', '.join(tile['items']) if len(tile['items']) > 1 else tile['items'][0]
        is_multi_item = 'requiredItems' in tile and len(tile.get('requiredItems', [])) > 1

        print(
            f"   Tile {index + 1}: Display='{display_name}' | Matches=[{all_items}] | Multi-item: {is_multi_item} | Completed by: {tile['completedBy']}")

        # Check if item matches any tile items
        for tile_item in tile['items']:
            tile_item_clean = tile_item.strip().lower()
            item_name_clean = item_name.strip().lower()

            if tile_item_clean == item_name_clean or tile_item_clean in item_name_clean or item_name_clean in tile_item_clean:
                print(f"      ✓ MATCH: '{item_name}' matches '{tile_item}'")

                # Handle multi-item requirement tiles
                if is_multi_item:
                    # Initialize itemProgress if not exists
                    if 'itemProgress' not in tile:
                        tile['itemProgress'] = {}
                    if player_name not in tile['itemProgress']:
                        tile['itemProgress'][player_name] = []

                    # Add item to player's progress if not already there
                    if tile_item not in tile['itemProgress'][player_name]:
                        tile['itemProgress'][player_name].append(tile_item)
                        updated = True
                        print(
                            f"      → Added {tile_item!r} to {player_name}'s progress: {len(tile['itemProgress'][player_name])}/{len(tile['requiredItems'])}")

                    # Check if player has collected all required items
                    required_items = tile['requiredItems']
                    player_items = tile['itemProgress'][player_name]

                    has_all = all(
                        any(req_item.strip().lower() == pi.strip().lower() for pi in player_items) for req_item in
                        required_items)

                    if has_all and player_name not in tile['completedBy']:
                        tile['completedBy'].append(player_name)
                        completed_tiles.append({
                            'tile': index + 1,
                            'items': tile['items'],
                            'value': tile['value']
                        })
                        print(
                            f"      → 🎉 {player_name} completed multi-item tile! All {len(required_items)} items collected!")
                    elif player_name in tile['completedBy']:
                        print(f"      → {player_name} already completed this tile")
                    else:
                        print(f"      → Progress: {len(player_items)}/{len(required_items)} items")
                else:
                    # Regular tile - single item completion
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

    # Save to history
    save_drop_to_history(
        player_name=player_name,
        item_name=item_name,
        tile_completed=updated,
        tiles_info=completed_tiles
    )

    if updated:
        save_bingo_data(bingo_data)
        print(f"✅ Saved updated data to MongoDB")
        print(f"{'=' * 60}\n")
        return jsonify({
            'success': True,
            'message': f'{player_name} completed {len(completed_tiles)} tile(s)!',
            'completedTiles': completed_tiles
        })

    print(f"❌ No matching tiles found or already completed")
    print(f"{'=' * 60}\n")
    return jsonify({
        'success': False,
        'message': 'No matching tiles found or already completed'
    })


@app.route('/update', methods=['POST'])
def update_board():
    """Update entire board (for syncing from website)"""
    data = request.json
    if save_bingo_data(data):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to save data'}), 500


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

            # Save to history (only on add)
            save_drop_to_history(
                player_name=player_name,
                item_name=tile['items'][0] if tile['items'] else 'Manual Override',
                tile_completed=True,
                tiles_info=[{
                    'tile': tile_index + 1,
                    'items': tile['items'],
                    'value': tile['value']
                }]
            )

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
            # Note: We don't remove from history - history is immutable audit log
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


@app.route('/manual-drop', methods=['POST'])
def manual_drop():
    """Manually add drop to history (admin only) - for drops not on board or missed by bot"""
    data = request.json
    password = data.get('password')

    # Verify admin password
    if password != ADMIN_PASSWORD:
        print(f"❌ Unauthorized manual drop attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    player_name = data.get('playerName')
    item_name = data.get('itemName')

    if not player_name or not item_name:
        return jsonify({'error': 'Missing player name or item name'}), 400

    # Save to history
    save_drop_to_history(
        player_name=player_name,
        item_name=item_name,
        tile_completed=False,
        tiles_info=[]
    )

    print(f"✅ Manual drop added: {player_name} - {item_name}")
    return jsonify({
        'success': True,
        'message': f'Added drop: {player_name} received {item_name}'
    })


@app.route('/delete-history', methods=['POST'])
def delete_history():
    """Delete a drop from history (admin only) - for fixing mistakes or test data"""
    if history_collection is None:
        return jsonify({'error': 'Database not available'}), 503

    data = request.json
    password = data.get('password')

    # Verify admin password
    if password != ADMIN_PASSWORD:
        print(f"❌ Unauthorized delete history attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    player_name = data.get('playerName')
    item_name = data.get('itemName')
    timestamp = data.get('timestamp')

    if not player_name or not item_name or not timestamp:
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        # Convert timestamp string to datetime
        from datetime import datetime as dt
        timestamp_dt = dt.fromisoformat(timestamp.replace('Z', '+00:00'))

        # Delete the specific record
        result = history_collection.delete_one({
            'player': player_name,
            'item': item_name,
            'timestamp': timestamp_dt
        })

        if result.deleted_count > 0:
            print(f"✅ Deleted history record: {player_name} - {item_name} at {timestamp}")
            return jsonify({
                'success': True,
                'message': f'Deleted drop: {player_name} - {item_name}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Drop not found in history'
            }), 404

    except Exception as e:
        print(f"❌ Error deleting history: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    mongo_status = "connected" if collection is not None else "disconnected"
    try:
        if client:
            client.server_info()
            mongo_status = "connected"
    except:
        mongo_status = "disconnected"

    return jsonify({
        'status': 'ok',
        'mongodb': mongo_status,
        'timestamp': datetime.utcnow().isoformat()
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Bingo API Server running on port {port}")
    print(f"Discord bot will send drops to: /drop endpoint")
    print(f"Website can fetch data from: /bingo endpoint")
    print(f"History available at: /history endpoint")
    print(f"Health check available at: /health endpoint")
    print()
    app.run(host='0.0.0.0', port=port, debug=False)