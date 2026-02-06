#!/usr/bin/env python3
"""
Fetch GIM highscore data and cache it in MongoDB.
Run this script periodically via GitHub Actions or cron.
"""

import os
import sys
from datetime import datetime

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    import requests
    HAS_CLOUDSCRAPER = False
GROUP_NAME = 'unsociables'
GROUP_SIZE = 5
MAX_PAGES = 150

def fetch_gim_data():
    """Fetch GIM highscore data from RuneScape"""
    print(f'🔍 Searching for group: {GROUP_NAME}')
    print(f'Using cloudscraper: {HAS_CLOUDSCRAPER}')

    # Create scraper/session
    if HAS_CLOUDSCRAPER:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
    else:
        import requests
        scraper = requests.Session()
        scraper.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    overall_rank = None
    total_xp = None
    prestige_count = 0
    found = False

    # Search through pages
    for page in range(1, MAX_PAGES + 1):
        if found:
            break

        url = f'https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/?groupSize={GROUP_SIZE}&page={page}'

        try:
            print(f'📄 Fetching page {page}...')
            response = scraper.get(url, timeout=30)

            if response.status_code != 200:
                print(f'❌ Page {page} returned {response.status_code}')
                if response.status_code == 403:
                    print('Blocked by Cloudflare - stopping')
                    return None
                continue

            html = response.text

            # Parse HTML (simple text parsing)
            from html.parser import HTMLParser

            class GIMParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.in_tbody = False
                    self.in_tr = False
                    self.in_td = False
                    self.td_count = 0
                    self.current_row = {}
                    self.rows = []

                def handle_starttag(self, tag, attrs):
                    if tag == 'tbody':
                        self.in_tbody = True
                    elif tag == 'tr' and self.in_tbody:
                        self.in_tr = True
                        self.current_row = {'has_star': False}
                        self.td_count = 0
                    elif tag == 'td' and self.in_tr:
                        self.in_td = True
                        self.td_count += 1
                    elif tag == 'img' and self.in_td:
                        # Prestige star
                        self.current_row['has_star'] = True

                def handle_endtag(self, tag):
                    if tag == 'tbody':
                        self.in_tbody = False
                    elif tag == 'tr':
                        if self.in_tr and len(self.current_row) > 1:
                            self.rows.append(self.current_row)
                        self.in_tr = False
                    elif tag == 'td':
                        self.in_td = False

                def handle_data(self, data):
                    if self.in_td:
                        data = data.strip()
                        if data:
                            if self.td_count == 1:  # Rank
                                self.current_row['rank'] = data.replace(',', '')
                            elif self.td_count == 2:  # Name
                                self.current_row['name'] = data
                            elif self.td_count == 4:  # XP
                                self.current_row['xp'] = data.replace(',', '')

            parser = GIMParser()
            parser.feed(html)

            # Process rows
            for row in parser.rows:
                if 'rank' not in row or 'name' not in row or 'xp' not in row:
                    continue

                try:
                    rank = int(row['rank'])
                    xp = int(row['xp'])
                    name = row['name'].lower()
                    has_star = row['has_star']

                    # Check if this is our group
                    if GROUP_NAME in name:
                        print(f'✅ FOUND: {name} at rank #{rank}')
                        overall_rank = rank
                        total_xp = xp
                        found = True
                        if has_star:
                            prestige_count += 1
                            print('⭐ Group has PRESTIGE!')
                        break

                    # Count prestige groups before us
                    if has_star and not found:
                        prestige_count += 1

                except (ValueError, KeyError):
                    continue

            # Progress indicator
            if page % 10 == 0 and not found:
                print(f'💤 Scanned {page * 20} groups, found {prestige_count} prestige groups...')

        except Exception as e:
            print(f'❌ Error fetching page {page}: {e}')
            continue

    if not found:
        print('❌ Group not found in top 3000')
        return None

    prestige_rank = prestige_count if prestige_count > 0 else None

    print('📊 RESULTS:')
    print(f'   Overall: #{overall_rank:,}')
    if prestige_rank:
        print(f'   Prestige: #{prestige_rank:,} ⭐')
    print(f'   XP: {total_xp:,}')

    return {
        'overall_rank': overall_rank,
        'prestige_rank': prestige_rank,
        'total_xp': total_xp,
        'last_updated': datetime.utcnow(),
        'group_name': GROUP_NAME
    }


def save_via_api(data):
    """Save GIM data via the existing /rank/snapshot API endpoint"""
    if not data:
        print('❌ No data to save')
        return False

    try:
        # Get API URL from environment or use default
        api_url = os.environ.get('API_URL', 'https://osrsbingobot.onrender.com')

        # Format data for the existing rank snapshot endpoint
        payload = {
            'rank': data['overall_rank'],
            'prestigeRank': data['prestige_rank'],
            'totalXp': data['total_xp'],
            'rankChange': 0,  # Will be calculated by the API
            'prestigeRankChange': 0,
            'xpChange': 0
        }

        import requests
        response = requests.post(
            f'{api_url}/rank/snapshot',
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        if response.status_code == 200:
            print('✅ Saved via API to rank_history collection')
            return True
        else:
            print(f'❌ API returned {response.status_code}: {response.text}')
            return False

    except Exception as e:
        print(f'❌ Failed to save via API: {e}')
        return False


def main():
    print('🚀 Starting GIM data fetch...')
    print(f'Time: {datetime.utcnow().isoformat()}')
    print()

    data = fetch_gim_data()

    if data:
        success = save_via_api(data)
        if success:
            print()
            print('✅ GIM data fetch completed successfully!')
            sys.exit(0)
        else:
            print()
            print('❌ Failed to save data')
            sys.exit(1)
    else:
        print()
        print('❌ Failed to fetch GIM data')
        sys.exit(1)


if __name__ == '__main__':
    main()
