"""
Integration tests for the multi-board API. Runs bingo_api against an in-memory mongomock database - it never
connects to a real MongoDB, so nothing here can touch live data.
"""
import os
import sys
import unittest

import mongomock
import pymongo

# Must happen before bingo_api is imported: it builds its MongoClient at import time.
os.environ['MONGODB_URI'] = 'mongodb://mock-only-never-connects/'
os.environ['BINGO_ADMIN_PASSWORD'] = 'test-admin'
pymongo.MongoClient = mongomock.MongoClient

import bingo_api  # noqa: E402

bingo_api.limiter.enabled = False

API_KEY = 'test-key'
ADMIN = 'test-admin'


def tile(item, value=10, completed_by=None):
    return {'items': [item] if item else [], 'value': value, 'completedBy': list(completed_by or []),
            'completedAt': {}, 'displayTitle': ''}


def small_board(items, size=2):
    tiles = [tile(i) for i in items] + [tile(None) for _ in range(size * size - len(items))]
    return {'boardSize': size, 'tiles': tiles, 'completions': {},
            'lineBonuses': {'rows': [50] * size, 'cols': [50] * size, 'diags': [100, 100]}}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        client = bingo_api.mongo_client
        client.drop_database('osrs_bingo')
        bingo_api.db = client['osrs_bingo']
        bingo_api.tenants_collection = bingo_api.db['tenants']
        bingo_api._indexed_tenant_subdomains.clear()
        bingo_api.tenants_collection.insert_one({
            'tenant_id': bingo_api.DEFAULT_TENANT_ID, 'subdomain': 'unsociables', 'name': 'Test',
            'api_key': API_KEY, 'plan': 'owner'})
        self.client = bingo_api.app.test_client()
        self.col = bingo_api.get_tenant_collections(bingo_api.DEFAULT_TENANT_ID)

        # The "existing" setup: one event + one board, exactly like production today.
        self.col['bingo'].insert_one({'_id': 'event_config', 'enabled': True, 'eventName': 'Main Event',
                                      'startDate': '2026-01-01T00:00:00Z', 'endDate': '2099-12-31T23:59:59Z'})
        board = small_board(['Dragon claws', 'Abyssal whip'])
        board['type'] = 'current_board'
        self.col['bingo'].insert_one(board)

    # helpers
    def drop(self, player, item, when='2026-03-15T12:00:00Z'):
        return self.client.post('/drop', json={'player': player, 'item': item, 'timestamp': when, 'value': 100},
                                headers={'X-API-Key': API_KEY})

    def admin(self, path, **body):
        return self.client.post(path, json={'password': ADMIN, **body})

    def add_event(self, name='Year', start='2026-01-01T00:00:00Z', end='2026-12-31T23:59:59Z', enabled=True):
        r = self.admin('/admin/events', event={'eventName': name, 'startDate': start, 'endDate': end,
                                               'enabled': enabled})
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()['event']['event_id']

    def add_board(self, name, event_id='main', items=None, **extra):
        r = self.admin('/admin/boards', board={'name': name, 'event_id': event_id, 'boardSize': 2, **extra})
        self.assertEqual(r.status_code, 200, r.get_json())
        board_id = r.get_json()['board']['board_id']
        if items:
            doc = small_board(items)
            doc['boardId'] = board_id
            r2 = self.admin('/update', **doc)
            self.assertEqual(r2.status_code, 200)
        return board_id


class LegacyBehaviourTests(ApiTestCase):
    def test_original_drop_flow_unchanged(self):
        r = self.drop('alice', 'Dragon claws')
        body = r.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['completedTiles'], [{'tile': 1, 'items': ['Dragon claws'], 'value': 10}])
        board = self.client.get('/bingo').get_json()
        self.assertEqual(board['tiles'][0]['completedBy'], ['alice'])

    def test_repeat_drop_is_not_double_counted(self):
        self.drop('alice', 'Dragon claws')
        r = self.drop('alice', 'Dragon claws')
        self.assertFalse(r.get_json()['success'])

    def test_unmatched_drop(self):
        self.assertFalse(self.drop('alice', 'Bones').get_json()['success'])

    def test_bingo_endpoint_defaults_to_main(self):
        self.assertEqual(self.client.get('/bingo').get_json()['boardSize'], 2)
        self.assertEqual(self.client.get('/bingo?board=nope').status_code, 404)

    def test_event_config_endpoint_still_works(self):
        cfg = self.client.get('/event/config').get_json()
        self.assertEqual(cfg['eventName'], 'Main Event')

    def test_update_without_board_id_saves_main_and_keeps_settings(self):
        self.admin('/admin/boards', board={'board_id': 'main', 'name': 'Season 1', 'weight': 2})
        board = self.client.get('/bingo').get_json()
        board['tiles'][2] = tile('Bandos chestplate')
        r = self.admin('/update', **board)  # client round-trips the whole board
        self.assertEqual(r.status_code, 200)
        saved = self.client.get('/bingo').get_json()
        self.assertEqual(saved['tiles'][2]['items'], ['Bandos chestplate'])
        self.assertEqual(saved['name'], 'Season 1')
        self.assertEqual(saved['weight'], 2)

    def test_update_keeps_settings_even_if_client_omits_them(self):
        self.admin('/admin/boards', board={'board_id': 'main', 'name': 'Season 1'})
        r = self.admin('/update', **small_board(['Dragon claws']))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get('/bingo').get_json()['name'], 'Season 1')

    def test_admin_endpoints_need_password(self):
        r = self.client.post('/admin/boards', json={'password': 'wrong', 'board': {'name': 'x'}})
        self.assertEqual(r.status_code, 401)
        r = self.client.post('/admin/events', json={'event': {'eventName': 'x'}})
        self.assertEqual(r.status_code, 401)


