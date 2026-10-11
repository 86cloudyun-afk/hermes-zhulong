"""Controller/SQLite integration; native provider acceptance is a separate script."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_autonomy as fixtures
from autonomy_store import Ledger


class FrontiersIntegrationTests(unittest.TestCase):
    def setUp(self):fixtures.AutonomyTests.setUp(self)
    def build(self):return fixtures.AutonomyTests.build(self)

    def test_dag_executes_children_once_and_finalizes_without_parent_run(self):
        source=self.raw['sources'][0]
        source['contracts']={'final':dict(source['contracts']['result']),
            'prepare':{'type':'file_contains','path':str(self.root/'prepared.txt'),'text':'ready'},
            'deliver':dict(source['contracts']['result'])}
        self.raw['workflows']=[{'id':'deliver-report','source_id':source['id'],'contract_id':'final',
            'steps':[{'id':'prepare','contract_id':'prepare','objective':'Prepare ready marker','depends_on':[], 'effect_mode':'read_only'},
                     {'id':'deliver','contract_id':'deliver','objective':'Deliver report','depends_on':['prepare'],'effect_mode':'opaque_nonretryable'}]}]
        self.controller=self.build()
        for _ in range(8):self.controller.tick();self.now[0]+=1
        parents=[g for g in self.ledger.goals() if g['contract_id']=='final']
        self.assertEqual(len(parents),1)
        self.assertEqual(parents[0]['state'],'succeeded')
        self.assertIsNone(parents[0]['submission'])
        self.assertEqual(self.runs.calls,2)
        self.controller=self.build()
        self.controller.tick()
        self.assertEqual(self.runs.calls,2)

    def test_attempt_monitor_is_frozen_before_native_submission_and_replay(self):
        self.raw['monitoring']={'enabled':True,'mode':'normal','threshold':0.6,'max_rechecks':1}
        self.controller=self.build();self.runs.lose=True
        self.controller.tick()
        goal=self.ledger.goals()[0];submission=goal['submission']
        intent=json.loads(submission['request']['input'])
        self.assertEqual(intent['functional_monitoring']['action'],'recheck')
        with self.ledger._connection() as c:
            prediction=c.execute('SELECT * FROM attempt_predictions WHERE submission_id=?',(submission['id'],)).fetchone()
            self.assertIsNotNone(prediction)
        frozen=submission['request']
        self.now[0]+=1;self.controller=self.build();self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['submission']['request'],frozen)
        self.assertEqual(self.runs.calls,1)

    def test_json_reference_uses_frozen_business_input_after_source_change(self):
        from autonomy_checks import observe_sources,Verifier,validate_config
        from work_reference import reference_output
        source=self.raw['sources'][0]
        source.update(input_fields=['tasks'],persist_input_fields=['tasks'])
        source['contracts']={'result':{'type':'json_reference','path':str(self.root/'result.json'),
                                      'reference_id':'workload_summary_v1','reference_version':1}}
        data={'tasks':[{'id':'a','team':'ops','minutes':13,'done':False}]}
        (self.root/'facts.json').write_text(json.dumps(data))
        policy=validate_config(self.raw,self.root);snapshot=observe_sources(policy)[0]['task_input']
        (self.root/'facts.json').write_text('{"tasks":[]}')
        (self.root/'result.json').write_text(json.dumps(reference_output('workload_summary_v1',data)))
        checked=Verifier(policy).capture(source['contracts']['result'],snapshot)
        self.assertIs(checked['verdict'],True)
        self.assertEqual(checked['input_hash'],snapshot['input_hash'])

    def test_trusted_outcome_timestamps_are_not_inferred_for_legacy_rows(self):
        self.controller.tick();self.now[0]+=1;self.controller.tick()
        submission=self.ledger.goals()[0]['submission']
        self.assertEqual(submission['evidence_created'],self.now[0])
        self.assertEqual(submission['settled_at'],self.now[0])
        with self.ledger._connection(True) as c:
            c.execute('UPDATE submissions SET evidence_created=NULL,settled_at=NULL')
        migrated=Ledger(self.ledger.path)
        self.assertIsNone(migrated.goals()[0]['submission']['evidence_created'])
        self.assertIsNone(migrated.goals()[0]['submission']['settled_at'])

    def test_public_assurance_runs_and_reports_real_implementation_trace(self):
        self.controller.tick();self.now[0]+=1;self.controller.tick()
        result=self.controller.assurance_status(run=True)
        self.assertTrue(result['implementation_trace']['valid'])
        self.assertIsNone(result['bounded_model']['counterexample'])
        self.assertGreater(result['bounded_model']['states'],0)

    def test_cancel_stops_verified_but_unsettled_execution(self):
        self.controller.tick()
        (self.root/'result.txt').write_text('done')
        self.runs.run_state='interrupted';self.now[0]+=1;self.controller.tick()
        goal=self.ledger.goals()[0]
        self.assertEqual(goal['state'],'succeeded')
        self.assertFalse(goal['submission']['settled'])
        stopped=[]
        self.runs.stop=lambda submission:stopped.append(submission['id'])
        self.controller.cancel(goal['id']);self.now[0]+=1;self.controller.tick()
        self.assertEqual(stopped,[goal['submission']['id']])
        self.assertEqual(self.ledger.get_goal(goal['id'])['state'],'succeeded')
        self.assertFalse(self.ledger.get_goal(goal['id'])['submission']['settled'])

    def test_state_transition_cannot_forge_verified_truth(self):
        self.controller.tick();goal=self.ledger.goals()[0]
        lease=self.ledger.claim('untrusted-terminal',self.now[0],30,(goal['id'],))
        self.assertTrue(self.ledger.transition(lease,'unknown_result','response uncertain',self.now[0],False,
            expected_submission_id=goal['submission']['id']))
        for state in ('failed','succeeded'):
            with self.subTest(state=state),self.assertRaises(ValueError):
                self.ledger.transition(lease,state,'unverified assertion',self.now[0],False,
                    expected_submission_id=goal['submission']['id'])
        self.assertEqual(self.ledger.get_goal(goal['id'])['state'],'unknown_result')

    def test_removed_diagnosis_config_keeps_unresolved_cleanup_gate(self):
        import test_diagnostics as diagnostic_fixture
        from autonomy import Controller
        from autonomy_checks import Verifier
        from self_model import SelfModel
        original=diagnostic_fixture.DiagnosticTests();original.setUp();self.addCleanup(original.doCleanups)
        original.origin()
        with patch.object(original.evaluator,'cleanup',return_value=False):original.runner.tick(1005,lambda:True)
        self.assertTrue(original.store.requires_quiescence())
        original.fixture.fact.write_text('{"observations":[7,8]}')
        runs=fixtures.Runs();model=SelfModel(original.ledger,original.fixture.root)
        policy={**original.policy,'diagnostics':[]}
        restarted=Controller(original.ledger,policy,fixtures.Planner(),runs,Verifier(policy),model,clock=lambda:1006)
        with patch('skill_evaluator.DockerEvaluator.cleanup',return_value=False):restarted.tick()
        self.assertEqual(runs.calls,0)
        self.assertTrue(restarted.diagnostics.store.requires_quiescence())


if __name__=='__main__':unittest.main()
