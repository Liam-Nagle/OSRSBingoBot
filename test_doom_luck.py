"""Checks doom_luck.py against the OSRS Wiki's published Doom drop table. Run: python test_doom_luck.py"""
import doom_luck as d


def close(a, b, tol=1e-3):
    return abs(a - b) <= tol * max(1.0, abs(b))


class Col:
    def __init__(self, docs=()):
        self.docs = list(docs)

    def find(self, q=None):
        return list(self.docs)


def test_one_run_matches_the_wikis_cumulative_rates():
    # The wiki's table lists the chance across a whole run: "delve 8: cloth ~1/140, eye ~1/148, treads ~1/160".
    # One completion of each level 1..8 must add up to those.
    run = [1] * 8
    exp = d.doom_expected(run, 0)
    assert close(1 / exp['mokhaiotl cloth'], 140, 0.01)
    assert close(1 / exp['eye of ayak'], 148, 0.01)
    assert close(1 / exp['avernic treads'], 160, 0.01)


def test_deep_delves_use_the_level_9_rate():
    exp = d.doom_expected([0] * 8, 540)                    # 540 deep delves at 1/540 each
    assert close(exp['mokhaiotl cloth'], 1.0) and close(exp['eye of ayak'], 1.0) and close(exp['avernic treads'], 1.0)


def test_low_levels_only_roll_the_uniques_they_can_drop():
    exp = d.doom_expected([5, 5, 0, 0, 0, 0, 0, 0], 0)     # five level-1 and five level-2 delves
    assert close(exp['mokhaiotl cloth'], 5 / 2500)         # cloth starts at level 2
    assert exp['eye of ayak'] == 0 and exp['avernic treads'] == 0


def test_compute_luck_scores_a_player_in_kills():
    cols = {
        'plugin_doom': Col([{'player': 'Zezima', 'levels': [20, 20, 20, 20, 20, 20, 20, 20], 'past8': 100}]),
        'plugin_clog': Col([{'player': 'Zezima', 'page': 'Doom of Mokhaiotl', 'items': [
            {'name': 'Mokhaiotl cloth', 'quantity': 2, 'obtained': True},
            {'name': 'Eye of Ayak (uncharged)', 'quantity': 0, 'obtained': False},
        ]}]),
    }
    out = d.compute_doom_luck(cols)['Zezima']
    assert out['completions'] == 260
    cloth = next(i for i in out['items'] if i['item'] == 'mokhaiotl cloth')
    assert close(cloth['expected'], 20 * (1 / 2500 + 1 / 2000 + 1 / 1350 + 1 / 810 + 1 / 765 + 1 / 720 + 1 / 630) + 100 / 540)
    assert cloth['actual'] == 2
    eye = next(i for i in out['items'] if i['item'] == 'eye of ayak')
    assert eye['actual'] == 0 and eye['diff'] < 0          # a dry unique is behind rate
    # Existing counts from drop history can raise the actual count but the plugin page never lowers it
    out2 = d.compute_doom_luck(cols, {'Zezima': {'mokhaiotl cloth': 5, 'avernic treads': 1}})['Zezima']
    assert next(i for i in out2['items'] if i['item'] == 'mokhaiotl cloth')['actual'] == 5
    assert next(i for i in out2['items'] if i['item'] == 'avernic treads')['actual'] == 1


def test_skips_players_with_no_delves_or_a_bad_record():
    cols = {'plugin_doom': Col([{'player': 'A', 'levels': [0] * 8, 'past8': 0}, {'player': 'B', 'levels': [1, 2], 'past8': 0}]),
            'plugin_clog': Col()}
    assert d.compute_doom_luck(cols) == {}


def test_event_window_ignores_the_lifetime_collection_log():
    cols = {
        'plugin_doom': Col([{'player': 'Zezima', 'levels': [20] * 8, 'past8': 100}]),
        'plugin_clog': Col([{'player': 'Zezima', 'page': 'Doom of Mokhaiotl', 'items': [
            {'name': 'Mokhaiotl cloth', 'quantity': 4, 'obtained': True}]}]),
    }
    all_time = d.compute_doom_luck(cols, {'Zezima': {'mokhaiotl cloth': 1}}, use_clog=True)['Zezima']
    event = d.compute_doom_luck(cols, {'Zezima': {'mokhaiotl cloth': 1}}, use_clog=False)['Zezima']
    cloth = lambda out: next(i for i in out['items'] if i['item'] == 'mokhaiotl cloth')
    assert cloth(all_time)['actual'] == 4                 # the lifetime log lifts it to 4
    assert cloth(event)['actual'] == 1                    # an event only counts that window's drops


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
