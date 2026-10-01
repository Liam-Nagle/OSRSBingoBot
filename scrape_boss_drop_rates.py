"""
One-off/occasional scraper: pulls real per-kill droprates for every item in
gear-data/boss-unique-items.json straight from the OSRS Wiki, and writes the
result to gear-data/boss-drop-rates.json.

Why this exists: the recap's luck badges (Tiny Violin/Silver Spoon) need an
"expected drops" baseline for a boss even when nobody on the team has pulled
its notable item yet this event (or ever) - which Dink's own live-captured
rarity data can't provide, since it only ever shows up attached to an actual
drop. The wiki's {{DropsLine}} template already has this data for every
boss, with droprate mechanics (e.g. Zulrah's 2-rolls-per-kill, Duke
Sucellus's pity-counter uniques) already folded into one usable number.

Not run automatically - re-run by hand (`python scrape_boss_drop_rates.py`)
whenever boss-unique-items.json changes or droprates need refreshing.
"""
import json
import os
import re
import time
import requests

WIKI_API = "https://oldschool.runescape.wiki/api.php"
HEADERS = {'User-Agent': 'OSRSBingoBot-DropRateScraper/1.0 (one-off script, github.com/Liam-Nagle/OSRSBingoBot)'}
REQUEST_DELAY_SECONDS = 0.4

# WiseOldMan boss key -> OSRS Wiki page title. Mirrors bingo_api.py's
# boss_mapping (kept separate - this runs standalone, not imported into the
# Flask app) since wiki titles usually match the in-game NPC name directly.
BOSS_WIKI_TITLES = {
    'abyssal_sire': 'Abyssal Sire',
    'alchemical_hydra': 'Alchemical Hydra',
    'amoxliatl': 'Amoxliatl',
    'araxxor': 'Araxxor',
    'artio': 'Artio',
    'bryophyta': 'Bryophyta',
    'callisto': 'Callisto',
    'calvarion': "Cal'varion",
    'cerberus': 'Cerberus',
    'chambers_of_xeric': 'Chambers of Xeric',
    'chaos_elemental': 'Chaos Elemental',
    'chaos_fanatic': 'Chaos Fanatic',
    'commander_zilyana': 'Commander Zilyana',
    'corporeal_beast': 'Corporeal Beast',
    'crazy_archaeologist': 'Crazy Archaeologist',
    'dagannoth_prime': 'Dagannoth Prime',
    'dagannoth_rex': 'Dagannoth Rex',
    'dagannoth_supreme': 'Dagannoth Supreme',
    'deranged_archaeologist': 'Deranged Archaeologist',
    'doom_of_mokhaiotl': 'Doom of Mokhaiotl',
    'duke_sucellus': 'Duke Sucellus',
    'general_graardor': 'General Graardor',
    'giant_mole': 'Giant Mole',
    'grotesque_guardians': 'Grotesque Guardians',
    'hespori': 'Hespori',
    'kalphite_queen': 'Kalphite Queen',
    'king_black_dragon': 'King Black Dragon',
    'kraken': 'Kraken',
    'kreearra': "Kree'arra",
    'kril_tsutsaroth': "K'ril Tsutsaroth",
    'nex': 'Nex',
    'nightmare': 'The Nightmare',
    'phosanis_nightmare': "Phosani's Nightmare",
    'obor': 'Obor',
    'phantom_muspah': 'Phantom Muspah',
    'sarachnis': 'Sarachnis',
    'scorpia': 'Scorpia',
    'scurrius': 'Scurrius',
    'skotizo': 'Skotizo',
    'sol_heredit': 'Sol Heredit',
    'spindel': 'Spindel',
    'tempoross': 'Tempoross',
    'the_gauntlet': 'The Gauntlet',
    'the_corrupted_gauntlet': 'The Corrupted Gauntlet',
    'the_hueycoatl': 'The Hueycoatl',
    'the_leviathan': 'The Leviathan',
    'the_whisperer': 'The Whisperer',
    'the_royal_titans': 'Royal Titans',
    'theatre_of_blood': 'Theatre of Blood',
    'thermonuclear_smoke_devil': 'Thermonuclear Smoke Devil',
    'tombs_of_amascut': 'Tombs of Amascut',
    'tzkal_zuk': 'TzKal-Zuk',
    'tztok_jad': 'TzTok-Jad',
    'vardorvis': 'Vardorvis',
    'venenatis': 'Venenatis',
    'vetion': "Vet'ion",
    'vorkath': 'Vorkath',
    'wintertodt': 'Wintertodt',
    'yama': 'Yama',
    'zalcano': 'Zalcano',
    'zulrah': 'Zulrah',
}

