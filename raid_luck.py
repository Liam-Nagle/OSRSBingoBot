"""
Raid (CoX / ToB / ToA) unique-drop luck, built from what the BingoLuckSync
RuneLite plugin reports for each player's OWN raids.

Everything here is per person. For all three raids the team's chance of a
unique is proportional to the team's points and the recipient is picked in
proportion to each player's share of those points, so the team total cancels:

    your chance = your points / (points needed per 1% x 100)       (CoX, ToA)
    your chance = your points / (unique rate x (18 x team + 14))   (ToB)

The team total only matters when the team's chance hits its cap (CoX 65.7%,
ToA 55%); the CoX endpoint sends it so that case is handled when it's known.

Sources (OSRS Wiki, checked 2026-10-03):
  CoX  Ancient chest             1% per 8,676 team points, cap 65.7%; unique weights
                                 out of 60 (normal) / 56 (challenge mode).
  ToB  Calculator:Theatre of Blood loot (+ Module:Theatre of Blood calculator)
                                 unique rate 1/9.1 normal, 1/7.7 hard; player score
                                 (6 - rooms skipped) x 3 + MVP points - 4 x deaths;
                                 max team score 18 x team size + 14.
  ToA  Chest (Tombs of Amascut)  1% per (10,500 - 20 x scaled raid level) points
                                 (starting 5,000 already excluded), cap 55%;
                                 weights from Module:Chart data/toa unique weights.

Known approximations are called out where they are made.
"""
import math
from datetime import datetime, timezone

# ---------------------------------------------------------------- CoX

COX_POINTS_PER_PERCENT = 8676
COX_MAX_CHANCE = 0.657

COX_WEIGHTS = {
    'NORMAL': {
        'dexterous prayer scroll': 14, 'arcane prayer scroll': 14, 'twisted buckler': 4,
        'dragon hunter crossbow': 4, "dinh's bulwark": 3, 'ancestral hat': 4,
        'ancestral robe top': 4, 'ancestral robe bottom': 4, 'dragon claws': 3,
        'elder maul': 2, 'kodai insignia': 2, 'twisted bow': 2,
    },
    'CHALLENGE': {
        'dexterous prayer scroll': 12, 'arcane prayer scroll': 12, 'twisted buckler': 4,
        'dragon hunter crossbow': 4, "dinh's bulwark": 3, 'ancestral hat': 4,
        'ancestral robe top': 4, 'ancestral robe bottom': 4, 'dragon claws': 3,
        'elder maul': 2, 'kodai insignia': 2, 'twisted bow': 2,
    },
}


def cox_individual_chance(personal_points, total_points=None):
    """Chance this player receives a unique from one CoX raid, or None if points unknown."""
    if personal_points is None or personal_points < 0:
        return None
    uncapped = personal_points / (COX_POINTS_PER_PERCENT * 100.0)
    if total_points and total_points > 0 and personal_points <= total_points:
        team_chance = total_points / (COX_POINTS_PER_PERCENT * 100.0)
        if team_chance > COX_MAX_CHANCE:
            return COX_MAX_CHANCE * personal_points / total_points
    return min(uncapped, COX_MAX_CHANCE)


# ---------------------------------------------------------------- ToB

TOB_UNIQUE_RATE = {'NORMAL': 9.1, 'HARD': 7.7}
TOB_WEIGHTS = {
    'NORMAL': {
        'avernic defender hilt': 8, 'ghrazi rapier': 2, 'sanguinesti staff': 2,
        'justiciar faceguard': 2, 'justiciar chestguard': 2, 'justiciar legguards': 2,
        'scythe of vitur': 1,
    },
    'HARD': {
        'avernic defender hilt': 7, 'ghrazi rapier': 2, 'sanguinesti staff': 2,
        'justiciar faceguard': 2, 'justiciar chestguard': 2, 'justiciar legguards': 2,
        'scythe of vitur': 1,
    },
}
TOB_MVP_POINTS_TOTAL = 14


def tob_individual_chance(mode, team_size, deaths):
    """
    Chance this player receives a unique from one ToB raid, or None if it can't be
    scored (no uniques in this mode, or team size unknown).

    Approximations: rooms skipped are assumed 0 (the wiki calls non-zero "almost
    never"), and the player's MVP points - which the game doesn't expose per room -
    are taken as the team average of 14 / team size. Unknown deaths are assumed 0.
    """
    rate = TOB_UNIQUE_RATE.get(mode)
    if rate is None or not team_size or team_size < 1:
        return None
    deaths = deaths if deaths is not None and deaths >= 0 else 0
    player_points = max(0.0, 6 * 3 + TOB_MVP_POINTS_TOTAL / team_size - 4 * deaths)
    return player_points / (rate * (18 * team_size + TOB_MVP_POINTS_TOTAL))


