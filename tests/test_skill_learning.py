import importlib.util
import json
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_skill_store as fixtures
CODE = fixtures.CODE


class SkillLearnerTests(unittest.TestCase):
    attempt = fixtures.SkillStoreTests.attempt
    report = fixtures.SkillStoreTests.report
    publish = fixtures.SkillStoreTests.publish

    def setUp(self):
        fixtures.SkillStoreTests.setUp(self)
        self.assertIsNotNone(importlib.util.find_spec('skill_learning'), 'executable skill learner missing')
        from skill_learning import SkillLearner
        self.now = [1002]; self.allowed = True; self.spent = 0; self.requests = []; self.evaluations = 0
        self.llm = SimpleNamespace(complete_structured=self.complete)
        self.budget = SimpleNamespace(take=self.take)
        self.evaluator = SimpleNamespace(locked=lambda: nullcontext(True), cleanup=lambda: True, evaluate=self.evaluate)
        self.learner = SkillLearner(self.store, self.llm, self.budget, self.evaluator, clock=lambda: self.now[0])

    def take(self):
        if not self.allowed: return False
        self.spent += 1; return True

    def complete(self, **kwargs):
        self.requests.append(kwargs); return SimpleNamespace(parsed={'code': CODE})

    def evaluate(self, code, task, token, admissible):
        self.assertTrue(admissible()); self.evaluations += 1; return self.report(code)

    def test_generation_shares_budget_and_never_discloses_hidden_cases(self):
        self.attempt('origin'); self.learner.tick(1002, lambda: True)
        self.assertEqual(self.spent, 1); self.assertEqual(self.evaluations, 1)
        self.assertEqual(self.store.summary()['states'], {'active': 1})
        request = self.requests[0]; payload = json.loads(request['input'][0]['text'])
        self.assertEqual(set(payload['task']), {'description', 'examples'})
        self.assertNotIn('holdout', request['input'][0]['text']); self.assertNotIn('facts', payload)
        self.assertEqual(request['timeout'], 45); self.assertEqual(request['purpose'], 'zhulong.skill.learn')
        self.learner.tick(1003, lambda: True); self.assertEqual(self.spent, 1)

    def test_zero_budget_does_not_consume_candidate_attempt(self):
        self.attempt('origin'); self.allowed = False; self.learner.tick(1002, lambda: True)
        self.assertEqual(self.spent, 0); self.assertEqual(self.evaluations, 0)
        self.allowed = True; self.now[0] = 1063; self.learner.tick(1063, lambda: True)
        self.assertEqual(self.spent, 1); self.assertEqual(self.store.summary()['states'], {'active': 1})

    def test_stop_during_evaluation_preserves_paid_code_and_resume_does_not_generate(self):
        self.attempt('origin'); active = [True]
        def stopped(*args):
            active[0] = False
            return dict(self.report(), verdict='unknown', reason='admission_closed')
        self.evaluator.evaluate = stopped; self.learner.tick(1002, lambda: active[0])
        self.assertEqual(self.store.summary()['states'], {'candidate': 1})
        active[0] = True; self.evaluator.evaluate = self.evaluate; self.now[0] = 1063
        self.learner.tick(1063, lambda: active[0]); self.assertEqual(self.spent, 1)
        self.assertEqual(self.store.summary()['states'], {'active': 1})

    def test_independent_failure_is_rejected_and_generation_is_bounded(self):
        self.attempt('origin'); self.evaluator.evaluate = lambda *args: self.report(verdict=False)
        for now in [1002, 1063, 1124]:
            self.now[0] = now; self.learner.tick(now, lambda: True)
        self.assertEqual(self.spent, 2); self.assertEqual(self.store.summary()['states'], {'rejected': 2})
        self.assertEqual(self.store.summary()['jobs'], {'invalid': 1})

    def test_paused_pipeline_still_settles_bound_regression_without_new_calls(self):
        goal, _, binding = self.publish()
        self.attempt('regression', bindings=[binding], now=1010)
        self.learner.tick(1012, lambda: False)
        self.assertEqual(self.store.retrieve(goal, self.identity), [])
        self.assertEqual(self.requests, []); self.assertEqual(self.evaluations, 0)

    def test_unknown_cleanup_blocks_generation_and_evaluation(self):
        self.attempt('origin'); self.evaluator.cleanup = lambda: False
        result = self.learner.tick(1002, lambda: True)
        self.assertEqual(result['reason'], 'cleanup_unknown'); self.assertEqual(self.spent, 0)

    def test_daily_evaluation_cap_persists_across_restart_without_regeneration(self):
        self.attempt('origin'); self.learner.daily_evaluations = 0
        self.learner.tick(1002, lambda: True)
        self.assertEqual(self.spent, 0); self.assertEqual(self.evaluations, 0)
        self.assertTrue(hasattr(self.store, 'reserve_evaluation'), 'durable evaluation budget missing')
        self.assertTrue(self.store.reserve_evaluation(1003, 1))
        from skill_store import SkillStore
        restarted = SkillStore(self.ledger, self.tasks, self.identity)
        self.assertFalse(restarted.reserve_evaluation(1004, 1))
        self.assertTrue(restarted.reserve_evaluation(90000, 1))

    def test_controller_freezes_single_published_program_in_request(self):
        from autonomy import Controller
        goal, _, binding = self.publish()
        policy = {'mission': 'Use verified programs', 'sources': [{'id': 'source-code', 'path': '/tmp/facts'}], 'workspace_roots': ['/tmp']}
        self.assertIn('skills', __import__('inspect').signature(Controller).parameters, 'controller skill integration missing')
        controller = Controller(self.ledger, policy, None, None, None, None, skills=self.learner)
        controller.execution_identity = self.identity
        request = json.loads(controller._request(goal)['input'])
        self.assertEqual(request['skills'], [binding]); self.assertIn('skill_rule', request)

    def test_controller_pause_still_retires_regression(self):
        from autonomy import Controller
        from autonomy_checks import validate_config, Verifier
        from helpers import policy_config
        goal, _, binding = self.publish()
        self.attempt('regression', bindings=[binding], now=1010)
        root = self.ledger.path.parent; (root/'facts.json').write_text('{}')
        policy = validate_config(policy_config(root), root)
        self.now[0] = 1012; self.ledger.set_pause(True)
        controller = Controller(self.ledger, policy, None, None, Verifier(policy), SimpleNamespace(refresh=lambda: None),
                                skills=self.learner, clock=lambda: self.now[0])
        controller.tick()
        self.assertEqual(self.store.retrieve(goal, self.identity), [])

    def test_self_model_tracks_published_skill_metadata_without_code_or_answers(self):
        from self_model import SelfModel
        self.publish()
        self.assertIn('skills', __import__('inspect').signature(SelfModel).parameters, 'self model skill evidence missing')
        model = SelfModel(self.ledger, self.ledger.path.parent, skills=self.store)
        snapshot = model.refresh()
        self.assertEqual(snapshot['skills']['states'], {'active': 1})
        self.assertNotIn('code', snapshot['skills']['versions'][0])
        self.assertNotIn('holdout', json.dumps(snapshot['skills']))


class SkillIntegrationTests(unittest.TestCase):
    def test_normalized_policy_accepts_empty_and_trusted_skill_manifest(self):
        import tempfile
        from autonomy_checks import validate_config
        from helpers import policy_config
        from test_skill_evaluator import task
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'facts.json').write_text('{}')
            raw = policy_config(root)
            value = dict(task(), source_id='code-facts')
            raw['executable_skills'] = [value]; raw['skill_daily_evaluations'] = 0
            policy = validate_config(raw, root)
            self.assertEqual(policy['executable_skills'][0]['id'], 'sum')
            self.assertEqual(policy['skill_daily_evaluations'], 0)

    def test_protected_evaluator_must_use_worker_image(self):
        import test_runtime_policy
        fixture = test_runtime_policy.PolicyTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        wrong = dict(fixture.policy, executable_skills=[{'image': 'python@sha256:'+'c'*64}])
        with self.assertRaisesRegex(ValueError, 'skill_worker_image_mismatch'):
            fixture.m.validate_worker_policy(fixture.manifest, wrong)


if __name__ == '__main__': unittest.main()
