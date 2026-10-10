"""Trusted original-goal regression, independent output checks and publication."""
import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_checks import observe_sources, validate_config
from autonomy_store import Ledger, canonical, digest
from helpers import evidence, policy_config
from skill_evaluator import DockerEvaluator, validate_skills
from skill_learning import SkillLearner
from skill_store import SkillStore
from test_skill_evaluator import IMAGE
import task_inputs

CODE = 'import json,sys\nx=json.load(sys.stdin)\nprint(json.dumps({"result":{"sum":sum(x["observations"])}}))\n'


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('skill_replay'), 'trusted origin replay missing')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.raw = policy_config(self.root)
        s = self.raw['sources'][0]
        s.update(input_fields=['observations'], persist_input_fields=['observations'])
        s['contracts']['result'] = {'type': 'json_equals', 'path': str(self.root/'out.json'), 'field': 'result.sum', 'value': 6}
        self.fact = self.root/'facts.json'; self.fact.write_text('{"observations":[2,4]}')
        self.policy = validate_config(self.raw, self.root)
        self.ledger = Ledger(self.root/'ledger.db')
        task_inputs.configure(self.ledger, self.policy['sources'], self.policy['input_snapshot_bytes'])
        self.raw_task = {'id': 'sum', 'source_id': 'code-facts', 'contract_id': 'result',
            'description': 'Read observations and return {"result":{"sum": their sum}}.', 'image': IMAGE,
            'examples': [{'input': {'observations':[1,2,3]}, 'output': {'result':{'sum':6}}}],
            'holdout': [{'input': {'observations':[]}, 'output': {'result':{'sum':0}}},
                        {'input': {'observations':[-3,2]}, 'output': {'result':{'sum':-1}}}], 'replay_origin': True}
        self.identity = {'api_url':'http://127.0.0.1:8642', 'identity_version':'v1'}
        self.tasks = validate_skills([self.raw_task], self.policy['sources'])
        self.store = SkillStore(self.ledger, self.tasks, self.identity)
        self.evaluator = DockerEvaluator(self.ledger.path)

    def attempt(self, legacy=False):
        if legacy: task_inputs.configure(self.ledger, [], 0)
        obs = observe_sources(self.policy)[0]
        goal = self.ledger.create_goal({'source_id':'code-facts', 'contract_id':'result', 'domain':'code',
            'objective':'Repair result', 'reason':'Missing output', 'confidence':0.7}, obs['revision'],
            self.policy['sources'][0]['contracts']['result'], {'verdict':False}, 1000, 600,
            task_input=None if legacy else obs['task_input'])
        lease = self.ledger.claim('origin', 1000, 30, (goal['id'],))
        request = {'input': canonical({} if legacy else {'task_input':goal['task_input']})}
        admitted = self.ledger.prepare_submission(lease, request, 's', self.identity, 1000, 10, 2, 3, 86400)
        self.assertTrue(admitted['admitted'], admitted); sub = admitted['submission']
        self.ledger.record_admission(lease, sub['id'], 'run-'+sub['id'], 'completed', 1000)
        self.assertTrue(self.ledger.record_attempt_result(lease,sub['id'],evidence(goal,False),1001))
        self.ledger.finish(lease, evidence(goal, False), 'failed', True, 1001, expected_submission_id=sub['id'])
        if legacy: task_inputs.configure(self.ledger, self.policy['sources'], self.policy['input_snapshot_bytes'])
        return self.ledger.get_goal(goal['id'])

    def claim(self):
        self.store.sync(1002); job = self.store.claim(1002)
        self.assertIsNotNone(job); return job

    def frozen(self, job):
        self.assertTrue(self.store.begin(job,1002)); self.assertTrue(self.store.freeze(job,CODE,1003))

    def evaluate(self, job, output=None):
        def case(code, data, *args):
            value = {'result':{'sum':sum(data['observations'])}} if output is None else output(data)
            return 0, value if isinstance(value,bytes) else canonical(value).encode(), b''
        with self.evaluator.locked(), patch.object(self.evaluator,'cleanup',return_value=True), patch.object(self.evaluator,'_case',side_effect=case):
            return self.evaluator.evaluate(CODE,job['task'], 'a'*32,lambda:True)

    def test_basic_cases_pass_but_wrong_original_field_blocks_publication(self):
        self.attempt(); job=self.claim(); self.frozen(job)
        report=self.evaluate(job,lambda data:{'result':{'sum':99 if data['observations']==[2,4] else sum(data['observations'])}})
        self.assertIs(report['verdict'],False); self.assertEqual(report['passed'],3)
        self.assertTrue(self.store.finish(job,report,1004)); self.assertEqual(self.store.summary()['states'],{'rejected':1})

    def test_new_origin_case_is_private_and_report_is_bound_to_exact_plan(self):
        goal=self.attempt(); job=self.claim(); self.frozen(job); report=self.evaluate(job)
        self.assertEqual(report['passed'],4); self.assertIs(report['origin_replay']['passed'],True)
        self.assertEqual(report['origin_replay']['input_hash'],goal['task_input']['input_hash'])
        self.assertEqual(report['origin_replay']['submission_id'],goal['submission']['id'])
        self.assertNotIn('observations',canonical(report)); self.assertNotIn('result.sum',canonical(report))
        self.assertTrue(self.store.finish(job,report,1004)); self.assertEqual(len(self.store.retrieve(goal,self.identity)),1)

    def test_duplicate_input_keeps_whole_output_and_original_field_checks(self):
        self.fact.write_text('{"observations":[1,2,3]}'); self.attempt(); job=self.claim()
        good=self.evaluate(job); self.assertEqual(good['passed'],3); self.assertTrue(good['origin_replay']['passed'])
        bad=self.evaluate(job,lambda data:{'result':{'sum':sum(data['observations'])},'extra':True})
        self.assertIs(bad['verdict'],False); self.assertEqual(len(bad['cases']),1)

    def test_conflicting_expected_field_or_missing_field_blocks_before_paid_call(self):
        self.fact.write_text('{"observations":[1,2,3]}'); self.attempt()
        for value in ({'result':{'sum':7}}, {'other':6}):
            raw=copy.deepcopy(self.raw_task); raw['examples'][0]['output']=value
            store=SkillStore(self.ledger,validate_skills([raw],self.policy['sources']),self.identity)
            store.sync(1002); self.assertIsNone(store.claim(1002))
            self.assertIn('spec_conflict',store.summary()['jobs'])
            with patch.object(SimpleNamespace(take=lambda:True),'take') as take:
                learner=SkillLearner(store,None,SimpleNamespace(take=take),
                    SimpleNamespace(locked=self.evaluator.locked,cleanup=lambda:True))
                learner.tick(1002,lambda:True);take.assert_not_called()

    def test_legacy_missing_snapshot_is_unavailable_without_backfilling(self):
        self.attempt(legacy=True); self.store.sync(1002)
        self.assertIsNone(self.store.claim(1002)); self.assertEqual(self.store.summary()['jobs'],{'replay_unavailable':1})
        self.assertEqual(task_inputs.summary(self.ledger)['stored'],0)

    def test_wrong_origin_plan_or_case_receipts_cannot_publish(self):
        self.attempt(); job=self.claim(); self.frozen(job); report=self.evaluate(job)
        for change in ({'evaluation_digest':'wrong'}, {'origin_replay':dict(report['origin_replay'],submission_id='other')},
                       {'origin_replay':dict(report['origin_replay'],passed=False)}, {'passed':3}, {'cases':report['cases'][:3]}):
            with self.subTest(change=change):self.assertFalse(self.store.finish(job,dict(report,**change),1004))
        self.assertEqual(self.store.summary()['states'],{'candidate':1})

    def test_other_instance_manifest_or_input_rule_drift_blocks_late_publication(self):
        self.attempt(); job=self.claim(); self.frozen(job); report=self.evaluate(job)
        SkillStore(Ledger(self.ledger.path),[],self.identity)
        self.assertFalse(self.store.finish(job,report,1004))
        SkillStore(self.ledger,self.tasks,self.identity)
        task_inputs.configure(Ledger(self.ledger.path),[],0)
        self.assertFalse(self.store.finish(job,report,1004))

    def test_restart_uses_original_bytes_after_source_changes(self):
        self.attempt(); job=self.claim(); self.frozen(job); original=job['task']['evaluation_digest']
        self.fact.write_text('{"observations":[999]}')
        other=SkillStore(Ledger(self.ledger.path),self.tasks,self.identity); recovered=other.claim(1203)
        self.assertEqual(recovered['code'],CODE); self.assertEqual(recovered['task']['evaluation_digest'],original)
        self.assertEqual(recovered['task']['_evaluation_cases'][-1]['input'],{'observations':[2,4]})

    def test_original_output_requires_strict_json_and_exact_numeric_type(self):
        self.attempt(); job=self.claim()
        for bad in (b'{"result":{"sum":true}}',b'{"result":{"sum":6.0}}',b'{"result":{"sum":7,"sum":6}}'):
            report=self.evaluate(job,lambda data:bad if data['observations']==[2,4] else {'result':{'sum':sum(data['observations'])}})
            self.assertIs(report['verdict'],False); self.assertEqual(report['passed'],3)

    def test_invalid_replay_manifest_and_rule_changes(self):
        for source in (dict(self.policy['sources'][0],persist_input_fields=[]),
                       dict(self.policy['sources'][0],contracts={'result':{'type':'file_contains'}})):
            with self.assertRaises(ValueError):validate_skills([self.raw_task],[source])
        with self.assertRaises(ValueError):validate_skills([dict(self.raw_task,replay_origin=1)],self.policy['sources'])
        changed=copy.deepcopy(self.policy['sources']);changed[0]['input_fields']=['other'];changed[0]['persist_input_fields']=['other']
        self.assertNotEqual(self.tasks[0]['task_digest'],validate_skills([self.raw_task],changed)[0]['task_digest'])

    def test_replay_accepts_maximum_valid_snapshot_depth_in_transport(self):
        from skill_replay import evaluation_task
        value=0
        for _ in range(31):value=[value]
        self.fact.write_text(canonical({'observations':value}));obs=observe_sources(self.policy)[0]
        goal=self.ledger.create_goal({'source_id':'code-facts','contract_id':'result','domain':'code',
            'objective':'depth boundary','reason':'missing'},obs['revision'],self.policy['sources'][0]['contracts']['result'],
            {'verdict':False},1000,600,task_input=obs['task_input'])
        sub={'id':'origin','goal_id':goal['id'],'request':{'input':canonical({'task_input':goal['task_input']})}}
        evaluated=evaluation_task(self.tasks[0],goal,sub)
        self.assertEqual(evaluated['_evaluation_cases'][-1]['input'],{'observations':value})
        report=self.evaluate({'task':evaluated},lambda data:{'result':{'sum':6 if data['observations']==value else sum(data['observations'])}})
        self.assertIs(report['verdict'],True);self.assertEqual(report['passed'],4)

    def test_learning_prompt_excludes_original_data_and_recovers_without_regeneration(self):
        self.fact.write_text('{"observations":[-47,53]}'); self.attempt(); requests=[]; now=[1002]; active=[True]
        llm=SimpleNamespace(complete_structured=lambda **kw:requests.append(kw) or SimpleNamespace(parsed={'code':CODE}))
        evaluator=SimpleNamespace(locked=self.evaluator.locked,cleanup=lambda:True,
            evaluate=lambda *a:{'verdict':'unknown','cleanup_confirmed':False})
        learner=SkillLearner(self.store,llm,SimpleNamespace(take=lambda:True),evaluator,clock=lambda:now[0])
        learner.tick(1002,lambda:active[0]); self.assertEqual(len(requests),1)
        prompt=requests[0]['input'][0]['text']; self.assertNotIn('[-47,53]',prompt);self.assertNotIn('-47',prompt)
        self.assertNotIn('origin_replay',prompt); self.assertNotIn('holdout',prompt)
        self.assertEqual(self.store.summary()['states'],{'candidate':1})
        active[0]=False;now[0]=1063;learner.tick(1063,lambda:active[0]);self.assertEqual(len(requests),1)
        active[0]=True;evaluator.evaluate=lambda code,task,token,gate:self.evaluate({'task':task})
        learner.tick(1063,lambda:active[0]);self.assertEqual(len(requests),1)
        self.assertEqual(self.store.summary()['states'],{'active':1})


