"""
One-off audit: for every boss in scrape_boss_drop_rates.py's BOSS_WIKI_TITLES,
fetches its wiki page, extracts the "Uniques" section specifically, and
checks two things against gear-data/boss-unique-items.json:

1. Missing items - things listed in the Uniques section that aren't in our
   curated file for that boss at all (undercounts "expected" if added later).
2. Anti-duplicate-set language ("no duplicate", "won't receive duplicate",
   "until...obtained/completed") near the Uniques section - bosses with this
   mechanic make the simple "sum each item's rate x KC" formula invalid,
   confirmed on Araxxor (2.5x too high) and Nex (~8% too high) against their
   own explicitly-stated combined "any unique" rate.

Read-only - just prints a report, doesn't write anything.
"""
import json
import os
import re
import time
import requests

from scrape_boss_drop_rates import BOSS_WIKI_TITLES, fetch_wikitext, parse_droplines

ANTI_DUP_PATTERN = re.compile(
    r'(no duplicate|won.?t receive duplicate|prevent.{0,30}duplicate|'
    r'until.{0,40}(obtained|completed|full (set|weapon))|not receive.{0,20}duplicate)',
    re.IGNORECASE
)

# Curated "source" strings that name more than one specific boss - expand to
# the individual boss display names (matching BOSS_WIKI_TITLES' values) so a
# shared item still gets checked against each real boss it can drop from.
GROUP_EXPANSIONS = {
    'Dagannoth Kings': ['Dagannoth Prime', 'Dagannoth Rex', 'Dagannoth Supreme'],
    'God Wars Dungeon bosses': ['General Graardor', 'Commander Zilyana', "K'ril Tsutsaroth", "Kree'arra"],
    'Desert Treasure II bosses': ['Duke Sucellus', 'Vardorvis', 'The Whisperer', 'The Leviathan'],
    'Callisto/Artio': ['Callisto', 'Artio'],
    "Vet'ion/Calvar'ion": ["Vet'ion", "Cal'varion"],
    'Venenatis/Spindel': ['Venenatis', 'Spindel'],
    'Callisto/Artio/Venenatis/Spindel/Vet\'ion/Calvar\'ion': ['Callisto', 'Artio', 'Venenatis', 'Spindel', "Vet'ion", "Cal'varion"],
    'The Gauntlet / Corrupted Gauntlet': ['The Gauntlet', 'The Corrupted Gauntlet'],
    'TzTok-Jad (Fight Caves)': ['TzTok-Jad'],
    'TzKal-Zuk (Inferno)': ['TzKal-Zuk'],
}


def extract_uniques_section(wikitext):
    """Slice out the '===Uniques===' (or similarly-named) heading's content, up to the next '==' heading."""
    match = re.search(r'===\s*Uniques?\s*===', wikitext, re.IGNORECASE)
    if not match:
        return None
    start = match.end()
    # Stop at the NEXT heading of any level (==, ===, ====...) - matching only
    # == specifically let content from later subsections (Mutagens, Pets,
    # Herblore materials, 100% drops) leak in as false "missing" items.
    next_heading = re.search(r'\n={2,}[^=\n]', wikitext[start:])
    end = start + next_heading.start() if next_heading else len(wikitext)
    return wikitext[start:end]


def curated_items_for_boss(notable_items, boss_title):
    result = set()
    for name, info in notable_items.items():
        source = info.get('source', '')
        if boss_title in source or boss_title in GROUP_EXPANSIONS.get(source, []):
            result.add(name)
    return result


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, 'gear-data', 'boss-unique-items.json'), encoding='utf-8') as f:
        notable_items = json.load(f)

    anti_dup_bosses = []
    missing_items_report = {}

    for boss_key, title in BOSS_WIKI_TITLES.items():
        print(f"Checking {title}...")
        try:
            wikitext = fetch_wikitext(title)
        except requests.RequestException as e:
            print(f"  [!] Request failed: {e}")
            time.sleep(0.4)
            continue

        if wikitext is None:
            print(f"  [!] No such page")
            time.sleep(0.4)
            continue

        section = extract_uniques_section(wikitext)
        if section is None:
            print(f"  (no Uniques section found)")
            time.sleep(0.4)
            continue

        if ANTI_DUP_PATTERN.search(section):
            anti_dup_bosses.append(title)
            print(f"  [ANTI-DUP MECHANIC DETECTED]")

        wiki_items = set()
        for r in parse_droplines(section):
            name = r['name']
            stripped = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
            wiki_items.add(stripped if stripped else name)
        curated = {c.lower() for c in curated_items_for_boss(notable_items, title)}
        missing = wiki_items - curated
        # Drop obvious non-unique noise that sometimes shares the section
        # (pets, "Always" drops already filtered by parse_droplines needing
        # a numeric rarity, raw materials with very common rates)
        if missing:
            missing_items_report[title] = sorted(missing)
            print(f"  Missing from curated list: {sorted(missing)}")

        time.sleep(0.4)

    print()
    print("=" * 78)
    print(f"Bosses with an anti-duplicate-set mechanic ({len(anti_dup_bosses)}):")
    for b in anti_dup_bosses:
        print(f"  {b}")

    print()
    print(f"Bosses with items missing from boss-unique-items.json ({len(missing_items_report)}):")
    for b, items in missing_items_report.items():
        print(f"  {b}: {items}")


if __name__ == '__main__':
    main()
