"""Production workspace boundaries; consumers are deterministic, provider-free."""
import copy
import importlib
import json
import sqlite3
import sys
import tempfile
import threading
import math
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomy import Controller, LLMPlanner
from autonomy_checks import validate_config, observe_sources, Verifier
from autonomy_store import Ledger, canonical, digest
from self_model import SelfModel
from helpers import policy_config
from test_autonomy import Runs


class CognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.raw=policy_config(self.root)
        template=self.raw['sources'][0];self.raw['sources']=[]
        for i in range(5):
            s=copy.deepcopy(template);s.update(id='source-'+str(i),path=str(self.root/f'facts{i}.json'))
            s['contracts']['result']['path']=str(self.root/f'result{i}.txt')
            Path(s['path']).write_text(canonical({'report':f'PRIVATE_FACT_{i}'}))
            self.raw['sources'].append(s)
        self.raw['max_candidates']=1
        self.ledger=Ledger(self.root/'ledger.db');self.now=1000.0
        self.calls=[];self.runs=Runs()

    def policy(self,**changes):
        self.raw['cognition']={'enabled':True,'capacity':2,**changes}
        return validate_config(self.raw,self.root)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('cognition'),'cognitive workspace missing')
        return importlib.import_module('cognition')

    def controller(self,policy,planner=None):
        def plan(obs,context,policy):
            self.calls.append(copy.deepcopy((obs,context)))
            return []
        model=SelfModel(self.ledger,self.root)
        model.snapshot=lambda:{'domains':{'leak':'PRIVATE_FACT_4'},'contexts':{'leak':{'domain':'code','execution_context':{},'fact':'PRIVATE_FACT_4'}},
                               'active_commitments':['PRIVATE_FACT_4'],'policy_hypotheses':['PRIVATE_FACT_4']}
        return Controller(self.ledger,policy,planner or SimpleNamespace(plan=plan),self.runs,Verifier(policy),model,clock=lambda:self.now)

    def workspace(self,policy):return self.module().Workspace(self.ledger,policy['cognition'],{'identity':'test'})

    def test_real_controller_capacity_all_sources_and_context_filter(self):
        c=self.controller(self.policy())
        c._synthesize(observe_sources(c.policy))
        obs,context=self.calls[-1]
        self.assertEqual(len(obs),2)
        self.assertEqual([o['id'] for o in obs],['source-0','source-1'])
        self.assertNotIn('PRIVATE_FACT_4',canonical((obs,context)))
        self.assertIn('workspace',context)
        for key in ('domains','contexts','active_commitments','policy_hypotheses','experience'):self.assertFalse(context.get(key))

    def test_rotation_beyond_max_candidates_and_constant_tail_control(self):
        for mode in ('adaptive','constant'):
            policy=self.policy(capacity=2,selection_mode=mode);w=self.workspace(policy)
            observations=observe_sources(policy);selected=[]
            for i in range(math.ceil(len(observations)/2)):
                if i==1:w=self.module().Workspace(Ledger(self.ledger.path),policy['cognition'],{'identity':'test'})
                f=w.select(list(reversed(observations)) if i%2 else observations,self.now+i);selected.extend(e['source_id'] for e in f['entries'])
                self.assertEqual(f['forecast']['source_ids'],[e['source_id'] for e in f['entries']])
            if mode=='adaptive':self.assertEqual(set(selected),{o['id'] for o in observations})
            else:self.assertEqual(set(selected),{'source-0','source-1'})

    def test_controller_claimed_source_is_not_exposed_and_tail_gets_turn(self):
        policy=self.policy(capacity=1);observations=observe_sources(policy)
        self.ledger.claim_source('source-0',observations[0]['revision'],'other',self.now,120,3)
        c=self.controller(policy);c._synthesize(observations)
        self.assertEqual(self.calls[-1][0][0]['id'],'source-1')
        for _ in range(4):
            self.now+=1;c._synthesize(observe_sources(policy))
        self.assertIn('source-4',{o['id'] for obs,_ in self.calls for o in obs})
        self.assertNotIn('source-0',{o['id'] for obs,_ in self.calls for o in obs})

    def test_planner_mask_and_restoration_remove_task_input_data(self):
        self.raw['sources']=self.raw['sources'][:1]
        self.raw['sources'][0]['persist_input_fields']=['report']
        self.raw['sources'][0]['input_fields']=['report']
        views=[];decisions=[]
        for mask in (None,'planner',None):
            policy=self.policy(capacity=1,mask_consumer=mask);w=self.workspace(policy);obs=observe_sources(policy)
            f=w.select(obs,self.now);view=w.planner_view(f,obs,self.now)
            views.append(view);decisions.append('PRIVATE_FACT_0' in canonical(view['observations']))
        self.assertEqual(decisions,[True,False,True])
        self.assertEqual(views[0]['observations'],views[2]['observations'])
        self.assertNotIn('PRIVATE_FACT_0',canonical(views[1]))
        self.assertEqual(views[0]['workspace']['entries'],views[2]['workspace']['entries'])
        self.assertNotEqual(views[0]['workspace']['frame_id'],views[2]['workspace']['frame_id'])

    def goal(self,w,f,obs,now=None):
        o=obs[0];candidate={'source_id':o['id'],'source_revision':o['revision'],'domain':o['domain'],'contract_id':'result',
                            'objective':'Build artifact','reason':'Unmet contract','confidence':.7}
        return self.ledger.create_goal(candidate,o['revision'],self.raw['sources'][0]['contracts']['result'],
                {'verdict':False},self.now if now is None else now,600,task_input=o.get('task_input'),cognition_frame=f)

    def test_ttl_source_input_recheck_rollback_and_dedupe(self):
        policy=self.policy(ttl_seconds=1);w=self.workspace(policy);obs=observe_sources(policy);f=w.select(obs,self.now)
        with self.assertRaises(ValueError):self.goal(w,f,obs,self.now+2)
        self.assertEqual(self.ledger.goals(),[])
        wrong=copy.deepcopy(obs);wrong[0]['revision']='changed'
        with self.assertRaises(ValueError):self.goal(w,f,wrong)
        self.assertEqual(self.ledger.goals(),[])
        goal=self.goal(w,f,obs);f2=w.select(obs,self.now)
        duplicate=self.goal(w,f2,obs)
        self.assertEqual(goal['id'],duplicate['id'])
        self.assertEqual(w.execution_packet(goal['id'])['frame_id'],f['frame_id'])
        with self.assertRaises(ValueError):w.bind_goal(goal['id'],f2,self.now)

    def test_restart_masks_historical_packets_privacy_and_replacements(self):
        policy=self.policy(mask_consumer='executor');w=self.workspace(policy);obs=observe_sources(policy)
        f=w.select(obs,self.now);g=self.goal(w,f,obs)
        normal=w.monitor_packet(g['id']);masked=w.execution_packet(g['id'])
        self.assertEqual(masked['visibility'],'masked');self.assertEqual(normal['visibility'],'visible')
        restarted=self.module().Workspace(Ledger(self.ledger.path),{'enabled':True,'mask_consumer':None},{})
        self.assertEqual(restarted.execution_packet(g['id']),masked)
        self.assertNotIn('PRIVATE_FACT',canonical(restarted.summary()))
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('PRAGMA recursive_triggers').fetchone()[0],0)
            for table in ('cognition_frames','cognition_bindings'):
                row=c.execute('SELECT * FROM '+table).fetchone()
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute('INSERT OR REPLACE INTO '+table+' VALUES('+','.join('?' for _ in row)+')',tuple(row))
                with self.assertRaises(sqlite3.IntegrityError):c.execute('DELETE FROM '+table)
                self.assertNotIn('PRIVATE_FACT',canonical([tuple(r) for r in c.execute('SELECT * FROM '+table)]))

    def test_forged_frame_and_changed_facts_rejected(self):
        policy=self.policy();w=self.workspace(policy);obs=observe_sources(policy);f=w.select(obs,self.now)
        altered=copy.deepcopy(f);altered['policy']['capacity']=8
        with self.assertRaises(ValueError):w.planner_view(altered,obs,self.now)
        altered=copy.deepcopy(obs);altered[0]['facts']='replacement'
        with self.assertRaises(ValueError):w.planner_view(f,altered,self.now)

    def test_concurrent_selection_persists_rotation(self):
        policy=self.policy(capacity=1);obs=observe_sources(policy);barrier=threading.Barrier(4);frames=[];errors=[]
        def run():
            try:
                w=self.workspace(policy);barrier.wait();frames.append(w.select(obs,self.now))
            except Exception as e:errors.append(e)
        threads=[threading.Thread(target=run) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join(10)
        self.assertEqual(errors,[]);self.assertEqual(len(frames),4)
        self.assertEqual(len({f['entries'][0]['source_id'] for f in frames}),4)

    def test_llmplanner_receives_frozen_packet_and_masked_facts(self):
        policy=self.policy(capacity=1,mask_consumer='planner');w=self.workspace(policy);obs=observe_sources(policy)
        f=w.select(obs,self.now);view=w.planner_view(f,obs,self.now);requests=[]
        def complete(**kw):requests.append(kw);return SimpleNamespace(parsed={'candidates':[]})
        planner=LLMPlanner(SimpleNamespace(complete_structured=complete),SimpleNamespace(take=lambda:True))
        planner.plan(view['observations'],{'workspace':view['workspace']},policy)
        payload=json.loads(requests[0]['input'][0]['text'])
        self.assertEqual(payload['workspace']['frame_id'],f['frame_id'])
        self.assertNotIn('PRIVATE_FACT',canonical(payload))

    def test_controller_goal_execution_monitor_and_actual_boundary_receipts(self):
        policy=self.policy(capacity=1)
        def plan(obs,context,policy):
            return [{'source_id':obs[0]['id'],'contract_id':'result','objective':'Build artifact','reason':'Unmet contract'}]
        c=self.controller(policy,SimpleNamespace(plan=plan));c.tick()
        goal=self.ledger.goals()[0];intent=json.loads(goal['submission']['request']['input'])
        packet=intent['cognitive_workspace'];frame_id=packet['frame_id']
        prediction=self.ledger.model_records()['predictions'][goal['submission']['id']]
        self.assertEqual(prediction['workspace']['frame_id'],frame_id)
        with self.ledger._connection() as db:
            receipts=[json.loads(r[0]) for r in db.execute('SELECT receipt FROM cognition_receipts')]
            self.assertTrue({'planner_method','monitor_capture','executor_prepared','runs_call_started','runs_call_returned'} <= {r['channel'] for r in receipts})
            prepared=next(r for r in receipts if r['channel']=='executor_prepared')
            self.assertEqual(prepared['submission_id'],goal['submission']['id'])
            self.assertEqual(prepared['payload_hash'],digest(goal['submission']['request']))
            row=db.execute('SELECT * FROM cognition_receipts LIMIT 1').fetchone()
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT OR REPLACE INTO cognition_receipts VALUES('+','.join('?' for _ in row)+')',tuple(row))

    def test_strict_config_and_disabled_baseline(self):
        m=self.module();self.assertEqual(m.validate_cognition(None),{'enabled':False,'capacity':3,'ttl_seconds':120,'mask_consumer':None,'selection_mode':'adaptive'})
        for raw in ({'wat':1},{'enabled':1},{'capacity':True},{'capacity':9},{'ttl_seconds':float('nan')},
                    {'mask_consumer':[]},{'selection_mode':{}},[],False):
            with self.subTest(raw=raw),self.assertRaises(ValueError):m.validate_cognition(raw)
        self.raw.pop('cognition',None);policy=validate_config(self.raw,self.root)
        c=self.controller(policy);c._synthesize(observe_sources(policy))
        self.assertEqual(len(self.calls[0][0]),1)
        with self.ledger._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM cognition_frames').fetchone()[0],0)

    def test_workspace_omits_unavailable_input_inside_selection_transaction(self):
        self.raw['sources']=self.raw['sources'][:1]
        self.raw['sources'][0].update(input_fields=['report'],persist_input_fields=['report'])
        policy=self.policy(capacity=1);c=self.controller(policy);obs=observe_sources(policy)
        with self.ledger._connection(True) as db:
            db.execute("UPDATE settings SET value='0' WHERE key='input_snapshot_bytes'")
        frame=c.workspace.select(obs,self.now,source_owner='planner')
        self.assertIsNone(frame)
        self.assertIsNone(self.ledger.source_state(obs[0]['id']))

    def test_consumer_packet_mutation_cannot_rewrite_historical_limitations(self):
        policy=self.policy();w=self.workspace(policy);obs=observe_sources(policy);f=w.select(obs,self.now);g=self.goal(w,f,obs)
        packet=w.execution_packet(g['id']);packet['limitations']['hidden_activations']='available'
        self.assertEqual(w.execution_packet(g['id'])['limitations']['hidden_activations'],'unavailable')

    def test_all_consumer_masks_are_frozen_matched_interventions(self):
        self.raw['sources']=self.raw['sources'][:1]
        self.raw['sources'][0].update(input_fields=['report'],persist_input_fields=['report'])
        for consumer in ('planner','executor','monitor'):
            runs=[]
            for i,mask in enumerate((None,consumer,None)):
                self.ledger=Ledger(self.root/f'{consumer}-{i}.db')
                policy=self.policy(capacity=1,mask_consumer=mask);c=self.controller(policy)
                obs=observe_sources(policy);f=c.workspace.select(obs,self.now);g=self.goal(c.workspace,f,obs)
                request=c._request(g);intent=json.loads(request['input'])
                with self.ledger._connection() as db:
                    import metacognition
                    forecast=metacognition.capture(db,g,c.execution_identity,request,self.now,{})
                packets={'planner':c.workspace.planner_view(f,obs,self.now)['workspace'],
                         'executor':intent.pop('cognitive_workspace'),'monitor':forecast['workspace']}
                runs.append((f,packets,intent))
            self.assertEqual([r[0]['entries'] for r in runs],[runs[0][0]['entries']]*3)
            self.assertEqual(len({r[0]['frame_id'] for r in runs}),3)
            self.assertEqual(runs[0][2],runs[1][2]);self.assertEqual(runs[0][2],runs[2][2])
            self.assertEqual(runs[1][2]['task_input']['data'],{'report':'PRIVATE_FACT_0'})
            for target in ('planner','executor','monitor'):
                def semantics(packet):
                    return {k:v for k,v in packet.items() if k not in ('frame_id','frame_hash','policy_hash')}
                values=[semantics(r[1][target]) for r in runs]
                self.assertEqual(values[0],values[2])
                if target==consumer:
                    self.assertEqual(values[1]['visibility'],'masked');self.assertEqual(values[1]['entries'],[])
                else:self.assertEqual(values[0],values[1])
                # Restart with normal policy keeps the intervention on its historical goal.
            restarted=self.module().Workspace(Ledger(self.ledger.path),{'enabled':True},{})
            self.assertEqual(restarted.execution_packet(g['id']),runs[2][1]['executor'])

    def test_real_controller_fact_dependent_decision_is_masked_and_restored(self):
        self.raw['sources']=self.raw['sources'][:1]
        self.raw['sources'][0].update(input_fields=['report'],persist_input_fields=['report'])
        decisions=[];independent=[];frames=[]
        for i,mask in enumerate((None,'planner',None)):
            self.ledger=Ledger(self.root/f'decision-{i}.db');policy=self.policy(capacity=1,mask_consumer=mask)
            def plan(obs,context,policy):
                independent.append(obs[0]['contract_ids']==['result'])
                choose='PRIVATE_FACT_0' in canonical(obs)
                decisions.append(choose);frames.append(context['workspace'])
                return ([{'source_id':obs[0]['id'],'contract_id':'result','objective':'Build artifact','reason':'Unmet contract'}] if choose else [])
            c=self.controller(policy,SimpleNamespace(plan=plan));accepted=c._synthesize(observe_sources(policy))
            self.assertEqual(accepted,int(mask is None))
        self.assertEqual(decisions,[True,False,True]);self.assertEqual(independent,[True]*3)
        self.assertEqual(frames[0]['entries'],frames[2]['entries'])

    def test_actual_llmplanner_controller_capacity_and_masked_decision(self):
        requests=[]
        for i,mask in enumerate((None,'planner',None)):
            self.ledger=Ledger(self.root/f'llm-{i}.db');policy=self.policy(capacity=1,mask_consumer=mask)
            def complete(**kw):
                payload=json.loads(kw['input'][0]['text']);requests.append(payload)
                decision='PRIVATE_FACT_0' in canonical(payload)
                return SimpleNamespace(parsed={'candidates':[{'source_id':'source-0','contract_id':'result','objective':'Build artifact','reason':'Unmet contract'}] if decision else []})
            planner=LLMPlanner(SimpleNamespace(complete_structured=complete),SimpleNamespace(take=lambda:True))
            c=self.controller(policy,planner);self.assertEqual(c._synthesize(observe_sources(policy)),int(mask is None))
        self.assertEqual([len(r['observations']) for r in requests],[1]*3)
        self.assertEqual(['PRIVATE_FACT_0' in canonical(r) for r in requests],[True,False,True])
        for r in requests:self.assertNotIn('PRIVATE_FACT_4',canonical(r))

    def test_input_hash_and_current_source_mismatch_roll_back_atomically(self):
        self.raw['sources']=self.raw['sources'][:1]
        self.raw['sources'][0].update(input_fields=['report'],persist_input_fields=['report'])
        policy=self.policy(capacity=1);c=self.controller(policy);obs=observe_sources(policy);w=c.workspace;f=w.select(obs,self.now)
        changed=copy.deepcopy(obs)
        changed[0]['task_input']['data']={'report':'different'}
        changed[0]['task_input']['input_hash']=digest(changed[0]['task_input']['data'])
        changed[0]['task_input']['size']=len(canonical(changed[0]['task_input']['data']).encode())
        with self.assertRaisesRegex(ValueError,'cognition_goal_binding_mismatch'):self.goal(w,f,changed)
        self.assertEqual(self.ledger.goals(),[])
        with self.ledger._connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM task_inputs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cognition_bindings').fetchone()[0],0)
        self.ledger.mark_source(obs[0]['id'],'new-revision',{},self.now)
        with self.assertRaisesRegex(ValueError,'cognition_source_changed'):self.goal(w,f,obs)
        self.assertEqual(self.ledger.goals(),[])
        from refinement import audit
        with self.ledger._connection() as db:self.assertEqual(audit(db)['status'],'valid_within_scope')

    def test_ttl_expiring_during_verifier_capture_prevents_controller_goal(self):
        policy=self.policy(capacity=1,ttl_seconds=1)
        def plan(obs,context,policy):return [{'source_id':obs[0]['id'],'contract_id':'result','objective':'Build artifact','reason':'Unmet contract'}]
        c=self.controller(policy,SimpleNamespace(plan=plan))
        def capture(*args):self.now+=2;return {'verdict':False}
        c.verifier.capture=capture
        self.assertEqual(c._synthesize(observe_sources(policy)),0)
        self.assertEqual(self.ledger.goals(),[])
        with self.ledger._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM cognition_bindings').fetchone()[0],0)

    def test_runs_timeout_records_attempt_without_remote_received_claim(self):
        from hermes_runs import RunsError
        policy=self.policy(capacity=1)
        def plan(obs,context,policy):return [{'source_id':obs[0]['id'],'contract_id':'result','objective':'Build artifact','reason':'Unmet contract'}]
        c=self.controller(policy,SimpleNamespace(plan=plan))
        def timeout(submission):raise RunsError('request_timeout',True,True)
        self.runs.submit=timeout;c.tick()
        goal=self.ledger.goals()[0];self.assertEqual(goal['state'],'unknown_result')
        with self.ledger._connection() as db:receipts=[json.loads(r[0]) for r in db.execute('SELECT receipt FROM cognition_receipts')]
        self.assertIn('runs_call_started',{r['channel'] for r in receipts});self.assertIn('runs_call_failed',{r['channel'] for r in receipts})
        self.assertNotIn('runs_call_returned',{r['channel'] for r in receipts})
        self.assertTrue(all(r['status']=='remote_receipt_unknown' for r in receipts if r['channel']=='runs_call_failed'))

    def test_read_only_action_command_and_module_lists(self):
        from commands import Commands
        import runtime_policy
        spec=importlib.util.spec_from_file_location('cognition_plugin_test',Path(__file__).resolve().parents[1]/'__init__.py',submodule_search_locations=[str(Path(__file__).resolve().parents[1])])
        plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
        c=self.controller(self.policy());w=c.workspace;obs=observe_sources(c.policy);w.select(obs,self.now)
        with self.ledger._connection() as db:before=tuple(db.iterdump())
        action=json.loads(plugin._autonomy_handler(c,self.ledger)({'action':'cognition'}))
        command=json.loads(Commands(None,calibration=object(),autonomy=c).handle('autonomy cognition'))
        self.assertEqual({k:v for k,v in action.items() if k!='ok'},command)
        self.assertEqual(command,w.summary());self.assertIn('cognition.py',runtime_policy.PLUGIN_FILES)
        self.assertIn('cognition.py',(Path(__file__).resolve().parents[1]/'scripts/install.sh').read_text())
        with self.ledger._connection() as db:self.assertEqual(tuple(db.iterdump()),before)

    def test_manual_legacy_and_real_workflow_children_are_explicitly_unavailable(self):
        from helpers import make_goal
        w=self.workspace(self.policy());manual=make_goal(self.ledger)
        self.assertEqual(w.execution_packet(manual['id'])['visibility'],'unavailable')
        restarted=self.module().Workspace(Ledger(self.ledger.path),{'enabled':True},{})
        self.assertEqual(restarted.monitor_packet(manual['id'])['visibility'],'unavailable')
        from test_workflow import WorkflowTests
        fixture=WorkflowTests();fixture.setUp()
        try:
            fixture.create_child()
            children=[g for g in fixture.ledger.goals() if g.get('workflow')]
            self.assertTrue(children)
            child_workspace=self.module().Workspace(fixture.ledger,{'enabled':True},{})
            for child in children:
                p=child_workspace.execution_packet(child['id']);self.assertEqual(p['visibility'],'unavailable');self.assertEqual(p['reason'],'no_historical_binding')
        finally:fixture.doCleanups()

    def test_planner_view_recomputes_input_data_hash_and_scope(self):
        self.raw['sources']=self.raw['sources'][:1]
        self.raw['sources'][0].update(input_fields=['report'],persist_input_fields=['report'])
        policy=self.policy(capacity=1);c=self.controller(policy);obs=observe_sources(policy);w=c.workspace;f=w.select(obs,self.now)
        for field,value in (('data',{'report':'FORGED_REPLACEMENT'}),('source_id','wrong-source'),('source_revision','wrong-revision')):
            changed=copy.deepcopy(obs);changed[0]['task_input'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):w.planner_view(f,changed,self.now)

    def test_disabled_path_does_not_inspect_irrelevant_tail_inputs(self):
        policy=validate_config(self.raw,self.root);c=self.controller(policy);obs=observe_sources(policy)
        obs[-1]['task_input']={}
        c._synthesize(obs)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][0][0]['id'],'source-0')

    def test_planner_delivery_requires_current_claim(self):
        self.raw['lease_seconds']=1
        policy=self.policy(capacity=1,ttl_seconds=120);c=self.controller(policy)
        readings=[1000,1002]
        c.clock=lambda:readings.pop(0) if readings else 1002
        c._synthesize(observe_sources(policy))
        self.assertEqual(self.calls,[])
        with self.ledger._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM cognition_receipts').fetchone()[0],0)

    def test_llmplanner_workspace_cannot_reintroduce_aggregate_facts(self):
        policy=self.policy(capacity=1);w=self.workspace(policy);obs=observe_sources(policy);f=w.select(obs,self.now);view=w.planner_view(f,obs,self.now)
        requests=[]
        def complete(**kw):requests.append(kw);return SimpleNamespace(parsed={'candidates':[]})
        planner=LLMPlanner(SimpleNamespace(complete_structured=complete),SimpleNamespace(take=lambda:True))
        context={'workspace':view['workspace'],'domains':{'leak':'PRIVATE_FACT_4'},'contexts':{'leak':{'fact':'PRIVATE_FACT_4'}},
                 'active_commitments':['PRIVATE_FACT_4'],'policy_hypotheses':['PRIVATE_FACT_4'],'experience':['PRIVATE_FACT_4']}
        planner.plan(view['observations'],context,policy)
        self.assertNotIn('PRIVATE_FACT_4',canonical(requests))

    def test_missing_receipt_journal_does_not_block_historical_retry_or_cancel(self):
        from hermes_runs import RunsError
        policy=self.policy(capacity=1)
        def plan(obs,context,policy):return [{'source_id':obs[0]['id'],'contract_id':'result','objective':'Build artifact','reason':'Unmet contract'}]
        c=self.controller(policy,SimpleNamespace(plan=plan));self.runs.lose=True;c.tick()
        goal=self.ledger.goals()[0];frozen=copy.deepcopy(goal['submission']['request'])
        with self.ledger._connection(True) as db:db.execute('DROP TABLE cognition_receipts')
        self.now+=1;c.tick()
        recovered=self.ledger.get_goal(goal['id'])
        self.assertIsNotNone(recovered['submission']['run_id'])
        self.assertEqual(recovered['submission']['request'],frozen)
        self.assertTrue(c.workspace.receipt_unavailable)
        c.cancel(goal['id']);self.now+=1;c.tick()
        self.assertTrue(self.ledger.get_goal(goal['id'])['cancel_requested'])

    def test_workflow_contract_surface_matches_disabled_controller_llmplanner(self):
        self.raw['sources']=self.raw['sources'][:1]
        source=self.raw['sources'][0]
        source['contracts']['child']=copy.deepcopy(source['contracts']['result'])
        source['contracts']['child']['path']=str(self.root/'child.txt')
        self.raw['workflows']=[{'id':'bounded-work','source_id':source['id'],'contract_id':'result',
            'steps':[{'id':'child','contract_id':'child','objective':'Build child artifact',
                      'depends_on':[],'effect_mode':'read_only'}]}]
        delivered=[]
        for i,enabled in enumerate((False,True)):
            self.ledger=Ledger(self.root/f'workflow-surface-{i}.db')
            policy=self.policy(enabled=enabled,capacity=1)
            def complete(**kw):
                payload=json.loads(kw['input'][0]['text']);obs=payload['observations'][0]
                delivered.append(obs['contract_ids'])
                return SimpleNamespace(parsed={'candidates':[{'source_id':obs['id'],
                    'contract_id':obs['contract_ids'][-1],'objective':'Build artifact','reason':'Unmet contract'}]})
            planner=LLMPlanner(SimpleNamespace(complete_structured=complete),SimpleNamespace(take=lambda:True))
            c=self.controller(policy,planner);result=c.tick()
            self.assertEqual(delivered[-1],['result'])
            self.assertEqual(result['accepted'],1)
            self.assertTrue(any(g['contract_id']=='result' for g in self.ledger.goals()))
            self.assertEqual(len(c.workflows.summary()['workflows']),1)
        self.assertEqual(delivered[0],delivered[1])
