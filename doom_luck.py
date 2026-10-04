"""
Doom of Mokhaiotl luck from exact per-level delve completions.

The hiscores only count deep delves ("the actual kill count is the amount of deep delves completed"),
but uniques can drop from delve 2 onwards, at rates that change with every level. So the old way - the
hiscores KC times one flat rate - gets both the number of attempts and the rate wrong. This works from
the player's real completions at each level, which the BingoLuckSync plugin reads off the in-game
scoreboard and keeps current from the "Delve level: N" game messages.

Rates are the OSRS Wiki's (Module:Doom of Mokhaiotl Completions, "unique drop rates per single kill at
each delve level"). Delve 9 stands for every level past 8. Dom (the pet) is left out: it isn't a
chase item on the curated list, and the wiki's own totals exclude it too.
"""

# item -> {delve level: 1 in X per completion of that level}
DOOM_UNIQUE_RATES = {
    'mokhaiotl cloth': {2: 2500, 3: 2000, 4: 1350, 5: 810, 6: 765, 7: 720, 8: 630, 9: 540},
    'eye of ayak': {3: 2000, 4: 1350, 5: 810, 6: 765, 7: 720, 8: 630, 9: 540},
    'avernic treads': {4: 1350, 5: 810, 6: 765, 7: 720, 8: 630, 9: 540},
}
LEVELS = 8
CLOG_PAGE = 'doom of mokhaiotl'


def doom_expected(levels, past8):
    """
    {item: expected uniques} for `levels` (completions of delve levels 1..8 in order) plus `past8`
    completions of every deeper level.
    """
    expected = {}
    for item, rates in DOOM_UNIQUE_RATES.items():
        total = 0.0
        for level in range(2, LEVELS + 1):
            if level in rates:
                total += levels[level - 1] / rates[level]
        total += past8 / rates[9]
        expected[item] = total
    return expected


def _canonical(name):
    n = (name or '').lower().strip()
    return n[:-len(' (uncharged)')] if n.endswith(' (uncharged)') else n


def compute_doom_luck(collections, known_actual=None, use_clog=True):
    """
    Per player: expected vs actual Doom uniques, in "kills ahead (+) / behind (-)" like the rest of the
    Luck tab, where a "kill" is any delve completion (level 1 included).

    `known_actual` is {player: {item: count}} already worked out from drop history and the collection
    log elsewhere. With `use_clog` (All Time) the plugin's own collection log page can raise a count
    but never lower it; for an event window it is left out, since the log is lifetime and the window's
    drops come from the drop history instead.

    The delve counts are lifetime, so for an event window this treats all of a player's delves as having
    happened inside it - true while Doom is new to the group. A later event should subtract a snapshot
    taken at its start (the server keeps one a day in plugin_doom_history).
    """
    known_actual = known_actual or {}
    clog = {}
    for page in (collections['plugin_clog'].find({}) if use_clog else []):
        if (page.get('page') or '').lower() == CLOG_PAGE:
            counts = {}
            for it in page.get('items') or []:
                if it.get('obtained'):
                    key = _canonical(it.get('name'))
                    counts[key] = max(counts.get(key, 0), it.get('quantity', 0) or 0)
            clog[page.get('player')] = counts

    result = {}
    for doc in collections['plugin_doom'].find({}):
        player = doc.get('player')
        levels = doc.get('levels') or []
        past8 = doc.get('past8', 0)
        if not player or len(levels) != LEVELS:
            continue
        completions = sum(levels) + past8
        if completions <= 0:
            continue
        expected = doom_expected(levels, past8)
        items = []
        for item, exp in expected.items():
            if exp <= 0:
                continue
            got = max((known_actual.get(player) or {}).get(item, 0), clog.get(player, {}).get(item, 0))
            rate = completions / exp
            items.append({'item': item, 'rarity_1_in': round(rate, 1), 'expected': round(exp, 4),
                          'actual': got, 'diff': round((got - exp) * rate)})
        if not items:
            continue
        items.sort(key=lambda i: i['diff'])
        result[player] = {
            'completions': completions, 'levels': list(levels), 'past8': past8,
            'expected_uniques': round(sum(i['expected'] for i in items), 4),
            'actual_uniques': sum(i['actual'] for i in items),
            'luck_kills': sum(i['diff'] for i in items), 'items': items,
        }
    return result
