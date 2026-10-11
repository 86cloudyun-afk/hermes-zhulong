import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomy_store import Ledger
from helpers import evidence,make_goal


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('self_model'),'evidence-grounded model is missing')
        self.m=importlib.import_module('self_model')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ledger=Ledger(self.root/'data.db')
        self.model=self.m.SelfModel(self.ledger,self.root)

    def prepare(self,lease,now=1000,expected_submission_id=None):
        return self.ledger.prepare_submission(lease,{'input':'intent'},'session',
            {'api_url':'http://127.0.0.1:8642','credential_env':'API_SERVER_KEY','identity_version':'v1'},now,8,1,3,86400,
            expected_submission_id=expected_submission_id)['submission']

    def test_empty_model_is_unknown_and_refresh_is_stable(self):
        snapshot=self.model.refresh()
        self.assertEqual(snapshot['domains']['code']['verified_samples'],0)
        self.assertIsNone(snapshot['domains']['code']['accuracy'])
        self.assertEqual(self.model.expected_success('code'),0.5)
        self.assertEqual(self.model.refresh()['version'],snapshot['version'])

    def test_experience_export_revision_tracks_strategy_state(self):
        from experience_store import ExperienceStore
        store=ExperienceStore(self.ledger)
        self.model=self.m.SelfModel(self.ledger,self.root,experience=store)
        snapshot=self.model.refresh()
        self.assertEqual(snapshot['experience']['states'],{})
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20);submission=self.prepare(lease)
        self.ledger.record_admission(lease,submission['id'],'r','completed',1000)
        self.ledger.record_attempt_result(lease,submission['id'],evidence(goal,False),1001)
        self.ledger.finish(lease,evidence(goal,False),'failed',True,1001,expected_submission_id=submission['id'])
        store.sync(1002);job=store.claim(1002);store.begin(job,1002);store.complete(job,'A scoped lesson.',1003)
        changed=self.model.refresh()
        self.assertEqual(changed['experience']['states'],{'candidate':1})
        self.assertGreater(changed['version'],snapshot['version'])
        self.assertEqual(self.model.refresh()['version'],changed['version'])

    def test_retry_final_success_is_one_sample(self):
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20)
        first=self.prepare(lease)
        self.ledger.record_attempt_result(lease,first['id'],evidence(goal,False),1001)
        self.ledger.transition(lease,'ready','safe retry',1001,True,expected_submission_id=first['id'])
        second=self.prepare(lease,1002,expected_submission_id=first['id'])
        self.ledger.record_attempt_result(lease,second['id'],evidence(goal,True),1003)
        self.ledger.finish(lease,evidence(goal,True),'succeeded',True,1003,expected_submission_id=second['id'])
        snapshot=self.model.refresh();code=snapshot['domains']['code']
        self.assertEqual(code['verified_samples'],1)
        self.assertEqual(code['first_attempt_success'],0)
        self.assertEqual(code['eventual_success'],1)
        self.assertIsNone(code['confidence_on_error'])
        self.assertAlmostEqual(code['brier'],0.09)
        self.assertEqual(code['attempts']['verified_samples'],2)

    def test_unknown_and_existing_are_not_capability_samples(self):
        for i,state in enumerate(('unknown_result','blocked','already_satisfied')):
            goal=make_goal(self.ledger,domain='research',source_revision=str(i))
            lease=self.ledger.claim('owner',1000+i,20,ranked_goal_ids=(goal['id'],))
            self.ledger.finish(lease,evidence(goal,None),state,True,1000+i)
        stats=self.model.refresh()['domains']['research']
        self.assertEqual(stats['verified_samples'],0)
        self.assertEqual(stats['unknown'],1);self.assertEqual(stats['blocked'],1)

    def test_restore_preserves_evidence_and_export_is_rebuildable(self):
        initial=self.model.refresh()
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20);submission=self.prepare(lease)
        self.ledger.finish(lease,evidence(goal),'succeeded',True,1001,expected_submission_id=submission['id'])
        updated=self.model.refresh()
        self.assertGreater(updated['version'],initial['version'])
        self.model.restore(initial['version'])
        self.assertEqual(json.loads((self.root/'self_model.json').read_text())['version'],initial['version'])
        self.assertEqual(len(self.ledger.model_records()['evidence']),1)
        (self.root/'self_model.json').write_text('{broken')
        self.model.refresh()
        self.assertEqual(json.loads((self.root/'self_model.json').read_text())['version'],updated['version'])

    def test_verified_history_changes_choice_estimate(self):
        before=self.model.expected_success('code')
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20);submission=self.prepare(lease)
        self.ledger.finish(lease,evidence(goal,False),'failed',True,1001,expected_submission_id=submission['id'])
        self.model.refresh()
        self.assertLess(self.model.expected_success('code'),before)
        self.assertEqual(self.model.expected_success('personal'),0.5)


