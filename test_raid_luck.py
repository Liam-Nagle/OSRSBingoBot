"""Checks raid_luck.py against the worked examples and tables on the OSRS Wiki. Run: python test_raid_luck.py"""
import math
from datetime import datetime, timezone

import raid_luck as r


def close(a, b, tol=1e-3):
    return abs(a - b) <= tol * max(1.0, abs(b))


def test_cox_chance():
    assert close(r.cox_individual_chance(8676), 0.01)
    assert close(r.cox_individual_chance(86760), 0.10)
    assert close(r.cox_individual_chance(10_000_000), 0.657)           # personal cap
    # Team over the cap: a 30% share of a 1,000,000 point team gets 30% of 65.7%
    assert close(r.cox_individual_chance(300_000, 1_000_000), 0.657 * 0.3)
    assert r.cox_individual_chance(-1) is None


def test_cox_weights_sum():
    assert sum(r.COX_WEIGHTS['NORMAL'].values()) == 60
    assert sum(r.COX_WEIGHTS['CHALLENGE'].values()) == 56


def test_tob_chance():
    # Deathless team of 4 -> 10.99% (1/9.1) split across 4 equal players
    assert close(4 * r.tob_individual_chance('NORMAL', 4, 0), 1 / 9.1)
    assert close(4 * r.tob_individual_chance('HARD', 4, 0), 1 / 7.7)
    # Team size doesn't change the team chance
    for n in (1, 2, 3, 5):
        assert close(n * r.tob_individual_chance('NORMAL', n, 0), 1 / 9.1)
    assert r.tob_individual_chance('STORY', 4, 0) is None
    assert r.tob_individual_chance('NORMAL', None, 0) is None
    # Each death costs 4 points, so a death lowers your chance
    assert r.tob_individual_chance('NORMAL', 4, 1) < r.tob_individual_chance('NORMAL', 4, 0)
    assert sum(r.TOB_WEIGHTS['NORMAL'].values()) == 19
    assert sum(r.TOB_WEIGHTS['HARD'].values()) == 18


def test_toa_chance():
    # Wiki example: raid level 400 -> 1% per 3,700 points
    assert close(r.toa_individual_chance(400, 3700), 0.01)
    assert close(r.toa_individual_chance(400, 37000), 0.10)
    assert close(r.toa_individual_chance(300, 4500), 0.01)             # 1% per 4,500 at RL300
    assert close(r.toa_individual_chance(400, 10_000_000), 0.55)       # cap
    # Team over the cap (300,000 points at RL400 would be 81%): a 1/6 share gets 1/6 of 55%
    assert close(r.toa_individual_chance(400, 50_000, 300_000), 0.55 / 6)
    # Team just under the cap is uncapped: 200,000 points is a 54% team chance
    assert close(r.toa_individual_chance(400, 50_000, 200_000), 50_000 / 370_000)
    assert close(r.toa_scaled_raid_level(500), 350 + 70 / 6)


def test_toa_weights_match_wiki_table():
    expect = {  # raid level -> (fang, lightbearer, ward, masori piece, shadow) as "1 in x"
        300: (3.43, 3.43, 8, 12, 24),
        350: (3.67, 3.67, 7.33, 11, 22),
        400: (4.75, 3.8, 6.33, 9.5, 19),
        450: (4.5, 4.5, 6, 9, 18),
        500: (5.5, 4.71, 5.5, 8.25, 16.5),
    }
    for rl, (fang, lb, ward, masori, shadow) in expect.items():
        w = r.toa_weights(rl)
        assert math.isclose(sum(w.values()), 1.0)
        assert close(1 / w["osmumten's fang"], fang, 5e-3), (rl, 'fang')
        assert close(1 / w['lightbearer'], lb, 5e-3), (rl, 'lightbearer')
        assert close(1 / w["elidinis' ward"], ward, 5e-3), (rl, 'ward')
        assert close(1 / w['masori mask'], masori, 5e-3), (rl, 'masori')
        assert close(1 / w["tumeken's shadow"], shadow, 5e-3), (rl, 'shadow')
    # Below RL 150 the non-fang/lightbearer uniques are 1/50 as likely
    low = r.toa_weights(100)
    assert low["tumeken's shadow"] < r.toa_weights(300)["tumeken's shadow"] / 20


class Col:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q=None):
        return list(self.docs)