@unittest.skipUnless(os.environ.get('ZHULONG_SKILL_DOCKER_TESTS')=='1','explicit local Docker validation')
class RealReplayTests(unittest.TestCase):
    setUp=ReplayTests.setUp
    attempt=ReplayTests.attempt
    claim=ReplayTests.claim

    def run_code(self,job,code,gate=lambda:True):
        with self.evaluator.locked():
            report=self.evaluator.evaluate(code,job['task'],'b'*32,gate)
            self.assertTrue(self.evaluator.cleanup()); return report

    def test_actual_docker_original_failure_and_deduplicated_success(self):
        self.attempt();job=self.claim()
        wrong=CODE.replace('sum(x["observations"])','99 if x["observations"]==[2,4] else sum(x["observations"])')
        report=self.run_code(job,wrong);self.assertIs(report['verdict'],False);self.assertEqual(report['passed'],3)
        self.assertEqual(self.run_code(job,CODE)['passed'],4)
        self.fact.write_text('{"observations":[1,2,3]}');self.attempt();job=self.claim()
        self.assertEqual(self.run_code(job,CODE)['passed'],3)

    def test_actual_docker_closed_gate_keeps_unknown_without_publication(self):
        self.attempt();job=self.claim()
        report=self.run_code(job,CODE,lambda:False)
        self.assertEqual(report['verdict'],'unknown');self.assertTrue(report['cleanup_confirmed'])


if __name__=='__main__':unittest.main()
