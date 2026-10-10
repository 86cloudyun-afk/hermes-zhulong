import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_experience_store as fixtures


class LearnerTests(unittest.TestCase):
    attempt = fixtures.ExperienceStoreTests.attempt

    def setUp(self):
        fixtures.ExperienceStoreTests.setUp(self)
        self.assertIsNotNone(importlib.util.find_spec('experience'), 'autonomous learner missing')
        from experience import ExperienceLearner
        self.now = [1002]; self.requests = []; self.allowed = True; self.spent = 0
        self.budget = SimpleNamespace(take=self.take)
        self.llm = SimpleNamespace(complete_structured=self.complete)
        self.learner = ExperienceLearner(self.store, self.llm, self.budget, clock=lambda: self.now[0])

    def take(self):
        if not self.allowed: return False
        self.spent += 1; return True

    def complete(self, **kw):
        self.requests.append(kw)
        return SimpleNamespace(parsed={'guidance': 'Check the required field type before creating the output.'})

    def test_actual_generation_budget_and_minimal_input(self):
        self.attempt('origin')
        self.learner.tick(1002, lambda: True)
        self.assertEqual(self.spent, 1); self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]['purpose'], 'zhulong.experience.learn')
        self.assertEqual(self.requests[0]['timeout'], 45)
        payload = json.loads(self.requests[0]['input'][0]['text'])
        self.assertNotIn('request', payload); self.assertNotIn('facts', payload)
        self.learner.tick(1002, lambda: True)
        self.assertEqual(self.spent, 1)
        self.assertEqual(self.store.summary()['states'], {'candidate': 1})

    def test_zero_budget_recovers_without_exhausting_failure(self):
        self.attempt('origin'); self.allowed = False
        self.learner.tick(1002, lambda: True)
        self.assertEqual(self.requests, [])
        self.allowed = True; self.now[0] = 1063
        self.learner.tick(1063, lambda: True)
        self.assertEqual(self.spent, 1)
        self.assertEqual(self.store.summary()['states'], {'candidate': 1})

    def test_stop_never_calls_model_and_late_response_is_discarded(self):
        self.attempt('origin'); self.learner.tick(1002, lambda: False)
        self.assertEqual(self.spent, 0)
        active = [True]
        def stop_during_call(**kw):
            active[0] = False
            return SimpleNamespace(parsed={'guidance': 'late'})
        self.llm.complete_structured = stop_during_call
        self.learner.tick(1002, lambda: active[0])
        self.assertEqual(self.store.summary()['strategies'], [])

    def test_invalid_model_payload_is_bounded_and_errors_sanitized(self):
        self.attempt('origin')
        self.llm.complete_structured = lambda **kw: SimpleNamespace(parsed={'guidance': 'x', 'permission': 'all'})
        for t in [1002, 1063, 1124, 1185]:
            self.now[0] = t; self.learner.tick(t, lambda: True)
        self.assertEqual(self.spent, 2)
        self.assertEqual(self.store.summary()['jobs'], {'invalid': 1})
        self.assertEqual(self.store.summary()['strategies'], [])


if __name__ == '__main__': unittest.main()