def test_compute_raid_luck():
    first_seen = datetime(2026, 10, 1, tzinfo=timezone.utc)
    after = int(first_seen.timestamp()) + 3600
    before = int(first_seen.timestamp()) - 3600
    raids = [
        # Counted: ToA expert RL 400, 37,000 points = 10% purple chance
        {'player': 'Zezima', 'raid': 'TOA', 'mode': 'EXPERT', 'kill_count': 1, 'completed_at': after,
         'personal_points': 37000, 'raid_level': 400, 'team_size': 2, 'total_points': -1},
        # Ignored: finished before the clog page was first synced
        {'player': 'Zezima', 'raid': 'TOA', 'mode': 'EXPERT', 'kill_count': 0, 'completed_at': before,
         'personal_points': 37000, 'raid_level': 400, 'team_size': 2, 'total_points': -1},
        # Unscored: no points recorded
        {'player': 'Zezima', 'raid': 'TOA', 'mode': 'EXPERT', 'kill_count': 2, 'completed_at': after + 10,
         'personal_points': -1, 'raid_level': 400, 'team_size': 2, 'total_points': -1},
    ]
    clog = [{
        'player': 'Zezima', 'page': 'Tombs of Amascut', 'first_seen_at': first_seen,
        'baseline': {'1': 1},
        'items': [
            {'id': 1, 'name': "Tumeken's shadow", 'quantity': 2, 'obtained': True},   # got one since baseline
            {'id': 2, 'name': "Osmumten's fang", 'quantity': 0, 'obtained': False},
            {'id': 3, 'name': 'Some pet', 'quantity': 1, 'obtained': True},
        ],
    }]
    assert r.classify_clog_page('Tombs of Amascut') == ('TOA', {'NORMAL', 'ENTRY', 'EXPERT'})
    assert r.classify_clog_page('Chambers of Xeric')[0] == 'COX'
    assert r.classify_clog_page('Theatre of Blood')[0] == 'TOB'
    assert r.classify_clog_page('Zulrah') == (None, set())
    out = r.compute_raid_luck_since_sync({'plugin_raids': Col(raids), 'plugin_clog': Col(clog)})
    toa = out['Zezima']['TOA']
    assert toa['raids_scored'] == 1 and toa['unscored'] == 1
    assert close(toa['expected_uniques'], 0.10)
    assert toa['actual_uniques'] == 1
    shadow = next(i for i in toa['items'] if i['item'] == "tumeken's shadow")
    assert shadow['actual'] == 1 and close(shadow['expected'], 0.10 * 10 / 190, 1e-3)
    assert shadow['diff'] > 0                       # a 1-in-190 item arriving in 1 raid is lucky
    fang = next(i for i in toa['items'] if i['item'] == "osmumten's fang")
    assert fang['actual'] == 0 and fang['diff'] < 0


def toa_raids(n, start_kc=1, points=37000, level=400, t0=1_700_000_000, source='screenshot'):
    return [{'player': 'Zezima', 'raid': 'TOA', 'mode': 'EXPERT', 'kill_count': start_kc + i, 'completed_at': t0 + i * 3600,
             'personal_points': points, 'raid_level': level, 'team_size': -1, 'total_points': -1, 'source': source}
            for i in range(n)]


def toa_page(shadow=0, fang=0):
    return {'player': 'Zezima', 'page': 'Tombs of Amascut', 'first_seen_at': datetime(2026, 10, 1, tzinfo=timezone.utc),
            'baseline': {}, 'items': [
                {'id': 1, 'name': "Tumeken's shadow (uncharged)", 'quantity': shadow, 'obtained': shadow > 0},
                {'id': 2, 'name': "Osmumten's fang", 'quantity': fang, 'obtained': fang > 0}]}


def test_lifetime_scales_known_raids_to_kc():
    # 30 of 40 completions known, each a 10% chance -> 3 expected, scaled by 40/30 to 4
    cols = {'plugin_raids': Col(toa_raids(30)), 'plugin_clog': Col([toa_page(shadow=1, fang=3)]),
            'plugin_kc': Col([{'player': 'Zezima', 'counts': [{'name': 'Tombs of Amascut (Expert)', 'kc': 40}]}])}
    info = r.compute_raid_luck_lifetime(cols)['Zezima']['TOA']
    assert info['basis'] == 'lifetime' and info['kc'] == 40 and info['raids_scored'] == 30
    assert close(info['coverage'], 0.75) and close(info['expected_uniques'], 4.0)
    assert info['actual_uniques'] == 4                      # lifetime quantity, no baseline subtracted
    fang = next(i for i in info['items'] if i['item'] == "osmumten's fang")
    assert close(fang['expected'], 4.0 * 70 / 190 * 0 + 4.0 * (40 / 190), 1e-3) and fang['actual'] == 3


