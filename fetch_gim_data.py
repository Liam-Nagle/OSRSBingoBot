#!/usr/bin/env python3
"""
Fetch GIM highscore data and cache it in MongoDB.
Run this script periodically via GitHub Actions or cron.
"""

import os
import sys
import time
import requests
from datetime import datetime
from urllib.parse import quote

try:
    from curl_cffi import requests as cf_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

GROUP_NAME = 'unsociables'
GROUP_SIZE = 5
MAX_PAGES = 150
PAGE_SIZE = 20  # groups listed per hiscores page

ZENROWS_API_KEY = os.environ.get('ZENROWS_API_KEY')
API_URL = os.environ.get('API_URL', 'https://osrsbingobot.onrender.com')


def get_last_known_data():
    """
    Ask the backend for our last recorded rank/prestige rank so we can search
    near the rank instead of re-scanning the hiscores from page 1 every run.
    Our rank only drifts a little between runs, but a full scan from page 1
    costs ~100 requests every time just to relocate a group sitting around
    rank #2000 - that's what blew through the ScraperAPI quota.
    """
    try:
        response = requests.get(f'{API_URL}/rank/latest', timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get('data') or {}
    except Exception as e:
        print(f'⚠️  Could not fetch last known rank ({e}), falling back to a full scan')
        return {}


def build_page_order(last_page):
    """
    Pages to check, in priority order: centered on the last known page and
    expanding outward one step at a time. Naturally covers the full 1..MAX_PAGES
    range if the group isn't found nearby (e.g. first run, or a big rank jump) -
    it just tries the likely spot first instead of always starting at page 1.
    """
    if last_page is None:
        return list(range(1, MAX_PAGES + 1))

    order = [last_page]
    radius = 1
    while len(order) < MAX_PAGES:
        for candidate in (last_page - radius, last_page + radius):
            if 1 <= candidate <= MAX_PAGES and candidate not in order:
                order.append(candidate)
        radius += 1

    return order


def fetch_gim_data(full_scan=False):
    """
    Fetch GIM highscore data from RuneScape.

    full_scan=False (default, used by the regular 3-day cron): searches near
    the last known rank only. Cheap (a handful of requests), but can't produce
    an accurate prestige_rank - that requires counting every prestige group
    from page 1 onwards, which this mode skips. prestige_rank is carried over
    unchanged from the last snapshot instead of being recomputed.

    full_scan=True (used by the periodic full-scan cron / manual dispatch):
    walks every page from 1, like the original script did. Expensive, but
    produces an exact, up-to-date prestige_rank.
    """
    print(f'🔍 Searching for group: {GROUP_NAME}')
    print(f'🔎 Mode: {"full scan (exact prestige rank)" if full_scan else "targeted search (cheap, prestige rank carried over)"}')

    if ZENROWS_API_KEY:
        print('Using ZenRows to bypass Cloudflare')
    elif HAS_CURL_CFFI:
        print('Using curl_cffi to bypass Cloudflare')
    else:
        print('❌ No bypass method available! Set ZENROWS_API_KEY environment variable.')
        return None

    last_known = get_last_known_data()
    last_rank = last_known.get('overall_rank')
    last_page = None
    if last_rank:
        last_page = max(1, ((last_rank - 1) // PAGE_SIZE) + 1)
        print(f'📍 Last known rank #{last_rank:,} -> page {last_page}')

    overall_rank = None
    total_xp = None
    prestige_count = 0
    found = False

    page_order = list(range(1, MAX_PAGES + 1)) if full_scan else build_page_order(last_page)

    # Search through pages, closest to our last known rank first
    for check_num, page in enumerate(page_order, start=1):
        if found:
            break

        base_url = f'https://secure.runescape.com/m=hiscore_oldschool_ironman/group-ironman/?groupSize={GROUP_SIZE}&page={page}'

        try:
            print(f'📄 [{check_num}/{len(page_order)} checked] Fetching page {page}...')

            # Retry logic
            max_retries = 3
            retry_delay = 2
            response = None

            for attempt in range(max_retries):
                try:
                    if ZENROWS_API_KEY:
                        response = requests.get(
                            'https://api.zenrows.com/v1/',
                            params={
                                'apikey': ZENROWS_API_KEY,
                                'url': base_url,
                                'premium_proxy': 'true'
                            },
                            timeout=60
                        )
                    elif HAS_CURL_CFFI:
                        response = cf_requests.get(
                            base_url,
                            impersonate="chrome120",
                            timeout=30
                        )
                    else:
                        return None

                except Exception as e:
                    print(f'❌ Request error: {e}')
                    break

                if response.status_code == 200:
                    break
                elif response.status_code in (429, 503):
                    if attempt < max_retries - 1:
                        print(f'⏳ Page {page} returned {response.status_code}, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})')
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        print(f'❌ Page {page} returned {response.status_code} after {max_retries} attempts')
                elif response.status_code in (401, 403):
                    print(f'❌ Page {page} returned {response.status_code} - blocked or bad API key: {response.text[:300]}')
                    return None
                else:
                    print(f'❌ Page {page} returned {response.status_code}: {response.text[:300]}')
                    break

            if response is None or response.status_code != 200:
                continue

            # Add delay between requests to avoid rate limiting
            time.sleep(0.5)

            # Parse HTML
            html = response.text

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Find table
            tbody = soup.find('tbody')
            if not tbody:
                table = soup.find('table')
                if table:
                    tbody = table
                else:
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

                except (ValueError, IndexError, AttributeError):
                    continue

            # Progress indicator
            if check_num % 10 == 0 and not found:
                print(f'💤 Checked {check_num} pages so far...')

        except Exception as e:
            print(f'❌ Error fetching page {page}: {e}')
            continue

    if not found:
        print('❌ Group not found in top 3000')
        return None

    if full_scan:
        prestige_rank = prestige_count if prestige_count > 0 else None
    else:
        prestige_rank = last_known.get('prestige_rank')
        print(f'↻ Reusing cached prestige rank (not recomputed in targeted-search mode): {prestige_rank}')

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
        api_url = os.environ.get('API_URL', 'https://osrsbingobot.onrender.com')

        payload = {
            'rank': data['overall_rank'],
            'prestigeRank': data['prestige_rank'],
            'totalXp': data['total_xp'],
            'rankChange': 0,
            'prestigeRankChange': 0,
            'xpChange': 0
        }

        response = requests.post(
            f'{api_url}/rank/snapshot',
            json=payload,
            headers={
                'Content-Type': 'application/json',
                'X-API-Key': os.environ.get('DROP_API_KEY', '')
            },
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
    full_scan = os.environ.get('FULL_SCAN', 'false').strip().lower() == 'true'

    print('🚀 Starting GIM data fetch...')
    print(f'Time: {datetime.utcnow().isoformat()}')
    print()

    data = fetch_gim_data(full_scan=full_scan)

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