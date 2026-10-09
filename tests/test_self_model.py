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

    def prepare(self,lease,now=1000):
        return self.ledger.prepare_submission(lease,{'input':'intent'},'session',
            {'api_url':'http://127.0.0.1:8642','credential_env':'API_SERVER_KEY','identity_version':'v1'},now,8,1,3,86400)['submission']

    def test_empty_model_is_unknown_and_refresh_is_stable(self):
        snapshot=self.model.refresh()
        self.assertEqual(snapshot['domains']['code']['verified_samples'],0)
        self.assertIsNone(snapshot['domains']['code']['accuracy'])
        self.assertEqual(self.model.expected_success('code'),0.5)
        self.assertEqual(self.model.refresh()['version'],snapshot['version'])

    def test_retry_final_success_is_one_sample(self):
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20)
        first=self.prepare(lease)
        self.ledger.record_attempt_result(lease,first['id'],evidence(goal,False),1001)
        self.ledger.transition(lease,'ready','safe retry',1001,True)
        second=self.prepare(lease,1002)
        self.ledger.record_attempt_result(lease,second['id'],evidence(goal,True),1003)
        self.ledger.finish(lease,evidence(goal,True),'succeeded',True,1003)
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
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20);self.prepare(lease)
        self.ledger.finish(lease,evidence(goal),'succeeded',True,1001)
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
        goal=make_goal(self.ledger);lease=self.ledger.claim('a',1000,20);self.prepare(lease)
        self.ledger.finish(lease,evidence(goal,False),'failed',True,1001)
        self.model.refresh()
        self.assertLess(self.model.expected_success('code'),before)
        self.assertEqual(self.model.expected_success('personal'),0.5)


if __name__=='__main__':unittest.main()
