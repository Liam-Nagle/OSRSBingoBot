"""
Multi-board helpers: board metadata defaults, date windows, per-board scoring (individual or team) and the
weighted "combined" leaderboard. Pure functions - no Flask, no database - so they're unit-testable on their own
(see test_multiboard.py). bingo_api.py owns storage and routes.

Concepts
  event  - the container (name + dates). The archive freezes one event, with all of its boards inside.
  board  - a bingo board that lives inside an event. Has its own dates (defaults to the event's), settings,
           optional team mode, and a weight used when boards are added into a combined leaderboard.
  The original single board/event are board_id "main" / event_id "main", so nothing about existing data moves.
"""
from datetime import datetime, timezone

MAIN_ID = 'main'

# Fields that describe a board rather than its tiles. The editor round-trips whole board documents, so these are
# preserved on save even when the client sends a board without them.
BOARD_META_KEYS = (
    'board_id', 'event_id', 'name', 'label', 'startDate', 'endDate', 'enabled',
    'teamMode', 'teams', 'inCombined', 'weight', 'order',
)


def parse_iso_utc(value):
    """ISO string (or datetime) -> naive UTC datetime, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def normalize_board_meta(doc, default_event_id=MAIN_ID):
    """Board metadata with defaults filled in (does not mutate doc)."""
    board_id = doc.get('board_id') or MAIN_ID
    return {
        'board_id': board_id,
        'event_id': doc.get('event_id') or default_event_id,
        'name': doc.get('name') or ('Main Board' if board_id == MAIN_ID else board_id),
        'label': doc.get('label') or '',
        'startDate': doc.get('startDate'),
        'endDate': doc.get('endDate'),
        'enabled': doc.get('enabled', True),
        'teamMode': bool(doc.get('teamMode', False)),
        'teams': doc.get('teams') or {},
        'inCombined': doc.get('inCombined', True),
        'weight': float(doc.get('weight', 1) if doc.get('weight') is not None else 1),
        'order': doc.get('order', 0),
    }


def board_window(board, event):
    """(start, end) naive-UTC datetimes for a board: its own dates, falling back to the event's per side."""
    start = parse_iso_utc(board.get('startDate')) or parse_iso_utc((event or {}).get('startDate'))
    end = parse_iso_utc(board.get('endDate')) or parse_iso_utc((event or {}).get('endDate'))
    return start, end


def window_contains(window, when):
    start, end = window
    if start and when < start:
        return False
    if end and when > end:
        return False
    return True


def merge_windows(windows):
    """Union of (start, end) windows as a minimal sorted list - overlapping windows must not double count drops."""
    cleaned = [(s, e) for s, e in windows if s or e]
    # Open-ended sides sort/compare as -inf/+inf.
    lo, hi = datetime.min, datetime.max
    cleaned = sorted(((s or lo, e or hi) for s, e in cleaned))
    merged = []
    for s, e in cleaned:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return [(None if s == lo else s, None if e == hi else e) for s, e in merged]


def validate_board_in_event(board_window_, event_window):
    """Error string if a board's dates fall outside its event's, else None."""
    bs, be = board_window_
    es, ee = event_window
    if bs and be and be <= bs:
        return 'Board end date must be after its start date'
    if bs and es and bs < es:
        return 'Board starts before its event does'
    if be and ee and be > ee:
        return 'Board ends after its event does'
    return None


# ----------------------------------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------------------------------

def _lines(board_size):
    """Every line as (kind, index, [tile indexes])."""
    out = []
    for r in range(board_size):
        out.append(('rows', r, [r * board_size + c for c in range(board_size)]))
    for c in range(board_size):
        out.append(('cols', c, [r * board_size + c for r in range(board_size)]))
    out.append(('diags', 0, [i * board_size + i for i in range(board_size)]))
    out.append(('diags', 1, [i * board_size + (board_size - 1 - i) for i in range(board_size)]))
    return out


def _score_holders(board, holders_of_tile):
    """
    Score a board for a set of "scorers". holders_of_tile(tile) -> set of scorer keys that count as having
    completed that tile. Same rules as the live leaderboard (tile value + row/col/diagonal bonuses).
    """
    tiles = board.get('tiles', [])
    size = board.get('boardSize', 5)
    bonuses = board.get('lineBonuses') or {}

    holders = [holders_of_tile(t) for t in tiles]
    scores = {}
    for tile, held in zip(tiles, holders):
        for key in held:
            entry = scores.setdefault(key, {'tiles': 0, 'tile_points': 0, 'line_bonus': 0, 'lines': 0})
            entry['tiles'] += 1
            entry['tile_points'] += tile.get('value', 0)

    for key, entry in scores.items():
        for kind, idx, indexes in _lines(size):
            if all(i < len(holders) and key in holders[i] for i in indexes):
                entry['lines'] += 1
                bonus_list = bonuses.get(kind) or []
                if idx < len(bonus_list):
                    entry['line_bonus'] += bonus_list[idx]
        entry['points'] = entry['tile_points'] + entry['line_bonus']
    return scores


def board_scores(board, meta=None):
    """
    {scorer: {tiles, tile_points, line_bonus, lines, points}} for one board.
    Individual boards score per player. In team mode the scorer is the team: a tile counts once for a team if any
    member completed it, and a line counts if the team's members between them cover it. A player who is on no
    team is ignored on a team board (they score nothing there) - the admin assigns everyone.
    """
    meta = meta or normalize_board_meta(board)
    if not meta['teamMode']:
        return _score_holders(board, lambda t: set(t.get('completedBy') or []))

    member_team = {}
    for team, members in (meta['teams'] or {}).items():
        for m in members:
            member_team[m] = team

    def teams_of(tile):
        return {member_team[p] for p in (tile.get('completedBy') or []) if p in member_team}

    scores = _score_holders(board, teams_of)
    for team, entry in scores.items():
        entry['members'] = list((meta['teams'] or {}).get(team, []))
    return scores


def rank_rows(rows):
    """Sort score rows by points (then tiles, then name) and assign ranks, ties sharing a rank."""
    rows.sort(key=lambda r: (-r['points'], -r.get('tiles', 0), str(r['name']).lower()))
    previous, rank = None, 0
    for position, row in enumerate(rows, start=1):
        if row['points'] != previous:
            rank, previous = position, row['points']
        row['rank'] = rank
    return rows


def board_leaderboard(board, meta=None):
    meta = meta or normalize_board_meta(board)
    rows = [{'name': k, **v} for k, v in board_scores(board, meta).items()]
    return rank_rows(rows)


def combined_leaderboard(boards_with_meta):
    """
    Sum of weighted per-board points per player, across [(board_doc, meta), ...] (callers pass only the boards
    that count). Team-mode boards give every team member the team's board points. Returns ranked rows:
      {name, points, tiles, breakdown: {board_id: {name, points, weighted}}}
    """
    totals = {}
    for board, meta in boards_with_meta:
        scores = board_scores(board, meta)
        weight = meta['weight']
        if meta['teamMode']:
            per_player = {}
            for team, entry in scores.items():
                for member in entry.get('members', []):
                    per_player[member] = entry
        else:
            per_player = scores
        for player, entry in per_player.items():
            row = totals.setdefault(player, {'name': player, 'points': 0, 'tiles': 0, 'breakdown': {}})
            weighted = round(entry['points'] * weight, 2)
            row['points'] = round(row['points'] + weighted, 2)
            row['tiles'] += entry['tiles']
            row['breakdown'][meta['board_id']] = {
                'name': meta['name'], 'points': entry['points'], 'weighted': weighted,
            }
    return rank_rows(list(totals.values()))