# ---------------------------------------------------------------- ToA

TOA_MAX_CHANCE = 0.55
_TOA_BASE_WEIGHTS = {
    "tumeken's shadow": 10, 'masori mask': 20, 'masori body': 20, 'masori chaps': 20,
    "elidinis' ward": 30, "osmumten's fang": 70, 'lightbearer': 70,
}


def toa_scaled_raid_level(raid_level):
    if raid_level <= 310:
        return raid_level
    if raid_level <= 430:
        return 310 + (raid_level - 310) / 3
    return 350 + (raid_level - 430) / 6


def toa_individual_chance(raid_level, personal_points, team_points=None):
    """Chance this player receives a unique from one ToA raid, or None if unknown."""
    if raid_level is None or raid_level < 0 or personal_points is None or personal_points < 0:
        return None
    divisor = 10500 - 20 * toa_scaled_raid_level(raid_level)
    if divisor <= 0:
        return None
    uncapped = personal_points / (divisor * 100.0)
    if team_points and team_points >= personal_points > 0:
        if team_points / (divisor * 100.0) > TOA_MAX_CHANCE:
            return TOA_MAX_CHANCE * personal_points / team_points
    return min(uncapped, TOA_MAX_CHANCE)


def toa_weights(raid_level):
    """
    Relative item weights at a raid level, mirroring the wiki's weighting module
    (stepped in 5s). Items outside their raid level (shadow/ward/masori below RL 150,
    fang/lightbearer below RL 50) only succeed on an extra 1/50 roll, so their
    weight is scaled by 1/50.
    """
    rl = max(0, int(raid_level) // 5 * 5)
    fang = lb = 70
    if 305 <= rl <= 350:
        fang = lb = 70 - math.floor((rl - 300) * 0.2)
    elif 355 <= rl <= 400:
        fang = 60 - math.floor((rl - 350) * 0.4)
        lb = 60 - math.floor((rl - 350) * 0.2)
    elif 405 <= rl <= 450:
        fang = 40
        lb = 50 - math.floor((rl - 400) * 0.2)
    elif 455 <= rl <= 500:
        fang = 40 - math.floor((rl - 450) * 0.2)
        lb = 40 - math.floor((rl - 450) * 0.1)
    elif rl >= 505:
        fang, lb = 30, 35
    weights = dict(_TOA_BASE_WEIGHTS)
    weights["osmumten's fang"] = fang
    weights['lightbearer'] = lb
    for item in ("tumeken's shadow", 'masori mask', 'masori body', 'masori chaps', "elidinis' ward"):
        if rl < 150:
            weights[item] /= 50.0
    if rl < 50:
        weights["osmumten's fang"] /= 50.0
        weights['lightbearer'] /= 50.0
    total = sum(weights.values())
    return {item: w / total for item, w in weights.items()}


# ---------------------------------------------------------------- aggregation

# Collection-log page -> (raid, modes it covers). Confirmed in-game: each raid has ONE
# page covering every mode (the modes only show up as separate KC lines inside it, e.g.
# "Tombs of Amascut (Expert) completions: 48"), so the page's item counts and the raids
# expected from all of those modes line up.
def classify_clog_page(page):
    name = (page or '').lower()
    if name == 'chambers of xeric':
        return 'COX', {'NORMAL', 'CHALLENGE'}
    if name == 'theatre of blood':
        return 'TOB', {'NORMAL', 'STORY', 'ENTRY', 'HARD'}
    if name == 'tombs of amascut':
        return 'TOA', {'NORMAL', 'ENTRY', 'EXPERT'}
    return None, set()


def _canonical_item(name):
    n = (name or '').lower().strip()
    if n.endswith(' (uncharged)'):
        n = n[: -len(' (uncharged)')]
    return n


def _raid_item_weights(raid, mode, raid_level):
    if raid == 'COX':
        w = COX_WEIGHTS.get(mode)
        total = sum(w.values()) if w else 0
        return {k: v / total for k, v in w.items()} if total else {}
    if raid == 'TOB':
        w = TOB_WEIGHTS.get(mode)
        total = sum(w.values()) if w else 0
        return {k: v / total for k, v in w.items()} if total else {}
    if raid == 'TOA':
        return toa_weights(raid_level if raid_level is not None and raid_level >= 0 else 300)
    return {}


def raid_unique_chance(doc):
    """Per-raid individual unique chance for a plugin_raids document, or None."""
    raid, mode = doc.get('raid'), doc.get('mode')
    if raid == 'COX':
        return cox_individual_chance(doc.get('personal_points'), doc.get('total_points'))
    if raid == 'TOB':
        return tob_individual_chance(mode, doc.get('team_size'), doc.get('deaths'))
    if raid == 'TOA':
        return toa_individual_chance(doc.get('raid_level'), doc.get('personal_points'))
    return None


def _as_epoch(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return float(value) if value is not None else 0.0


def compute_raid_luck_since_sync(collections):
    """
    Per player, per raid: expected vs actual uniques since the player's collection
    log page was first synced, scored in "kills ahead (+) / behind (-)" like the
    rest of the Luck tab (each item's effective rate is raids scored / expected).

    Only raids completed AFTER the page's first sync count, so the expected side
    covers exactly the same period as the actual side (collection log quantity now
    minus quantity at first sync). Raids that can't be scored (missing points, mode
    with no uniques) are counted in `unscored`, never guessed.

    Returns {player: {raid: {'raids_scored', 'unscored', 'expected_uniques',
    'actual_uniques', 'luck_kills', 'items': [{item, expected, actual, rarity_1_in, diff}]}}}
    """
    raids_by_player = {}
    for doc in collections['plugin_raids'].find({}):
        raids_by_player.setdefault(doc['player'], []).append(doc)

    result = {}
    for clog in collections['plugin_clog'].find({}):
        raid, modes = classify_clog_page(clog.get('page'))
        player = clog.get('player')
        if not raid or player not in raids_by_player:
            continue
        since = _as_epoch(clog.get('first_seen_at'))
        baseline = clog.get('baseline') or {}

        scored = unscored = 0
        expected = {}
        mode_acc = {}
        for doc in raids_by_player[player]:
            if doc.get('raid') != raid or doc.get('mode') not in modes:
                continue
            if doc.get('completed_at', 0) < since:
                continue
            chance = raid_unique_chance(doc)
            if chance is None:
                unscored += 1
                continue
            scored += 1
            acc = mode_acc.setdefault(doc['mode'], [0, 0.0])
            acc[0] += 1
            acc[1] += chance
            weights = _raid_item_weights(raid, doc['mode'], doc.get('raid_level'))
            for item, w in weights.items():
                expected[item] = expected.get(item, 0.0) + chance * w
        if not scored:
            continue

        actual = {}
        for it in clog.get('items') or []:
            key = _canonical_item(it.get('name'))
            if key in expected:
                qty = it.get('quantity', 0) or 0
                actual[key] = max(0, qty - (baseline.get(str(it.get('id'))) or 0))

        items_out = []
        for item, exp in expected.items():
            if exp <= 0:
                continue
            rate = scored / exp
            got = actual.get(item, 0)
            items_out.append({
                'item': item,
                'expected': round(exp, 4),
                'actual': got,
                'rarity_1_in': round(rate, 1),
                'diff': round((got - exp) * rate),
            })
        items_out.sort(key=lambda i: i['diff'])

        entry = result.setdefault(player, {}).setdefault(raid, {
            'raids_scored': 0, 'unscored': 0, 'expected_uniques': 0.0,
            'actual_uniques': 0, 'luck_kills': 0, 'items': [], 'modes': [],
        })
        entry['modes'] = _merge_modes(entry['modes'], [_mode_row(m, a[0], a[0], a[1]) for m, a in mode_acc.items()])
        entry['raids_scored'] += scored
        entry['unscored'] += unscored
        entry['expected_uniques'] = round(entry['expected_uniques'] + sum(expected.values()), 4)
        entry['actual_uniques'] += sum(actual.values())
        entry['luck_kills'] += sum(i['diff'] for i in items_out)
        entry['items'].extend(items_out)
    return result


# ---------------------------------------------------------------- lifetime and event windows

# plugin_kc counter name for each raid + mode (the collection log's own labels, lower-cased).
KC_NAMES = {
    ('COX', 'NORMAL'): 'chambers of xeric', ('COX', 'CHALLENGE'): 'chambers of xeric (cm)',
    ('TOB', 'NORMAL'): 'theatre of blood', ('TOB', 'ENTRY'): 'theatre of blood (entry)',
    ('TOB', 'HARD'): 'theatre of blood (hard)',
    ('TOA', 'NORMAL'): 'tombs of amascut', ('TOA', 'ENTRY'): 'tombs of amascut (entry)',
    ('TOA', 'EXPERT'): 'tombs of amascut (expert)',
}
RAID_SOURCES = {'COX': 'chambers of xeric', 'TOB': 'theatre of blood', 'TOA': 'tombs of amascut'}
# A mode's raids only count towards lifetime luck if at least this share of its completions is
# known (plugin reports plus screenshots). The rest are assumed to look like the known ones.
MIN_COVERAGE = 0.5


def _group_by_player_raid_mode(collections):
    out = {}
    for doc in collections['plugin_raids'].find({}):
        out.setdefault(doc['player'], {}).setdefault(doc['raid'], {}).setdefault(doc['mode'], []).append(doc)
    return out


def _mode_row(mode, raids, known, expected, counted=True):
    """One line of a raid row's per-mode breakdown (completions, how many were known, expected uniques)."""
    return {'mode': mode, 'raids': raids, 'known': known, 'expected': round(expected, 3), 'counted': counted}


def _merge_modes(existing, new_rows):
    """Adds per-mode rows into a list, summing a mode that is already there."""
    by_mode = {r['mode']: dict(r) for r in existing}
    for r in new_rows:
        if r['mode'] in by_mode:
            cur = by_mode[r['mode']]
            cur['raids'] += r['raids']
            cur['known'] += r['known']
            cur['expected'] = round(cur['expected'] + r['expected'], 3)
            cur['counted'] = cur['counted'] or r['counted']
        else:
            by_mode[r['mode']] = dict(r)
    return sorted(by_mode.values(), key=lambda r: r['mode'])


def _item_name_set(raid):
    """Lower-case names of every unique this raid can drop (any mode)."""
    names = set()
    if raid == 'COX':
        for w in COX_WEIGHTS.values():
            names |= set(w)
    elif raid == 'TOB':
        for w in TOB_WEIGHTS.values():
            names |= set(w)
    else:
        names |= set(_TOA_BASE_WEIGHTS)
    return names


def _expected_items(docs, raid):
    """(scored count, unscored count, {item: expected uniques}) over these raids."""
    scored = unscored = 0
    expected = {}
    for doc in docs:
        chance = raid_unique_chance(doc)
        if chance is None:
            unscored += 1
            continue
        scored += 1
        for item, w in _raid_item_weights(raid, doc['mode'], doc.get('raid_level')).items():
            expected[item] = expected.get(item, 0.0) + chance * w
    return scored, unscored, expected


def _items_out(expected, actual, n):
    rows = []
    for item, exp in expected.items():
        if exp <= 0:
            continue
        rate = n / exp
        got = actual.get(item, 0)
        rows.append({'item': item, 'expected': round(exp, 4), 'actual': got,
                     'rarity_1_in': round(rate, 1), 'diff': round((got - exp) * rate)})
    rows.sort(key=lambda r: r['diff'])
    return rows


def compute_raid_luck_lifetime(collections):
    """
    Lifetime raid luck: every raid the plugin or a screenshot told us about, against the player's
    whole collection log (nothing subtracted, since the log is lifetime).

    Per raid mode, the known raids' expected uniques are scaled up to the mode's full completion
    count (KC from the collection log page or the highest completion count seen, whichever is
    larger), on the assumption that unknown raids resemble known ones. A mode with under
    MIN_COVERAGE known is left out and reported in `uncovered_modes`, and so is any raid with no
    collection log page synced yet (nothing to compare against).

    Returns {player: {raid: {'basis': 'lifetime', 'raids_scored', 'kc', 'coverage', 'unscored',
    'uncovered_modes', 'expected_uniques', 'actual_uniques', 'luck_kills', 'items'}}}
    """
    grouped = _group_by_player_raid_mode(collections)
    kc_lookup = {}
    for doc in collections['plugin_kc'].find({}):
        kc_lookup[doc.get('player')] = {str(c.get('name', '')).lower(): c.get('kc', 0) for c in doc.get('counts') or []}
    clog_pages = {}
    for page in collections['plugin_clog'].find({}):
        raid, _ = classify_clog_page(page.get('page'))
        if raid:
            clog_pages[(page.get('player'), raid)] = page

    result = {}
    for player, raids in grouped.items():
        for raid, modes in raids.items():
            page = clog_pages.get((player, raid))
            if not page:
                continue
            expected_total = {}
            kc_total = scored_total = unscored_total = 0
            uncovered = []
            mode_lines = []
            for mode, docs in modes.items():
                scored, unscored, expected = _expected_items(docs, raid)
                unscored_total += unscored
                kc = max(kc_lookup.get(player, {}).get(KC_NAMES.get((raid, mode), ''), 0),
                         max((d.get('kill_count', 0) for d in docs), default=0))
                if not scored or not kc or scored / kc < MIN_COVERAGE:
                    if kc:
                        uncovered.append({'mode': mode, 'kc': kc, 'known': scored})
                        mode_lines.append(_mode_row(mode, kc, scored, 0.0, counted=False))
                    continue
                factor = max(1.0, kc / scored)
                for item, exp in expected.items():
                    expected_total[item] = expected_total.get(item, 0.0) + exp * factor
                kc_total += kc
                scored_total += scored
                mode_lines.append(_mode_row(mode, kc, scored, sum(expected.values()) * factor))
            if not kc_total:
                continue
            actual = {}
            for it in page.get('items') or []:
                key = _canonical_item(it.get('name'))
                if key in expected_total and it.get('obtained'):
                    actual[key] = max(actual.get(key, 0), it.get('quantity', 0) or 0)
            items = _items_out(expected_total, actual, kc_total)
            result.setdefault(player, {})[raid] = {
                'basis': 'lifetime', 'raids_scored': scored_total, 'kc': kc_total,
                'coverage': round(scored_total / kc_total, 3), 'unscored': unscored_total,
                'uncovered_modes': uncovered, 'modes': sorted(mode_lines, key=lambda r: r['mode']),
                'expected_uniques': round(sum(expected_total.values()), 4),
                'actual_uniques': sum(actual.values()), 'luck_kills': sum(i['diff'] for i in items), 'items': items,
            }
    return result


def _drop_raid(doc):
    """Which raid a Dink drop document came from, by its source text, or None."""
    source = (doc.get('source') or '').lower()
    for raid, name in RAID_SOURCES.items():
        if name in source:
            return raid
    return None


def compute_raid_luck_event(collections, start_epoch, end_epoch, drops):
    """
    Raid luck for a window (a bingo event): raids completed inside [start, end] (their times come
    from the plugin or from screenshot filenames) against uniques in the Dink drop history inside
    the same window. `drops` are the already-deduplicated history documents for that window.
    Nothing is scaled up here: only raids actually known count, so a missing screenshot makes a
    player look slightly unluckier, and `unscored` is reported.

    Returns {player: {raid: {'basis': 'event', 'raids_scored', 'unscored', 'expected_uniques',
    'actual_uniques', 'luck_kills', 'items'}}}
    """
    result = {}
    for player, raids in _group_by_player_raid_mode(collections).items():
        for raid, modes in raids.items():
            docs = [d for ds in modes.values() for d in ds if start_epoch <= d.get('completed_at', 0) <= end_epoch]
            scored, unscored, expected = _expected_items(docs, raid)
            if not scored:
                continue
            mode_lines = []
            for mode, mode_docs in modes.items():
                in_window = [d for d in mode_docs if start_epoch <= d.get('completed_at', 0) <= end_epoch]
                m_scored, _, m_expected = _expected_items(in_window, raid)
                if m_scored:
                    mode_lines.append(_mode_row(mode, len(in_window), m_scored, sum(m_expected.values())))
            names = _item_name_set(raid)
            actual = {}
            for drop in drops:
                if drop.get('player') != player or _drop_raid(drop) != raid:
                    continue
                key = _canonical_item(drop.get('item'))
                if key in names:
                    actual[key] = actual.get(key, 0) + 1
            items = _items_out(expected, actual, scored)
            result.setdefault(player, {})[raid] = {
                'basis': 'event', 'raids_scored': scored, 'unscored': unscored,
                'modes': sorted(mode_lines, key=lambda r: r['mode']),
                'expected_uniques': round(sum(expected.values()), 4), 'actual_uniques': sum(actual.values()),
                'luck_kills': sum(i['diff'] for i in items), 'items': items,
            }
    return result


def compute_raid_luck(collections):
    """
    All Time raid luck: lifetime where enough raids are known, otherwise falling back to
    "since the plugin first synced" for that player and raid.
    """
    merged = compute_raid_luck_since_sync(collections)
    for player, raids in compute_raid_luck_lifetime(collections).items():
        for raid, info in raids.items():
            merged.setdefault(player, {})[raid] = info
    for raids in merged.values():
        for info in raids.values():
            info.setdefault('basis', 'since_plugin')
    return merged