class MultiBoardDropTests(ApiTestCase):
    def test_one_drop_scores_on_every_active_board(self):
        year = self.add_event('Year 2026')
        long_board = self.add_board('Year-long', year, ['Dragon claws'])
        monthly = self.add_board('March', year, ['Dragon claws', 'Zenyte shard'],
                                 startDate='2026-03-01T00:00:00Z', endDate='2026-03-31T23:59:59Z')
        body = self.drop('alice', 'Dragon claws', '2026-03-15T12:00:00Z').get_json()
        self.assertTrue(body['success'])
        # main + long + monthly all have the tile
        self.assertEqual(len(body['completedTiles']), 3)
        self.assertEqual(self.client.get('/bingo').get_json()['tiles'][0]['completedBy'], ['alice'])
        self.assertEqual(self.client.get(f'/bingo?board={long_board}').get_json()['tiles'][0]['completedBy'], ['alice'])
        self.assertEqual(self.client.get(f'/bingo?board={monthly}').get_json()['tiles'][0]['completedBy'], ['alice'])

    def test_board_outside_its_window_is_skipped(self):
        year = self.add_event('Year 2026')
        march = self.add_board('March', year, ['Dragon claws'],
                               startDate='2026-03-01T00:00:00Z', endDate='2026-03-31T23:59:59Z')
        self.drop('alice', 'Dragon claws', '2026-05-10T12:00:00Z')
        self.assertEqual(self.client.get(f'/bingo?board={march}').get_json()['tiles'][0]['completedBy'], [])
        self.assertEqual(self.client.get('/bingo').get_json()['tiles'][0]['completedBy'], ['alice'])

    def test_disabled_board_and_disabled_event_are_skipped(self):
        year = self.add_event('Year 2026')
        off = self.add_board('Off', year, ['Dragon claws'], enabled=False)
        dead_event = self.add_event('Dead', enabled=False)
        dead = self.add_board('Dead board', dead_event, ['Dragon claws'])
        self.drop('alice', 'Dragon claws')
        for board_id in (off, dead):
            self.assertEqual(self.client.get(f'/bingo?board={board_id}').get_json()['tiles'][0]['completedBy'], [])

    def test_long_board_with_monthly_boards_inside(self):
        """One 6-month board plus six monthly boards inside the same event."""
        half = self.add_event('H1', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        long_id = self.add_board('H1 long', half, ['Dragon claws'])
        months = {}
        starts = ['2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01', '2026-06-01']
        ends = ['2026-01-31', '2026-02-28', '2026-03-31', '2026-04-30', '2026-05-31', '2026-06-30']
        for n, (s, e) in enumerate(zip(starts, ends), start=1):
            months[n] = self.add_board(f'Month {n}', half, ['Dragon claws'],
                                       startDate=f'{s}T00:00:00Z', endDate=f'{e}T23:59:59Z')
        self.drop('alice', 'Dragon claws', '2026-04-10T12:00:00Z')
        got = lambda b: self.client.get(f'/bingo?board={b}').get_json()['tiles'][0]['completedBy']
        self.assertEqual(got(long_id), ['alice'])
        self.assertEqual(got(months[4]), ['alice'])
        for n in (1, 2, 3, 5, 6):
            self.assertEqual(got(months[n]), [], f'month {n}')

    def test_window_check_enforces_dates(self):
        tid = bingo_api.DEFAULT_TENANT_ID
        self.assertTrue(bingo_api.is_within_event_window(tenant_id=tid))                      # now is inside 2026..2099
        self.assertTrue(bingo_api.is_within_event_window('2026-05-01T00:00:00Z', tid))
        self.assertFalse(bingo_api.is_within_event_window('2025-05-01T00:00:00Z', tid))      # before start
        self.assertFalse(bingo_api.is_within_event_window('2100-01-01T00:00:00Z', tid))      # after end

    def test_drop_after_event_end_is_rejected(self):
        self.col['bingo'].update_one({'_id': 'event_config'}, {'$set': {'endDate': '2026-01-02T00:00:00Z'}})
        body = self.drop('alice', 'Dragon claws').get_json()
        self.assertFalse(body['success'])
        self.assertIn('Outside', body['message'])
        self.assertEqual(self.client.get('/bingo').get_json()['tiles'][0]['completedBy'], [])

    def test_drop_inside_another_live_event_is_accepted(self):
        self.col['bingo'].update_one({'_id': 'event_config'}, {'$set': {'endDate': '2026-01-02T00:00:00Z'}})
        self.add_event('Later', '2026-01-03T00:00:00Z', '2099-01-01T00:00:00Z')
        self.assertTrue(bingo_api.is_within_event_window(tenant_id=bingo_api.DEFAULT_TENANT_ID))


class AdminValidationTests(ApiTestCase):
    def test_board_must_fit_inside_its_event(self):
        year = self.add_event('Half', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        r = self.admin('/admin/boards', board={'name': 'Too long', 'event_id': year, 'boardSize': 2,
                                              'endDate': '2026-09-01T00:00:00Z'})
        self.assertEqual(r.status_code, 400)
        r = self.admin('/admin/boards', board={'name': 'Nope', 'event_id': 'ghost', 'boardSize': 2})
        self.assertEqual(r.status_code, 404)

    def test_teams_cannot_overlap(self):
        r = self.admin('/admin/boards', board={'name': 'T', 'boardSize': 2, 'teamMode': True,
                                              'teams': {'Red': ['a'], 'Blue': ['a']}})
        self.assertEqual(r.status_code, 400)

    def test_cannot_delete_main(self):
        self.assertEqual(self.admin('/admin/boards', action='delete', board={'board_id': 'main'}).status_code, 400)
        self.assertEqual(self.admin('/admin/events', action='delete', event={'event_id': 'main'}).status_code, 400)

    def test_delete_event_needs_force_when_it_has_boards(self):
        year = self.add_event('Year')
        self.add_board('B', year)
        r = self.admin('/admin/events', action='delete', event={'event_id': year})
        self.assertEqual(r.status_code, 409)
        r = self.admin('/admin/events', action='delete', event={'event_id': year}, force=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.client.get('/events').get_json()['events']), 1)

    def test_copy_from_clears_completions(self):
        self.drop('alice', 'Dragon claws')
        r = self.admin('/admin/boards', board={'name': 'Copy', 'event_id': 'main'}, copyFrom='main')
        board_id = r.get_json()['board']['board_id']
        copied = self.client.get(f'/bingo?board={board_id}').get_json()
        self.assertEqual(copied['tiles'][0]['items'], ['Dragon claws'])
        self.assertEqual(copied['tiles'][0]['completedBy'], [])

    def test_events_listing_groups_boards(self):
        year = self.add_event('Year')
        self.add_board('Long', year)
        data = self.client.get('/events').get_json()
        by_id = {e['event_id']: e for e in data['events']}
        self.assertEqual([b['meta']['board_id'] for b in by_id['main']['boards']], ['main'])
        self.assertEqual(len(by_id[year]['boards']), 1)
        self.assertNotIn('tiles', by_id[year]['boards'][0])


class LeaderboardTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.year = self.add_event('Year')
        self.long_id = self.add_board('Long', self.year, ['Dragon claws', 'Abyssal whip'])
        self.drop('alice', 'Dragon claws')
        self.drop('bob', 'Abyssal whip')

    def lb(self, scope):
        return self.client.get(f'/leaderboard?scope={scope}')

    def test_single_board(self):
        body = self.lb('board:main').get_json()
        self.assertFalse(body['combined'])
        self.assertEqual({r['name']: r['points'] for r in body['rows']}, {'alice': 10, 'bob': 10})

    def test_event_combined_sums_and_weights(self):
        self.admin('/admin/boards', board={'board_id': self.long_id, 'weight': 3})
        body = self.lb(f'event:{self.year}').get_json()
        self.assertTrue(body['combined'])
        self.assertEqual({r['name']: r['points'] for r in body['rows']}, {'alice': 30, 'bob': 30})

    def test_main_event_combined_only_counts_its_boards(self):
        body = self.lb('event:main').get_json()
        self.assertEqual([b['board_id'] for b in body['boards']], ['main'])

    def test_in_combined_flag_excludes_a_board(self):
        extra = self.add_board('Side', self.year, ['Dragon claws'], inCombined=False)
        body = self.lb(f'event:{self.year}').get_json()
        self.assertNotIn(extra, [b['board_id'] for b in body['boards']])

    def test_custom_selection_across_events(self):
        body = self.lb(f'boards:main,{self.long_id}').get_json()
        self.assertEqual({r['name']: r['points'] for r in body['rows']}, {'alice': 20, 'bob': 20})

    def test_team_board_ranks_teams(self):
        self.admin('/admin/boards', board={'board_id': self.long_id, 'teamMode': True,
                                           'teams': {'Red': ['alice', 'bob'], 'Blue': ['carol']}})
        body = self.lb(f'board:{self.long_id}').get_json()
        self.assertTrue(body['teamMode'])
        self.assertEqual([(r['name'], r['points']) for r in body['rows']], [('Red', 70)])  # 2 tiles + the 50pt row the team completes between them

    def test_unknown_scope(self):
        self.assertEqual(self.lb('board:ghost').status_code, 404)
        self.assertEqual(self.lb('nonsense').status_code, 404)


class ArchiveTests(ApiTestCase):
    """Archives are per EVENT: one document holding every board inside it."""

    def make_past_event(self):
        # a finished 6-month event with one long board and two monthly boards, all with history
        ev = self.add_event('H1 2026', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        long_id = self.add_board('H1 long', ev, ['Dragon claws', 'Abyssal whip'])
        jan = self.add_board('January', ev, ['Dragon claws'],
                             startDate='2026-01-01T00:00:00Z', endDate='2026-01-31T23:59:59Z')
        feb = self.add_board('February', ev, ['Abyssal whip'],
                             startDate='2026-02-01T00:00:00Z', endDate='2026-02-28T23:59:59Z')
        self.drop('alice', 'Dragon claws', '2026-01-10T12:00:00Z')
        self.drop('bob', 'Abyssal whip', '2026-02-10T12:00:00Z')
        return ev, long_id, jan, feb

    def test_archive_holds_all_boards_in_one_document(self):
        ev, long_id, jan, feb = self.make_past_event()
        r = self.admin('/event/archive', event_id=ev)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.col['archive'].count_documents({}), 1)
        doc = self.client.get(f"/event/archive/{r.get_json()['archive_id']}").get_json()
        self.assertEqual(doc['event_id'], ev)
        self.assertEqual({b['board_id'] for b in doc['boards']}, {long_id, jan, feb})
        by = {b['board_id']: b for b in doc['boards']}
        self.assertEqual(by[jan]['leaderboard'][0]['name'], 'alice')
        self.assertEqual(by[feb]['leaderboard'][0]['name'], 'bob')
        # combined = long + jan + feb, each at weight 1
        points = {r['name']: r['points'] for r in doc['combined_leaderboard']}
        self.assertEqual(points, {'alice': 20, 'bob': 20})

    def test_archive_is_frozen_copy(self):
        ev, long_id, jan, feb = self.make_past_event()
        archive_id = self.admin('/event/archive', event_id=ev).get_json()['archive_id']
        # later edits to the live board must not change the archive
        live = self.client.get(f'/bingo?board={jan}').get_json()
        live['tiles'][0]['completedBy'] = []
        live['boardId'] = jan
        self.admin('/update', **live)
        doc = self.client.get(f'/event/archive/{archive_id}').get_json()
        frozen = {b['board_id']: b for b in doc['boards']}[jan]
        self.assertEqual(frozen['board']['tiles'][0]['completedBy'], ['alice'])

    def test_second_archive_of_same_event_is_refused_without_force(self):
        ev, *_ = self.make_past_event()
        self.admin('/event/archive', event_id=ev)
        self.assertEqual(self.admin('/event/archive', event_id=ev).status_code, 409)
        self.assertEqual(self.admin('/event/archive', event_id=ev, force=True).status_code, 200)
        self.assertEqual(self.col['archive'].count_documents({}), 1)

    def test_running_event_not_archived_without_force(self):
        ev = self.add_event('Future', '2099-01-01T00:00:00Z', '2099-12-31T00:00:00Z')
        self.assertEqual(self.admin('/event/archive', event_id=ev).status_code, 409)

    def test_events_with_identical_dates_get_separate_archives(self):
        a = self.add_event('A', '2026-01-01T00:00:00Z', '2026-06-30T00:00:00Z')
        b = self.add_event('B', '2026-01-01T00:00:00Z', '2026-06-30T00:00:00Z')
        self.admin('/event/archive', event_id=a)
        self.admin('/event/archive', event_id=b)
        self.assertEqual(self.col['archive'].count_documents({}), 2)

    def test_list_stays_light_but_names_boards(self):
        ev, *_ = self.make_past_event()
        self.admin('/event/archive', event_id=ev)
        listing = self.client.get('/event/archive/list').get_json()['archives'][0]
        self.assertNotIn('boards', listing)
        self.assertEqual(len(listing['boards_meta']), 3)

    def test_main_event_archive_keeps_legacy_shape(self):
        self.drop('alice', 'Dragon claws')
        archive_id = self.admin('/event/archive', force=True).get_json()['archive_id']
        doc = self.client.get(f'/event/archive/{archive_id}').get_json()
        self.assertEqual(doc['event_name'], 'Main Event')
        self.assertEqual(doc['board']['tiles'][0]['completedBy'], ['alice'])
        self.assertEqual(doc['leaderboard'][0]['player'], 'alice')
        self.assertEqual(doc['boards'][0]['board_id'], 'main')

    def test_auto_archive_does_every_ended_event_once(self):
        ev, *_ = self.make_past_event()
        self.col['bingo'].update_one({'_id': 'event_config'}, {'$set': {'endDate': '2026-02-01T00:00:00Z'}})
        h = {'X-API-Key': API_KEY}
        dry = self.client.post('/event/archive/auto', json={'dry_run': True}, headers=h).get_json()
        self.assertTrue(dry['needs_archive'])
        done = self.client.post('/event/archive/auto', json={}, headers=h).get_json()
        self.assertTrue(done['archived'])
        self.assertEqual(len(done['archive_ids']), 2)  # main + H1
        again = self.client.post('/event/archive/auto', json={}, headers=h).get_json()
        self.assertFalse(again['archived'])
        self.assertEqual(self.col['archive'].count_documents({}), 2)


class AnalyticsScopeTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.ev = self.add_event('H1', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        self.jan = self.add_board('Jan', self.ev, [], startDate='2026-01-01T00:00:00Z', endDate='2026-01-31T23:59:59Z')
        self.mar = self.add_board('Mar', self.ev, [], startDate='2026-03-01T00:00:00Z', endDate='2026-03-31T23:59:59Z')
        self.long = self.add_board('Long', self.ev, [])
        # one drop (value 100) in each of Jan, Feb, Mar, Aug; the Aug one is outside every H1 board
        for when in ('2026-01-10', '2026-02-10', '2026-03-10', '2026-08-10'):
            self.drop('alice', 'Bones', f'{when}T12:00:00Z')
        import datetime as dt
        self.col['deaths'].insert_many([
            {'player': 'alice', 'npc': 'Vorkath', 'timestamp': dt.datetime(2026, 1, 11)},
            {'player': 'alice', 'npc': 'Zulrah', 'timestamp': dt.datetime(2026, 2, 11)},
            {'player': 'bob', 'npc': 'Zulrah', 'timestamp': dt.datetime(2026, 8, 11)},
        ])

    def total(self, scope):
        return self.client.get(f'/history?limit=100&scope={scope}').get_json()['total']

    def test_history_by_board(self):
        self.assertEqual(self.total(f'board:{self.jan}'), 1)
        self.assertEqual(self.total(f'board:{self.mar}'), 1)

    def test_history_by_event_uses_union_of_its_boards(self):
        # the "Long" board has no dates of its own => it spans the whole event, so Jan+Feb+Mar are all inside it
        self.assertEqual(self.total(f'event:{self.ev}'), 3)

    def test_overlapping_boards_do_not_double_count(self):
        self.assertEqual(self.total(f'boards:{self.jan},{self.long}'), 3)

    def test_disjoint_boards_add(self):
        self.assertEqual(self.total(f'boards:{self.jan},{self.mar}'), 2)

    def test_custom_range(self):
        self.assertEqual(self.total('range:2026-02-01T00:00:00Z,2026-02-28T00:00:00Z'), 1)
        self.assertEqual(self.total('range:2026-07-01T00:00:00Z,'), 1)  # open-ended

    def test_all_and_unscoped_are_everything(self):
        self.assertEqual(self.total('all'), 4)
        self.assertEqual(self.client.get('/history?limit=100').get_json()['total'], 4)

    def test_bad_scope_is_a_400(self):
        self.assertEqual(self.client.get('/history?scope=board:ghost').status_code, 400)
        self.assertEqual(self.client.get('/history?scope=weird:1').status_code, 400)

    def test_total_value_scope(self):
        body = self.client.get(f'/history/total-value?scope=board:{self.jan}').get_json()
        self.assertEqual(body['total_value'], 100)

    def test_deaths_scope(self):
        self.assertEqual(self.client.get(f'/deaths?scope=board:{self.jan}').get_json()['total_deaths'], 1)
        self.assertEqual(self.client.get(f'/deaths?scope=event:{self.ev}').get_json()['total_deaths'], 2)
        self.assertEqual(self.client.get('/deaths').get_json()['total_deaths'], 3)
        by_npc = self.client.get(f'/deaths/by-npc?scope=board:{self.jan}').get_json()
        self.assertEqual(sum(n['deaths'] for n in by_npc['npc_stats']), 1)

    def test_scope_windows_endpoint(self):
        body = self.client.get(f'/scope/windows?scope=boards:{self.jan},{self.mar}').get_json()
        self.assertEqual(len(body['windows']), 2)
        self.assertIsNone(self.client.get('/scope/windows?scope=all').get_json()['windows'])


class StatsScopeTests(ApiTestCase):
    """KC gained, luck and PBs follow the same scopes as analytics."""

    def setUp(self):
        super().setUp()
        import datetime as dt
        self.calls = []

        def fake_wom(player, start, end):
            self.calls.append((player, start, end))
            return {'Zulrah': {'start': 0, 'end': 5, 'gained': 5}}, []
        self._orig = bingo_api.fetch_wom_gained
        bingo_api.fetch_wom_gained = fake_wom
        self.addCleanup(lambda: setattr(bingo_api, 'fetch_wom_gained', self._orig))

        self.ev = self.add_event('H1', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        self.jan = self.add_board('Jan', self.ev, [], startDate='2026-01-01T00:00:00Z', endDate='2026-01-31T23:59:59Z')
        self.mar = self.add_board('Mar', self.ev, [], startDate='2026-03-01T00:00:00Z', endDate='2026-03-31T23:59:59Z')
        self.col['kc'].insert_many([
            {'player': 'alice', 'timestamp': dt.datetime(2026, 4, 1), 'snapshot_type': 'current', 'bosses': {'Zulrah': 10}},
            {'player': 'bob', 'timestamp': dt.datetime(2026, 4, 1), 'snapshot_type': 'current', 'bosses': {'Zulrah': 20}},
        ])
        self.col['personal_bests'].insert_many([
            {'player': 'alice', 'boss': 'Zulrah', 'time_seconds': 70, 'party_size': 1, 'timestamp': dt.datetime(2026, 1, 10)},
            {'player': 'alice', 'boss': 'Zulrah', 'time_seconds': 60, 'party_size': 1, 'timestamp': dt.datetime(2026, 3, 10)},
            {'player': 'alice', 'boss': 'Vorkath', 'time_seconds': 90, 'party_size': 1, 'timestamp': dt.datetime(2026, 8, 10)},
        ])

    def test_effort_for_a_board_asks_wom_for_that_window(self):
        body = self.client.get(f'/kc/effort?scope=board:{self.jan}').get_json()
        self.assertTrue(body['success'])
        self.assertEqual({p['player']: p['effort'] for p in body['players']}, {'alice': {'Zulrah': 5}, 'bob': {'Zulrah': 5}})
        self.assertEqual(self.calls[0][1], '2026-01-01T00:00:00Z')
        self.assertEqual(self.calls[0][2], '2026-01-31T23:59:59Z')

    def test_finished_window_is_fetched_once(self):
        self.client.get(f'/kc/effort?scope=board:{self.jan}')
        n = len(self.calls)
        self.client.get(f'/kc/effort?scope=board:{self.jan}')
        self.assertEqual(len(self.calls), n)

    def test_different_windows_are_cached_separately(self):
        self.client.get(f'/kc/effort?scope=board:{self.jan}')
        self.client.get(f'/kc/effort?scope=board:{self.mar}')
        self.assertEqual({c[1] for c in self.calls}, {'2026-01-01T00:00:00Z', '2026-03-01T00:00:00Z'})

    def test_disjoint_boards_span_the_gap_and_say_so(self):
        body = self.client.get(f'/kc/effort?scope=boards:{self.jan},{self.mar}').get_json()
        self.assertTrue(body['spans_gaps'])
        self.assertEqual(self.calls[0][1], '2026-01-01T00:00:00Z')
        self.assertEqual(self.calls[0][2], '2026-03-31T23:59:59Z')

    def test_wom_failure_reports_unavailable(self):
        bingo_api.fetch_wom_gained = lambda *a: (None, ['down'])
        body = self.client.get(f'/kc/effort?scope=board:{self.jan}').get_json()
        self.assertFalse(body['success'])
        self.assertEqual(sorted(body['unavailable']), ['alice', 'bob'])

    def test_future_window_has_nothing(self):
        ev = self.add_event('Next', '2098-01-01T00:00:00Z', '2098-12-31T00:00:00Z')
        body = self.client.get(f'/kc/effort?scope=event:{ev}').get_json()
        self.assertFalse(body['success'])
        self.assertEqual(self.calls, [])

    def test_unscoped_effort_is_unchanged(self):
        body = self.client.get('/kc/effort').get_json()
        self.assertFalse(body['success'])  # nothing cached the old way => old message path
        self.assertEqual(self.calls, [])

    def test_bad_scope_is_400(self):
        self.assertEqual(self.client.get('/kc/effort?scope=board:ghost').status_code, 400)
        self.assertEqual(self.client.get('/event/luck?scope=board:ghost').status_code, 400)
        self.assertEqual(self.client.get('/pbs?scope=board:ghost').status_code, 400)

    def test_luck_scope_uses_window_kc(self):
        body = self.client.get(f'/event/luck?scope=board:{self.jan}').get_json()
        self.assertEqual(body['eventName'], 'Jan')
        self.assertEqual(body['startDate'], '2026-01-01T00:00:00Z')
        self.assertIsInstance(body['players'], dict)
        self.assertTrue(self.calls)

    def test_pbs_scope(self):
        pbs = lambda q: self.client.get('/pbs' + q).get_json()['personal_bests']
        self.assertEqual({(p['boss'], p['time_seconds']) for p in pbs('')}, {('Zulrah', 60), ('Vorkath', 90)})
        self.assertEqual({(p['boss'], p['time_seconds']) for p in pbs(f'?scope=board:{self.jan}')}, {('Zulrah', 70)})
        self.assertEqual({(p['boss'], p['time_seconds']) for p in pbs(f'?scope=event:{self.ev}')}, {('Zulrah', 60)})
        self.assertEqual({(p['boss'], p['time_seconds']) for p in pbs(f'?scope=boards:{self.jan},{self.mar}')}, {('Zulrah', 60)})


class PluginDataScopeTests(ApiTestCase):
    """The RuneLite plugin's data (Doom delves, KC counters WiseOldMan lacks) follows any window, not just 'now'."""

    def setUp(self):
        super().setUp()
        import datetime as dt
        self.dt = dt
        self._orig = bingo_api.fetch_wom_gained
        bingo_api.fetch_wom_gained = lambda p, s, e: ({'Zulrah': {'start': 0, 'end': 9, 'gained': 9}}, [])
        self.addCleanup(lambda: setattr(bingo_api, 'fetch_wom_gained', self._orig))
        self.ev = self.add_event('H1', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        self.jan = self.add_board('Jan', self.ev, [], startDate='2026-01-01T00:00:00Z', endDate='2026-01-31T23:59:59Z')
        self.col['kc'].insert_one({'player': 'alice', 'timestamp': dt.datetime(2026, 4, 1), 'snapshot_type': 'current',
                                   'bosses': {'Zulrah': 10}})

        def levels(l8):
            return [10, 8, 6, 5, 4, 3, 2, l8]
        # Doom: nothing before the window, 3 delve-8s by Jan 20, 7 by Mar 5, 10 today
        self.col['plugin_doom'].insert_one({'player': 'alice', 'levels': levels(10), 'past8': 6})
        self.col['plugin_doom_history'].insert_many([
            {'player': 'alice', 'timestamp': dt.datetime(2025, 12, 20), 'levels': levels(0), 'past8': 0},
            {'player': 'alice', 'timestamp': dt.datetime(2026, 1, 20), 'levels': levels(3), 'past8': 1},
            {'player': 'alice', 'timestamp': dt.datetime(2026, 3, 5), 'levels': levels(7), 'past8': 4},
        ])
        # Tormented Demon: a boss WiseOldMan doesn't track, counted by the plugin only
        counts = lambda kc: [{'name': 'Tormented Demon', 'kc': kc}]
        self.col['plugin_kc'].insert_one({'player': 'alice', 'counts': counts(500)})
        self.col['plugin_kc_history'].insert_many([
            {'player': 'alice', 'timestamp': dt.datetime(2026, 1, 2), 'counts': counts(100)},
            {'player': 'alice', 'timestamp': dt.datetime(2026, 1, 25), 'counts': counts(160)},
            {'player': 'alice', 'timestamp': dt.datetime(2026, 3, 3), 'counts': counts(400)},
        ])

    def alice_effort(self, scope):
        body = self.client.get(f'/kc/effort?scope={scope}').get_json()
        return next(p['effort'] for p in body['players'] if p['player'] == 'alice')

    def alice_luck(self, scope):
        return self.client.get(f'/event/luck?scope={scope}').get_json()['players'].get('alice', {})

    def boss_row(self, luck, name):
        return next((b for b in luck.get('bosses', []) if b['boss'] == name), None)

    def test_kc_gained_doom_rows_stop_at_the_window_end(self):
        effort = self.alice_effort(f'board:{self.jan}')
        self.assertEqual(effort['Doom of Mokhaiotl (Delve 8)'], 3)       # not today's 10
        self.assertEqual(effort['Doom of Mokhaiotl (Delve 9+)'], 1)
        self.assertEqual(effort['Zulrah'], 9)                            # WiseOldMan part still there

    def test_kc_gained_doom_for_a_longer_window(self):
        effort = self.alice_effort('range:2026-01-01T00:00:00Z,2026-04-01T00:00:00Z')
        self.assertEqual(effort['Doom of Mokhaiotl (Delve 8)'], 7)

    def test_luck_doom_uses_window_delves(self):
        row = self.boss_row(self.alice_luck(f'board:{self.jan}'), 'Doom of Mokhaiotl')
        self.assertIsNotNone(row)
        self.assertEqual(row['kc_gained'], 3 + 1)   # 3 delve-8s + 1 deeper, done inside January (not the lifetime total)

    def test_luck_includes_plugin_only_bosses_and_stops_at_window_end(self):
        row = self.boss_row(self.alice_luck(f'board:{self.jan}'), 'Tormented Demon')
        self.assertIsNotNone(row)
        self.assertEqual(row['kc_gained'], 60)    # 160 (Jan 25) - 100 (Jan 2), not 500 (today) - 100

    def test_luck_plugin_boss_for_a_wider_window(self):
        row = self.boss_row(self.alice_luck('range:2026-01-01T00:00:00Z,2026-04-01T00:00:00Z'), 'Tormented Demon')
        self.assertEqual(row['kc_gained'], 300)   # 400 (Mar 3) - 100

    def test_open_ended_range_still_scores_raids(self):
        # no end date: must not crash or silently skip the raid pass
        r = self.client.get('/event/luck?scope=range:2026-01-01T00:00:00Z,')
        self.assertEqual(r.status_code, 200)

    def test_all_time_views_are_untouched(self):
        r = self.client.get('/event/luck?all_time=true')
        self.assertIn(r.status_code, (200, 404))
        self.assertEqual(self.client.get('/kc/all').status_code, 200)


class PluginOnlyKcGainedTests(ApiTestCase):
    """KC gained includes bosses only the plugin counts: Tormented Demon, gorillas, raid entry modes."""

    def setUp(self):
        super().setUp()
        import datetime as dt
        self._orig = bingo_api.fetch_wom_gained
        bingo_api.fetch_wom_gained = lambda p, s, e: ({'Zulrah': {'start': 0, 'end': 9, 'gained': 9},
                                                       'Chambers of Xeric': {'start': 0, 'end': 4, 'gained': 4}}, [])
        self.addCleanup(lambda: setattr(bingo_api, 'fetch_wom_gained', self._orig))
        self.ev = self.add_event('H1', '2026-01-01T00:00:00Z', '2026-06-30T23:59:59Z')
        self.jan = self.add_board('Jan', self.ev, [], startDate='2026-01-01T00:00:00Z', endDate='2026-01-31T23:59:59Z')
        self.col['kc'].insert_one({'player': 'alice', 'timestamp': dt.datetime(2026, 4, 1), 'snapshot_type': 'current',
                                   'bosses': {'Zulrah': 10}})

        def counts(td, gor, entry, cox):
            return [{'name': 'Tormented Demon', 'kc': td}, {'name': 'Demonic gorilla', 'kc': gor},
                    {'name': 'Theatre of Blood (Entry)', 'kc': entry}, {'name': 'Chambers of Xeric', 'kc': cox},
                    {'name': 'Barrows Chests', 'kc': 99}]
        self.col['plugin_kc'].insert_one({'player': 'alice', 'counts': counts(500, 300, 30, 80)})
        self.col['plugin_kc_history'].insert_many([
            {'player': 'alice', 'timestamp': dt.datetime(2026, 1, 2), 'counts': counts(100, 50, 5, 10)},
            {'player': 'alice', 'timestamp': dt.datetime(2026, 1, 25), 'counts': counts(160, 90, 9, 20)},
            {'player': 'alice', 'timestamp': dt.datetime(2026, 3, 3), 'counts': counts(400, 250, 22, 60)},
        ])

    def effort(self, scope):
        body = self.client.get(f'/kc/effort?scope={scope}').get_json()
        return next(p['effort'] for p in body['players'] if p['player'] == 'alice')

    def test_scoped_includes_plugin_only_bosses(self):
        e = self.effort(f'board:{self.jan}')
        self.assertEqual(e['Tormented Demon'], 60)
        self.assertEqual(e['Demonic gorilla'], 40)
        self.assertEqual(e['Theatre of Blood (Entry)'], 4)
        self.assertEqual(e['Zulrah'], 9)

    def test_raids_wiseoldman_has_are_not_double_counted(self):
        e = self.effort(f'board:{self.jan}')
        self.assertEqual(e['Chambers of Xeric'], 4)       # WiseOldMan's number, not the plugin's 20-10
        self.assertNotIn('Barrows Chests', e)             # not a boss we know droprates for

    def test_baseline_is_the_snapshot_before_the_window_start(self):
        e = self.effort('range:2026-02-01T00:00:00Z,2026-04-01T00:00:00Z')
        self.assertEqual(e['Tormented Demon'], 400 - 160)  # Jan 25 snapshot -> Mar 3 snapshot

    def test_a_running_window_counts_to_the_live_counter(self):
        e = self.effort('range:2026-02-01T00:00:00Z,')
        self.assertEqual(e['Tormented Demon'], 500 - 160)

    def test_current_bingo_effort_includes_them_too(self):
        self.col['gained_cache'].insert_one({
            'player': 'alice', 'event_start': '2026-01-01T00:00:00Z', 'event_end': '2099-12-31T23:59:59Z',
            'bosses': {'Zulrah': {'start': 0, 'end': 9, 'gained': 9}}, 'fetched_at': __import__('datetime').datetime.utcnow()})
        body = self.client.get('/kc/effort').get_json()
        effort = next(p['effort'] for p in body['players'] if p['player'] == 'alice')
        self.assertEqual(effort['Zulrah'], 9)
        self.assertEqual(effort['Tormented Demon'], 500 - 100)   # first snapshot in the window -> live counter

    def test_a_player_only_the_plugin_knows_still_appears(self):
        import datetime as dt
        self.col['plugin_kc'].insert_one({'player': 'dave', 'counts': [{'name': 'Tormented Demon', 'kc': 70}]})
        self.col['plugin_kc_history'].insert_many([
            {'player': 'dave', 'timestamp': dt.datetime(2026, 1, 3), 'counts': [{'name': 'Tormented Demon', 'kc': 20}]},
            {'player': 'dave', 'timestamp': dt.datetime(2026, 1, 25), 'counts': [{'name': 'Tormented Demon', 'kc': 45}]}])
        body = self.client.get(f'/kc/effort?scope=board:{self.jan}').get_json()
        dave = next(p['effort'] for p in body['players'] if p['player'] == 'dave')
        self.assertEqual(dave, {'Tormented Demon': 25})

    def test_boss_with_no_snapshot_is_left_out_not_guessed(self):
        self.col['plugin_kc'].update_one({'player': 'alice'}, {'$push': {'counts': {'name': 'Tortured gorilla', 'kc': 40}}})
        self.assertNotIn('Tortured gorilla', self.effort(f'board:{self.jan}'))


if __name__ == '__main__':
    unittest.main()