# Bosses confirmed (via audit_boss_drop_rates.py + manual wiki verification)
# to have a "no duplicates until you've completed the set" mechanic - e.g.
# Araxxor's noxious halberd pieces are a published 1/200 EACH, but that's a
# blended average over a full completion journey, not a constant per-kill
# probability; summing all of a set's per-item rates overcounts badly
# (confirmed 2.5x too high for Araxxor against its own stated 1/150 table-
# access rate). For these, use the single stated combined rate instead of
# summing the per-item ones. {boss_key: (display_name, combined_rarity_1_in)}
ANTI_DUP_COMBINED_RATES = {
    'araxxor': ('any araxxor unique', 150.0),
}


def canonical_boss_key(title):
    """
    Same slugification as bingo_api.py's normalize_boss_name() - the output
    file's keys MUST match that function's output exactly, since that's how
    compute_luck_breakdown() looks a boss up. Derived from the wiki title,
    not from BOSS_WIKI_TITLES's own dict key (which mirrors WOM's boss-key
    convention and can disagree - e.g. 'the_gauntlet' vs normalize_boss_name's
    'gauntlet' - which silently orphaned Gauntlet/Corrupted Gauntlet/
    Hueycoatl/Leviathan/Whisperer's scraped rates until this was caught).
    """
    slug = title.strip().lower()
    slug = slug.replace("'", '')
    slug = re.sub(r'^the\s+', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    return slug


def fetch_wikitext(title):
    resp = requests.get(WIKI_API, headers=HEADERS, params={
        'action': 'query',
        'format': 'json',
        'titles': title,
        'prop': 'revisions',
        'rvprop': 'content',
        'rvslots': 'main',
    }, timeout=15)
    resp.raise_for_status()
    pages = resp.json().get('query', {}).get('pages', {})
    for page in pages.values():
        if 'missing' in page:
            return None
        revisions = page.get('revisions')
        if revisions:
            return revisions[0]['slots']['main']['*']
    return None


def parse_droplines(wikitext):
    """
    Extract {{DropsLine|name=...|rarity=...|rolls=...}} entries. Effective
    per-kill rate = parsed denominator / rolls (default rolls=1). Skips
    entries with a non-numeric rarity (Always, Varies, etc.) or no name.
    """
    results = []
    i = 0
    while True:
        start = wikitext.find('{{DropsLine', i)
        if start == -1:
            break
        depth = 0
        j = start
        while j < len(wikitext):
            if wikitext[j:j + 2] == '{{':
                depth += 1
                j += 2
            elif wikitext[j:j + 2] == '}}':
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        block = wikitext[start:j]
        i = j

        name_match = re.search(r'\|\s*name\s*=\s*([^|}]+)', block)
        rarity_match = re.search(r'\|\s*rarity\s*=\s*([^|}]+)', block)
        rolls_match = re.search(r'\|\s*rolls\s*=\s*(\d+)', block)
        if not name_match or not rarity_match:
            continue

        name = name_match.group(1).strip()
        rarity_raw = rarity_match.group(1).strip()
        rolls = int(rolls_match.group(1)) if rolls_match else 1

        frac_match = re.match(r'^(\d+(?:\.\d+)?)\s*/\s*([\d,]+(?:\.\d+)?)$', rarity_raw)
        if frac_match:
            numerator = float(frac_match.group(1))
            denominator = float(frac_match.group(2).replace(',', ''))
        else:
            # A denominator can be a MediaWiki {{#expr: ... round N}} arithmetic
            # expression instead of a plain number - e.g. Alchemical Hydra's
            # items encode the real combinatorial odds (avoiding duplicate
            # drops) as "1/{{#expr:180/(1999/2000*1999/2000*...) round 1}}".
            # Evaluate it ourselves rather than skip it, but only after
            # confirming it's pure arithmetic - never eval free-form text.
            expr_match = re.match(
                r'^(\d+(?:\.\d+)?)\s*/\s*\{\{#expr:\s*([0-9.\s+\-*/()]+?)\s+round\s+\d+$',
                rarity_raw
            )
            if not expr_match:
                continue
            numerator = float(expr_match.group(1))
            try:
                denominator = eval(expr_match.group(2), {'__builtins__': {}}, {})
            except (SyntaxError, ZeroDivisionError, TypeError):
                continue
        if numerator <= 0 or denominator <= 0:
            continue
        effective_1_in = (denominator / numerator) / rolls
        results.append({'name': name.lower(), 'rarity_1_in': round(effective_1_in, 4)})
    return results


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, 'gear-data', 'boss-unique-items.json'), encoding='utf-8') as f:
        notable_items = json.load(f)
    notable_names = {name for name, info in notable_items.items() if info.get('_notable', True)}

    boss_drop_rates = {}
    missing_pages = []
    no_notable_match = []

    for boss_key, title in BOSS_WIKI_TITLES.items():
        print(f"Fetching {title}...")
        try:
            wikitext = fetch_wikitext(title)
        except requests.RequestException as e:
            print(f"  [!] Request failed: {e}")
            missing_pages.append(title)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if wikitext is None:
            print(f"  [!] No such page")
            missing_pages.append(title)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        lines = parse_droplines(wikitext)
        matched = {}
        for r in lines:
            name = r['name']
            if name in notable_names:
                matched[name] = r['rarity_1_in']
                continue
            # Some drops come in a qualified form (e.g. "Torva full helm
            # (damaged)" at Nex) that doesn't match our curated key for the
            # finished item - fall back to the name with any trailing
            # "(word[s])" qualifier stripped.
            stripped = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
            if stripped != name and stripped in notable_names:
                matched[stripped] = r['rarity_1_in']

        if boss_key in ANTI_DUP_COMBINED_RATES and matched:
            combined_name, combined_rate = ANTI_DUP_COMBINED_RATES[boss_key]
            matched = {combined_name: combined_rate}

        if matched:
            boss_drop_rates[canonical_boss_key(title)] = matched
            print(f"  OK: {matched}")
        else:
            no_notable_match.append(title)
            print(f"  (no curated notable items found on this page)")

        time.sleep(REQUEST_DELAY_SECONDS)

    # "The Corrupted Gauntlet" wiki page has no drop table of its own -
    # Corrupted-exclusive uniques (and the armour seed shared with regular
    # mode) are documented on "The Gauntlet" page instead, so the scrape
    # above already caught them, just filed under 'gauntlet'. Split out
    # whichever of those apply to Corrupted Gauntlet by their own curated
    # source, rather than leaving it with zero droprates.
    gauntlet_matches = boss_drop_rates.get('gauntlet', {})
    corrupted_matches = {
        name: rate for name, rate in gauntlet_matches.items()
        if 'corrupted gauntlet' in notable_items.get(name, {}).get('source', '').lower()
    }
    if corrupted_matches:
        boss_drop_rates.setdefault('corrupted_gauntlet', {}).update(corrupted_matches)
        print(f"Corrupted Gauntlet: {corrupted_matches} (split from The Gauntlet's shared page)")

    # The reverse of the above: that same shared page also means 'gauntlet'
    # picked up Corrupted-exclusive items (e.g. Enhanced crystal weapon
    # seed) it can never actually drop in regular mode - drop anything
    # whose curated source doesn't actually include "The Gauntlet" itself.
    if 'gauntlet' in boss_drop_rates:
        filtered = {
            name: rate for name, rate in boss_drop_rates['gauntlet'].items()
            if 'the gauntlet' in notable_items.get(name, {}).get('source', '').lower()
        }
        if filtered != boss_drop_rates['gauntlet']:
            dropped = set(boss_drop_rates['gauntlet']) - set(filtered)
            print(f"The Gauntlet: dropping Corrupted-only items {dropped}")
        boss_drop_rates['gauntlet'] = filtered

    out_path = os.path.join(base_dir, 'gear-data', 'boss-drop-rates.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(boss_drop_rates, f, indent=2, sort_keys=True)

    print()
    print(f"Wrote {out_path} - {len(boss_drop_rates)} bosses with matched rates")
    if missing_pages:
        print(f"Pages not found ({len(missing_pages)}): {missing_pages}")
    if no_notable_match:
        print(f"Pages with no curated notable items matched ({len(no_notable_match)}): {no_notable_match}")


if __name__ == '__main__':
    main()
