import copy
import importlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_checks import validate_config
from autonomy_store import Ledger, canonical, digest
import task_inputs
from helpers import policy_config


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('workflow'), 'durable workflow module is missing')
        self.w = importlib.import_module('workflow')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = policy_config(self.root)
        source = raw['sources'][0]
        source['input_fields'] = ['report']; source['persist_input_fields'] = ['report']
        source['contracts']['draft'] = {'type':'file_contains', 'path':str(self.root/'draft.txt'), 'text':'draft', 'require_change':True, 'safe_retry':True}
        source['contracts']['review'] = {'type':'file_contains', 'path':str(self.root/'review.txt'), 'text':'review', 'require_change':True}
        self.policy = validate_config(raw, self.root)
        self.raw = [{'id':'report-work', 'source_id':'code-facts', 'contract_id':'result', 'steps':[
            {'id':'draft', 'contract_id':'draft', 'objective':'Prepare draft', 'depends_on':[], 'effect_mode':'read_only'},
            {'id':'review', 'contract_id':'review', 'objective':'Review draft', 'depends_on':['draft'], 'effect_mode':'opaque_nonretryable'}]}]
        self.ledger = Ledger(self.root/'ledger.db')
        task_inputs.configure(self.ledger, self.policy['sources'], 65536)
        source = self.policy['sources'][0]
        snapshot = task_inputs.project(source, {'report':{'items':[1,2]}})
        self.snapshot = snapshot | {'source_revision':'original-r1'}
        self.parent = self.ledger.create_goal({'source_id':source['id'], 'domain':'code', 'contract_id':'result',
            'objective':'Create report', 'reason':'Missing report', 'confidence':.7, 'expected_benefit':.5},
            'original-r1', source['contracts']['result'], {'verdict':False, 'artifact_hash':None}, 1000, 600,
            task_input=self.snapshot)
        self.store = self.w.WorkflowStore(self.ledger, self.w.validate_workflows(self.raw, self.policy))
        self.store.capture = lambda contract, task_input=None: {'verdict':False, 'artifact_hash':None}

    def create_child(self):
        self.store.sync(1000)
        return self.store.advance(1001, lambda: True)['created']

    def settle(self, goal_id, state='succeeded', settled=True):
        with self.ledger._connection(True) as c:
            goal = self.ledger._goal(c, c.execute('SELECT * FROM goals WHERE id=?', (goal_id,)).fetchone())
            lease = None
            sid = 'submission-'+goal_id
            c.execute('INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds,settled) VALUES(?,?,?,?,?,?,?,?,?)',
                      (sid,goal_id,1,'{}','session','{}',1002,3600,int(settled)))
            c.execute('UPDATE goals SET state=?,attempts=1,submission_id=? WHERE id=?', (state,sid,goal_id))
            if state == 'succeeded':
                evidence = {'verdict':True,'contract_hash':goal['contract_hash'],'artifact_hash':'actual','reason':'test_verified'}
                c.execute('INSERT INTO evidence(goal_id,receipt,outcome,data,created) VALUES(?,?,?,?,?)', (goal_id,digest(evidence),'succeeded',canonical(evidence),1002))

    def test_rejects_cycles_oversize_foreign_contracts_and_duplicate_parents(self):
        variants=[]
        bad=copy.deepcopy(self.raw); bad[0]['steps'][0]['depends_on']=['review']; variants.append(bad)
        bad=copy.deepcopy(self.raw); bad[0]['steps'][0]['depends_on']=['missing']; variants.append(bad)
        bad=copy.deepcopy(self.raw); bad[0]['steps'][0]['contract_id']='foreign'; variants.append(bad)
        bad=copy.deepcopy(self.raw); bad[0]['steps']*=5; variants.append(bad)
        variants.append(self.raw*2)
        bad=copy.deepcopy(self.raw); bad[0]['steps'][0]['effect_mode']='exactly_once_remote'; variants.append(bad)
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):self.w.validate_workflows(variant,self.policy)

    def test_child_atomic_binding_and_distinct_root_dedupe(self):
        root=self.ledger.create_goal(self.parent['candidate'] | {'contract_id':'draft'},'original-r1',
            self.policy['sources'][0]['contracts']['draft'],{'verdict':False},1000,600,task_input=self.snapshot)
        child=self.create_child()
        self.assertNotEqual(child,root['id'])
        with self.ledger._connection() as c:
            binding=self.w.binding(c,child)
        self.assertEqual(binding['workflow']['parent_id'],self.parent['id'])
        self.assertEqual(binding['workflow']['step_id'],'draft')
        self.assertEqual(self.ledger.get_goal(child)['task_input'],self.snapshot)
        self.assertFalse(self.store.dispatchable(self.parent['id']))
        self.assertTrue(self.store.dispatchable(child))

    def test_failed_child_binding_rolls_back_goal_and_input(self):
        self.store.sync(1000)
        with self.ledger._connection(True) as c:
            c.execute("CREATE TRIGGER fail_child BEFORE INSERT ON workflow_steps WHEN NEW.child_goal_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'injected_bind_crash'); END")
            c.execute("CREATE TRIGGER fail_child_update BEFORE UPDATE OF child_goal_id ON workflow_steps WHEN NEW.child_goal_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'injected_bind_crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.advance(1001,lambda:True)
        self.assertEqual(len(self.ledger.goals()),1)
        self.assertEqual(task_inputs.summary(self.ledger)['stored'],1)

    def test_pause_and_gate_prevent_child_creation(self):
        self.store.sync(1000); self.ledger.set_pause(True)
        self.assertIsNone(self.store.advance(1001,lambda:True)['created'])
        self.ledger.set_pause(False)
        self.assertIsNone(self.store.advance(1001,lambda:False)['created'])
        self.assertIsNotNone(self.store.advance(1001,lambda:True)['created'])

    def test_restart_reuses_child_and_completed_dependency(self):
        child=self.create_child(); operation=self.store.operation_id(child)
        restarted=self.w.WorkflowStore(self.ledger,self.w.validate_workflows(self.raw,self.policy))
        restarted.capture=self.store.capture; restarted.sync(1002)
        self.assertIsNone(restarted.advance(1002,lambda:True)['created'])
        self.assertEqual(restarted.operation_id(child),operation)
        self.settle(child)
        next_child=restarted.advance(1003,lambda:True)['created']
        self.assertIsNotNone(next_child); self.assertNotEqual(next_child,child)
        self.assertEqual(len(self.ledger.goals()),3)
        self.settle(next_child)
        self.assertEqual(restarted.advance(1004,lambda:True)['finalizable'],[self.parent['id']])
        self.assertEqual(restarted.advance(1005,lambda:True)['finalizable'],[self.parent['id']])
        self.assertEqual(len(self.ledger.goals()),3)

    def test_changed_manifest_does_not_rewrite_original_plan(self):
        child=self.create_child()
        changed=copy.deepcopy(self.raw); changed[0]['steps'][1]['objective']='Changed objective'
        changed[0]['steps'][1]['contract_id']='draft'
        restarted=self.w.WorkflowStore(self.ledger,self.w.validate_workflows(changed,self.policy)); restarted.capture=self.store.capture
        restarted.sync(1002); self.settle(child)
        next_child=restarted.advance(1003,lambda:True)['created']
        self.assertEqual(self.ledger.get_goal(next_child)['objective'],'Review draft')
        self.assertEqual(self.ledger.get_goal(next_child)['source_revision'],'original-r1')
        self.assertEqual(self.ledger.get_goal(next_child)['task_input'],self.snapshot)
        with self.ledger._connection(True) as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE workflows SET plan='{}'")
            with self.assertRaises(sqlite3.IntegrityError):c.execute("DELETE FROM workflow_steps")

    def test_unsettled_success_and_failed_dependency_never_unlock_next_step(self):
        child=self.create_child(); self.settle(child,settled=False)
        result=self.store.advance(1003,lambda:True)
        self.assertIsNone(result['created']); self.assertEqual(result['finalizable'],[])
        with self.ledger._connection(True) as c:c.execute('UPDATE submissions SET settled=1 WHERE goal_id=?',(child,));c.execute("UPDATE goals SET state='failed' WHERE id=?",(child,))
        self.assertIsNone(self.store.advance(1004,lambda:True)['created'])
        self.assertIn('dependency_failed',canonical(self.store.summary()))

    def test_opaque_effect_cannot_retry_and_unknown_is_visible(self):
        raw=copy.deepcopy(self.raw); raw[0]['steps'][0]['effect_mode']='opaque_nonretryable'
        self.store=self.w.WorkflowStore(self.ledger,self.w.validate_workflows(raw,self.policy));self.store.capture=lambda *a: {'verdict':False}
        child=self.create_child(); self.settle(child,state='unknown_result',settled=False)
        self.assertFalse(self.store.retry_allowed(child))
        self.assertFalse(self.store.dispatchable(child))
        self.assertIn('unknown_remote_effects',canonical(self.store.summary()))
        with self.ledger._connection(True) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds) VALUES(?,?,?,?,?,?,?,?)',('illegal-retry',child,2,'{}','s','{}',1003,3600))

    def test_local_outbox_deduplicates_intent_and_refuses_conflict(self):
        raw=copy.deepcopy(self.raw); raw[0]['steps'][0]['effect_mode']='local_outbox'
        self.store=self.w.WorkflowStore(self.ledger,self.w.validate_workflows(raw,self.policy));self.store.capture=lambda *a: {'verdict':False}
        child=self.create_child(); operation=self.store.operation_id(child)
        receipt=self.store.record_effect(operation, {'recipient':'local', 'message':'ready'},1002)
        again=self.store.record_effect(operation, {'message':'ready','recipient':'local'},1003)
        self.assertEqual(receipt,again); self.assertEqual(receipt['status'],'recorded_local')
        self.assertFalse(receipt['delivered'])
        with self.assertRaisesRegex(ValueError,'effect_intent_conflict'):self.store.record_effect(operation,{'message':'changed'},1004)
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_outbox').fetchone()[0],1)
        self.assertEqual(self.store.operation_id(child),operation)

    def test_effect_record_requires_known_operation_and_valid_current_lease(self):
        child=self.create_child(); lease=self.ledger.claim('worker',1002,30,(child,))
        with self.assertRaisesRegex(ValueError,'unknown_operation'):self.store.record_effect('invented',{},1003)
        with self.assertRaisesRegex(ValueError,'stale_lease'):self.store.record_effect(self.store.operation_id(child),{},1033,lease=lease)
        self.assertEqual(self.store.summary()['outbox']['records'],0)

    def test_parent_reports_blocked_failure_without_creating_dependent(self):
        child=self.create_child();self.settle(child,state='failed')
        self.store.advance(1003,lambda:True)
        parent=self.ledger.get_goal(self.parent['id'])
        self.assertEqual(parent['state'],'blocked')
        self.assertEqual(parent['recovery_reason'],'workflow_dependency_failed')
        self.assertFalse(self.store.dispatchable(parent['id']))

    def test_success_without_mechanical_evidence_never_completes_workflow(self):
        child=self.create_child()
        with self.ledger._connection(True) as c:c.execute("UPDATE goals SET state='succeeded' WHERE id=?",(child,))
        self.assertIsNone(self.store.advance(1003,lambda:True)['created'])
        self.assertEqual(self.store.advance(1004,lambda:True)['finalizable'],[])

    def test_outbox_failure_rolls_back_effect_receipt(self):
        raw=copy.deepcopy(self.raw);raw[0]['steps'][0]['effect_mode']='local_outbox'
        self.store=self.w.WorkflowStore(self.ledger,self.w.validate_workflows(raw,self.policy));self.store.capture=lambda *a: {'verdict':False}
        child=self.create_child()
        with self.ledger._connection(True) as c:
            c.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON workflow_outbox BEGIN SELECT RAISE(ABORT,'injected_outbox_crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.record_effect(self.store.operation_id(child),{'message':'ready'},1002)
        with self.ledger._connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_effects').fetchone()[0],0)

    def test_opaque_late_acceptance_preserves_first_effect_observation(self):
        raw=copy.deepcopy(self.raw);raw[0]['steps'][0]['effect_mode']='opaque_nonretryable'
        self.store=self.w.WorkflowStore(self.ledger,self.w.validate_workflows(raw,self.policy));self.store.capture=lambda *a: {'verdict':False}
        child=self.create_child();self.settle(child,state='unknown_result',settled=True)
        self.store.advance(1003,lambda:False)
        with self.ledger._connection() as c:
            before=dict(c.execute('SELECT * FROM workflow_effects').fetchone())
        with self.ledger._connection(True) as c:
            goal=self.ledger._goal(c,c.execute('SELECT * FROM goals WHERE id=?',(child,)).fetchone())
            receipt={'verdict':True,'contract_hash':goal['contract_hash'],'artifact_hash':'late-actual','reason':'late_verified'}
            c.execute("UPDATE goals SET state='succeeded' WHERE id=?",(child,))
            c.execute('INSERT INTO evidence(goal_id,receipt,outcome,data,created) VALUES(?,?,?,?,?)',(child,digest(receipt),'succeeded',canonical(receipt),1004))
        try:self.store.advance(1005,lambda:False)
        except ValueError as exc:self.fail('Late acceptance must preserve the existing observation: '+str(exc))
        with self.ledger._connection() as c:self.assertEqual(dict(c.execute('SELECT * FROM workflow_effects').fetchone()),before)

    def test_baseline_capture_does_not_block_unrelated_submission_admission(self):
        self.store.sync(1000)
        unrelated=self.ledger.create_goal(self.parent['candidate'] | {'source_id':'unrelated-source'},'r-other',
            {'type':'file_contains','path':str(self.root/'other.txt'),'text':'other'}, {'verdict':False},1000,600)
        lease=self.ledger.claim('other-worker',1001,30,(unrelated['id'],))
        entered,release,admitted=threading.Event(),threading.Event(),threading.Event()
        failures=[]
        def capture(*args):entered.set();release.wait(5);return {'verdict':False}
        self.store.capture=capture
        def advance():
            try:self.store.advance(1002,lambda:True)
            except Exception as exc:failures.append(exc)
        def prepare():
            try:
                result=self.ledger.prepare_submission(lease,{'input':'{}'},'other-session',{},1002,10,2,2,3600)
                if result['admitted']:admitted.set()
                else:failures.append(result)
            except Exception as exc:failures.append(exc)
        first=threading.Thread(target=advance);first.start()
        self.assertTrue(entered.wait(1))
        second=threading.Thread(target=prepare);second.start()
        try:self.assertTrue(admitted.wait(2),'Baseline verification must not hold the SQLite write lock')
        finally:release.set();first.join(3);second.join(3)
        self.assertEqual(failures,[])

    def test_pause_during_baseline_capture_prevents_binding(self):
        self.store.sync(1000)
        def capture(*args):self.ledger.set_pause(True);return {'verdict':False}
        self.store.capture=capture
        self.assertIsNone(self.store.advance(1002,lambda:True)['created'])
        self.assertEqual(len(self.ledger.goals()),1)

    def test_parent_cancel_reaches_active_child_without_claiming_quiescence(self):
        child=self.create_child();self.settle(child,state='running',settled=False)
        self.ledger.request_cancel(self.parent['id'])
        self.store.advance(1003,lambda:True)
        parent=self.ledger.get_goal(self.parent['id']);active=self.ledger.get_goal(child)
        self.assertEqual(parent['state'],'cancelled')
        self.assertTrue(active['cancel_requested'])
        self.assertFalse(active['submission']['settled'])
        self.assertFalse(self.store.dispatchable(child))
        self.assertIn('children_pending',parent['recovery_reason'])

    def test_parent_submission_rejected_even_before_child_work(self):
        self.store.sync(1000)
        with self.ledger._connection(True) as c:
            self.assertEqual(self.w.admission_reason(c,self.parent['id']),'workflow_parent')
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds) VALUES(?,?,?,?,?,?,?,?)',('bad-parent',self.parent['id'],1,'{}','s','{}',1001,3600))


