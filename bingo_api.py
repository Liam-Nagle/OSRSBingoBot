from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from GitHub Pages

# Use persistent disk path for data storage
BINGO_FILE = '/data/bingo_data.json' if os.path.exists('/data') else 'bingo_data.json'
ADMIN_PASSWORD = os.environ.get('BINGO_ADMIN_PASSWORD', 'bingo2025')  # Change this or set environment variable
DROP_API_KEY = os.environ.get('DROP_API_KEY', 'your_secret_drop_key_here')  # Set this in Render environment variables

print(
    f"🔐 Admin password is set {'from environment variable' if os.environ.get('BINGO_ADMIN_PASSWORD') else 'to default (change this!)'}")
print(f"   To change: export BINGO_ADMIN_PASSWORD='your_password_here'")
print(
    f"🔑 Drop API key is set {'from environment variable' if os.environ.get('DROP_API_KEY') else 'to default (change this!)'}")
print(f"   To change: export DROP_API_KEY='your_secret_key_here'")
print(f"💾 Data will be saved to: {BINGO_FILE}")
print()


def load_bingo_data():
    if os.path.exists(BINGO_FILE):
        with open(BINGO_FILE, 'r') as f:
            data = json.load(f)
            # Ensure boardSize exists
            if 'boardSize' not in data:
                data['boardSize'] = 5
            # Remove adminPassword from data if it exists (moved to server-side)
            if 'adminPassword' in data:
                del data['adminPassword']
            # Ensure lineBonuses structure exists
            if 'lineBonuses' not in data:
                size = data['boardSize']
                data['lineBonuses'] = {
                    'rows': [50] * size,
                    'cols': [50] * size,
                    'diags': [100, 100]
                }
            return data
    return {
        'boardSize': 5,
        'tiles': [{'items': [], 'value': 10, 'completedBy': []} for _ in range(25)],
        'completions': {},
        'lineBonuses': {
            'rows': [50, 50, 50, 50, 50],
            'cols': [50, 50, 50, 50, 50],
            'diags': [100, 100]
        }
    }


def save_bingo_data(data):
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
    """Receive drop from Discord bot"""
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
        print(
            f"   Tile {index + 1}: Display='{display_name}' | Matches=[{all_items}] | Completed by: {tile['completedBy']}")

        # Check if item matches any tile items
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
        print(f"✅ Saved updated data to {BINGO_FILE}")
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
    save_bingo_data(data)
    return jsonify({'success': True})


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
    print(f"Website can fetch data from: /bingo endpoint")
    print()
    app.run(host='0.0.0.0', port=port, debug=False)