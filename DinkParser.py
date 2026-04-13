import os
import discord
from discord.ext import commands, tasks
import json
import requests
import asyncio
import re
from datetime import datetime, timedelta
import time
import random
from pymongo import MongoClient

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store drops in memory
drops_data = []

# Bingo API Configuration
BINGO_API_BASE = os.environ.get('BINGO_API_URL', 'http://localhost:5000')
# Remove /drop from end if present (for legacy compatibility)
if BINGO_API_BASE.endswith('/drop'):
    BINGO_API_BASE = BINGO_API_BASE[:-5]

DROP_API_KEY = os.environ.get('DROP_API_KEY', 'your_secret_drop_key_here')

def send_to_bingo_api(player_name, item_name, drop_type='loot', source=None, value=0, value_string=''):
    """Send drop to bingo board API with value information"""
    try:
        response = requests.post(f"{BINGO_API_BASE}/drop",
            headers={
                'Content-Type': 'application/json',
                'X-API-Key': DROP_API_KEY
            },
            json={
                'player': player_name,
                'item': item_name,
                'drop_type': drop_type,
                'source': source,
                'value': value,  # ← NEW: Send numeric value
                'value_string': value_string  # ← NEW: Send original text (e.g., "2.95M")
            },
            timeout=5)

        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"✅ Bingo API: {result.get('message')}")
                for tile in result.get('completedTiles', []):
                    print(f"   Tile {tile['tile']}: {', '.join(tile['items'])} ({tile['value']} points)")
            else:
                print(f"ℹ️  Bingo API: {result.get('message')}")
        elif response.status_code == 401:
            print(f"❌ Bingo API: Unauthorized - Check DROP_API_KEY environment variable")
        else:
            print(f"⚠️  Bingo API returned status {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Could not connect to Bingo API: {e}")
    except Exception as e:
        print(f"❌ Bingo API error: {e}")


def send_to_history_only(player_name, item_name, drop_type='loot', source=None, timestamp=None, value=0, value_string=''):
    """Send drop to history-only endpoint (no tile checking)"""
    try:
        response = requests.post(f"{BINGO_API_BASE}/history-only",
                                 headers={
                                     'Content-Type': 'application/json',
                                     'X-API-Key': DROP_API_KEY
                                 },
                                 json={
                                     'player': player_name,
                                     'item': item_name,
                                     'drop_type': drop_type,
                                     'source': source,
                                     'timestamp': timestamp or datetime.utcnow().isoformat(),
                                     'value': value,
                                     'value_string': value_string
                                 },
                                 timeout=5)

        if response.status_code == 200:
            result = response.json()
            return result.get('success', False), result.get('duplicate', False)
        return False, False
    except Exception as e:
        print(f"❌ History API error: {e}")
        return False, False


def send_death_to_api(player_name, npc=None, timestamp=None):
    """Send death to bingo board API"""
    try:
        response = requests.post(f"{BINGO_API_BASE}/death",
                                 headers={
                                     'Content-Type': 'application/json',
                                     'X-API-Key': DROP_API_KEY
                                 },
                                 json={
                                     'player': player_name,
                                     'npc': npc,
                                     'timestamp': timestamp or datetime.utcnow().isoformat()
                                 },
                                 timeout=5)

        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                npc_text = f" to {npc}" if npc else ""
                print(f"💀 Death recorded: {player_name}{npc_text}")
            return True
        else:
            print(f"⚠️  Death API returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Death API error: {e}")
        return False