class MonitoringMetricTests(unittest.TestCase):
    def test_auroc_ties_reverse_and_single_class(self):
        from self_model import _metrics
        for samples,expected in (([(.9,True),(.1,False)],1),
                                 ([(.1,True),(.9,False)],0),
                                 ([(.5,True),(.5,False)],.5)):
            with self.subTest(samples=samples):
                result=_metrics(samples)
                self.assertEqual(result['auroc2'],expected)
                self.assertTrue(result['discrimination_available'])
                self.assertEqual(result['positive_samples'],1)
                self.assertEqual(result['negative_samples'],1)
        result=_metrics([(.8,True)])
        self.assertIsNone(result['auroc2'])
        self.assertFalse(result['discrimination_available'])
        self.assertEqual(result['error_discrimination'],'unavailable')

    def test_unknown_labels_are_excluded_from_coverage_and_risk(self):
        from self_model import _metrics
        result=_metrics([(.9,True),(.1,False),(.99,None),(None,False)])
        self.assertEqual(result['forecast_samples'],2)
        self.assertAlmostEqual(result['confidence_gap'],.8)
        row=next(row for row in result['coverage_risk'] if row['threshold']==.6)
        self.assertEqual(row['coverage'],.5)
        self.assertEqual(row['risk'],0)
        self.assertEqual(row['covered'],1)

    def test_bound_forecast_is_exported_with_scope_and_measured_cost(self):
        import metacognition
        from self_model import SelfModel
        with tempfile.TemporaryDirectory() as name:
            ledger=Ledger(Path(name)/'data.db');goal=make_goal(ledger)
            lease=ledger.claim('a',1000,20);identity={'version':'v1'};request={'input':json.dumps({'objective':'Work'})}
            policy=metacognition.validate_monitoring({'enabled':True,'mode':'constant','constant_probability':.7})
            with ledger._connection(True) as c:
                metacognition.initialize(c)
                captured=metacognition.capture(c,goal,identity,request,1000,policy)
            submission=ledger.prepare_submission(lease,request,'session',identity,1000,8,1,3,86400,
                                                monitoring_policy=policy,monitoring_capture=captured)['submission']
            before=SelfModel(ledger,Path(name)).refresh()
            ledger.record_attempt_result(lease,submission['id'],evidence(goal,True),1001)
            ledger.finish(lease,evidence(goal,True),'succeeded',True,1001,expected_submission_id=submission['id'])
            snapshot=SelfModel(ledger,Path(name)).refresh()
            self.assertGreater(snapshot['version'],before['version'])
            self.assertEqual(snapshot['functional_monitoring']['bound_predictions'],1)
            self.assertEqual(snapshot['functional_monitoring']['actual_extra_checks'],0)
            attempts=snapshot['domains']['code']['attempts']
            self.assertEqual(attempts['forecast_provenance'][0]['origin'],'trusted_constant')
            self.assertEqual(attempts['forecast_provenance'][0]['scope']['source_id'],goal['source_id'])
            self.assertAlmostEqual(attempts['brier'],.09)

    def test_self_model_reports_functional_monitoring_and_legacy_origin(self):
        from self_model import SelfModel
        with tempfile.TemporaryDirectory() as name:
            ledger=Ledger(Path(name)/'data.db');goal=make_goal(ledger)
            lease=ledger.claim('a',1000,20)
            submission=ledger.prepare_submission(lease,{'input':'intent'},'session',{'version':'v1'},
                                                1000,8,1,3,86400)['submission']
            # A pre-monitoring ledger contains submissions but no prediction side table.
            with ledger._connection(True) as c:c.execute('DROP TABLE attempt_predictions')
            ledger.record_attempt_result(lease,submission['id'],evidence(goal,True),1001)
            ledger.finish(lease,evidence(goal,True),'succeeded',True,1001,expected_submission_id=submission['id'])
            model=SelfModel(ledger,Path(name)).refresh()
            summary=model['functional_monitoring']
            self.assertEqual(summary['legacy_forecasts'],1)
            self.assertEqual(summary['bound_predictions'],0)
            provenance=model['domains']['code']['attempts']['forecast_provenance'][0]
            self.assertEqual(provenance['origin'],'goal_prior_reused_before_submission')
            self.assertNotIn('consciousness_score',model)


if __name__=='__main__':unittest.main()
