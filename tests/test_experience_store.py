import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_store import Ledger, digest
from helpers import make_goal, evidence


class ExperienceStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('experience_store'), 'strategy ledger missing')
        from experience_store import ExperienceStore
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / 'ledger.db')
        self.store = ExperienceStore(self.ledger)
        self.identity = {'api_url': 'http://127.0.0.1:8642', 'identity_version': 'v1'}

    def attempt(self, revision, verdict=False, guidance=None, domain='code', now=1000,
                settled=True, attempt=1, goal=None):
        goal = goal or make_goal(self.ledger, now=now, source_revision=revision, domain=domain)
        lease = self.ledger.claim('owner', now, 50, (goal['id'],))
        request = {'input': json.dumps({'experience': guidance or []})}
        old = goal['submission']['id'] if goal['submission'] else None
        sub = self.ledger.prepare_submission(lease, request, 'session', self.identity, now, 100, 10, 3, 86400,
            expected_submission_id=old)['submission']
        self.ledger.record_admission(lease, sub['id'], 'run-' + sub['id'], 'completed', now)
        if verdict is not None:
            self.ledger.record_attempt_result(lease, sub['id'], evidence(goal, verdict), now+1)
            self.ledger.finish(lease, evidence(goal, verdict), 'succeeded' if verdict else 'failed', settled,
                               now+1, expected_submission_id=sub['id'])
        else:
            self.ledger.finish(lease, evidence(goal, None), 'unknown_result', settled,
                               now+1, expected_submission_id=sub['id'])
        return self.ledger.get_goal(goal['id']), sub

    def candidate(self):
        origin, sub = self.attempt('origin')
        self.store.sync(1002)
        job = self.store.claim(1002); self.assertIsNotNone(job)
        self.assertTrue(self.store.begin(job, 1002))
        self.assertTrue(self.store.complete(job, 'Inspect the JSON field type before writing the result.', 1003))
        return origin, sub, self.store.retrieve(origin, self.identity)[0]

    def test_failure_provenance_is_required_and_duplicate_generation_is_rejected(self):
        origin, sub, strategy = self.candidate()
        self.attempt('unknown', None)
        self.attempt('success', True)
        self.attempt('unsettled', False, settled=False)
        self.store.sync(1002)
        self.assertIsNone(self.store.claim(1002))
        self.store.sync(1004)
        self.assertIsNone(self.store.claim(1004))
        self.assertEqual(strategy['origin_submission'], sub['id'])
        self.assertEqual(strategy['status'], 'candidate')
        self.assertEqual(len(self.store.summary()['strategies']), 1)

    def test_expired_owner_cannot_accept_response_and_restart_keeps_strategy(self):
        self.attempt('origin'); self.store.sync(1002)
        first = self.store.claim(1002); self.assertTrue(self.store.begin(first, 1002))
        from experience_store import ExperienceStore
        other = ExperienceStore(Ledger(self.ledger.path))
        self.assertIsNone(other.claim(1003))
        second = other.claim(1123); self.assertTrue(other.begin(second, 1123))
        self.assertFalse(self.store.complete(first, 'stale response', 1124))
        self.assertTrue(other.complete(second, 'current response', 1124))
        self.assertEqual(self.store.summary()['strategies'][0]['guidance'], 'current response')

    def test_budget_deferral_does_not_spend_generation_attempt(self):
        self.attempt('origin'); self.store.sync(1002)
        job = self.store.claim(1002); self.store.defer(job, 1002, 'budget')
        self.assertIsNone(self.store.claim(1003))
        job = self.store.claim(1063); self.assertEqual(job['attempts'], 0)
        self.assertTrue(self.store.begin(job, 1063))
        self.store.reject(job, 1064)
        job = self.store.claim(1125); self.assertEqual(job['attempts'], 1)
        self.assertTrue(self.store.begin(job, 1125)); self.store.reject(job, 1126)
        self.assertIsNone(self.store.claim(1200))

    def test_two_independent_first_pass_goals_activate_then_failure_retires(self):
        origin, _, strategy = self.candidate()
        for i in range(2):
            self.attempt('heldout-'+str(i), True, [strategy], now=1010+i*10)
            self.store.evaluate(1012+i*10)
        current = self.store.retrieve(origin, self.identity)[0]
        self.assertEqual(current['status'], 'active')
        self.assertEqual(self.store.summary()['strategies'][0]['heldout_successes'], 2)
        self.store.evaluate(1030)
        self.assertEqual(self.store.summary()['strategies'][0]['heldout_successes'], 2)
        self.attempt('regression', False, [current], now=1040); self.store.evaluate(1042)
        self.assertEqual(self.store.retrieve(origin, self.identity), [])
        self.assertEqual(self.store.summary()['strategies'][0]['status'], 'retired')
        self.store.evaluate(1050)
        self.assertEqual(self.store.summary()['strategies'][0]['status'], 'retired')

    def test_preexisting_goal_unknown_and_hash_mismatch_do_not_activate(self):
        old = make_goal(self.ledger, source_revision='accepted-before', now=999)
        origin, _, strategy = self.candidate()
        self.attempt('old', True, [strategy], now=1010, goal=old)
        self.attempt('unknown', None, [strategy], now=1020)
        forged = dict(strategy, body_hash='other')
        self.attempt('forged', True, [forged], now=1030)
        self.store.evaluate(1040)
        self.assertEqual(self.store.summary()['strategies'][0]['heldout_successes'], 0)
        self.assertEqual(self.store.retrieve(origin, self.identity)[0]['status'], 'candidate')

    def test_scope_prevents_cross_domain_source_contract_and_identity_transfer(self):
        origin, _, strategy = self.candidate()
        for key, value in [('domain', 'research'), ('source_id', 'different'), ('contract_hash', 'different')]:
            modified = dict(origin, **{key: value})
            self.assertEqual(self.store.retrieve(modified, self.identity), [])
        self.assertEqual(self.store.retrieve(origin, dict(self.identity, identity_version='v2')), [])
        with self.ledger._connection(True) as c:
            with self.assertRaisesRegex(Exception, 'frozen_strategy'):
                c.execute('UPDATE strategies SET guidance=? WHERE id=?', ('rewritten', strategy['id']))

    def test_original_retry_never_supplies_heldout_success(self):
        goal = make_goal(self.ledger, source_revision='retry')
        lease = self.ledger.claim('owner', 1000, 50, (goal['id'],))
        first = self.ledger.prepare_submission(lease, {'input': '{}'}, 's', self.identity, 1000, 100, 10, 3, 86400)['submission']
        self.ledger.record_admission(lease, first['id'], 'r', 'completed', 1000)
        self.ledger.record_attempt_result(lease, first['id'], evidence(goal, False), 1001)
        self.ledger.transition(lease, 'ready', 'safe retry', 1001, True, expected_submission_id=first['id'])
        self.ledger.release(lease, 1001)
        self.store.sync(1002); job = self.store.claim(1002); self.store.begin(job, 1002)
        self.store.complete(job, 'Try a typed value.', 1003)
        strategy = self.store.retrieve(goal, self.identity)[0]
        self.attempt('retry', True, [strategy], now=1010, goal=self.ledger.get_goal(goal['id']))
        self.store.evaluate(1012)
        self.assertEqual(self.store.summary()['strategies'][0]['heldout_successes'], 0)

    def test_concurrent_connections_claim_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from experience_store import ExperienceStore
        self.attempt('origin'); self.store.sync(1002)
        def claim(_):
            return ExperienceStore(Ledger(self.ledger.path)).claim(1002)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(x is not None for x in pool.map(claim, range(4))), 1)

    def test_invalid_guidance_does_not_create_strategy(self):
        self.attempt('origin'); self.store.sync(1002)
        job = self.store.claim(1002); self.store.begin(job, 1002)
        for invalid in ['', 'x'*601, {'guidance': 'text'}, '\x00bad']:
            with self.assertRaises(ValueError): self.store.complete(job, invalid, 1003)
        self.assertEqual(self.store.summary()['strategies'], [])

    def test_last_generation_crash_is_exhausted_after_lease_expiry(self):
        self.attempt('origin'); self.store.sync(1002)
        first=self.store.claim(1002); self.store.begin(first,1002)
        second=self.store.claim(1123); self.store.begin(second,1123)
        self.assertIsNone(self.store.claim(1244))
        self.assertEqual(self.store.summary()['jobs'],{'invalid':1})

    def test_planning_context_excludes_changed_acceptance(self):
        origin, _, strategy=self.candidate()
        observations=[{'id':origin['source_id']}]
        policy={'sources':[{'id':origin['source_id'],'domain':origin['domain'],
                            'contracts':{'result':dict(origin['contract'],text='different')}}]}
        self.assertEqual(self.store.planning_context(observations,self.identity,policy),[])


if __name__ == '__main__': unittest.main()
