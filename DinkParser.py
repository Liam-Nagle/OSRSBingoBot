import os

import discord
from discord.ext import commands
import re
import json
from datetime import datetime
import requests

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store drops in memory (you can later save to a file or database)
drops_data = []

# Bingo API Configuration - Updated for Render deployment
BINGO_API_URL = os.environ.get('BINGO_API_URL', 'http://localhost:5000/drop')


def send_to_bingo_api(player_name, item_name):
    """Send drop to bingo board API"""
    try:
        response = requests.post(BINGO_API_URL, json={
            'player': player_name,
            'item': item_name
        }, timeout=5)

        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"✅ Bingo API: {result.get('message')}")
                for tile in result.get('completedTiles', []):
                    print(f"   Tile {tile['tile']}: {', '.join(tile['items'])} ({tile['value']} points)")
            else:
                print(f"ℹ️  Bingo API: {result.get('message')}")
        else:
            print(f"⚠️  Bingo API returned status {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Could not connect to Bingo API: {e}")
    except Exception as e:
        print(f"❌ Bingo API error: {e}")


def parse_value(value_str):
    """Convert value strings like '2.95M' to numbers"""
    # Skip if it's a URL
    if value_str.startswith('http') or value_str.startswith('HTTP'):
        return 0

    # Remove Discord code block formatting
    value_str = value_str.replace('```', '').replace('LDIF', '').replace('ldif', '').replace('\n', '')
    value_str = value_str.upper().replace('GP', '').replace(',', '').strip()

    # Handle empty or invalid strings
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
        # Only print warning if it doesn't look like a URL
        if not any(x in value_str for x in ['HTTP', 'HTTPS', 'WWW', '://']):
            print(f"Warning: Could not parse value: {value_str}")
        return 0


def parse_item_line(item_text):
    """Parse '1 x [Item Name] (wiki URL)' or '1 x Item Name (2.95M)' """
    # Try pattern with square brackets first (newer Dink format)
    pattern_brackets = r'(\d+)\s*x\s*\[(.+?)\]\s*\((.+?)\)'
    match = re.search(pattern_brackets, item_text)

    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        third_group = match.group(3).strip()

        # Check if third group is a URL (wiki link) or a value
        if third_group.startswith('http'):
            # It's a wiki URL, no value available
            return {
                'quantity': quantity,
                'name': item_name,
                'value': 'Unknown',
                'value_numeric': 0
            }
        else:
            # It's a value
            return {
                'quantity': quantity,
                'name': item_name,
                'value': third_group,
                'value_numeric': parse_value(third_group)
            }

    # Try old pattern without brackets
    pattern_old = r'(\d+)\s*x\s*(.+?)\s*\((.+?)\)'
    match = re.search(pattern_old, item_text)
    if match:
        quantity = int(match.group(1))
        item_name = match.group(2).strip()
        value = match.group(3).strip()

        # Check if it's a URL
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
    print(f'{bot.user} is now tracking Dink drops!')
    print('Listening for loot drops...')


@bot.event
async def on_message(message):
    # Check if this is a webhook message (Dink posts via webhook)
    if message.webhook_id is None:
        await bot.process_commands(message)
        return

    # Check if message has embeds (Dink uses embeds)
    if not message.embeds:
        await bot.process_commands(message)
        return

    embed = message.embeds[0]

    # Check if this is a "Loot Drop" message
    if embed.title and "Loot Drop" in embed.title:
        drop_data = parse_drop_embed(embed, message)

        if drop_data:
            drops_data.append(drop_data)
            print_drop_info(drop_data)

            # Send to bingo board
            if drop_data['player'] and drop_data['items']:
                for item in drop_data['items']:
                    send_to_bingo_api(drop_data['player'], item['name'])

            # Optional: Save to file
            save_drop_to_file(drop_data)

    await bot.process_commands(message)


def parse_drop_embed(embed, message):
    """Extract all information from the Dink embed"""
    drop_info = {
        'timestamp': datetime.now().isoformat(),
        'player': None,
        'items': [],
        'source': None,
        'kill_count': None,
        'total_value': None,
        'rarity': None
    }

    # Extract player name from description "Vuxten has looted:"
    if embed.description:
        player_match = re.search(r'(.+?)\s+has looted:', embed.description)
        if player_match:
            drop_info['player'] = player_match.group(1).strip()

    # Parse embed fields
    for field in embed.fields:
        field_name = field.name.strip() if field.name else ""
        field_value = field.value.strip() if field.value else ""

        # Extract items (look for 'x' pattern but avoid parsing as value if it contains http)
        if 'x' in field_value and ('(' in field_value or '[' in field_value):
            item = parse_item_line(field_value)
            if item:
                drop_info['items'].append(item)

        # Extract source "From: Brande the Fire Queen"
        if field_value.startswith('From:'):
            drop_info['source'] = field_value.replace('From:', '').strip()

        # Extract stats
        if 'Kill Count' in field_name:
            try:
                drop_info['kill_count'] = int(field_value)
            except:
                pass

        if 'Total Value' in field_name:
            # Only parse if it's not a URL
            if not field_value.startswith('http'):
                drop_info['total_value'] = field_value
                drop_info['total_value_numeric'] = parse_value(field_value)

        if 'Item Rarity' in field_name:
            drop_info['rarity'] = field_value

    # Sometimes item info is in the description
    if not drop_info['items'] and embed.description:
        lines = embed.description.split('\n')
        for line in lines:
            if ('x' in line and '(' in line) or ('x' in line and '[' in line):
                item = parse_item_line(line)
                if item:
                    drop_info['items'].append(item)

    return drop_info if drop_info['player'] else None


def print_drop_info(drop_data):
    """Print the drop information to console"""
    print("\n" + "=" * 50)
    print(f"🎉 NEW DROP DETECTED!")
    print(f"Player: {drop_data['player']}")

    for item in drop_data['items']:
        if item['value'] == 'Unknown':
            print(f"Item: {item['quantity']}x {item['name']}")
        else:
            print(f"Item: {item['quantity']}x {item['name']} ({item['value']})")

    if drop_data['source']:
        print(f"Source: {drop_data['source']}")
    if drop_data['kill_count']:
        print(f"Kill Count: {drop_data['kill_count']}")
    if drop_data['total_value']:
        print(f"Total Value: {drop_data['total_value']}")
    if drop_data['rarity']:
        print(f"Rarity: {drop_data['rarity']}")
    print("=" * 50 + "\n")


def save_drop_to_file(drop_data):
    """Save drop data to a JSON file"""
    try:
        # Read existing data
        try:
            with open('drops_log.json', 'r') as f:
                all_drops = json.load(f)
        except FileNotFoundError:
            all_drops = []

        # Append new drop
        all_drops.append(drop_data)

        # Save back to file
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

    msg = f"📊 **Drop Statistics{' for ' + player_name if player_name else ''}**\n"
    msg += f"Total Drops: {total_drops}\n"
    msg += f"Total Value: {total_value:,.0f} gp"

    await ctx.send(msg)


# Run the bot
if __name__ == "__main__":
    TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("❌ ERROR: DISCORD_BOT_TOKEN environment variable not set!")
        print("Please set it in your Render dashboard environment variables.")
        exit(1)

    print("=" * 50)
    print("🤖 OSRS Bingo Drop Tracker Bot")
    print("=" * 50)
    print(f"Bingo API: {BINGO_API_URL}")
    print("=" * 50)

    bot.run(TOKEN)