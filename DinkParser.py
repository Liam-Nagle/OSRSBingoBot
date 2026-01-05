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

# MongoDB Setup
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
try:
    mongo_client = MongoClient(MONGODB_URI)
    db = mongo_client['osrs_bingo']
    gim_collection = db['gim_highscore']
    # Test connection
    mongo_client.admin.command('ping')
    print("✅ Connected to MongoDB for GIM tracking")
except Exception as e:
    print(f"⚠️ MongoDB not available: {e}")
    gim_collection = None

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
    print('  !stats [player] - Show drop statistics')
    # Start the GIM auto-update task
    if not auto_update_gim.is_running():
        auto_update_gim.start()
        print('🔄 Started GIM auto-update task')


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

                # Remove markdown links: [NPC Name](URL) -> NPC Name
                npc_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', npc_text)

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
            target_channel = bot.get_channel(int(channel_id))
            if not target_channel:
                await ctx.send(f"❌ Could not find channel with ID: {channel_id}")
                return
        except ValueError:
            await ctx.send(f"❌ Invalid channel ID: {channel_id}")
            return
    else:
        target_channel = ctx.channel

    await ctx.send(f"🔍 Importing drop history from {target_channel.mention} (last {limit} messages)...\n"
                   f"⚠️ **History only** - tiles will NOT be marked as complete.\n"
                   f"This may take a while!")

    imported_count = 0
    duplicates = 0

    try:
        async for message in target_channel.history(limit=limit):
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
        summary += f"📥 Imported: {imported_count} drops\n"
        if duplicates > 0:
            summary += f"🔁 Deduplicated: {duplicates} (Loot Drop + Collection Log pairs)\n"
        summary += f"\n✅ History populated! Check Analytics → View History"

        await ctx.send(summary)
        print(f"📊 History import complete: {imported_count} drops imported, {duplicates} deduplicated")

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
            target_channel = bot.get_channel(int(channel_id))
            if not target_channel:
                await ctx.send(f"❌ Could not find channel with ID: {channel_id}")
                return
        except ValueError:
            await ctx.send(f"❌ Invalid channel ID: {channel_id}")
            return
    else:
        target_channel = ctx.channel

    await ctx.send(f"💀 Importing death history from {target_channel.mention} (last {limit} messages)...\n"
                   f"This may take a while!")

    imported_count = 0

    try:
        async for message in target_channel.history(limit=limit):
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
        summary += f"💀 Imported: {imported_count} deaths\n"
        summary += f"\n Check your bingo board → 💀 Deaths button"

        await ctx.send(summary)
        print(f"💀 Death import complete: {imported_count} deaths imported")

    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to read message history!")
    except Exception as e:
        await ctx.send(f"❌ Error during import: {str(e)}")
        print(f"Death import error: {e}")