def test_lifetime_needs_enough_coverage_and_a_synced_page():
    kc = Col([{'player': 'Zezima', 'counts': [{'name': 'Tombs of Amascut (Expert)', 'kc': 49}]}])
    few = {'plugin_raids': Col(toa_raids(10)), 'plugin_clog': Col([toa_page()]), 'plugin_kc': kc}
    assert 'Zezima' not in r.compute_raid_luck_lifetime(few)          # 10 of 49 is under half
    nopage = {'plugin_raids': Col(toa_raids(30)), 'plugin_clog': Col([]), 'plugin_kc': kc}
    assert r.compute_raid_luck_lifetime(nopage) == {}
    # The highest completion count in the filenames is a floor for KC when no counter was synced
    nokc = {'plugin_raids': Col(toa_raids(30, start_kc=1)), 'plugin_clog': Col([toa_page()]), 'plugin_kc': Col([])}
    assert r.compute_raid_luck_lifetime(nokc)['Zezima']['TOA']['kc'] == 30


def test_all_time_prefers_lifetime_and_falls_back_to_since_sync():
    first_seen = datetime(2026, 10, 1, tzinfo=timezone.utc)
    after = int(first_seen.timestamp()) + 3600
    # One raid known out of 5 completions (20% coverage): too thin for lifetime, so it is scored
    # from the plugin's first sync onwards.
    thin = [{'player': 'Zezima', 'raid': 'TOA', 'mode': 'EXPERT', 'kill_count': 5, 'completed_at': after,
             'personal_points': 37000, 'raid_level': 400, 'team_size': 1, 'total_points': -1}]
    cols = {'plugin_raids': Col(thin), 'plugin_clog': Col([toa_page()]), 'plugin_kc': Col([])}
    assert r.compute_raid_luck(cols)['Zezima']['TOA']['basis'] == 'since_plugin'
    # 30 known of 30: lifetime takes over for that player and raid.
    full = {'plugin_raids': Col(toa_raids(30)), 'plugin_clog': Col([toa_page()]), 'plugin_kc': Col([])}
    assert r.compute_raid_luck(full)['Zezima']['TOA']['basis'] == 'lifetime'


def test_event_window_uses_raid_times_and_dink_drops():
    raids = toa_raids(6, t0=1_000_000)                                    # six raids an hour apart
    drops = [
        {'player': 'Zezima', 'item': "Tumeken's shadow (uncharged)", 'source': 'Tombs of Amascut'},
        {'player': 'Zezima', 'item': 'Zulrah scales', 'source': 'Zulrah'},          # not a raid unique
        {'player': 'Other', 'item': "Osmumten's fang", 'source': 'Tombs of Amascut'},  # someone else
    ]
    inside = r.compute_raid_luck_event({'plugin_raids': Col(raids)}, 1_000_000, 1_000_000 + 2 * 3600, drops)['Zezima']['TOA']
    assert inside['basis'] == 'event' and inside['raids_scored'] == 3            # only the 3 raids in the window
    assert inside['actual_uniques'] == 1 and close(inside['expected_uniques'], 0.3)
    assert r.compute_raid_luck_event({'plugin_raids': Col(raids)}, 5_000_000, 6_000_000, drops) == {}


def test_entry_mode_is_scored_by_raid_level():
    # Entry Mode is just low raid levels (0-149): same formula, with the shadow/ward/masori weights cut to 1/50
    # below level 150 and fang/lightbearer cut below 50.
    entry = [{'player': 'Zezima', 'raid': 'TOA', 'mode': 'ENTRY', 'kill_count': 1 + i, 'completed_at': 1_700_000_000 + i * 3600,
              'personal_points': 16513, 'raid_level': 105, 'team_size': -1, 'total_points': -1} for i in range(10)]
    page = toa_page()
    kc = Col([{'player': 'Zezima', 'counts': [{'name': 'Tombs of Amascut (Entry)', 'kc': 10}]}])
    info = r.compute_raid_luck_lifetime({'plugin_raids': Col(entry), 'plugin_clog': Col([page]), 'plugin_kc': kc})['Zezima']['TOA']
    assert info['raids_scored'] == 10 and close(info['coverage'], 1.0)
    chance = r.toa_individual_chance(105, 16513)
    assert close(info['expected_uniques'], 10 * chance)
    shadow = next(i for i in info['items'] if i['item'] == "tumeken's shadow")
    fang = next(i for i in info['items'] if i['item'] == "osmumten's fang")
    assert shadow['expected'] < fang['expected'] / 20            # shadow is far rarer below level 150


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