class WorkflowControllerTests(unittest.TestCase):
    def setUp(self):
        import test_autonomy as fixtures
        self.fixtures=fixtures
        fixtures.AutonomyTests.setUp(self)

    def build(self):
        return self.fixtures.AutonomyTests.build(self)

    def workflow(self, mode):
        source=self.raw['sources'][0]
        contract=source['contracts']['result']
        source['contracts']={'final':copy.deepcopy(contract),'produce':copy.deepcopy(contract)}
        self.raw['workflows']=[{'id':'produce-report','source_id':source['id'],'contract_id':'final',
            'steps':[{'id':'produce','contract_id':'produce','objective':'Produce verified report',
                      'depends_on':[],'effect_mode':mode}]}]
        self.controller=self.build()

    def test_controller_records_local_outbox_after_verified_settlement_once(self):
        self.workflow('local_outbox')
        self.controller.tick()
        self.assertEqual(self.controller.workflows.summary()['outbox']['records'],0)
        self.now[0]+=1;self.controller.tick()
        with self.ledger._connection() as c:
            rows=c.execute('SELECT * FROM workflow_outbox').fetchall()
            self.assertEqual(len(rows),1,'Controller must persist the configured local outbox effect')
            effect=c.execute('SELECT * FROM workflow_effects').fetchone()
            intent=json.loads(effect['intent']);receipt=json.loads(effect['receipt'])
            self.assertEqual(receipt['status'],'recorded_local');self.assertFalse(receipt['delivered'])
            self.assertEqual(intent['notification'],'verified_workflow_step')
            self.assertEqual(intent['artifact_hash'],c.execute("SELECT json_extract(data,'$.artifact_hash') FROM evidence WHERE goal_id=? AND outcome='succeeded'",(intent['child_goal_id'],)).fetchone()[0])
            self.assertEqual(intent['receipt_hash'],c.execute("SELECT receipt FROM evidence WHERE goal_id=? AND outcome='succeeded'",(intent['child_goal_id'],)).fetchone()[0])
            self.assertNotIn('data',intent)
            import assurance
            trace=assurance.validate_trace(c)
            self.assertTrue(trace['valid'],trace.get('counterexample'))
            original=dict(rows[0])
        self.controller=self.build()
        for _ in range(3):self.now[0]+=1;self.controller.tick()
        with self.ledger._connection() as c:
            self.assertEqual([dict(row) for row in c.execute('SELECT * FROM workflow_outbox')],[original])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_effects').fetchone()[0],1)
        self.assertEqual(self.runs.calls,1)

    def test_controller_opaque_effect_receipt_is_unknown_with_no_delivery(self):
        self.workflow('opaque_nonretryable')
        self.controller.tick();self.now[0]+=1;self.controller.tick()
        with self.ledger._connection() as c:
            effects=c.execute('SELECT * FROM workflow_effects').fetchall()
            self.assertEqual(len(effects),1,'settled opaque attempt must have an actual effect receipt')
            receipt=json.loads(effects[0]['receipt'])
            self.assertEqual(receipt['status'],'unknown_remote_effects');self.assertFalse(receipt['delivered'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_outbox').fetchone()[0],0)

    def test_cancelling_finished_workflow_preserves_verified_parent_truth(self):
        self.workflow('read_only')
        self.controller.tick();self.now[0]+=1;self.controller.tick()
        parent=next(goal for goal in self.ledger.goals() if goal['contract_id']=='final')
        self.assertEqual(parent['state'],'succeeded')
        self.ledger.request_cancel(parent['id'])
        self.now[0]+=1;self.controller.tick()
        self.assertEqual(self.ledger.get_goal(parent['id'])['state'],'succeeded')

    def test_pending_child_settles_after_parent_cancel_without_submission_or_cost(self):
        from autonomy_checks import observe_sources
        self.workflow('local_outbox')
        self.controller._synthesize(observe_sources(self.controller.policy))
        self.controller.workflows.sync(self.now[0])
        child_id=self.controller.workflows.advance(self.now[0],lambda:True)['created']
        child=self.ledger.get_goal(child_id)
        self.assertEqual(child['state'],'ready');self.assertIsNone(child['submission'])
        self.controller.cancel(child['workflow']['parent_id'])
        self.now[0]+=1;self.controller.tick()
        child=self.ledger.get_goal(child_id)
        self.assertEqual(child['state'],'cancelled')
        self.assertEqual(child['attempts'],0);self.assertIsNone(child['submission'])
        self.assertEqual(self.runs.calls,0)
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COALESCE(SUM(runs),0) FROM run_budget').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_effects').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_outbox').fetchone()[0],0)

    def test_controller_unverified_local_step_creates_no_outbox_notification(self):
        self.workflow('local_outbox');self.runs.complete_artifact=False
        self.controller.tick();self.now[0]+=1;self.controller.tick()
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_outbox').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_effects').fetchone()[0],0)


if __name__=='__main__':unittest.main()
