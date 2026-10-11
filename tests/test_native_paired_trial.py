"""Provider-free paired adapter tests; local artifacts are explicit test fixtures."""
import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from autonomy_store import canonical,digest
from test_cohort import Clock

HOST=Path('/workspace/.cloud-onboarding/dependencies/hermes-agent')
IMAGE='python:3.11-slim@sha256:'+'a'*64


class PairedTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('native_trial'),'paired native adapter missing')
        import native_trial
        self.m=native_trial;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.clock=Clock()
        self.fixture={'id':'empty-work','reference_id':'workload_summary_v1','data':{'tasks':[]}}
        self.expected={'task_count':0,'total_minutes':0,'open_minutes':0,'teams':[]}
        self.oracle=self.root/'oracle.json'
        self.oracle.write_text(canonical({'schema':1,'written_utc':'2026-10-11T00:00:00Z','method':'Independent hand-authored empty business case','fixtures':[dict(id=self.fixture['id'],reference_id=self.fixture['reference_id'],input_hash=digest(self.fixture['data']),expected=self.expected,expected_hash=digest(self.expected))]}))
    def freeze(self):
        return self.m.FrozenTrial.freeze(self.root/'trial',host=HOST,image=IMAGE,oracle=self.oracle,fixtures=[self.fixture])
    def test_freeze_is_provider_free_exact_ledger_schedule_and_explicit_one_factor(self):
        with patch('scripts.native_work_acceptance.create_deployment',side_effect=AssertionError('deployment during freeze')),patch('work_reference.reference_output',side_effect=AssertionError('shared oracle')):
            trial=self.freeze();r=trial.summary()
        self.assertEqual(r['allocated'],2);self.assertEqual(r['unrun'],2)
        self.assertEqual(r['protocol']['control_arm'],'planner_masked')
        self.assertEqual(r['estimand'],'planner_visible minus planner_masked')
        controls=trial.protocol['declared_controls'][self.fixture['id']]
        a=copy.deepcopy(controls['planner_masked']);b=copy.deepcopy(controls['planner_visible'])
        self.assertTrue(a['policy']['monitoring']['enabled']);self.assertEqual(a['policy']['cognition']['mask_consumer'],'planner')
        a['policy']['cognition']['mask_consumer']=None;self.assertEqual(a,b)
        self.assertFalse(r['causal_gain_supported'])
        from causal_trial import TrialLedger
        self.assertEqual(trial.allocations,TrialLedger(trial.root/'trial.db').preregister(trial.protocol))
    def test_changed_oracle_input_protocol_and_arm_manifest_rejected(self):
        trial=self.freeze()
        for name in ('oracle.json','protocol.json','inputs/empty-work.json'):
            path=trial.root/name;before=path.read_bytes();path.write_bytes(before+b' ')
            with self.assertRaises(ValueError):self.m.FrozenTrial(trial.root)
            path.write_bytes(before)
    def test_strict_fixture_and_oracle_scope_do_not_trust_hash_strings(self):
        for change in ({'id':'../escape'},{'data':{'tasks':[{'id':'x','team':'a','minutes':True,'done':False}]}},{'data':{'tasks':[]},'extra':True}):
            with self.subTest(change=change):
                f=dict(self.fixture,**change)
                with self.assertRaises(ValueError):self.m.FrozenTrial.freeze(self.root/'bad',host=HOST,image=IMAGE,oracle=self.oracle,fixtures=[f])
        o=json.loads(self.oracle.read_text());o['fixtures'][0]['expected_hash']='a'*64;self.oracle.write_text(canonical(o))
        with self.assertRaises(ValueError):self.freeze()
    def test_actual_config_and_manifest_omission_reject_even_if_hash_is_recomputed(self):
        trial=self.freeze();allocation=trial.allocations[0];prepared=trial.prepare(allocation['id'])
        self.assertTrue(trial.inspect_controls(allocation['id'])['qualified'])
        config=Path(prepared['manifest']).parent/'profile/config.yaml';mfile=Path(prepared['manifest']);before=config.read_bytes();mbefore=mfile.read_bytes()
        data=json.loads(before);data['terminal']['docker_network']=True;config.write_text(canonical(data))
        m=json.loads(mbefore);m['hashes'][str(config)]=self.m.file_sha(config);mfile.write_text(canonical(m))
        with self.assertRaises(ValueError):trial.inspect_controls(allocation['id'])
        config.write_bytes(before);mfile.write_bytes(mbefore)
        m=json.loads(mbefore);m['hashes'].pop(str(config));mfile.write_text(canonical(m))
        with self.assertRaises(ValueError):trial.inspect_controls(allocation['id'])
    def test_typed_normalization_keeps_unrelated_strings_and_rejects_wrong_bindings(self):
        trial=self.freeze();a=trial.allocations[0];p=trial.prepare(a['id']);manifest=json.loads(Path(p['manifest']).read_text())
        from autonomy_checks import validate_config
        raw=json.loads((Path(manifest['root'])/'profile/zhulong/config.json').read_text())['autonomy']
        policy=validate_config(raw,Path(manifest['root'])/'profile/zhulong')
        normalized=self.m.normalize_policy(policy,manifest)
        self.assertEqual(normalized['workspace_roots'],['@work'])
        changed=copy.deepcopy(policy);changed['mission']+=' '+manifest['work'];n=self.m.normalize_policy(changed,manifest)
        self.assertIn(manifest['work'],n['mission'])
        changed=copy.deepcopy(policy);changed['api_url']='http://127.0.0.1:9999'
        with self.assertRaises(ValueError):self.m.normalize_policy(changed,manifest)
    def test_one_deadline_slow_phase_overrun_and_resume_do_not_refill(self):
        d=self.m.Deadline.start(180,clock=self.clock);origin=copy.deepcopy(d.origin)
        self.clock.advance(70);self.assertEqual(d.remaining(),110)
        resumed=self.m.Deadline(origin,180,clock=self.clock);self.assertEqual(resumed.remaining(),110)
        with self.assertRaises(TimeoutError):resumed.call(lambda timeout:self.clock.advance(timeout+1))
        self.assertEqual(resumed.remaining(),0)
    def test_boot_or_clock_rollback_invalidates_deadline(self):
        for change in ('boot','wall'):
            self.clock=Clock();d=self.m.Deadline.start(180,clock=self.clock)
            if change=='boot':self.clock.boot='other'
            else:self.clock.utc-=10
            with self.assertRaises(ValueError):d.remaining()
    def test_durable_launch_intent_ambiguity_blocks_resubmit_and_keeps_denominator(self):
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id']);trial.launch_intent(a['id'])
        trial=self.m.FrozenTrial(trial.root)
        with self.assertRaisesRegex(ValueError,'reconciliation'):trial.launch_intent(a['id'])
        self.assertEqual(trial.summary()['unrun'],2)
        with self.assertRaisesRegex(ValueError,'paid'):trial.execute(paid=False)
    def test_endpoint_cannot_be_overwritten_or_upgraded_by_cleanup(self):
        trial=self.freeze();a=trial.allocations[0]
        endpoint=dict(origin=self.clock(),observed=self.clock(),business=None,native=None,settled=None,arm_qualified=None,reasons=['missing'])
        trial.freeze_endpoint(a['id'],endpoint)
        with self.assertRaises((ValueError,sqlite3.IntegrityError)):trial.freeze_endpoint(a['id'],dict(endpoint,business=True))
        trial.append_reconciliation(a['id'],{'settled':True,'cleanup':True})
        self.assertEqual(trial.endpoint(a['id']),endpoint)
    def test_cleanup_unknown_stops_remaining_and_unknown_costs_stay_unknown(self):
        trial=self.freeze();a=trial.allocations[0]
        trial.freeze_endpoint(a['id'],dict(origin=self.clock(),observed=self.clock(),business=None,native=None,settled=None,arm_qualified=None,reasons=['unrun']))
        trial.record_result(a['id'],{'confirmed':None})
        r=trial.summary();self.assertEqual(r['unknown'],1);self.assertEqual(r['unrun'],1)
        self.assertTrue(r['protocol_stopped']);self.assertEqual(r['billing_unknown'],2);self.assertEqual(r['missing_auxiliary_calls'],2)

    def execution_artifacts(self,*,wrong_business=False,trial=None,allocation=None):
        self.assertTrue(callable(getattr(self.m.FrozenTrial,'qualify_artifacts',None)),'trusted artifact qualification missing')
        trial=trial or self.freeze();a=allocation or trial.allocations[0];prepared=trial.prepare(a['id'])
        from autonomy import Controller
        from autonomy_checks import Verifier
        from autonomy_store import Ledger
        from self_model import SelfModel
        from test_autonomy import Planner,Runs
        inspected=trial.inspect_controls(a['id']);policy=inspected['policy'];manifest=inspected['manifest']
        profile=Path(manifest['root'])/'profile';work=Path(manifest['work']);expected=copy.deepcopy(self.expected)
        trial._append('endpoint_origin',a['id'],self.m.Deadline.start(180,clock=self.clock).record())
        if wrong_business:expected['task_count']=7
        class LocalRuns(Runs):
            def status(inner,submission):
                (work/'result.json').write_text(canonical(expected))
                return {'run_id':submission['run_id'],'status':'completed','usage':None,'runtime':{'provider':'deepseek','model':'deepseek-flash'}}
        ledger=Ledger(profile/'zhulong/autonomy.db');ledger.set_pause(False)
        controller=Controller(ledger,policy,Planner(),LocalRuns(),Verifier(policy),SelfModel(ledger,profile/'zhulong'),clock=lambda:self.clock.utc)
        controller.tick();self.clock.advance(1);controller.tick()
        goal=ledger.goals()[0];sub=goal['submission'];self.assertIsNotNone(sub);self.assertTrue(sub['settled'])
        code='print("test fixture code")\n';(work/'.zhulong-work.py').write_text(code)
        command=self.m.native.TRUSTED_RUNNER_COMMAND
        with closing(sqlite3.connect(profile/'runs_idempotency.db')) as c,c:
            c.execute('CREATE TABLE run_idempotency(idempotency_key TEXT,run_id TEXT,fingerprint TEXT,status_json TEXT)')
            c.execute('INSERT INTO run_idempotency VALUES(?,?,?,?)',(sub['id'],sub['run_id'],digest({'body':sub['request'],'gateway_session_key':sub['session_key']}),canonical({'session_id':'native-session','run_id':sub['run_id'],'status':'completed'})))
        with closing(sqlite3.connect(profile/'state.db')) as c,c:
            c.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT,tool_call_id TEXT)')
            call=[{'id':'foreground','function':{'name':'terminal','arguments':{'command':command,'background':False}}}]
            c.execute('INSERT INTO messages VALUES(1,?,?,?,?,?)',('native-session','assistant',None,canonical(call),None))
            value={'code_hash':self.m.file_sha(work/'.zhulong-work.py'),'input_hash':a['input_hash'],'value':expected}
            c.execute('INSERT INTO messages VALUES(2,?,?,?,?,?)',('native-session','tool',canonical({'exit_code':0,'error':None,'output':canonical(value)}),None,'foreground'))
        return trial,a,profile,sub

    def test_qualifier_reads_actual_planner_native_and_independent_business_axes(self):
        trial,a,profile,sub=self.execution_artifacts(wrong_business=True)
        with patch('work_reference.reference_output',side_effect=AssertionError('product oracle forbidden')),patch.object(self.m.native,'reference_output',side_effect=AssertionError('product oracle forbidden')):
            value=trial.qualify_artifacts(a['id'])
        self.assertFalse(value['business']);self.assertTrue(value['native']);self.assertTrue(value['settled'])
        self.assertTrue(value['planner_qualified']);self.assertIn('actual_worker_unobserved',value['reasons'])
        self.assertIsNone(value['arm_qualified']);self.assertIsNone(value['billing'])

    def test_forged_planner_receipt_or_missing_executor_never_qualifies(self):
        trial,a,profile,sub=self.execution_artifacts()
        db=profile/'zhulong/autonomy.db'
        with closing(sqlite3.connect(db)) as c,c:
            c.execute('DROP TRIGGER frozen_cognition_receipts_update')
            row=c.execute("SELECT id,receipt FROM cognition_receipts WHERE receipt LIKE '%planner_method%'").fetchone()
            value=json.loads(row[1]);value['payload_hash']='a'*64
            c.execute('UPDATE cognition_receipts SET receipt=? WHERE id=?',(canonical(value),row[0]))
        value=trial.qualify_artifacts(a['id']);self.assertIsNone(value['planner_qualified']);self.assertIsNone(value['arm_qualified'])
        self.assertIn('planner_delivery_mismatch',value['reasons'])

    def test_missing_native_transcript_is_unknown_not_client_success(self):
        trial,a,profile,sub=self.execution_artifacts();(profile/'state.db').unlink()
        value=trial.qualify_artifacts(a['id'])
        self.assertTrue(value['business']);self.assertIsNone(value['native']);self.assertIsNone(value['arm_qualified'])

    def test_private_cli_has_no_paid_default_and_no_clock_injection(self):
        script=Path(self.m.ROOT)/'scripts/native_paired_trial.py'
        self.assertTrue(script.is_file(),'paired freeze/execute/summary CLI missing')
        import subprocess,sys
        result=subprocess.run([sys.executable,str(script),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertNotIn('--clock',result.stdout)
        trial=self.freeze()
        result=subprocess.run([sys.executable,str(script),'execute','--root',str(trial.root)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(trial.summary()['unrun'],2)

    def test_single_endpoint_capture_uses_actual_artifacts_and_rejects_late_audit(self):
        trial,a,profile,sub=self.execution_artifacts()
        self.assertTrue(callable(getattr(trial,'capture_endpoint',None)),'bounded capture missing')
        d=self.m.Deadline(trial._event('endpoint_origin',a['id'])['origin'],180,clock=self.clock)
        e=trial.capture_endpoint(a['id'],d)
        self.assertTrue(e['business']);self.assertTrue(e['native']);self.assertTrue(e['timely'])
        import subprocess
        def slow(*args,**kw):
            self.clock.advance(181)
            return subprocess.CompletedProcess(args,0)
        with patch.object(self.m.subprocess,'run',side_effect=slow):
            late=trial.capture_endpoint(a['id'],d)
        self.assertFalse(late['timely']);self.assertIsNone(late['business']);self.assertIsNone(late['settled'])

    def test_reconcile_ambiguous_intent_never_relaunches_and_records_unknown(self):
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id']);trial.launch_intent(a['id'])
        self.assertTrue(callable(getattr(trial,'reconcile',None)),'reconciliation missing')
        with patch.object(self.m.subprocess,'Popen',side_effect=AssertionError('relaunch')),patch.object(self.m.subprocess,'run',side_effect=OSError('offline')):
            r=trial.reconcile()
        self.assertEqual(r['unknown'],1);self.assertEqual(r['unrun'],1);self.assertTrue(r['protocol_stopped'])

    def test_actual_trial_ledger_replacement_is_not_silently_refilled(self):
        trial=self.freeze();db=trial.root/'trial.db';replacement=trial.root/'replacement.db'
        import shutil
        shutil.copyfile(db,replacement);replacement.replace(db)
        with self.assertRaisesRegex(ValueError,'ledger_identity'):self.m.FrozenTrial(trial.root)

    def test_strict_helper_requires_matching_frozen_context_and_preserves_default_signature(self):
        import inspect
        self.assertIn('strict_trial',inspect.signature(self.m.native.execute_allocation).parameters,'strict native helper context missing')
        trial=self.freeze();a=trial.allocations[0]
        with self.assertRaises(ValueError):
            self.m.native.execute_allocation(trial.base(a),HOST,IMAGE,self.fixture,a,explicit_policy={},strict_trial=trial)

    def test_forged_positive_endpoint_and_cleanup_are_not_authoritative(self):
        trial=self.freeze();a=trial.allocations[0]
        fake=dict(origin=self.clock(),observed=self.clock(),business=True,native=True,settled=True,arm_qualified=True,timely=True,reasons=[])
        with self.assertRaisesRegex(ValueError,'untrusted_endpoint'):trial.freeze_endpoint(a['id'],fake)
        unknown=dict(fake,business=None,native=None,settled=None,arm_qualified=None,timely=False)
        trial.freeze_endpoint(a['id'],unknown)
        with self.assertRaisesRegex(ValueError,'untrusted_cleanup'):trial.record_result(a['id'],{'confirmed':True})

    def test_swapped_arm_input_and_monitoring_changes_cannot_cross_qualifier(self):
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id'])
        other=trial.allocations[1]
        self.assertNotEqual(a['arm'],other['arm'])
        with self.assertRaises(ValueError):trial.inspect_controls(other['id'])
        path=trial.base(a)/'work/facts.json';path.write_text('{"tasks":[false]}')
        with self.assertRaises(ValueError):trial.inspect_controls(a['id'])

    def test_readback_rejects_untrusted_trial_receipts(self):
        trial=self.freeze();a=trial.allocations[0]
        forged=self.m.native._blank_receipt(a);trial.ledger.record(a['id'],forged)
        with self.assertRaisesRegex(ValueError,'untrusted_trial_receipt'):trial.summary()

    def test_masked_planner_payload_leak_with_rehashed_receipt_is_rejected(self):
        trial,a,profile,sub=self.execution_artifacts()
        # This seed happens to select an arm; independently construct the exact
        # delivered payload and add a forbidden aggregate fact before rehashing.
        controls=trial.inspect_controls(a['id']);policy=controls['policy']
        from cognition import Workspace
        from autonomy_store import Ledger
        from autonomy_checks import observe_sources
        ledger=Ledger(profile/'zhulong/autonomy.db')
        with closing(sqlite3.connect(ledger.path)) as c,c:
            frame=json.loads(c.execute('SELECT frame FROM cognition_frames LIMIT 1').fetchone()[0])
            view=Workspace(ledger,policy,sub['execution_identity']).planner_view(frame,observe_sources(policy),frame['captured_at'])
            payload={'observations':view['observations'],'context':{'current_execution_identity':sub['execution_identity'],'workspace':view['workspace'],'experience':[self.fixture['data']]},'policy':policy}
            c.execute('DROP TRIGGER frozen_cognition_receipts_update')
            row=c.execute("SELECT id,receipt FROM cognition_receipts WHERE receipt LIKE '%planner_method%'").fetchone()
            r=json.loads(row[1]);r['payload_hash']=digest(payload)
            c.execute('UPDATE cognition_receipts SET receipt=? WHERE id=?',(canonical(r),row[0]))
        result=trial.qualify_artifacts(a['id']);self.assertIsNone(result['planner_qualified'])
        self.assertIn('planner_delivery_mismatch',result['reasons'])

    def test_missing_executor_receipt_is_an_independent_unknown_qualifier(self):
        trial,a,profile,sub=self.execution_artifacts()
        with closing(sqlite3.connect(profile/'zhulong/autonomy.db')) as c,c:
            c.execute('DROP TRIGGER frozen_cognition_receipts_delete')
            c.execute("DELETE FROM cognition_receipts WHERE receipt LIKE '%executor_prepared%'")
        r=trial.qualify_artifacts(a['id']);self.assertTrue(r['native']);self.assertIsNone(r['planner_qualified'])
        self.assertIn('executor_delivery_mismatch',r['reasons'])

    def worker_artifact(self,trial,a,*,image=IMAGE):
        import os
        from runtime_policy import TMPFS_POLICY
        m=trial.inspect_controls(a['id'])['manifest'];work=m['work'];profile=Path(m['root'])/'profile'
        raw={'Config':{'Image':image,'User':f'{os.getuid()}:{os.getgid()}','Env':['HOME=/home'],'Labels':{'zhulong.runtime':m['deployment_id'],'zhulong.boot':'test-boot'}},
             'HostConfig':{'ReadonlyRootfs':True,'NetworkMode':'none','Privileged':False,'PidMode':'','IpcMode':'private','Memory':536870912,'MemorySwap':536870912,'ShmSize':67108864,'NanoCpus':1000000000,'PidsLimit':128,'SecurityOpt':['no-new-privileges'],'CapDrop':['ALL'],'CapAdd':[],'Tmpfs':dict(TMPFS_POLICY)},
             'Mounts':[{'Type':'bind','Source':work,'Destination':work,'RW':True},{'Type':'bind','Source':work+'/facts.json','Destination':work+'/facts.json','RW':False}]}
        self.m.durable_json(trial.base(a)/'worker.json',raw,exclusive=True)
        trial._append('worker',a['id'],{'worker_sha256':digest(raw),'clock':self.clock(),'service_boot_id':'test-boot','container_id':'explicit-local-test-worker'})

    def test_worker_full_actual_boundary_enables_arm_qualification(self):
        trial,a,profile,sub=self.execution_artifacts();self.worker_artifact(trial,a)
        r=trial.qualify_artifacts(a['id']);self.assertTrue(r['arm_qualified']);self.assertTrue(r['native']);self.assertTrue(r['business'])
        self.assertIsNone(r['response_observed_model']);self.assertEqual(r['observed_model'],'deepseek-flash')

    def test_runtime_model_wrong_first_and_consistent_wrong_cells_never_qualify(self):
        trial=self.freeze()
        for a in trial.allocations:
            trial,a,profile,sub=self.execution_artifacts(trial=trial,allocation=a);self.worker_artifact(trial,a)
            with closing(sqlite3.connect(profile/'zhulong/autonomy.db')) as c,c:
                c.execute('UPDATE submissions SET runtime=? WHERE id=?',(canonical({'provider':'deepseek','model':'unregistered-other-model'}),sub['id']))
            result=trial.qualify_artifacts(a['id'])
            self.assertIsNone(result['arm_qualified']);self.assertIn('actual_model_changed',result['reasons'])
            self.assertEqual(result['observed_model'],'unregistered-other-model');self.assertIsNone(result['response_observed_model'])
        rule=trial.protocol['runtime_identity_rule']
        self.assertEqual(rule['allowed'],[{'provider':'deepseek','model':'deepseek-flash'}])
        self.assertEqual(rule['basis_sha256'],trial.protocol['versions']['host_files']['gateway/platforms/api_server.py'])

    def test_persisted_runs_runtime_disagreement_rejects_qualified_submission(self):
        trial,a,profile,sub=self.execution_artifacts();self.worker_artifact(trial,a)
        with closing(sqlite3.connect(profile/'runs_idempotency.db')) as c,c:
            row=c.execute('SELECT status_json FROM run_idempotency').fetchone();status=json.loads(row[0])
            status['runtime']={'provider':'deepseek','model':'unregistered-other-model'}
            c.execute('UPDATE run_idempotency SET status_json=?',(canonical(status),))
        result=trial.qualify_artifacts(a['id'])
        self.assertIsNone(result['arm_qualified']);self.assertIn('runs_runtime_identity_mismatch',result['reasons'])

    def test_wrong_runtime_model_stops_before_next_allocation(self):
        trial,a,profile,sub=self.execution_artifacts();self.worker_artifact(trial,a)
        with closing(sqlite3.connect(profile/'zhulong/autonomy.db')) as c,c:
            c.execute('UPDATE submissions SET runtime=? WHERE id=?',(canonical({'provider':'deepseek','model':'unregistered-other-model'}),sub['id']))
        def local_execution(*args,**kwargs):
            self.assertEqual(args[4]['id'],a['id'],'second native allocation launched')
            endpoint=trial.capture_endpoint(a['id'],self.m.Deadline(trial._event('endpoint_origin',a['id'])['origin'],180,clock=self.clock));trial.freeze_endpoint(a['id'],endpoint)
            origin=self.clock();trial._append('cleanup_origin',a['id'],origin)
            cleanup=dict(confirmed=True,within_grace=True,origin=origin,observed=origin)
            trial._append('cleanup_capture','local',dict(allocation_id=a['id'],cleanup_sha256=digest(cleanup)))
            return trial.record_result(a['id'],cleanup)
        with patch.object(self.m.native,'execute_allocation',side_effect=local_execution):report=trial.execute(paid=True)
        self.assertTrue(report['protocol_stopped']);self.assertEqual(report['unrun'],1)
        self.assertFalse(report['allocations'][0]['receipt']['paired_qualified'])

    def test_wrong_actual_worker_image_cannot_qualify_even_with_bound_hash(self):
        trial,a,profile,sub=self.execution_artifacts();self.worker_artifact(trial,a,image='other@sha256:'+'b'*64)
        r=trial.qualify_artifacts(a['id']);self.assertIsNone(r['arm_qualified']);self.assertIn('actual_worker_image_changed',r['reasons'])

    def test_launch_must_replay_exact_frozen_order(self):
        trial=self.freeze();second=trial.allocations[1];trial.prepare(second['id'])
        with self.assertRaisesRegex(ValueError,'allocation_order'):trial.launch_intent(second['id'])

    def test_expired_cleanup_grace_is_never_refilled_on_reconciliation(self):
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id']);trial.launch_intent(a['id'])
        old=self.m.host_clock();old['utc']-=1000;old['monotonic']-=1000
        trial._append('endpoint_origin',a['id'],{'origin':old,'deadline_utc':old['utc']+180,'seconds':180})
        with patch.object(self.m.subprocess,'run',side_effect=OSError('offline')):
            trial.reconcile()
        start=trial._event('cleanup_origin',a['id'])
        self.assertLessEqual(start['monotonic'],old['monotonic']+180)

    def test_capture_cannot_reset_registered_origin_after_outcome(self):
        trial,a,profile,sub=self.execution_artifacts()
        reset=self.m.Deadline.start(180,clock=self.clock)
        result=trial.capture_endpoint(a['id'],reset)
        self.assertFalse(result['timely']);self.assertIsNone(result['business'])

    def test_qualified_endpoint_receipts_are_derived_and_keep_small_n_conservatism(self):
        trial,a,profile,sub=self.execution_artifacts();self.worker_artifact(trial,a)
        d=self.m.Deadline(trial._event('endpoint_origin',a['id'])['origin'],180,clock=self.clock)
        endpoint=trial.capture_endpoint(a['id'],d);trial.freeze_endpoint(a['id'],endpoint)
        # Cleanup fixture uses actual process-absence observations and explicit
        # local transport fixtures, never runs Docker or a native provider.
        owner={'pid':99999991,'start_ticks':1};child={'pid':99999992,'start_ticks':1}
        trial._append('process',a['id'],{'identity':owner,'clock':self.clock()})
        self.m.durable_json(profile.parent/'service/status.json',{'state':'stopped','supervisor_identity':owner,'child_identity':child})
        import subprocess
        now=self.m.host_clock();trial._append('cleanup_origin',a['id'],now)
        with patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='',stderr='')):
            cleanup=trial._cleanup(a)
        self.assertTrue(cleanup['confirmed']);receipt=trial.record_result(a['id'],cleanup)
        self.assertEqual(receipt['outcome'],'succeeded')
        summary=trial.summary();self.assertTrue(summary['allocations'][0]['receipt']['paired_qualified'])
        self.assertFalse(summary['causal_gain_supported']);self.assertIn('small_n',summary['paired_analysis']['disqualifications'])
        self.assertNotIn('declared_controls',summary['protocol']);self.assertNotIn('oracle',summary['protocol'])

    def test_cleanup_crossing_grace_during_final_absence_read_stays_unknown(self):
        import subprocess
        trial,a,profile,sub=self.execution_artifacts();self.worker_artifact(trial,a)
        Deadline=self.m.Deadline
        endpoint=trial.capture_endpoint(a['id'],Deadline(trial._event('endpoint_origin',a['id'])['origin'],180,clock=self.clock));trial.freeze_endpoint(a['id'],endpoint)
        owner={'pid':99999991,'start_ticks':1};child={'pid':99999992,'start_ticks':1}
        trial._append('process',a['id'],{'identity':owner,'clock':self.clock()})
        self.m.durable_json(profile.parent/'service/status.json',{'state':'stopped','supervisor_identity':owner,'child_identity':child})
        trial._append('cleanup_origin',a['id'],self.clock())
        def delayed_absence(pid):self.clock.advance(41);return None
        with patch.object(self.m,'Deadline',side_effect=lambda origin,seconds:Deadline(origin,seconds,clock=self.clock)),patch.object(self.m,'host_clock',self.clock),patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='',stderr='')),patch('runtime_channel.process_identity',side_effect=delayed_absence):
            cleanup=trial._cleanup(a)
        self.assertIsNone(cleanup['confirmed']);self.assertFalse(cleanup['within_grace'])
        receipt=trial.record_result(a['id'],cleanup)
        self.assertIsNone(receipt['cleanup']);self.assertEqual(receipt['outcome'],'unknown')
        self.assertFalse(trial.summary()['allocations'][0]['receipt']['paired_qualified'])
        self.assertTrue(trial.summary()['protocol_stopped'])

    def test_authenticated_cleanup_still_requires_registered_observation_timing(self):
        trial=self.freeze();a=trial.allocations[0];origin=self.clock()
        trial.freeze_endpoint(a['id'],dict(origin=origin,observed=origin,business=None,native=None,settled=None,arm_qualified=None))
        trial._append('cleanup_origin',a['id'],origin)
        self.clock.advance(121)
        cleanup=dict(confirmed=True,within_grace=True,origin=origin,observed=self.clock())
        trial._append('cleanup_capture','late',dict(allocation_id=a['id'],cleanup_sha256=digest(cleanup)))
        receipt=trial.record_result(a['id'],cleanup)
        self.assertIsNone(receipt['cleanup']);self.assertTrue(trial.summary()['protocol_stopped'])

    def test_reconcile_live_owner_has_no_endpoint_receipt_or_cleanup_sideeffects(self):
        import fcntl
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id']);trial.launch_intent(a['id'])
        with trial.journal.transaction() as c:before=trial.journal.rows(c)
        with (trial.root/'execute.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(trial,'_cleanup',side_effect=AssertionError('live owner cleanup forbidden')):
                with self.assertRaisesRegex(ValueError,'already_owned'):trial.reconcile()
        with trial.journal.transaction() as c:self.assertEqual(trial.journal.rows(c),before)
        self.assertIsNone(trial.endpoint(a['id']));self.assertEqual(trial.summary()['unrun'],2)
        with patch.object(trial,'_cleanup',return_value={'confirmed':None}):report=trial.reconcile()
        self.assertEqual(report['unknown'],1);self.assertEqual(report['unrun'],1)

    def test_execute_ambiguous_recovery_under_own_lock_never_relaunches(self):
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id']);trial.launch_intent(a['id'])
        with patch.object(trial,'_cleanup',return_value={'confirmed':None}),patch.object(self.m.native,'execute_allocation',side_effect=AssertionError('relaunch forbidden')):
            report=trial.execute(paid=True)
        self.assertEqual(report['unknown'],1);self.assertEqual(report['unrun'],1)
        self.assertTrue(report['protocol_stopped'])

    def test_endpoint_journal_failure_still_attempts_scoped_cleanup(self):
        trial=self.freeze();a=trial.allocations[0];trial.prepare(a['id']);controls=trial.inspect_controls(a['id'])
        with patch.object(trial,'inspect_controls',return_value=controls),patch.object(self.m.subprocess,'run',side_effect=OSError('offline startup')),patch.object(trial,'freeze_endpoint',side_effect=ValueError('journal_unavailable')),patch.object(trial,'_cleanup',return_value={'confirmed':None}) as cleanup:
            with self.assertRaisesRegex(ValueError,'journal_unavailable'):trial._run_allocation(a['id'])
        cleanup.assert_called_once()

    def test_saved_input_byte_hash_and_python_launcher_are_frozen(self):
        trial=self.freeze()
        self.assertTrue('python' in trial.protocol['versions'],'interpreter version missing')
        self.assertTrue('launcher_sha256' in trial.protocol,'launcher executable binding missing')
        self.assertEqual(trial.protocol['input_artifacts'][0]['byte_sha256'],self.m.file_sha(trial.root/'inputs/empty-work.json'))

if __name__=='__main__':unittest.main()
