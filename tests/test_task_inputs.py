"""Real observation/SQLite/Controller regressions for frozen authorized inputs."""
import copy
import importlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_checks import Verifier, observe_sources, validate_config
from autonomy_store import Ledger, canonical
from helpers import policy_config
from self_model import SelfModel
from test_autonomy import Planner, Runs


class TaskInputTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('task_inputs'), 'frozen input module missing')
        self.m = importlib.import_module('task_inputs')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.raw = policy_config(self.root)
        source = self.raw['sources'][0]
        source.update(input_fields=['observations'], persist_input_fields=['observations'])
        source['contracts']['result'] = {'type': 'json_equals', 'path': str(self.root/'result.json'), 'field': 'sum', 'value': 3}
        self.fact = self.root/'facts.json'
        self.fact.write_text('{"observations":[1,2],"unused_private":"excluded-original"}')
        self.policy = validate_config(self.raw, self.root)
        self.ledger = Ledger(self.root/'ledger.db')
        self.m.configure(self.ledger, self.policy['sources'], self.policy['input_snapshot_bytes'])
        self.obs = observe_sources(self.policy)[0]
        self.identity = {'api_url': 'http://127.0.0.1:8642', 'identity_version': 'v1'}

    def goal(self, revision=None, task_input=True, ledger=None):
        revision = revision or self.obs['revision']
        binding = copy.deepcopy(self.obs['task_input']) if task_input is True else task_input
        if binding is not None: binding['source_revision'] = revision
        return (ledger or self.ledger).create_goal(
            {'source_id': 'code-facts', 'contract_id': 'result', 'domain': 'code',
             'objective': 'Create verified sum', 'reason': 'Observed missing result', 'confidence': 0.7},
            revision, self.policy['sources'][0]['contracts']['result'],
            {'verdict': False, 'artifact_hash': None}, 1000, 600, task_input=binding)

    def prepare(self, goal, body):
        lease = self.ledger.claim('owner', 1000, 50, (goal['id'],))
        return lease, self.ledger.prepare_submission(lease, {'input': canonical(body)}, 'session', self.identity,
                                                  1000, 1, 1, 2, 86400)

    def test_only_explicit_fields_are_frozen_and_duplicate_goal_costs_no_more_bytes(self):
        g = self.goal(); repeated = self.goal()
        self.assertEqual(g['task_input']['data'], {'observations': [1, 2]})
        self.assertEqual(g['id'], repeated['id'])
        self.assertEqual(self.m.summary(self.ledger)['used_bytes'], len(canonical({'observations': [1, 2]}).encode()))
        with self.ledger._connection() as c:
            contents = c.execute('SELECT payload FROM task_inputs').fetchone()[0]
        self.assertNotIn('excluded-original', contents)

    def test_capture_is_opt_in_and_zero_bytes_blocks_new_planning(self):
        from autonomy import Controller
        raw = copy.deepcopy(self.raw); raw['input_snapshot_bytes'] = 0
        policy = validate_config(raw, self.root); planner = Planner(); runs = Runs()
        model = SelfModel(self.ledger, self.root)
        controller = Controller(self.ledger, policy, planner, runs, Verifier(policy), model, clock=lambda:1000)
        controller.tick()
        self.assertEqual(planner.calls, 0); self.assertEqual(runs.calls, 0)
        self.assertEqual(self.ledger.goals(), [])
        raw = copy.deepcopy(self.raw); raw['sources'][0].pop('persist_input_fields')
        self.assertNotIn('task_input', observe_sources(validate_config(raw, self.root))[0])

    def test_invalid_persistence_rules_are_rejected(self):
        for fields in ([], ['observations','observations'], ['missing'], ['nested.value'], ['x'*65]):
            raw = copy.deepcopy(self.raw); raw['sources'][0]['persist_input_fields'] = fields
            with self.subTest(fields=fields), self.assertRaises(ValueError): validate_config(raw, self.root)
        raw = copy.deepcopy(self.raw); raw['sources'][0].pop('input_fields')
        with self.assertRaises(ValueError): validate_config(raw, self.root)

    def test_strict_json_and_payload_limits_close_observation(self):
        for text in ('{"observations":[1],"observations":[2]}', '{"observations":[NaN]}',
                     '{"observations":[1e999]}', '{"observations":'+('['*34)+'0'+(']'*34)+'}',
                     json.dumps({'observations':'x'*4097}), '{"other":1}'):
            with self.subTest(text=text[:50]):
                self.fact.write_text(text)
                self.assertFalse(observe_sources(self.policy)[0]['available'])

    def test_revision_tracks_input_and_persistence_rule(self):
        initial = self.obs['revision']
        self.fact.write_text('{"observations":[1,3]}')
        changed = observe_sources(self.policy)[0]
        self.assertNotEqual(initial, changed['revision'])
        raw = copy.deepcopy(self.raw); raw['sources'][0].pop('persist_input_fields')
        self.assertNotEqual(changed['revision'], observe_sources(validate_config(raw,self.root))[0]['revision'])

    def test_goal_keeps_old_input_when_source_changes_and_cannot_rewrite_or_delete(self):
        goal = self.goal()
        self.fact.write_text('{"observations":[99]}')
        self.assertEqual(self.ledger.get_goal(goal['id'])['task_input']['data'], {'observations':[1,2]})
        with self.ledger._connection(True) as c:
            for query in ('UPDATE task_inputs SET payload=? WHERE goal_id=?', 'DELETE FROM task_inputs WHERE goal_id=?'):
                args = ('{}',goal['id']) if query.startswith('UPDATE') else (goal['id'],)
                with self.subTest(query=query), self.assertRaisesRegex(sqlite3.DatabaseError,'frozen_task_input'):
                    c.execute(query,args)

    def test_two_connections_cannot_overrun_last_payload_quota(self):
        size = self.obs['task_input']['size']; self.m.configure(self.ledger,self.policy['sources'],size)
        barrier = threading.Barrier(2)
        def create(i):
            ledger = Ledger(self.ledger.path); barrier.wait()
            try: return bool(self.goal('parallel-'+str(i),ledger=ledger))
            except ValueError as exc: self.assertEqual(str(exc),'input_snapshot_budget_exhausted'); return False
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(create,(1,2)))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(len(self.ledger.goals()),1)
        self.assertEqual(self.m.summary(self.ledger)['used_bytes'],size)

    def test_missing_or_corrupt_input_rolls_back_entire_new_goal(self):
        for binding in (None,dict(self.obs['task_input'],input_hash='0'*64),dict(self.obs['task_input'],size=999)):
            with self.subTest(binding=binding is None), self.assertRaises(ValueError):self.goal(task_input=binding)
            self.assertEqual(self.ledger.goals(),[])

    def test_old_goal_is_not_retroactively_given_current_input(self):
        self.m.configure(self.ledger,[],0)
        legacy = self.goal(task_input=None)
        self.m.configure(self.ledger,self.policy['sources'],8388608)
        with self.assertRaisesRegex(ValueError,'input_snapshot_legacy_unavailable'):self.goal()
        self.assertIsNone(self.ledger.get_goal(legacy['id'])['task_input'])

    def test_forged_binding_does_not_consume_run_or_attempt_budget(self):
        goal = self.goal(); forged = copy.deepcopy(goal['task_input']); forged['data']['observations']=[99]
        lease,result = self.prepare(goal,{'task_input':forged})
        self.assertFalse(result['admitted']); self.assertEqual(result['reason'],'input_snapshot_no_longer_applicable')
        self.assertEqual(self.ledger.get_goal(goal['id'])['attempts'],0)
        correct = self.ledger.prepare_submission(lease,{'input':canonical({'task_input':goal['task_input']})},
            'session',self.identity,1000,1,1,2,86400)
        self.assertTrue(correct['admitted'])

    def test_configuration_removed_blocks_new_work_but_preserves_existing_reconciliation(self):
        goal = self.goal(); lease,result = self.prepare(goal,{'task_input':goal['task_input']})
        self.assertTrue(result['admitted']); sub=result['submission']
        self.m.configure(self.ledger,[],0)
        again=self.ledger.prepare_submission(lease,{'input':'{}'},'other',self.identity,
            1001,0,1,2,86400,expected_submission_id=sub['id'])
        self.assertEqual(again['reason'],'reconcile_existing')
        self.assertEqual(again['submission']['request'],sub['request'])

    def test_old_controller_cannot_admit_binding_after_new_instance_changes_rule(self):
        goal=self.goal(); self.m.configure(self.ledger,[],8388608)
        _,result=self.prepare(goal,{'task_input':goal['task_input']})
        self.assertFalse(result['admitted']); self.assertEqual(self.ledger.get_goal(goal['id'])['attempts'],0)

    def test_controller_uses_selected_observation_and_rejects_planning_time_source_change(self):
        from autonomy import Controller
        planner=Planner(); runs=Runs(); model=SelfModel(self.ledger,self.root)
        controller=Controller(self.ledger,self.policy,planner,runs,Verifier(self.policy),model,clock=lambda:1000)
        controller.tick(); goal=self.ledger.goals()[0]
        self.assertEqual(json.loads(goal['submission']['request']['input'])['task_input'],goal['task_input'])
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp)/'db'); planner=Planner()
            original=planner.plan
            def changing(*args): result=original(*args);self.fact.write_text('{"observations":[90]}');return result
            planner.plan=changing
            controller=Controller(ledger,self.policy,planner,Runs(),Verifier(self.policy),SelfModel(ledger,Path(tmp)),clock=lambda:1000)
            controller.tick();self.assertEqual(ledger.goals(),[])

    def test_private_envelope_is_not_expanded_into_planner_prompt(self):
        from autonomy import LLMPlanner
        requests=[]
        def complete(**kwargs): requests.append(kwargs);return SimpleNamespace(parsed={'candidates':[]})
        observation=copy.deepcopy(self.obs)
        observation['task_input']['data']={'never-forward':'private-envelope-marker'}
        LLMPlanner(SimpleNamespace(complete_structured=complete),SimpleNamespace(take=lambda:True)).plan([observation],{},self.policy)
        self.assertNotIn('private-envelope-marker',requests[0]['input'][0]['text'])
        self.assertNotIn('task_input',json.loads(requests[0]['input'][0]['text'])['observations'][0])

    def test_public_goals_and_self_model_export_metadata_without_request_or_input_data(self):
        from autonomy import Controller
        from commands import Commands
        goal=self.goal();self.prepare(goal,{'task_input':goal['task_input'],'private-test':'ordinary-export-secret'})
        model=SelfModel(self.ledger,self.root);model.refresh()
        controller=Controller(self.ledger,self.policy,Planner(),Runs(),Verifier(self.policy),model,clock=lambda:1000)
        command=Commands(None,calibration=SimpleNamespace(),autonomy=controller)
        rendered=command._autonomy(['goals'])
        self.assertNotIn('ordinary-export-secret',rendered);self.assertNotIn('"data"',rendered)
        self.assertIn(goal['task_input']['input_hash'],rendered)
        self.assertNotIn('"task_input"',canonical(model.snapshot()))


if __name__=='__main__':unittest.main()