def extract_invocation_from_image(image_url):
    """
    Download the Dink game screenshot and OCR the top-left corner for the TOA invocation level.

    In OSRS, the invocation level is shown as white text in the top-left of the game window
    e.g. "Level: 315". We crop that region, isolate white pixels to cut out the dark
    background noise, then run RapidOCR (pure Python, no system binaries needed).
    Returns int or None.
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image, ImageFilter
        import io
        import numpy as np
    except ImportError as e:
        print(f"⚠️  OCR dependencies not installed ({e}) - invocation level will not be read from image")
        return None

    try:
        resp = requests.get(image_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert('RGB')
    except Exception as e:
        print(f"⚠️  Could not download embed image for OCR: {e}")
        return None

    w, h = img.size

    def isolate_white(pil_img):
        """
        Keep only near-white pixels (OSRS invocation level text colour).
        Everything else becomes black so the dark background doesn't confuse the OCR.
        """
        arr = np.array(pil_img, dtype=np.uint8)
        mask = (arr[:, :, 0] > 180) & (arr[:, :, 1] > 180) & (arr[:, :, 2] > 180)
        out = np.zeros_like(arr)
        out[mask] = [255, 255, 255]
        return Image.fromarray(out, mode='RGB')

    def run_ocr(pil_img):
        """Scale 4x (NEAREST preserves pixel-font edges) then run RapidOCR."""
        cw, ch = pil_img.size
        pil_img = pil_img.resize((cw * 4, ch * 4), Image.NEAREST)
        pil_img = pil_img.filter(ImageFilter.SHARPEN)
        engine = RapidOCR()
        result, _ = engine(np.array(pil_img))
        # result is a list of [box, text, confidence] or None
        if not result:
            return ''
        return ' '.join(item[1] for item in result)

    def find_invoc(text):
        """Match 'Level 315' or 'Level: 315'. Valid TOA range is 0–595."""
        m = re.search(r'[Ll]evel\s*:?\s*(\d{1,3})\b', text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 595:
                return val
        return None

    # Attempt 1: tight top-left crop with white pixel isolation
    # (~15% width, ~12% height) — this is where OSRS shows the invocation level
    crop_w = max(int(w * 0.15), 80)
    crop_h = max(int(h * 0.12), 40)
    top_left = img.crop((0, 0, crop_w, crop_h))
    text = run_ocr(isolate_white(top_left))
    print(f"[OCR attempt 1 - top-left white] {text.strip()!r}")
    result = find_invoc(text)
    if result is not None:
        return result

    # Attempt 2: wider crop in case the game window is a different resolution
    crop_w2 = max(int(w * 0.22), 120)
    crop_h2 = max(int(h * 0.18), 60)
    top_left2 = img.crop((0, 0, crop_w2, crop_h2))
    text = run_ocr(isolate_white(top_left2))
    print(f"[OCR attempt 2 - wider top-left white] {text.strip()!r}")
    result = find_invoc(text)
    if result is not None:
        return result

    # Attempt 3: wider crop without colour filter (catches any edge cases)
    text = run_ocr(top_left2)
    print(f"[OCR attempt 3 - wider top-left no filter] {text.strip()!r}")
    result = find_invoc(text)
    if result is not None:
        return result

    print("⚠️  OCR could not find invocation level in embed image")
    return None


def parse_time_to_seconds(time_str):
    """Convert OSRS time string (H:MM:SS or MM:SS or MM:SS.ss) to total seconds"""
    time_str = time_str.strip()
    # H:MM:SS.ss
    match = re.match(r'^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?$', time_str)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        s = int(match.group(3))
        cs = int(match.group(4) or 0)
        return h * 3600 + m * 60 + s + cs / 100
    # MM:SS.ss or MM:SS
    match = re.match(r'^(\d+):(\d{2})(?:\.(\d+))?$', time_str)
    if match:
        m = int(match.group(1))
        s = int(match.group(2))
        cs = int(match.group(3) or 0)
        return m * 60 + s + cs / 100
    return None


def parse_pb_embed(embed, message):
    """Parse a Personal Best or raid completion embed from Dink.

    Handles two cases:
      1. Explicit PB notification: title contains 'Personal Best'
      2. Any raid/boss completion that includes a time field
    """
    pb_info = {
        'timestamp': message.created_at.isoformat(),
        'player': None,
        'boss': None,
        'time_string': None,
        'time_seconds': None,
        'party_size': 1,
        'invocation_level': None
    }

    # Boss name from embed author (Dink "Completion Count" format puts boss in author.name)
    if embed.author and embed.author.name:
        pb_info['boss'] = embed.author.name.strip()

    if embed.description:
        desc = embed.description

        # Player name - "PlayerName has..."
        player_match = re.search(r'^(.+?)\s+has\b', desc, re.MULTILINE)
        if player_match:
            pb_info['player'] = player_match.group(1).strip()

        # Time - "personal best [time] of MM:SS" (Dink Completion Count format) preferred,
        # then bold (**MM:SS**), then bare time anywhere
        time_match = re.search(r'personal best(?:\s+time)? of (\d+:\d{2}(?::\d{2})?(?:\.\d+)?)', desc, re.IGNORECASE)
        if not time_match:
            time_match = re.search(r'\*\*(\d+:\d{2}(?::\d{2})?(?:\.\d+)?)\*\*', desc)
        if not time_match:
            time_match = re.search(r'\b(\d+:\d{2}(?::\d{2})?(?:\.\d+)?)\b', desc)
        if time_match:
            pb_info['time_string'] = time_match.group(1)
            pb_info['time_seconds'] = parse_time_to_seconds(pb_info['time_string'])

        # Invocation level (TOA specific): "invocation level of 350"
        inv_match = re.search(r'invocation level of (\d+)', desc, re.IGNORECASE)
        if inv_match:
            pb_info['invocation_level'] = int(inv_match.group(1))

        # Party size from description: "party of 2" or "party size: 2"
        party_match = re.search(r'party(?:\s+size)?(?:\s+of)?\s*:?\s*(\d+)', desc, re.IGNORECASE)
        if party_match:
            pb_info['party_size'] = int(party_match.group(1))

        # Boss name from description: "has defeated {boss} with..." (Dink Completion Count format)
        if not pb_info['boss']:
            defeated_match = re.search(r'has defeated (.+?)(?:\s+with\s|\n|$)', desc, re.IGNORECASE)
            if defeated_match:
                pb_info['boss'] = defeated_match.group(1).strip()

        # Boss name fallback from description: "personal best in X", "completed X"
        if not pb_info['boss']:
            boss_match = re.search(
                r'(?:personal best in|new best in|new best at|completed|achievement in)\s+(?:the\s+)?(.+?)(?:\s+with|\s*:|\s+in\s+|\.|$)',
                desc, re.IGNORECASE
            )
            if boss_match:
                pb_info['boss'] = boss_match.group(1).strip()

    # Boss name fallback: title suffix after " - " (e.g. "Personal Best - Tombs of Amascut")
    if not pb_info['boss'] and embed.title:
        parts = embed.title.split(' - ', 1)
        if len(parts) == 2:
            pb_info['boss'] = parts[1].strip()

    # Parse embed fields
    for field in embed.fields:
        field_name = (field.name or '').strip()
        field_value = (field.value or '').strip()

        if re.search(r'party\s*size', field_name, re.IGNORECASE):
            size_match = re.search(r'(\d+)', field_value)
            if size_match:
                pb_info['party_size'] = int(size_match.group(1))

        # Some Dink versions put the time in a field
        if re.search(r'\btime\b|\bduration\b', field_name, re.IGNORECASE) and pb_info['time_seconds'] is None:
            t_match = re.search(r'(\d+:\d{2}(?::\d{2})?(?:\.\d+)?)', field_value)
            if t_match:
                pb_info['time_string'] = t_match.group(1)
                pb_info['time_seconds'] = parse_time_to_seconds(pb_info['time_string'])

    # For TOA, try to read invocation level from the embedded game screenshot via OCR.
    # The invocation level only appears in the game UI image, not in any embed text field.
    is_toa = pb_info['boss'] and re.search(r'tombs?\s+of\s+amascut|toa', pb_info['boss'], re.IGNORECASE)
    if is_toa and pb_info['invocation_level'] is None:
        image_url = None
        if embed.image and embed.image.url:
            image_url = embed.image.url
        elif embed.thumbnail and embed.thumbnail.url:
            image_url = embed.thumbnail.url

        if image_url:
            print(f"[OCR] Attempting to read invocation level from image: {image_url[:80]}...")
            pb_info['invocation_level'] = extract_invocation_from_image(image_url)

    return pb_info if pb_info['player'] else None


def send_pb_to_api(player_name, boss_name, time_seconds, time_string, party_size=1, invocation_level=None, timestamp=None):
    """Send personal best to bingo board API"""
    payload = {
        'player': player_name,
        'boss': boss_name,
        'time_seconds': time_seconds,
        'time_string': time_string,
        'party_size': party_size,
        'invocation_level': invocation_level,
        'timestamp': timestamp or datetime.utcnow().isoformat()
    }
    headers = {'Content-Type': 'application/json', 'X-API-Key': DROP_API_KEY}
    for attempt in range(3):
        try:
            response = requests.post(
                f"{BINGO_API_BASE}/pb",
                headers=headers,
                json=payload,
                timeout=15
            )
            if response.status_code == 200:
                result = response.json()
                if result.get('duplicate'):
                    return False, True
                if result.get('success'):
                    print(f"🏆 PB saved: {player_name} - {boss_name} {time_string}"
                          + (f" @ invoc {invocation_level}" if invocation_level else "")
                          + f" (party {party_size})")
                    return True, False
            elif response.status_code in (502, 503, 504):
                print(f"⚠️  PB API {response.status_code} on attempt {attempt + 1}, retrying...")
                time.sleep(3 * (attempt + 1))
                continue
            else:
                print(f"⚠️  PB API returned status {response.status_code}")
                break
        except Exception as e:
            print(f"❌ PB API error (attempt {attempt + 1}): {e}")
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    return False, False


def parse_value(value_str):
    """Convert value strings like '2.95M' to numbers"""
    if value_str.startswith('http') or value_str.startswith('HTTP'):
        return 0

    value_str = value_str.replace('```', '').replace('LDIF', '').replace('ldif', '').replace('\n', '')
    value_str = value_str.upper().replace('GP', '').replace(',', '').strip()

    if not value_str or value_str == '':
        return 0

    try:
        if 'M' in value_str:
            return float(value_str.replace('M', '')) * 1_000_000
        elif 'K' in value_str:
            return float(value_str.replace('K', '')) * 1_000
        else:
            return float(value_str)
    except ValueError:
        if not any(x in value_str for x in ['HTTP', 'HTTPS', 'WWW', '://']):
            print(f"Warning: Could not parse value: {value_str}")
        return 0


def parse_item_line(item_text):
    """Parse Dink item formats:
    - '60 x [Dragonstone](wiki_url) (668K)' - Link with value
    - '1 x [Black mask (10)](wiki_url) (781K)' - Item name with parens + value
    - '60 x [Dragonstone](wiki_url)' - Link without value
    - '60 x Dragonstone (668K)' - No link with value
    """

    # Pattern 1: [Item Name](wiki_url) (value) - Link with value
    # Example: 1 x [Black mask (10)](https://wiki.../Black_mask_(10)) (781K)
    # Use [^\s]+ to match URL (no spaces in URLs) instead of [^\)]+ (breaks on parens in URL)
    pattern_link_value = r'(\d+)\s*x\s*\[([^\]]+)\]\(https?://[^\s]+\)\s*\(([^)]+)\)'
    match = re.search(pattern_link_value, item_text)
    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        value = match.group(3).strip()
        return {
            'quantity': quantity,
            'name': item_name,
            'value': value,
            'value_numeric': parse_value(value)
        }

    # Pattern 2: [Item Name](wiki_url) - Link without value (collection log)
    # Example: 1 x [Dragonstone](https://wiki...)
    pattern_link_only = r'(\d+)\s*x\s*\[([^\]]+)\]\(https?://[^\s]+\)'
    match = re.search(pattern_link_only, item_text)
    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        return {
            'quantity': quantity,
            'name': item_name,
            'value': 'Unknown',
            'value_numeric': 0
        }

    # Pattern 3: Item Name (value) - No link, with value (old format)
    # Example: 60 x Dragonstone (668K)
    pattern_no_link = r'(\d+)\s*x\s*(.+?)\s*\((.+?)\)'
    match = re.search(pattern_no_link, item_text)
    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        value = match.group(3).strip()

        # Skip if it's a URL (shouldn't happen but just in case)
        if value.startswith('http'):
            return {
                'quantity': quantity,
                'name': item_name,
                'value': 'Unknown',
                'value_numeric': 0
            }

        return {
            'quantity': quantity,
            'name': item_name,
            'value': value,
            'value_numeric': parse_value(value)
        }

    # No pattern matched
    return None


@bot.event
async def on_ready():
    print(f'{bot.user} is now tracking Dink notifications!')
    print('Listening for: Loot Drops, Collection Logs, Deaths')
    print('Commands available:')
    print('  !import_history [channel_id] [limit] - Import drop history')
    print('  !import_deaths [channel_id] [limit] - Import death history')
    print('  !import_pbs [channel_id] [limit] - Import personal best history')
    print('  !stats [player] - Show drop statistics')


@bot.event
async def on_message(message):
    # Always process commands first (for !import_history, !stats, etc.)
    await bot.process_commands(message)

    # Only process webhook messages (Dink notifications)
    if message.webhook_id is None:
        return

    if not message.embeds:
        return

    embed = message.embeds[0]

    # Check if this is a "Loot Drop" or "Collection Log" message
    drop_type = None
    if embed.title:
        title_lower = embed.title.lower()  # Convert to lowercase for comparison
        if "loot drop" in title_lower:
            drop_type = 'loot'
        elif "collection log" in title_lower:  # Now catches all variations
            drop_type = 'collection_log'

    if drop_type:
        drop_data = parse_drop_embed(embed, message)

        if drop_data:
            drop_data['drop_type'] = drop_type  # Add drop type to data
            drops_data.append(drop_data)
            print_drop_info(drop_data)

            # Send to bingo board
            if drop_data['player'] and drop_data['items']:
                for item in drop_data['items']:
                    send_to_bingo_api(
                        player_name=drop_data['player'],
                        item_name=item['name'],
                        drop_type=drop_type,  # ← PASS THE DROP TYPE
                        source=drop_data.get('source'),
                        value=item.get('value_numeric', 0),
                        value_string=item.get('value', '')
                    )

            save_drop_to_file(drop_data)

    # Check for Personal Best notification (title "Personal Best" or Dink's "Completion Count" with PB in description)
    elif embed.title and (
        "personal best" in embed.title.lower()
        or ("completion count" in embed.title.lower() and "personal best" in (embed.description or '').lower())
    ):
        pb_data = parse_pb_embed(embed, message)
        if pb_data and pb_data['player'] and pb_data['time_seconds'] is not None:
            print(f"\n{'=' * 50}")
            print(f"🏆 PERSONAL BEST DETECTED!")
            print(f"Player: {pb_data['player']}")
            print(f"Boss: {pb_data['boss']}")
            print(f"Time: {pb_data['time_string']}")
            if pb_data.get('invocation_level') is not None:
                print(f"Invocation: {pb_data['invocation_level']}")
            print(f"Party Size: {pb_data['party_size']}")
            print(f"{'=' * 50}\n")
            send_pb_to_api(
                player_name=pb_data['player'],
                boss_name=pb_data['boss'],
                time_seconds=pb_data['time_seconds'],
                time_string=pb_data['time_string'],
                party_size=pb_data['party_size'],
                invocation_level=pb_data.get('invocation_level'),
                timestamp=pb_data['timestamp']
            )

    # Check for Player Death
    elif embed.title and "Player Death" in embed.title:
        death_data = parse_death_embed(embed, message)

        if death_data:
            print(f"\n{'=' * 50}")
            print(f"💀 PLAYER DEATH DETECTED!")
            print(f"Player: {death_data['player']}")
            if death_data.get('npc'):
                print(f"Cause: {death_data['npc']}")
            print(f"{'=' * 50}\n")

            send_death_to_api(death_data['player'], death_data.get('npc'), death_data['timestamp'])


def parse_drop_embed(embed, message):
    """Extract all information from the Dink embed"""
    drop_info = {
        'timestamp': datetime.now().isoformat(),
        'player': None,
        'items': [],
        'source': None,
        'kill_count': None,
        'total_value': None,
        'rarity': None,
        'drop_type': None
    }

    if embed.title:
        title_lower = embed.title.lower()  # Convert to lowercase
        if "loot drop" in title_lower:
            drop_info['drop_type'] = 'loot'
        elif "collection log" in title_lower:
            drop_info['drop_type'] = 'collection_log'

    if embed.description:
        player_match = re.search(r'(.+?)\s+has looted:', embed.description)
        if player_match:
            drop_info['player'] = player_match.group(1).strip()
        else:
            player_match = re.search(r'(.+?)\s+has added', embed.description)
            if player_match:
                drop_info['player'] = player_match.group(1).strip()

    for field in embed.fields:
        field_name = field.name.strip() if field.name else ""
        field_value = field.value.strip() if field.value else ""

        if 'x' in field_value and ('(' in field_value or '[' in field_value):
            print(f"DEBUG: Parsing field value: {field_value}")
            item = parse_item_line(field_value)
            if item:
                print(f"DEBUG: Parsed item: {item}")
                drop_info['items'].append(item)
            else:
                print(f"DEBUG: Failed to parse!")

        if field_value.startswith('From:') or field_name == 'Source':
            source_text = field_value.replace('From:', '').replace('Source:', '').strip()
            drop_info['source'] = source_text

        if 'Kill Count' in field_name or 'Completion Count' in field_name:
            try:
                count_match = re.search(r'(\d+)', field_value)
                if count_match:
                    drop_info['kill_count'] = int(count_match.group(1))
            except:
                pass

        if 'Total Value' in field_name:
            if not field_value.startswith('http'):
                drop_info['total_value'] = field_value
                drop_info['total_value_numeric'] = parse_value(field_value)

        if 'Item Rarity' in field_name or 'Rank' in field_name:
            drop_info['rarity'] = field_value

    # Always check description for items (especially loot drops with values)
    if embed.description:
        # Collection Log format
        item_match = re.search(r'has added \[(.+?)\](?:\(.+?\))? to their collection', embed.description)
        if item_match:
            item_name = item_match.group(1).strip()
            drop_info['items'].append({
                'quantity': 1,
                'name': item_name,
                'value': 'Collection Log',
                'value_numeric': 0
            })
            print(f"   ✅ Extracted Collection Log item: {item_name}")
        else:
            # Loot Drop format - parse lines for items with values
            lines = embed.description.split('\n')
            for line in lines:
                if ('x' in line and '(' in line) or ('x' in line and '[' in line):
                    item = parse_item_line(line)
                    if item:
                        # Only add if not already in items, or if this one has a value
                        existing = next((i for i in drop_info['items'] if i['name'] == item['name']), None)
                        if not existing or (item.get('value_numeric', 0) > 0 and existing.get('value_numeric', 0) == 0):
                            if existing:
                                drop_info['items'].remove(existing)
                            drop_info['items'].append(item)
                            print(f"   ✅ Extracted item: {item['name']} = {item.get('value', 'no value')}")

    return drop_info if drop_info['player'] else None


def parse_death_embed(embed, message):
    """Extract player name and NPC from death notification"""
    death_info = {
        'timestamp': message.created_at.isoformat(),
        'player': None,
        'npc': None
    }

    if embed.description:
        # Format: "PlayerName has died... to NPC Name"
        # Also handle old format without NPC: "PlayerName has died..."
        death_match = re.search(r'(.+?)\s+has died', embed.description)
        if death_match:
            death_info['player'] = death_match.group(1).strip()

            # Try to extract NPC/location
            npc_match = re.search(r'has died.*?to\s+(.+?)(?:\.|$)', embed.description)
            if npc_match:
                npc_text = npc_match.group(1).strip()

                # Remove markdown links more aggressively
                # Step 1: Complete markdown links [text](url)
                npc_text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', npc_text)

                # Step 2: Incomplete markdown [text](
                npc_text = re.sub(r'\[([^\]]+)\]\(', r'\1', npc_text)

                # Step 3: Just brackets [text]
                npc_text = re.sub(r'\[([^\]]+)\]', r'\1', npc_text)

                # Step 4: Remove any remaining brackets/parentheses
                npc_text = npc_text.replace('[', '').replace(']', '')
                npc_text = npc_text.replace('(', '').replace(')', '')

                # Step 5: Remove URLs
                npc_text = re.sub(r'https?://[^\s]+', '', npc_text)

                # Step 6: Clean whitespace
                npc_text = npc_text.strip()

                # Remove %NPC% placeholder if present
                if npc_text == '%NPC%' or npc_text == '':
                    npc_text = 'Unknown'

                death_info['npc'] = npc_text
                print(f"   💀 Death cause: {death_info['npc']}")

    return death_info if death_info['player'] else None


def print_drop_info(drop_data):
    """Print the drop information to console"""
    print("\n" + "=" * 50)
    drop_type = "COLLECTION LOG" if drop_data['drop_type'] == 'collection_log' else "LOOT DROP"
    print(f"🎉 NEW {drop_type} DETECTED!")
    print(f"Player: {drop_data['player']}")

    for item in drop_data['items']:
        if item['value'] == 'Unknown' or item['value'] == 'Collection Log':
            print(f"Item: {item['quantity']}x {item['name']}")
        else:
            print(f"Item: {item['quantity']}x {item['name']} ({item['value']})")

    if drop_data['source']:
        print(f"Source: {drop_data['source']}")
    if drop_data['kill_count']:
        count_label = "Completion Count" if drop_data['drop_type'] == 'collection_log' else "Kill Count"
        print(f"{count_label}: {drop_data['kill_count']}")
    if drop_data['total_value']:
        print(f"Total Value: {drop_data['total_value']}")
    if drop_data['rarity']:
        print(f"Rarity: {drop_data['rarity']}")
    print("=" * 50 + "\n")


def save_drop_to_file(drop_data):
    """Save drop data to a JSON file"""
    try:
        try:
            with open('drops_log.json', 'r') as f:
                all_drops = json.load(f)
        except FileNotFoundError:
            all_drops = []

        all_drops.append(drop_data)

        with open('drops_log.json', 'w') as f:
            json.dump(all_drops, f, indent=2)

        print(f"✅ Drop saved to drops_log.json")
    except Exception as e:
        print(f"❌ Error saving drop: {e}")


@bot.command()
async def stats(ctx, player_name: str = None):
    """Get drop statistics for a player"""
    if player_name:
        player_drops = [d for d in drops_data if d['player'].lower() == player_name.lower()]
    else:
        player_drops = drops_data

    if not player_drops:
        await ctx.send(f"No drops found{' for ' + player_name if player_name else ''}!")
        return

    total_value = sum(d.get('total_value_numeric', 0) for d in player_drops)
    total_drops = len(player_drops)
    loot_drops = sum(1 for d in player_drops if d.get('drop_type') == 'loot')
    collection_logs = sum(1 for d in player_drops if d.get('drop_type') == 'collection_log')

    msg = f"📊 **Drop Statistics{' for ' + player_name if player_name else ''}**\n"
    msg += f"Total Drops: {total_drops}\n"
    msg += f"Loot Drops: {loot_drops}\n"
    msg += f"Collection Log: {collection_logs}\n"
    msg += f"Total Value: {total_value:,.0f} gp"

    await ctx.send(msg)


@bot.command()
async def import_history(ctx, channel_id: str = None, limit: int = 1000):
    """
    Import historical drops (saves to history only, does NOT complete tiles)

    Usage:
      !import_history                - Import from current channel (last 1000 messages)
      !import_history 123456789      - Import from specific channel ID
      !import_history 123456789 5000 - Import last 5000 messages
    """

    if channel_id:
        try:
            target_channel = await bot.fetch_channel(int(channel_id))
        except ValueError:
            await ctx.send(f"❌ Invalid channel ID: {channel_id}")
            return
        except discord.NotFound:
            await ctx.send(f"❌ Channel not found: {channel_id}")
            return
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have permission to access that channel.")
            return
    else:
        target_channel = ctx.channel

    progress_msg = await ctx.send(
        f"🔍 Importing drop history from {target_channel.mention}...\n"
        f"⚠️ **History only** — tiles will NOT be marked as complete.\n"
        f"📨 Scanning up to **{limit:,}** messages — I'll update every 5,000."
    )

    imported_count = 0
    duplicates = 0
    scanned = 0
    PROGRESS_EVERY = 5000

    try:
        async for message in target_channel.history(limit=limit):
            scanned += 1

            if scanned % PROGRESS_EVERY == 0:
                try:
                    await progress_msg.edit(content=(
                        f"🔍 Importing drop history from {target_channel.mention}...\n"
                        f"📨 **{scanned:,} / {limit:,}** messages scanned\n"
                        f"📥 {imported_count} imported\n 🔁 {duplicates} duplicates"
                    ))
                except Exception:
                    pass

            if message.webhook_id and message.embeds:
                embed = message.embeds[0]

                if embed.title and ("Loot Drop" in embed.title or "Collection Log" in embed.title):
                    drop_data = parse_drop_embed(embed, message)

                    if drop_data:
                        drop_data['timestamp'] = message.created_at.isoformat()

                        if drop_data['player'] and drop_data['items']:
                            for item in drop_data['items']:
                                success, is_dup = send_to_history_only(
                                    drop_data['player'],
                                    item['name'],
                                    drop_type=drop_data['drop_type'],
                                    source=drop_data.get('source'),
                                    timestamp=drop_data['timestamp'],
                                    value=item.get('value_numeric', 0),
                                    value_string=item.get('value', '')
                                )

                                if success:
                                    imported_count += 1
                                elif is_dup:
                                    duplicates += 1

                            await asyncio.sleep(0.1)

        summary = f"✅ **History Import Complete!**\n"
        summary += f"📨 Messages scanned: {scanned:,}\n"
        summary += f"📥 Imported: {imported_count} drops\n"
        if duplicates > 0:
            summary += f"🔁 Deduplicated: {duplicates} (Loot Drop + Collection Log pairs)\n"
        summary += f"\n✅ History populated! Check Analytics → View History"

        await progress_msg.edit(content=summary)
        print(f"📊 History import complete: {scanned} scanned, {imported_count} drops imported, {duplicates} deduplicated")

    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to read message history!")
    except Exception as e:
        await ctx.send(f"❌ Error during import: {str(e)}")
        print(f"Import error: {e}")


@bot.command()
async def import_deaths(ctx, channel_id: str = None, limit: int = 5000):
    """
    Import historical player deaths

    Usage:
      !import_deaths                - Import from current channel (last 5000 messages)
      !import_deaths 123456789      - Import from specific channel ID
      !import_deaths 123456789 10000 - Import last 10000 messages
    """

    if channel_id:
        try:
            target_channel = await bot.fetch_channel(int(channel_id))
        except ValueError:
            await ctx.send(f"❌ Invalid channel ID: {channel_id}")
            return
        except discord.NotFound:
            await ctx.send(f"❌ Channel not found: {channel_id}")
            return
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have permission to access that channel.")
            return
    else:
        target_channel = ctx.channel

    progress_msg = await ctx.send(
        f"💀 Importing death history from {target_channel.mention}...\n"
        f"📨 Scanning up to **{limit:,}** messages — I'll update every 5,000."
    )

    imported_count = 0
    scanned = 0
    PROGRESS_EVERY = 5000

    try:
        async for message in target_channel.history(limit=limit):
            scanned += 1

            if scanned % PROGRESS_EVERY == 0:
                try:
                    await progress_msg.edit(content=(
                        f"💀 Importing death history from {target_channel.mention}...\n"
                        f"📨 **{scanned:,} / {limit:,}** messages scanned &nbsp;·&nbsp; "
                        f"💀 {imported_count} imported"
                    ))
                except Exception:
                    pass

            if message.webhook_id and message.embeds:
                embed = message.embeds[0]

                if embed.title and "Player Death" in embed.title:
                    death_data = parse_death_embed(embed, message)

                    if death_data and death_data['player']:
                        success = send_death_to_api(
                            death_data['player'],
                            npc=death_data.get('npc'),
                            timestamp=death_data['timestamp']
                        )

                        if success:
                            imported_count += 1

                        await asyncio.sleep(0.05)

        summary = f"✅ **Death Import Complete!**\n"
        summary += f"📨 Messages scanned: {scanned:,}\n"
        summary += f"💀 Imported: {imported_count} deaths\n"
        summary += f"\nCheck your bingo board → 💀 Deaths button"

        await progress_msg.edit(content=summary)
        print(f"💀 Death import complete: {scanned} scanned, {imported_count} deaths imported")

    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to read message history!")
    except Exception as e:
        await ctx.send(f"❌ Error during import: {str(e)}")
        print(f"Death import error: {e}")

@bot.command()
async def import_pbs(ctx, channel_id: str = None, limit: int = 5000):
    """
    Scan channel history for Personal Best notifications and backfill the PB tracker.

    Usage:
      !import_pbs                      - Scan current channel (last 5000 messages)
      !import_pbs 123456789            - Scan a specific channel by ID
      !import_pbs 123456789 50000      - Scan last 50000 messages
    """
    if channel_id:
        try:
            target_channel = await bot.fetch_channel(int(channel_id))
        except ValueError:
            await ctx.send(f"❌ Invalid channel ID: {channel_id}")
            return
        except discord.NotFound:
            await ctx.send(f"❌ Channel not found: {channel_id}")
            return
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have permission to access that channel.")
            return
    else:
        target_channel = ctx.channel

    progress_msg = await ctx.send(
        f"🏆 Scanning {target_channel.mention} for Personal Bests...\n"
        f"📨 Scanning up to **{limit:,}** messages — I'll update every 5,000."
    )

    imported_count = 0
    duplicates = 0
    skipped = 0
    scanned = 0
    PROGRESS_EVERY = 5000

    last_message_id = None
    remaining = limit
    done = False

    try:
        while not done and remaining > 0:
            batch_size = min(remaining, 100)
            retries = 0
            messages = []

            while retries < 5:
                try:
                    kwargs = {'limit': batch_size}
                    if last_message_id:
                        kwargs['before'] = discord.Object(id=last_message_id)
                    messages = [m async for m in target_channel.history(**kwargs)]
                    break
                except discord.HTTPException as e:
                    if e.status in (502, 503, 504):
                        retries += 1
                        wait = 5 * retries
                        print(f"⚠️  Discord {e.status} on history fetch, retry {retries}/5 in {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        raise

            if not messages:
                done = True
                break

            for message in messages:
                scanned += 1
                remaining -= 1
                last_message_id = message.id

                if scanned % PROGRESS_EVERY == 0:
                    try:
                        await progress_msg.edit(content=(
                            f"🏆 Scanning {target_channel.mention} for Personal Bests...\n"
                            f"📨 **{scanned:,} / {limit:,}** messages scanned &nbsp;·&nbsp; "
                            f"🏆 {imported_count} imported &nbsp;·&nbsp; 🔁 {duplicates} duplicates"
                        ))
                    except Exception:
                        pass

                if not (message.webhook_id and message.embeds):
                    continue

                embed = message.embeds[0]
                if not embed.title:
                    continue
                title_lower = embed.title.lower()
                desc_lower = (embed.description or '').lower()
                is_pb = (
                    "personal best" in title_lower
                    or ("completion count" in title_lower and "personal best" in desc_lower)
                )
                if not is_pb:
                    continue

                pb_data = parse_pb_embed(embed, message)

                if not pb_data or not pb_data['player'] or pb_data['time_seconds'] is None:
                    skipped += 1
                    continue

                success, is_dup = send_pb_to_api(
                    player_name=pb_data['player'],
                    boss_name=pb_data['boss'],
                    time_seconds=pb_data['time_seconds'],
                    time_string=pb_data['time_string'],
                    party_size=pb_data['party_size'],
                    invocation_level=pb_data.get('invocation_level'),
                    timestamp=pb_data['timestamp']
                )

                if success:
                    imported_count += 1
                elif is_dup:
                    duplicates += 1

                await asyncio.sleep(0.05)

            if len(messages) < batch_size:
                done = True

        summary = f"✅ **PB Import Complete!**\n"
        summary += f"📨 Messages scanned: {scanned:,}\n"
        summary += f"🏆 Imported: {imported_count} personal best{'' if imported_count == 1 else 's'}\n"
        if duplicates > 0:
            summary += f"🔁 Already recorded: {duplicates}\n"
        if skipped > 0:
            summary += f"⚠️ Skipped (no time data): {skipped}\n"

        await progress_msg.edit(content=summary)
        print(f"🏆 PB import complete: {scanned} scanned, {imported_count} imported, {duplicates} duplicates, {skipped} skipped")

    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to read message history!")
    except Exception as e:
        await ctx.send(f"❌ Error during PB import: {str(e)}")
        print(f"PB import error: {e}")


# Run the bot
if __name__ == "__main__":
    TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("❌ ERROR: DISCORD_BOT_TOKEN environment variable not set!")
        print("Please set it in your Render dashboard environment variables.")
        exit(1)

    print("=" * 50)
    print("🤖 OSRS Bingo Drop Tracker Bot + Death Tracker")
    print("=" * 50)
    print(f"Bingo API: {BINGO_API_BASE}")
    print("Tracking: Loot Drops, Collection Log, Deaths")
    print("=" * 50)

    bot.run(TOKEN)