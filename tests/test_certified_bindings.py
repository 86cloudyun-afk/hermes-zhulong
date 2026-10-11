"""Authority tests use real Controller, immutable inputs, and SQLite admission."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from autonomy_store import Ledger,canonical,digest
from autonomy_checks import validate_config,observe_sources,Verifier
from helpers import policy_config
from self_model import SelfModel
from test_autonomy import Planner,Runs
from test_certified_ticket import bundle,program


class CertifiedBindingsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('certified_bindings'),'certification authority missing')
        import certified_bindings
        from autonomy import Controller
        self.b=certified_bindings
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.raw=policy_config(self.root)
        source=self.raw['sources'][0];source.update(input_fields=['tickets'],persist_input_fields=['tickets'])
        source['contracts']['result']={'type':'json_reference','path':str(self.root/'result.json'),
            'reference_id':'ticket_priority_v1','reference_version':1,'program_bundle':bundle()}
        (self.root/'facts.json').write_text(canonical({'tickets':[{'id':'t','severity':4,'age_hours':100,'blocked':False}]}))
        self.policy=validate_config(self.raw,self.root);self.ledger=Ledger(self.root/'db')
        self.runs=Runs();self.controller=Controller(self.ledger,self.policy,Planner(),self.runs,Verifier(self.policy),SelfModel(self.ledger,self.root),clock=lambda:1000)
        self.identity=self.controller.execution_identity;self.obs=observe_sources(self.policy)[0]

    def goal(self,contract=None,revision=None):
        revision=revision or self.obs['revision'];snapshot=copy.deepcopy(self.obs['task_input']);snapshot['source_revision']=revision
        return self.ledger.create_goal({'source_id':'code-facts','contract_id':'result','domain':'code','objective':'tickets','reason':'missing','confidence':.5},
            revision,contract or self.policy['sources'][0]['contracts']['result'],{'verdict':False},1000,600,task_input=snapshot)

    def request(self,goal):return self.controller._request(goal)

    def prepare(self,g,request,identity=None,lease=None,**kwargs):
        lease=lease or self.ledger.claim('owner',1000,50,(g['id'],))
        return self.ledger.prepare_submission(lease,request,'session',self.identity if identity is None else identity,1000,2,1,2,86400,**kwargs)

    def snapshot(self):
        with self.ledger._connection() as c:
            return {table:[tuple(r) for r in c.execute('SELECT * FROM '+table)] for table in ('goals','submissions','run_budget','attempt_predictions')}

    def test_normalized_bundle_is_idempotent_bounded_and_ticket_only(self):
        from autonomy_checks import contract_policy
        contract=self.policy['sources'][0]['contracts']['result']
        self.assertEqual(contract_policy(contract,self.policy),contract)
        b=self.policy['sources'][0]['contracts']['result']['program_bundle']
        self.assertLessEqual(len(canonical(b).encode()),6000)
        for update in ({'reference_id':'workload_summary_v1'},{'reference_version':True},{'type':'file_contains','text':'ok'}):
            raw=copy.deepcopy(self.raw);raw['sources'][0]['contracts']['result'].update(update)
            with self.assertRaises(ValueError):validate_config(raw,self.root)
        raw=copy.deepcopy(self.raw);raw['sources'][0]['contracts']['result']['program_bundle']['verified']=True
        with self.assertRaises(ValueError):validate_config(raw,self.root)
        raw=copy.deepcopy(self.raw);raw['sources'][0]['persist_input_fields']=['other'];raw['sources'][0]['input_fields']=['other']
        with self.assertRaises(ValueError):validate_config(raw,self.root)

    def test_controller_request_single_bundle_bound_to_real_submission(self):
        g=self.goal();request=self.request(g);intent=json.loads(request['input'])
        self.assertNotIn('program_bundle',intent);self.assertIn('program_binding',intent)
        self.assertEqual(request['input'].count('"cells"'),1)
        metadata=intent['program_binding'];self.assertEqual(metadata['goal_id'],g['id'])
        self.assertEqual(metadata['execution_identity_hash'],digest(self.identity));self.assertNotIn('submission_id',metadata)
        self.assertLessEqual(len(request['input'].encode()),16384)
        result=self.prepare(g,request);self.assertTrue(result['admitted'],result)
        sub=result['submission'];self.assertEqual(sub['request'],request);self.assertEqual(sub['goal_id'],g['id'])
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM attempt_predictions').fetchone()[0],1)

    def test_tampering_or_omission_rejects_before_any_reservation(self):
        g=self.goal();lease=self.ledger.claim('owner',1000,50,(g['id'],));request=self.request(g)
        variants=[]
        for field in ('program_binding','acceptance_contract','task_input'):
            r=copy.deepcopy(request);intent=json.loads(r['input']);intent.pop(field);r['input']=canonical(intent);variants.append(r)
        for field in ('goal_id','contract_hash','input_hash','rule_hash','execution_identity_hash','checker_hash','source_revision'):
            r=copy.deepcopy(request);intent=json.loads(r['input']);intent['program_binding'][field]='forged';r['input']=canonical(intent);variants.append(r)
        r=copy.deepcopy(request);intent=json.loads(r['input']);intent['acceptance_contract']['program_bundle']['program']['score']=['int',0];r['input']=canonical(intent);variants.append(r)
        r=copy.deepcopy(request);intent=json.loads(r['input']);intent['task_input']['data']['tickets'][0]['severity']=5;r['input']=canonical(intent);variants.append(r)
        r=copy.deepcopy(request);r['session_id']='other';variants.append(r)
        r=copy.deepcopy(request);intent=json.loads(r['input']);intent['padding']='x'*16384;r['input']=canonical(intent);variants.append(r)
        for r in variants:
            before=self.snapshot();result=self.prepare(g,r,lease=lease)
            self.assertFalse(result['admitted'],result);self.assertEqual(before,self.snapshot())
        self.assertEqual(self.runs.calls,0)

    def test_direct_goal_cannot_downgrade_configured_certified_contract(self):
        contract=copy.deepcopy(self.policy['sources'][0]['contracts']['result']);contract.pop('program_bundle')
        g=self.goal(contract);request={'input':canonical({'task_input':g['task_input'],'acceptance_contract':contract}),'session_id':'zhulong-'+g['id']}
        self.assertFalse(self.prepare(g,request)['admitted']);self.assertEqual(self.ledger.get_goal(g['id'])['attempts'],0)

    def test_identity_missing_wrong_or_registry_drift_reject(self):
        g=self.goal();request=self.request(g);lease=self.ledger.claim('owner',1000,50,(g['id'],))
        for identity in ({},{**self.identity,'profile':'other'}):
            self.assertFalse(self.prepare(g,request,identity,lease)['admitted'])
        source=copy.deepcopy(self.policy['sources']);source[0]['contracts']['result']['program_bundle']['program']=program(True)
        self.b.configure(self.ledger,source,self.identity)
        self.assertFalse(self.prepare(g,request,lease=lease)['admitted'])
        self.b.configure(self.ledger,self.policy['sources'],{**self.identity,'profile':'new'})
        self.assertFalse(self.prepare(g,request,lease=lease)['admitted'])

    def test_checker_change_or_unavailability_fails_new_admission(self):
        import certified_ticket
        g=self.goal();request=self.request(g);lease=self.ledger.claim('owner',1000,50,(g['id'],))
        original=certified_ticket.verify_ticket_certificate
        def changed(*a,**kw):return {**original(*a,**kw),'checker_hash':'a'*64}
        with patch.object(certified_ticket,'verify_ticket_certificate',side_effect=changed):
            self.assertFalse(self.prepare(g,request,lease=lease)['admitted'])
        with patch.object(certified_ticket,'verify_ticket_certificate',return_value={'status':'unavailable'}):
            self.assertFalse(self.prepare(g,request,lease=lease)['admitted'])

    def test_reconciliation_and_cancellation_survive_unavailable_registry(self):
        g=self.goal();lease=self.ledger.claim('owner',1000,50,(g['id'],));sub=self.prepare(g,self.request(g),lease=lease)['submission']
        with self.ledger._connection(True) as c:c.execute("DELETE FROM settings WHERE key='certified_registry'")
        result=self.prepare(g,{'input':'{}'},lease=lease,expected_submission_id=sub['id'])
        self.assertEqual(result['reason'],'reconcile_existing');self.assertEqual(result['submission']['request'],sub['request'])
        self.ledger.request_cancel(g['id']);self.assertTrue(self.ledger.get_goal(g['id'])['cancel_requested'])

    def test_oversized_intent_is_not_truncated(self):
        from hermes_runs import RunsError
        g=self.goal();self.controller.policy['mission']='x'*16384
        with self.assertRaisesRegex(RunsError,'execution_intent_too_large'):self.request(g)

    def test_old_noncertified_contract_remains_compatible(self):
        contract=copy.deepcopy(self.policy['sources'][0]['contracts']['result']);contract.pop('program_bundle')
        sources=copy.deepcopy(self.policy['sources']);sources[0]['contracts']['result']=contract
        self.b.configure(self.ledger,sources,self.identity)
        self.controller.policy['sources']=sources
        g=self.goal(contract);request=self.request(g);self.assertNotIn('program_binding',json.loads(request['input']))
        self.assertTrue(self.prepare(g,request)['admitted'])

    def test_legacy_plain_text_request_remains_admissible(self):
        from helpers import make_goal
        other=Ledger(self.root/'legacy.db');g=make_goal(other)
        lease=other.claim('legacy',1000,50,(g['id'],))
        result=other.prepare_submission(lease,{'input':'ordinary text'},'s',{},1000,1,1,1,86400)
        self.assertTrue(result['admitted'],result)

    def test_gate_checks_exact_canonical_bytes_reserved_not_mutable_caller(self):
        import task_inputs
        g=self.goal();good=self.request(g);bad=copy.deepcopy(good)
        intent=json.loads(bad['input']);intent['program_binding']['input_hash']='forged';bad['input']=canonical(intent)
        original=task_inputs.valid_binding
        def mutate(c,goal,request):
            result=original(c,goal,request)
            request.update(good)
            return result
        with patch.object(task_inputs,'valid_binding',side_effect=mutate):
            result=self.prepare(g,bad)
        self.assertFalse(result['admitted'],result)
        self.assertEqual(self.ledger.get_goal(g['id'])['attempts'],0)

    def test_missing_registry_and_unsupported_workflow_fail_closed(self):
        g=self.goal();request=self.request(g)
        with self.ledger._connection(True) as c:c.execute("DELETE FROM settings WHERE key='certified_registry'")
        self.assertFalse(self.prepare(g,request)['admitted'])
        g['workflow']={'step_id':'child'}
        with self.assertRaisesRegex(ValueError,'certified_workflow_unsupported'):self.request(g)

    def test_valid_oversized_certificate_bundle_is_rejected_without_truncation(self):
        from autonomy_checks import contract_policy
        contract=copy.deepcopy(self.policy['sources'][0]['contracts']['result'])
        cells=contract['program_bundle']['certificate']['cells'];split=[]
        for cell in cells:
            cuts=[cell['lo']+(cell['hi']-cell['lo']+1)*i//4 for i in range(5)]
            split.extend(dict(cell,lo=lo,hi=end-1) for lo,end in zip(cuts,cuts[1:]))
        contract['program_bundle']['certificate']['cells']=split
        self.assertGreater(len(canonical(contract['program_bundle']).encode()),6000)
        with self.assertRaisesRegex(ValueError,'program_bundle_too_large'):contract_policy(contract,self.policy)

    def test_legacy_controller_source_without_contract_map_keeps_plain_request(self):
        from autonomy import Controller
        from helpers import make_goal
        ledger=Ledger(self.root/'minimal-policy.db');g=make_goal(ledger)
        policy={'mission':'legacy','sources':[{'id':'source-code','path':str(self.root/'facts.json')}],
                'workspace_roots':[str(self.root)]}
        controller=Controller(ledger,policy,None,None,None,None)
        intent=json.loads(controller._request(g)['input'])
        self.assertEqual(intent['acceptance_contract'],g['contract']);self.assertNotIn('program_binding',intent)
        # Replacing authority with a legacy policy cannot authorize an old
        # certified goal whose frozen contract still requires certification.
        certified=self.goal();request=self.request(certified)
        self.b.configure(self.ledger,policy['sources'],self.identity)
        self.assertFalse(self.prepare(certified,request)['admitted'])
