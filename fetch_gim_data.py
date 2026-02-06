#!/usr/bin/env python3
"""
Fetch GIM highscore data and cache it in MongoDB.
Run this script periodically via GitHub Actions or cron.
"""

import os
import sys
import gzip
from datetime import datetime
from urllib.parse import quote

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

    # Use corsproxy.io with browser headers to avoid detection
    import requests
    scraper = requests.Session()

    # Add browser-like headers to avoid being blocked as a bot
    # NOTE: Removed Accept-Encoding to avoid compression issues with corsproxy.io
    scraper.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    })

    PROXY_URL = 'https://corsproxy.io/?'
    print(f'Using corsproxy.io with browser headers')

    overall_rank = None
    total_xp = None
    prestige_count = 0
    found = False

    # Search through pages
    for page in range(1, MAX_PAGES + 1):
        if found:
            break

        base_url = f'https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/?groupSize={GROUP_SIZE}&page={page}'
        url = PROXY_URL + quote(base_url, safe='')

        try:
            print(f'📄 Fetching page {page}...')
            response = scraper.get(url, timeout=30)

            if response.status_code != 200:
                print(f'❌ Page {page} returned {response.status_code}')
                if response.status_code == 403:
                    print('Blocked by Cloudflare - stopping')
                    return None
                continue

            # Debug response on first page
            if page == 1:
                print(f'📝 Response headers: {dict(response.headers)}')
                print(f'📝 Content-Type: {response.headers.get("Content-Type")}')
                print(f'📝 Content-Encoding: {response.headers.get("Content-Encoding")}')
                print(f'📝 Content length: {len(response.content)} bytes')

            # Get HTML text (requests should auto-decode)
            html = response.text

            # Debug: Print first page HTML structure (only once)
            if page == 1:
                print(f'📝 First 500 chars of HTML: {html[:500]}')
                print(f'📝 Looking for table elements...')

            # Parse HTML with BeautifulSoup
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Debug: Check what we got
            if page == 1:
                print(f'📝 Found {len(soup.find_all("table"))} table(s)')
                print(f'📝 Found {len(soup.find_all("tr"))} tr(s)')
                print(f'📝 Found {len(soup.find_all("tbody"))} tbody(s)')

            # Find table - try both with and without tbody
            tbody = soup.find('tbody')
            if not tbody:
                # Try finding table directly
                table = soup.find('table')
                if table:
                    tbody = table
                else:
                    print(f'⚠️ No table found on page {page}')
                    continue

            rows = tbody.find_all('tr')

            for row in rows:
                cells = row.find_all('td')
                if len(cells) < 4:
                    continue

                try:
                    # Cell 0: Rank
                    rank_text = cells[0].get_text(strip=True).replace(',', '')
                    rank = int(rank_text)

                    # Cell 1: Group name
                    name_cell = cells[1]
                    has_star = name_cell.find('img') is not None
                    clean_name = name_cell.get_text(strip=True).lower()

                    # Cell 3: XP
                    xp_text = cells[3].get_text(strip=True).replace(',', '')
                    xp = int(xp_text)

                    # Check if this is our group
                    if GROUP_NAME in clean_name:
                        print(f'✅ FOUND: {clean_name} at rank #{rank}')
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

                except (ValueError, IndexError, AttributeError) as e:
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