async def scrape_gim_highscore():
    """Scrape OSRS GIM hiscores for Unsociables group"""
    try:
        if gim_collection is None:
            print("❌ MongoDB not available - cannot save GIM data")
            return False

        group_name = 'unsociables'

        print(f"\n{'=' * 60}")
        print(f"🛡️ Scraping GIM Highscore for: {group_name}")
        print(f"{'=' * 60}")

        # More realistic browser headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'DNT': '1'
        }

        base_url = 'https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/?groupSize=5&page='

        overall_rank = None
        total_xp = None
        prestige_count = 0
        found = False

        # Start with a session for cookies
        session = requests.Session()

        # Try to get initial cookies by visiting the homepage first
        print("🌐 Getting initial session...")
        try:
            session.get('https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/',
                        headers=headers, timeout=15)
            time.sleep(random.uniform(2.0, 4.0))
        except:
            pass

        # Search through pages (max 150 pages)
        for page in range(1, 151):
            if found:
                break

            url = f"{base_url}{page}"

            try:
                print(f"📄 Fetching page {page}...")

                # Longer random delay (3-5 seconds) to look more human
                time.sleep(random.uniform(3.0, 5.0))

                response = session.get(url, headers=headers, timeout=15)

                if response.status_code == 403:
                    print(f"⚠️  Page {page} blocked (403) - trying with different approach...")
                    # Wait longer and try again
                    time.sleep(random.uniform(5.0, 8.0))
                    response = session.get(url, headers=headers, timeout=15)

                    if response.status_code == 403:
                        print(f"❌ Still blocked - stopping search")
                        break

                if response.status_code != 200:
                    print(f"⚠️  Page {page} returned status {response.status_code}")
                    continue

                html = response.text

                # Parse tbody
                tbody_match = re.search(r'<tbody[^>]*>(.*?)</tbody>', html, re.DOTALL)
                if not tbody_match:
                    print(f"⚠️  No tbody found on page {page}")
                    continue

                tbody_content = tbody_match.group(1)
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody_content, re.DOTALL)

                print(f"   Found {len(rows)} rows")

                for row_html in rows:
                    cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)

                    if len(cells) < 4:
                        continue

                    # Cell 0: Rank
                    rank_text = re.sub(r'<.*?>', '', cells[0]).strip()
                    try:
                        rank = int(rank_text.replace(',', ''))
                    except:
                        continue

                    # Cell 1: Group name
                    name_cell = cells[1]
                    has_star = '<img' in name_cell and ('prestige' in name_cell.lower() or 'star' in name_cell.lower())
                    clean_name = re.sub(r'<.*?>', '', name_cell).strip().lower()

                    # Cell 3: XP
                    xp_text = re.sub(r'<.*?>', '', cells[3]).strip()
                    try:
                        xp = int(xp_text.replace(',', ''))
                    except:
                        xp = None

                    # Check if this is our group
                    if group_name in clean_name:
                        print(f"\n✅ FOUND: '{clean_name}' at rank #{rank}")

                        overall_rank = rank
                        total_xp = xp
                        found = True

                        if total_xp:
                            print(f"💎 Total XP: {total_xp:,}")

                        if has_star:
                            prestige_count += 1
                            print(f"⭐ Group has PRESTIGE status!")
                        else:
                            print(f"❌ Group does NOT have prestige")

                        break

                    # Count prestige groups before us
                    if has_star and not found:
                        prestige_count += 1

                # Progress update every 5 pages
                if page % 5 == 0 and not found:
                    print(f"   💤 Checked {prestige_count} prestige groups so far...")

            except Exception as e:
                print(f"❌ Error on page {page}: {e}")
                # Wait longer on error
                time.sleep(random.uniform(5.0, 8.0))
                continue

        if not found:
            print(f"❌ Group '{group_name}' not found")
            return False

        # Calculate prestige rank
        prestige_rank = prestige_count if prestige_count > 0 else None

        print(f"\n📊 FINAL RESULTS:")
        print(f"   Overall Rank: #{overall_rank:,}")
        if prestige_rank:
            print(f"   Prestige Rank: #{prestige_rank:,} ⭐")
        else:
            print(f"   Prestige: LOST")
        if total_xp:
            print(f"   Total XP: {total_xp:,}")
        print(f"{'=' * 60}\n")

        # Save to MongoDB
        gim_data = {
            'group_name': 'Unsociables',
            'overall_rank': overall_rank,
            'prestige_rank': prestige_rank,
            'has_prestige': prestige_rank is not None,
            'total_xp': total_xp,
            'updated_at': datetime.utcnow()
        }

        gim_collection.update_one(
            {'group_name': 'Unsociables'},
            {'$set': gim_data},
            upsert=True
        )

        print(f"💾 Saved to MongoDB")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


@bot.command()
async def gimrank(ctx):
    """Update GIM highscore"""
    await ctx.send("🛡️ Updating GIM highscore... 1-2 minutes.")
    success = await scrape_gim_highscore()

    if success:
        await ctx.send("✅ Updated!")
    else:
        await ctx.send("❌ Failed - check logs")




@tasks.loop(hours=24)
async def auto_update_gim():
    print("🔄 Auto-updating GIM highscore...")
    await scrape_gim_highscore()

@auto_update_gim.before_loop
async def before_auto_update():
    await bot.wait_until_ready()
    await asyncio.sleep(300)



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