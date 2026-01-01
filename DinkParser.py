import os
import discord
from discord.ext import commands
import re
import json
from datetime import datetime, timedelta
import requests
import asyncio

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


def send_to_history_only(player_name, item_name, drop_type='loot', source=None, timestamp=None):
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
                                     'timestamp': timestamp or datetime.utcnow().isoformat()
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
    """Parse '1 x [Item Name] (wiki URL)' or '1 x Item Name (2.95M)' """
    pattern_brackets = r'(\d+)\s*x\s*\[(.+?)\]\s*\((.+?)\)'
    match = re.search(pattern_brackets, item_text)

    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        third_group = match.group(3).strip()

        if third_group.startswith('http'):
            return {
                'quantity': quantity,
                'name': item_name,
                'value': 'Unknown',
                'value_numeric': 0
            }
        else:
            return {
                'quantity': quantity,
                'name': item_name,
                'value': third_group,
                'value_numeric': parse_value(third_group)
            }

    pattern_old = r'(\d+)\s*x\s*(.+?)\s*\((.+?)\)'
    match = re.search(pattern_old, item_text)
    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        value = match.group(3).strip()

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

    return None


@bot.event
async def on_ready():
    print(f'{bot.user} is now tracking Dink notifications!')
    print('Listening for: Loot Drops, Collection Logs, Deaths')
    print('Commands available:')
    print('  !import_history [channel_id] [limit] - Import drop history')
    print('  !import_deaths [channel_id] [limit] - Import death history')
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

    # Check for Loot Drop or Collection Log
    if embed.title and ("Loot Drop" in embed.title or "Collection Log" in embed.title):
        drop_data = parse_drop_embed(embed, message)

        if drop_data:
            drops_data.append(drop_data)
            print_drop_info(drop_data)

            # Send to bingo board
            if drop_data['player'] and drop_data['items']:
                for item in drop_data['items']:
                    send_to_bingo_api(
                        player_name=drop_data['player'],
                        item_name=item['name'],
                        drop_type='loot',
                        source=drop_data.get('source'),
                        value=item.get('value_numeric', 0),  # Send numeric value
                        value_string=item.get('value', '')  # Send value text
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
        if "Loot Drop" in embed.title:
            drop_info['drop_type'] = 'loot'
        elif "Collection Log" in embed.title:
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
            item = parse_item_line(field_value)
            if item:
                drop_info['items'].append(item)

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

    if not drop_info['items'] and embed.description:
        # Collection Log format can be either:
        # - "PlayerName has added [Item Name] to their collection"
        # - "PlayerName has added [Item Name](wiki_url) to their collection"
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
            lines = embed.description.split('\n')
            for line in lines:
                if ('x' in line and '(' in line) or ('x' in line and '[' in line):
                    item = parse_item_line(line)
                    if item:
                        drop_info['items'].append(item)

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
                death_info['npc'] = npc_match.group(1).strip()
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
                                    timestamp=drop_data['timestamp']
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