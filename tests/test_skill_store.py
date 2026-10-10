import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_store import Ledger, digest
from helpers import make_goal, evidence
from skill_evaluator import validate_skills
from test_skill_evaluator import task, sources

CODE = 'import json,sys\nprint(json.dumps(sum(json.load(sys.stdin))))\n'


class SkillStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('skill_store'), 'durable skill versions missing')
        from skill_store import SkillStore
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name)/'ledger.db')
        raw_sources = sources(); raw_sources[0]['contracts']['result']['path'] = '/tmp/result'
        raw_sources[0]['contracts']['result']['require_change'] = True
        self.tasks = validate_skills([task()], raw_sources)
        self.identity = {'api_url': 'http://127.0.0.1:8642', 'identity_version': 'v1'}
        self.store = SkillStore(self.ledger, self.tasks, self.identity)

    def attempt(self, revision, verdict=False, bindings=None, now=1000, settled=True):
        goal = make_goal(self.ledger, now=now, source_revision=revision)
        lease = self.ledger.claim('owner', now, 50, (goal['id'],))
        result = self.ledger.prepare_submission(lease, {'input': json.dumps({'skills': bindings or []})}, 's', self.identity,
                                                now, 100, 10, 3, 86400)
        self.assertTrue(result['admitted'], result)
        sub = result['submission']
        self.ledger.record_admission(lease, sub['id'], 'run-'+sub['id'], 'completed', now)
        self.ledger.record_attempt_result(lease, sub['id'], evidence(goal, verdict), now+1)
        outcome = 'succeeded' if verdict is True else ('failed' if verdict is False else 'unknown_result')
        self.ledger.finish(lease, evidence(goal, verdict), outcome, settled,
                           now+1, expected_submission_id=sub['id'])
        return self.ledger.get_goal(goal['id']), sub

    def report(self, code=CODE, verdict=True):
        cases = self.tasks[0]['examples']+self.tasks[0]['holdout']
        return {'verdict': verdict, 'reason': 'trusted_cases_passed' if verdict else 'case_failed',
                'cleanup_confirmed': True, 'code_hash': hashlib.sha256(code.encode()).hexdigest(),
                'task_digest': self.tasks[0]['task_digest'], 'image': self.tasks[0]['image'], 'passed': len(cases),
                'cases': [{'input_hash': digest(c['input']), 'output_hash': digest(c['output']), 'passed': True} for c in cases]}

    def publish(self, revision='origin', now=1000, code=CODE):
        goal, sub = self.attempt(revision, now=now)
        self.store.sync(now+2); job = self.store.claim(now+2)
        self.assertTrue(self.store.begin(job, now+2))
        self.assertTrue(self.store.freeze(job, code, now+3))
        self.assertTrue(self.store.finish(job, self.report(code), now+4))
        return goal, sub, self.store.retrieve(goal, self.identity)[0]

    def test_only_settled_failures_generate_and_duplicates_do_not(self):
        self.attempt('success', True); self.attempt('unknown', None)
        self.store.sync(1002); self.assertIsNone(self.store.claim(1002))
        goal, _, binding = self.publish()
        self.attempt('unsettled', False, now=1010, settled=False)
        self.store.sync(1005); self.assertIsNone(self.store.claim(1005))
        self.assertEqual(binding['code'], CODE); self.assertEqual(self.store.summary()['states'], {'active': 1})

    def test_frozen_candidate_and_report_reject_database_rewrites(self):
        _, _, binding = self.publish()
        with self.ledger._connection(True) as c:
            for field in ['code', 'code_hash', 'scope', 'report']:
                with self.subTest(field=field), self.assertRaisesRegex(Exception, 'frozen_skill'):
                    c.execute('UPDATE skill_versions SET '+field+'=? WHERE id=?', ('changed', binding['id']))

    def test_bad_or_unknown_evaluation_cannot_publish(self):
        self.attempt('failure'); self.store.sync(1002); job = self.store.claim(1002); self.store.begin(job, 1002)
        self.store.freeze(job, CODE, 1003)
        for change in [{'cleanup_confirmed': False}, {'task_digest': 'wrong'}, {'passed': 1}, {'cases': []}, {'code_hash': 'wrong'}]:
            self.assertFalse(self.store.finish(job, dict(self.report(), **change), 1004))
        self.assertEqual(self.store.summary()['states'], {'candidate': 1})

    def test_restart_recovers_frozen_code_without_new_generation(self):
        self.attempt('origin'); self.store.sync(1002)
        first = self.store.claim(1002); self.store.begin(first, 1002); self.store.freeze(first, CODE, 1003)
        from skill_store import SkillStore
        other = SkillStore(Ledger(self.ledger.path), self.tasks, self.identity)
        self.assertIsNone(other.claim(1004)); second = other.claim(1203)
        self.assertEqual(second['code'], CODE); self.assertEqual(second['attempts'], 1)
        self.assertFalse(self.store.finish(first, self.report(), 1204))
        self.assertTrue(other.finish(second, self.report(), 1204))

    def test_budget_deferral_and_two_generation_attempt_limit(self):
        self.attempt('origin'); self.store.sync(1002)
        job = self.store.claim(1002); self.store.defer(job, 1002, 'budget')
        job = self.store.claim(1063); self.assertEqual(job['attempts'], 0)
        for now in [1063, 1124]:
            if now != 1063: job = self.store.claim(now)
            self.assertTrue(self.store.begin(job, now)); self.store.defer(job, now+1, 'invalid_response')
        self.assertIsNone(self.store.claim(1300)); self.assertEqual(self.store.summary()['jobs'], {'invalid': 1})

    def test_published_replacement_regression_rolls_back_without_rewriting_old_request(self):
        goal, _, first = self.publish('v1')
        _, _, second = self.publish('v2', now=1020, code=CODE+'# v2\n')
        failed, sub = self.attempt('regression', bindings=[second], now=1040)
        frozen = sub['request']
        self.store.sync(1042)
        self.assertEqual(self.store.retrieve(goal, self.identity)[0]['id'], first['id'])
        self.assertEqual(self.ledger.get_goal(failed['id'])['submission']['request'], frozen)
        self.assertEqual(self.store.summary()['states'], {'active': 1, 'retired': 1})

    def test_late_old_failure_does_not_roll_back_new_active(self):
        goal, _, first = self.publish('v1')
        self.attempt('v2-origin', now=1010)
        old, sub = self.attempt('old-inflight', bindings=[first], now=1020, settled=False)
        self.store.sync(1030); job = self.store.claim(1030); self.store.begin(job, 1030)
        code = CODE+'# v2\n'; self.store.freeze(job, code, 1031); self.store.finish(job, self.report(code), 1032)
        second = self.store.retrieve(goal, self.identity)[0]
        lease = self.ledger.claim('recovery', 1040, 20, (old['id'],))
        self.ledger.finish(lease, evidence(old, False), 'failed', True, 1041, expected_submission_id=sub['id'])
        self.store.sync(1042)
        self.assertEqual(self.store.retrieve(goal, self.identity)[0]['id'], second['id'])

    def test_stale_binding_is_rejected_atomically_without_budget(self):
        _, _, first = self.publish('v1')
        self.publish('v2', now=1020, code=CODE+'# v2\n')
        goal = make_goal(self.ledger, now=1040, source_revision='new')
        lease = self.ledger.claim('next', 1040, 20, (goal['id'],))
        result = self.ledger.prepare_submission(lease, {'input': json.dumps({'skills': [first]})}, 's', self.identity, 1040, 100, 10, 3, 86400)
        self.assertFalse(result['admitted']); self.assertEqual(result['reason'], 'skill_no_longer_applicable')
        self.assertEqual(self.ledger.get_goal(goal['id'])['attempts'], 0)

    def test_failure_without_backup_disables_skill_and_cancelled_failure_is_ignored(self):
        goal, _, binding = self.publish()
        self.attempt('regression', bindings=[binding], now=1020)
        self.store.sync(1022)
        self.assertEqual(self.store.retrieve(goal, self.identity), [])
        cancelled, _ = self.attempt('cancelled-origin', now=1040)
        self.ledger.request_cancel(cancelled['id']); self.store.sync(1042)
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM skill_jobs WHERE submission_id=?', (cancelled['submission']['id'],)).fetchone()[0], 0)

    def test_older_candidate_finishing_after_newer_cannot_replace_head(self):
        self.attempt('older', now=1000); self.store.sync(1002)
        first = self.store.claim(1002); self.store.begin(first, 1002); self.store.freeze(first, CODE, 1003)
        self.attempt('newer', now=1010); self.store.sync(1012)
        second = self.store.claim(1012); self.store.begin(second, 1012)
        code = CODE+'# newer\n'; self.store.freeze(second, code, 1013)
        self.assertTrue(self.store.finish(second, self.report(code), 1014))
        self.assertTrue(self.store.finish(first, self.report(), 1015))
        goal = make_goal(self.ledger, source_revision='future', now=1020)
        self.assertEqual(self.store.retrieve(goal, self.identity)[0]['code'], code)

    def test_manifest_and_identity_drift_block_retrieval_and_admission(self):
        goal, _, binding = self.publish()
        self.assertEqual(self.store.retrieve(goal, dict(self.identity, identity_version='v2')), [])
        from skill_store import SkillStore
        changed = dict(task(), holdout=[{'input': [], 'output': 0}, {'input': [7], 'output': 7}])
        raw_sources = sources(); raw_sources[0]['contracts']['result'] = goal['contract']
        other = SkillStore(self.ledger, validate_skills([changed], raw_sources), self.identity)
        self.assertEqual(other.retrieve(goal, self.identity), [])
        future = make_goal(self.ledger, now=1040, source_revision='changed-suite')
        lease = self.ledger.claim('next', 1040, 20, (future['id'],))
        self.assertFalse(self.ledger.prepare_submission(lease, {'input': json.dumps({'skills': [binding]})}, 's', self.identity, 1040, 100, 10, 3, 86400)['admitted'])


if __name__ == '__main__': unittest.main()
