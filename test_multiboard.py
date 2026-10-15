import unittest
from datetime import datetime

import multiboard as mb


def make_board(size=3, done=None, value=10, bonuses=None):
    """done: {tile_index: [players]}"""
    done = done or {}
    return {
        'boardSize': size,
        'tiles': [{'items': ['x'], 'value': value, 'completedBy': list(done.get(i, []))} for i in range(size * size)],
        'lineBonuses': bonuses or {'rows': [50] * size, 'cols': [20] * size, 'diags': [100, 100]},
    }


class BoardScoreTests(unittest.TestCase):
    def test_tile_points_only(self):
        s = mb.board_scores(make_board(done={0: ['a'], 1: ['a', 'b']}))
        self.assertEqual(s['a']['points'], 20)
        self.assertEqual(s['b']['points'], 10)

    def test_row_col_diag_bonuses(self):
        # a holds the whole top row (0,1,2) and the main diagonal (0,4,8)
        board = make_board(done={0: ['a'], 1: ['a'], 2: ['a'], 4: ['a'], 8: ['a']})
        a = mb.board_scores(board)['a']
        self.assertEqual(a['tiles'], 5)
        self.assertEqual(a['tile_points'], 50)
        self.assertEqual(a['line_bonus'], 50 + 100)  # row 0 + diag 0
        self.assertEqual(a['lines'], 2)

    def test_anti_diagonal(self):
        board = make_board(done={2: ['a'], 4: ['a'], 6: ['a']})
        self.assertEqual(mb.board_scores(board)['a']['line_bonus'], 100)


class TeamTests(unittest.TestCase):
    def meta(self, board, teams):
        m = mb.normalize_board_meta({**board, 'board_id': 't', 'teamMode': True, 'teams': teams})
        return m

    def test_tile_counts_once_per_team(self):
        board = make_board(done={0: ['a', 'b'], 1: ['b']})
        meta = self.meta(board, {'Red': ['a', 'b'], 'Blue': ['c']})
        s = mb.board_scores(board, meta)
        self.assertEqual(s['Red']['tiles'], 2)
        self.assertEqual(s['Red']['points'], 20)
        self.assertNotIn('Blue', s)

    def test_team_line_across_members(self):
        # a has tiles 0,1; b has tile 2 -> together the team owns row 0
        board = make_board(done={0: ['a'], 1: ['a'], 2: ['b']})
        meta = self.meta(board, {'Red': ['a', 'b']})
        s = mb.board_scores(board, meta)
        self.assertEqual(s['Red']['line_bonus'], 50)

    def test_unassigned_player_scores_nothing(self):
        board = make_board(done={0: ['loner']})
        meta = self.meta(board, {'Red': ['a']})
        self.assertEqual(mb.board_scores(board, meta), {})


class CombinedTests(unittest.TestCase):
    def test_sums_boards_with_weights(self):
        b1 = make_board(done={0: ['a']})            # a: 10
        b2 = make_board(done={0: ['a'], 1: ['b']})  # a: 10, b: 10
        m1 = mb.normalize_board_meta({'board_id': 'one', 'name': 'One'})
        m2 = mb.normalize_board_meta({'board_id': 'two', 'name': 'Two', 'weight': 2})
        rows = mb.combined_leaderboard([(b1, m1), (b2, m2)])
        by = {r['name']: r for r in rows}
        self.assertEqual(by['a']['points'], 10 + 20)
        self.assertEqual(by['b']['points'], 20)
        self.assertEqual(by['a']['rank'], 1)
        self.assertEqual(by['a']['breakdown']['two']['weighted'], 20)

    def test_same_item_on_two_boards_scores_on_both(self):
        b1 = make_board(done={0: ['a']})
        b2 = make_board(done={0: ['a']})
        rows = mb.combined_leaderboard([
            (b1, mb.normalize_board_meta({'board_id': 'one'})),
            (b2, mb.normalize_board_meta({'board_id': 'two'})),
        ])
        self.assertEqual(rows[0]['points'], 20)

    def test_team_board_gives_each_member_team_points(self):
        board = make_board(done={0: ['a']})
        meta = mb.normalize_board_meta({'board_id': 't', 'teamMode': True, 'teams': {'Red': ['a', 'b']}})
        rows = mb.combined_leaderboard([(board, meta)])
        self.assertEqual({r['name']: r['points'] for r in rows}, {'a': 10, 'b': 10})

    def test_ties_share_rank(self):
        b = make_board(done={0: ['a'], 1: ['b'], 2: ['c', 'd']})
        rows = mb.combined_leaderboard([(b, mb.normalize_board_meta({'board_id': 'x'}))])
        self.assertEqual([r['rank'] for r in rows], [1, 1, 1, 1])


class WindowTests(unittest.TestCase):
    D = staticmethod(lambda s: datetime.fromisoformat(s))

    def test_board_inherits_event_dates(self):
        event = {'startDate': '2026-01-01T00:00:00Z', 'endDate': '2026-12-31T00:00:00Z'}
        s, e = mb.board_window({'startDate': '2026-03-01T00:00:00Z'}, event)
        self.assertEqual(s, datetime(2026, 3, 1))
        self.assertEqual(e, datetime(2026, 12, 31))

    def test_validate_board_in_event(self):
        ev = (datetime(2026, 1, 1), datetime(2026, 12, 31))
        self.assertIsNone(mb.validate_board_in_event((datetime(2026, 2, 1), datetime(2026, 3, 1)), ev))
        self.assertIsNotNone(mb.validate_board_in_event((datetime(2025, 12, 1), None), ev))
        self.assertIsNotNone(mb.validate_board_in_event((None, datetime(2027, 1, 1)), ev))
        self.assertIsNotNone(mb.validate_board_in_event((datetime(2026, 3, 1), datetime(2026, 2, 1)), ev))

    def test_merge_overlapping_windows(self):
        w = [(datetime(2026, 1, 1), datetime(2026, 6, 30)),   # 6-month long board
             (datetime(2026, 1, 1), datetime(2026, 1, 31)),   # month boards inside it
             (datetime(2026, 2, 1), datetime(2026, 2, 28)),
             (datetime(2026, 8, 1), datetime(2026, 8, 31))]
        merged = mb.merge_windows(w)
        self.assertEqual(merged, [(datetime(2026, 1, 1), datetime(2026, 6, 30)),
                                  (datetime(2026, 8, 1), datetime(2026, 8, 31))])

    def test_window_contains(self):
        w = (datetime(2026, 1, 1), datetime(2026, 2, 1))
        self.assertTrue(mb.window_contains(w, datetime(2026, 1, 15)))
        self.assertFalse(mb.window_contains(w, datetime(2026, 3, 1)))
        self.assertTrue(mb.window_contains((None, None), datetime(2026, 3, 1)))


if __name__ == '__main__':
    unittest.main()
