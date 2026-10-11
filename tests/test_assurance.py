"""Independent finite assurance, including SQLite commit-order evidence."""
import importlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def event(kind, payload, now=1):
    return {'protocol_version': 1, 'event': kind, 'payload': payload, 'created': now}


def lease(goal='g', generation=1, now=1):
    return event('lease', {'goal_id': goal, 'owner': 'worker', 'generation': generation,
                           'expires_at': now + 10}, now)


def admission(goal='g', sid='s', generation=1, cap=2, max_active=1, now=1):
    return event('admission', {'goal_id': goal, 'owner': 'worker', 'generation': generation,
                             'submission_id': sid, 'day': 'day', 'daily_cap': cap,
                             'max_active': max_active, 'operation_id': goal,
                             'request_hash': sid}, now)


class AssuranceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('assurance'), 'assurance module is missing')
        self.a = importlib.import_module('assurance')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'journal.db'

    def connection(self):
        c = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def test_journal_commits_and_rolls_back_with_application_state(self):
        c = self.connection()
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.a.initialize(c)
        c.commit()
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT INTO settings VALUES('paused','true')")
        self.a.record_event(c, 'pause', {'paused': True}, 1)
        c.rollback()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM settings').fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM protocol_events WHERE event='pause'").fetchone()[0], 0)
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT INTO settings VALUES('paused','true')")
        self.a.record_event(c, 'pause', {'paused': True}, 2)
        c.commit()
        self.assertTrue(self.a.validate_trace(c)['valid'])
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("UPDATE protocol_events SET payload='{}'")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute('DELETE FROM protocol_events')

    def test_journal_rejects_unknown_protocol_and_unbounded_payload(self):
        c = self.connection()
        self.a.initialize(c)
        for kind, payload in [('invented', {}), ('pause', {'paused': 'yes'}),
                              ('pause', {'paused': True, 'raw_request': 'secret'}),
                              ('operation', {'operation_id': 'x', 'intent_hash': 'x' * 5000})]:
            with self.subTest(kind=kind, payload=str(payload)[:80]):
                with self.assertRaises(ValueError):
                    self.a.record_event(c, kind, payload, 1)
        self.assertFalse(self.a.validate_trace([{'event': 'pause', 'protocol_version': 99,
                                                'payload': {'paused': True}, 'created': 1}])['valid'])

    def test_checkpoint_projects_legacy_sqlite_state_without_rewriting_it(self):
        c = self.connection()
        c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        c.execute("INSERT INTO settings VALUES('paused','true')")
        c.execute('CREATE TABLE run_budget(day TEXT PRIMARY KEY,runs INTEGER NOT NULL)')
        c.execute("INSERT INTO run_budget VALUES('day',2)")
        self.a.initialize(c)
        self.a.initialize(c)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM protocol_events WHERE event='initial_checkpoint'").fetchone()[0], 1)
        self.a.record_event(c, 'publication', {'skill_id': 'new', 'positive': True}, 2)
        result = self.a.validate_trace(c)
        self.assertFalse(result['valid'])
        self.assertEqual(result['counterexample']['invariant'], 'pause_publication')
        self.assertEqual(c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0], 'true')

    def test_large_legacy_checkpoint_is_complete_and_paged_without_size_failure(self):
        c = self.connection()
        c.execute('CREATE TABLE goals(id TEXT PRIMARY KEY,owner TEXT,generation INTEGER,lease_until REAL,submission_id TEXT,state TEXT)')
        c.execute('CREATE TABLE evidence(goal_id TEXT,outcome TEXT)')
        c.execute('BEGIN IMMEDIATE')
        rows = [(('g' + str(n)).ljust(64, 'x'), 'legacy-worker-' + 'o' * 50, 2, 999999., None, 'failed') for n in range(6500)]
        c.executemany('INSERT INTO goals VALUES(?,?,?,?,?,?)', rows)
        c.executemany('INSERT INTO evidence VALUES(?,?)', [(row[0], 'failed') for row in rows])
        self.assertGreater(len(json.dumps(self.a._checkpoint(c)).encode()), 1024 * 1024)
        try:
            self.a.initialize(c)
        except ValueError as exc:
            self.fail('legacy checkpoint must paginate instead of blocking Ledger initialization: ' + str(exc))
        c.commit()
        pages = c.execute("SELECT payload FROM protocol_events WHERE event='checkpoint_part'").fetchall()
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(row[0].encode()) <= 4096 for row in pages))
        result = self.a.validate_trace(c)
        self.assertTrue(result['valid'], result)
        self.assertEqual(len(result['state']['goals']), len(rows))
        self.assertTrue(all(g['truth'] == 'failed' and g['generation'] == 2
                            for g in result['state']['goals'].values()))
        truncated = self.a._events(c)[:-1]
        missing = self.a.validate_trace(truncated)
        self.assertFalse(missing['valid'])
        self.assertEqual(missing['counterexample']['invariant'], 'protocol_schema')

    def test_independent_trace_rejects_stale_and_expired_lease_writes(self):
        release = event('release', {'goal_id': 'g', 'owner': 'worker', 'generation': 1}, 2)
        for trace in [[lease(), release, lease(generation=2, now=3), admission(generation=1, now=4)],
                      [lease(), admission(now=12)]]:
            result = self.a.validate_trace(trace)
            self.assertFalse(result['valid'])
            self.assertEqual(result['counterexample']['invariant'], 'lease_fencing')

    def test_independent_trace_rejects_budget_race_and_nonquiet_retry(self):
        trace = [lease('g'), admission('g', 's', cap=1), lease('h'),
                 admission('h', 't', cap=1, max_active=2)]
        result = self.a.validate_trace(trace)
        self.assertFalse(result['valid'])
        self.assertEqual(result['counterexample']['invariant'], 'budget')
        unknown = event('transition', {'goal_id': 'g', 'owner': 'worker', 'generation': 1,
                                       'submission_id': 's', 'outcome': 'unknown_result',
                                       'settled': False})
        result = self.a.validate_trace([lease(), admission(), unknown, admission(sid='retry')])
        self.assertFalse(result['valid'])
        self.assertEqual(result['counterexample']['invariant'], 'quiet_before_admission')

    def test_unknown_cannot_become_failure_without_boolean_evidence(self):
        outcome = event('settlement', {'goal_id': 'g', 'owner': 'worker', 'generation': 1,
                                       'submission_id': 's', 'outcome': 'failed',
                                       'settled': False, 'verdict': None})
        result = self.a.validate_trace([lease(), admission(), outcome])
        self.assertFalse(result['valid'])
        self.assertEqual(result['counterexample']['invariant'], 'unknown_not_failure')

    def test_unverified_terminal_transitions_cannot_convert_unknown_into_truth(self):
        for outcome in ('failed', 'succeeded'):
            with self.subTest(outcome=outcome):
                c = sqlite3.connect(':memory:', isolation_level=None)
                self.addCleanup(c.close)
                self.a.initialize(c)
                for item in [lease(), admission(), event('transition', {
                    'goal_id': 'g', 'owner': 'worker', 'generation': 1,
                    'submission_id': 's', 'outcome': 'unknown_result', 'settled': False})]:
                    self.a.record_event(c, item['event'], item['payload'], item['created'])
                # Record the unsafe mutation directly: a production guard is not an oracle.
                self.a.record_event(c, 'transition', {'goal_id': 'g', 'owner': 'worker',
                    'generation': 1, 'submission_id': 's', 'outcome': outcome,
                    'settled': False, 'verdict': outcome == 'succeeded'}, 2)
                result = self.a.validate_trace(c)
                self.assertFalse(result['valid'], result)
                self.assertEqual(result['counterexample']['invariant'], 'unknown_not_failure')

    def test_terminal_transition_can_track_a_preserved_trusted_final_result(self):
        for outcome in ('failed', 'succeeded'):
            with self.subTest(outcome=outcome):
                trace = [lease(), admission(), event('settlement', {
                    'goal_id': 'g', 'owner': 'worker', 'generation': 1,
                    'submission_id': 's', 'outcome': outcome, 'settled': False,
                    'verdict': outcome == 'succeeded'}), lease(generation=2, now=2),
                    event('transition', {'goal_id': 'g', 'owner': 'worker', 'generation': 2,
                        'submission_id': 's', 'outcome': outcome, 'settled': True}, 3)]
                result = self.a.validate_trace(trace)
                self.assertTrue(result['valid'], result)
                self.assertEqual(result['state']['goals']['g']['truth'], outcome)
                self.assertTrue(result['state']['submissions']['s']['settled'])

    def test_operation_intent_is_immutable_but_retry_request_can_change(self):
        trace = [event('operation', {'operation_id': 'stable', 'intent_hash': 'a'}),
                 event('operation', {'operation_id': 'stable', 'intent_hash': 'a'})]
        self.assertTrue(self.a.validate_trace(trace)['valid'])
        result = self.a.validate_trace(trace + [event('operation', {'operation_id': 'stable', 'intent_hash': 'b'})])
        self.assertFalse(result['valid'])
        self.assertEqual(result['counterexample']['invariant'], 'operation_intent')

    def test_bfs_executes_explicit_bounds_and_catches_mutants(self):
        result = self.a.bounded_check(goals=2, generations=2, budget=2, depth=8)
        self.assertEqual(result['status'], 'no_counterexample_within_bounds')
        self.assertEqual(result['scope']['goals'], 2)
        self.assertEqual(result['scope']['depth'], 8)
        self.assertEqual(result['scope']['max_active'], 1)
        self.assertGreater(result['states'], 20)
        self.assertGreater(result['transitions'], result['states'])
        self.assertEqual(len(result['model_hash']), 64)
        self.assertFalse(result['general_proof'])
        for mutant, invariant in [('budget_guard', 'budget'), ('stale_lease_guard', 'lease_fencing'),
                                  ('pause_publication_guard', 'pause_publication'),
                                  ('unsettled_guard', 'quiet_before_admission'),
                                  ('unknown_failure_guard', 'unknown_not_failure'),
                                  ('operation_intent_guard', 'operation_intent'),
                                  ('active_capacity_guard', 'active_capacity'),
                                  ('pause_admission_guard', 'pause_admission')]:
            with self.subTest(mutant=mutant):
                bad = self.a.bounded_check(mutation=mutant)
                self.assertEqual(bad['status'], 'counterexample')
                self.assertEqual(bad['counterexample']['invariant'], invariant)
                self.assertFalse(self.a.validate_trace(bad['counterexample']['trace'])['valid'])
        with self.assertRaises(ValueError):
            self.a.bounded_check(depth=10000)

    def test_status_only_reports_executed_current_model_check(self):
        from autonomy_store import Ledger
        ledger = Ledger(self.path)
        self.assertEqual(self.a.check_status(ledger)['status'], 'unrun')
        result = self.a.bounded_check(ledger=ledger, goals=1, depth=4)
        status = self.a.check_status(ledger)
        self.assertEqual(status['status'], 'no_counterexample_within_bounds')
        self.assertEqual(status['model_hash'], result['model_hash'])
        self.assertEqual(status['scope'], result['scope'])
        self.assertGreaterEqual(status['executed_at'], 0)

    def test_actual_ledger_events_project_truth_and_fence_stale_writes(self):
        from autonomy_store import Ledger
        from helpers import make_goal, evidence
        ledger = Ledger(self.path)
        goal = make_goal(ledger)
        old = ledger.claim('old', 1000, 2)
        sub = ledger.prepare_submission(old, {'input': 'intent'}, 'session', {'identity_version': 'v1'},
                                        1000, 2, 1, 2, 86400)['submission']
        new = ledger.claim('new', 1003, 20)
        self.assertFalse(ledger.record_admission(old, sub['id'], 'stale', 'running', 1003))
        self.assertTrue(ledger.record_admission(new, sub['id'], 'real', 'running', 1003))
        self.assertTrue(ledger.finish(new, evidence(goal), 'succeeded', False, 1004,
                                      expected_submission_id=sub['id']))
        recovery = ledger.claim('recovery', 1005, 20)
        self.assertTrue(ledger.finish(recovery, evidence(goal, None), 'unknown_result', True, 1006,
                                      expected_submission_id=sub['id']))
        with ledger._connection() as c:
            result = self.a.validate_trace(c)
            events = [r[0] for r in c.execute('SELECT event FROM protocol_events ORDER BY seq')]
            self.assertEqual(events.count('admission'), 1)
            self.assertEqual(events.count('runtime'), 1)
            self.assertTrue(result['valid'], result)
            self.assertEqual(result['state']['goals'][goal['id']]['truth'], 'succeeded')
            self.assertTrue(result['state']['submissions'][sub['id']]['settled'])

    def test_two_real_ledgers_admission_budget_commit_order(self):
        from autonomy_store import Ledger
        ledger = Ledger(self.path)
        goal_ids = []
        for n in range(2):
            contract = {'type': 'file_contains', 'path': str(Path(self.temp.name) / str(n)),
                        'text': 'done', 'require_change': True}
            goal = ledger.create_goal({'source_id': str(n), 'contract_id': 'c', 'domain': 'code',
                                      'objective': 'work', 'confidence': .5}, 'r', contract,
                                     {'verdict': False}, 1000, 600)
            goal_ids.append(goal['id'])
        barrier = threading.Barrier(2)
        outcomes, errors = [], []
        def admit(gid):
            try:
                other = Ledger(self.path)
                claimed = other.claim(gid, 1000, 20, ranked_goal_ids=(gid,))
                barrier.wait(5)
                result = other.prepare_submission(claimed, {'input': 'intent'}, 'session',
                    {'identity_version': 'v1'}, 1001, 1, 2, 1, 86400)
                outcomes.append((claimed, result))
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=admit, args=(gid,)) for gid in goal_ids]
        for worker in threads:
            worker.start()
        for worker in threads:
            worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sum(r['admitted'] for _, r in outcomes), 1)
        rejected_lease, rejected = next((l, r) for l, r in outcomes if not r['admitted'])
        self.assertEqual(rejected['reason'], 'daily_cap')
        with ledger._connection() as c:
            result = self.a.validate_trace(c)
            self.assertTrue(result['valid'], result)
            self.assertEqual(c.execute('SELECT SUM(runs) FROM run_budget').fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM protocol_events WHERE event='admission'").fetchone()[0], 1)
            rows = self.a._events(c)
        mutant = event('admission', {'goal_id': rejected_lease.goal_id, 'owner': rejected_lease.owner,
            'generation': rejected_lease.generation, 'submission_id': 'mutant', 'day': '1970-01-01',
            'daily_cap': 1, 'max_active': 2}, 1002)
        bad = self.a.validate_trace(rows + [mutant])
        self.assertFalse(bad['valid'])
        self.assertEqual(bad['counterexample']['invariant'], 'budget')

    def test_actual_skill_publication_and_deferred_fallback_events(self):
        from test_skill_store import SkillStoreTests, CODE
        fixture = SkillStoreTests('test_pause_before_publication_preserves_paid_candidate_until_resume')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        goal, _, first = fixture.publish('v1')
        fixture.attempt('v2', now=1020)
        fixture.store.sync(1022)
        job = fixture.store.claim(1022)
        fixture.store.begin(job, 1022)
        fixture.store.freeze(job, CODE + '# v2\n', 1023)
        fixture.ledger.set_pause(True)
        self.assertFalse(fixture.store.finish(job, fixture.report(CODE + '# v2\n'), 1024))
        with fixture.ledger._connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM protocol_events WHERE event='publication'").fetchone()[0], 1)
        fixture.ledger.set_pause(False)
        self.assertTrue(fixture.store.finish(job, fixture.report(CODE + '# v2\n'), 1025))
        second = fixture.store.retrieve(goal, fixture.identity)[0]
        fixture.attempt('regression', bindings=[second], now=1040)
        fixture.ledger.set_pause(True)
        fixture.store.sync(1042)
        self.assertEqual(fixture.store.retrieve(goal, fixture.identity), [])
        fixture.ledger.set_pause(False)
        fixture.store.sync(1043)
        self.assertEqual(fixture.store.retrieve(goal, fixture.identity)[0]['id'], first['id'])
        with fixture.ledger._connection() as c:
            self.assertTrue(self.a.validate_trace(c)['valid'])
            positive = [json.loads(r[0]) for r in c.execute("SELECT payload FROM protocol_events WHERE event='publication' ORDER BY seq")]
            self.assertEqual([row['skill_id'] for row in positive if row['positive']],
                             [first['id'], second['id'], first['id']])

    def test_malformed_checkpoint_fails_closed(self):
        checkpoint = event('initial_checkpoint', {'paused': False, 'budgets': [],
                                                  'goals': {}, 'submissions': {}})
        result = self.a.validate_trace([checkpoint])
        self.assertFalse(result['valid'])
        self.assertEqual(result['counterexample']['invariant'], 'protocol_schema')

    def test_two_connections_serialize_pause_and_publication_in_commit_order(self):
        for first in ('pause', 'publication'):
            with self.subTest(first=first):
                path = Path(self.temp.name) / (first + '.db')
                c = sqlite3.connect(path, isolation_level=None)
                c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                self.a.initialize(c)
                c.execute('BEGIN IMMEDIATE')
                if first == 'pause':
                    c.execute("INSERT INTO settings VALUES('paused','true')")
                    self.a.record_event(c, 'pause', {'paused': True}, 1)
                else:
                    self.a.record_event(c, 'publication', {'skill_id': 'head', 'positive': True}, 1)
                started = threading.Event()
                completed = threading.Event()
                errors = []
                def later():
                    other = sqlite3.connect(path, isolation_level=None, timeout=5)
                    try:
                        started.set()
                        other.execute('BEGIN IMMEDIATE')
                        if first == 'publication':
                            other.execute("INSERT INTO settings VALUES('paused','true')")
                            self.a.record_event(other, 'pause', {'paused': True}, 2)
                        else:
                            paused = other.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
                            if not (paused and json.loads(paused[0])):
                                self.a.record_event(other, 'publication', {'skill_id': 'head', 'positive': True}, 2)
                        other.commit()
                    except BaseException as exc:
                        errors.append(exc)
                    finally:
                        other.close()
                        completed.set()
                thread = threading.Thread(target=later)
                thread.start()
                self.assertTrue(started.wait(2))
                self.assertFalse(completed.wait(.02))
                c.commit()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertTrue(self.a.validate_trace(c)['valid'])
                rows = [r[0] for r in c.execute("SELECT event FROM protocol_events WHERE event!='initial_checkpoint' ORDER BY seq")]
                self.assertEqual(rows, ['pause'] if first == 'pause' else ['publication', 'pause'])
                c.close()


if __name__ == '__main__':
    unittest.main()
