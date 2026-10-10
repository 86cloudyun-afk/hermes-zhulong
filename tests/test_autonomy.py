import copy
import importlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomy_checks import validate_config,Verifier
from autonomy_store import Ledger
from self_model import SelfModel
from hermes_runs import RunsError
from helpers import policy_config,evidence,make_goal


class Planner:
    def __init__(self):self.calls=0
    def plan(self,observations,model,policy):
        self.calls+=1
        return [{'source_id':o['id'],'contract_id':o['contract_ids'][0],
                 'objective':'Create the missing '+o['domain']+' artifact',
                 'reason':'Source facts identify an unmet need','confidence':0.7} for o in observations if o['available']]


class Runs:
    def __init__(self):self.submissions={};self.calls=0;self.complete_artifact=True;self.run_state='completed';self.lose=False
    def capabilities(self):return {'retention_seconds':86400,'durable':True}
    def submit(self,submission):
        if submission['id'] not in self.submissions:
            self.calls+=1;self.submissions[submission['id']]=copy.deepcopy(submission)
        if self.lose:self.lose=False;raise RunsError('lost',True,True)
        return {'run_id':'run_'+submission['id'],'status':'queued'}
    def status(self,submission):
        request=json.loads(submission['request']['input'])
        contract=request['acceptance_contract']
        if self.complete_artifact and self.run_state=='completed':Path(contract['path']).write_text(contract['text'])
        return {'run_id':submission['run_id'],'status':self.run_state,'runtime':{'provider':'test'},'usage':None}
    def stop(self,submission):return {'run_id':submission['run_id'],'status':'stopping'}


class AutonomyTests(unittest.TestCase):
    def test_service_starting_and_stopping_gate_planning_but_allow_recovery(self):
        self.controller.admission_gate=lambda:False
        self.controller.tick()
        self.assertEqual(self.planner.calls,0)
        self.controller.admission_gate=lambda:True
        self.controller.tick()
        self.controller.admission_gate=lambda:False
        self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'succeeded')
        self.assertEqual(self.planner.calls,1)
        self.assertEqual(self.runs.calls,1)

    def test_stop_request_prevents_planner_and_exposes_progress(self):
        self.controller.request_stop()
        self.controller.tick()
        self.assertEqual(self.planner.calls,0)
        progress=self.controller.progress()
        self.assertEqual(progress['ticks'],1)
        self.assertEqual(progress['phase'],'idle')
        self.assertTrue(self.controller.stop(timeout=0.1))

    def test_background_errors_are_sanitized_and_counted(self):
        def broken():raise RuntimeError('private-provider-response')
        self.controller.tick=broken
        self.controller.start(0.01)
        until=time.monotonic()+2
        while self.controller.progress()['errors']==0 and time.monotonic()<until:time.sleep(0.01)
        self.assertTrue(self.controller.stop(timeout=2))
        progress=self.controller.progress()
        self.assertGreater(progress['errors'],0)
        self.assertEqual(progress['reason'],'tick_error:RuntimeError')
        self.assertNotIn('private-provider-response',json.dumps(progress))

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('autonomy'),'autonomous loop is missing')
        self.m=importlib.import_module('autonomy')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.raw=policy_config(self.root)
        (self.root/'facts.json').write_text('{"report":"missing"}')
        self.now=[1000.0];self.ledger=Ledger(self.root/'ledger.db');self.model=SelfModel(self.ledger,self.root)
        self.planner=Planner();self.runs=Runs();self.controller=self.build()

    def build(self):
        policy=validate_config(self.raw,self.root)
        return self.m.Controller(self.ledger,policy,self.planner,self.runs,Verifier(policy),self.model,clock=lambda:self.now[0])

    def test_three_domains_finish_from_facts_without_human(self):
        code=self.raw['sources'][0];self.raw['sources']=[]
        for domain in ('code','research','personal'):
            source=copy.deepcopy(code);source.update(id=domain+'-facts',domain=domain,path=str(self.root/(domain+'.json')))
            Path(source['path']).write_text('{"desired_report":"missing", "facts":[1,2,3]}')
            source['contracts']['result']['path']=str(self.root/(domain+'-result.txt'));self.raw['sources'].append(source)
        self.controller=self.build()
        for _ in range(7):self.controller.tick();self.now[0]+=1
        self.assertEqual({g['domain'] for g in self.ledger.goals() if g['state']=='succeeded'},{'code','research','personal'})
        before=self.planner.calls;self.controller.tick();self.assertEqual(self.planner.calls,before)
        self.assertEqual(self.runs.calls,3)
        self.assertEqual(self.controller.status()['required_human_interventions'],0)

    def test_assistant_success_without_artifact_is_not_success(self):
        self.runs.complete_artifact=False
        self.controller.tick();self.controller.tick()
        goal=self.ledger.goals()[0];self.assertEqual(goal['state'],'failed')
        self.assertEqual(self.model.snapshot()['domains']['code']['success'],0)

    def attach_learning(self):
        self.assertIsNotNone(importlib.util.find_spec('experience'), 'learning integration missing')
        from experience import ExperienceLearner
        from experience_store import ExperienceStore
        self.learning_calls = []
        def complete(**kw):
            self.learning_calls.append(kw)
            return SimpleNamespace(parsed={'guidance': 'Read the acceptance text before writing the file.'})
        self.store = ExperienceStore(self.ledger)
        self.controller.experience = ExperienceLearner(self.store, SimpleNamespace(complete_structured=complete),
            SimpleNamespace(take=lambda: True), clock=lambda: self.now[0])

    def test_failure_learning_changes_future_execution_and_plain_baseline_has_no_lesson(self):
        self.attach_learning(); self.runs.complete_artifact=False
        self.controller.tick(); self.now[0]+=1; self.controller.tick()
        self.assertEqual(len(self.learning_calls),1)
        self.assertEqual(self.controller.experience_status()['states'],{'candidate':1})
        (self.root/'facts.json').write_text('{"report":"a new gap"}')
        self.now[0]+=1; self.runs.complete_artifact=True; self.controller.tick()
        request=json.loads(self.ledger.goals()[0]['submission']['request']['input'])
        self.assertEqual(request['experience'][0]['guidance'],'Read the acceptance text before writing the file.')
        goal=self.ledger.goals()[0]
        self.controller=self.build()
        request=json.loads(self.controller._request(goal)['input'])
        self.assertNotIn('experience',request)

    def test_learning_error_and_pause_preserve_pending_execution_recovery(self):
        self.attach_learning(); self.controller.tick(); self.controller.pause()
        self.controller.experience.tick=lambda *a: (_ for _ in ()).throw(RuntimeError('private-model-details'))
        self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'succeeded')
        self.assertEqual(self.controller.progress()['learning_reason'],'experience_unavailable')
        self.assertNotIn('private-model-details',json.dumps(self.controller.progress()))

    def test_safe_retry_receives_lesson_and_lost_reply_freezes_original_binding(self):
        self.raw['sources'][0]['contracts']['result']['safe_retry']=True
        self.controller=self.build(); self.attach_learning(); self.runs.complete_artifact=False
        self.controller.tick(); self.now[0]+=1; self.controller.tick()
        self.now[0]+=1; self.runs.lose=True; self.controller.tick()
        goal=self.ledger.goals()[0]; frozen=goal['submission']['request']
        self.assertEqual(len(json.loads(frozen['input'])['experience']),1)
        self.controller.experience.store.retrieve=lambda *a: self.fail('recovery rebuilt guidance')
        self.runs.complete_artifact=True; self.controller.pause(); self.now[0]+=1; self.controller.tick()
        self.now[0]+=1; self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['submission']['request'],frozen)
        self.assertEqual(self.ledger.goals()[0]['state'],'succeeded')
        self.assertEqual(self.store.summary()['strategies'][0]['heldout_successes'],0)

    def test_planner_gets_contexts_commitments_and_experience(self):
        received=[]
        llm=SimpleNamespace(complete_structured=lambda **kw: (received.append(kw) or SimpleNamespace(parsed={'candidates':[]})))
        model={'domains':{},'contexts':{'ctx':{'domain':'code'}},'active_commitments':[{'goal_id':'g'}],
               'experience':[{'guidance':'lesson'}]}
        self.m.LLMPlanner(llm,SimpleNamespace(take=lambda:True)).plan([],model,validate_config(self.raw,self.root))
        payload=json.loads(received[0]['input'][0]['text'])
        self.assertEqual(payload['self_model']['contexts'],model['contexts'])
        self.assertEqual(payload['self_model']['active_commitments'],model['active_commitments'])
        self.assertEqual(payload['self_model']['experience'],model['experience'])

    def test_disabled_learning_excludes_existing_guidance(self):
        self.attach_learning();self.runs.complete_artifact=False
        self.controller.tick();self.now[0]+=1;self.controller.tick()
        self.controller.policy['learning_enabled']=False
        self.assertNotIn('experience',json.loads(self.controller._request(self.ledger.goals()[0])['input']))

    def test_planner_capability_scope_is_filtered_before_history_limit(self):
        for i in range(22):
            goal=make_goal(self.ledger,domain='research',source_revision='foreign-'+str(i))
            lease=self.ledger.claim('history',1000,30,(goal['id'],))
            identity=dict(self.controller.execution_identity,identity_version='identity-'+str(i))
            sub=self.ledger.prepare_submission(lease,{'input':'history'},'history',identity,1000,100,1,1,86400)['submission']
            self.ledger.finish(lease,evidence(goal,True),'succeeded',True,1001,expected_submission_id=sub['id'])
        self.model.refresh()
        self.raw['api_identity_version']='identity-21';self.controller=self.build()
        captured=[]
        llm=SimpleNamespace(complete_structured=lambda **kw:(captured.append(kw) or SimpleNamespace(parsed={'candidates':[]})))
        self.controller.planner=self.m.LLMPlanner(llm,SimpleNamespace(take=lambda:True))
        self.controller.tick()
        context=json.loads(captured[0]['input'][0]['text'])['self_model']
        self.assertEqual(len(context['contexts']),1)
        self.assertEqual(next(iter(context['contexts'].values()))['execution_context'],self.controller.execution_identity)
        self.assertEqual(context['current_execution_identity'],self.controller.execution_identity)
        self.assertEqual(len(self.model.snapshot()['contexts']),22)
        self.raw['api_identity_version']='brand-new';self.controller=self.build()
        (self.root/'facts.json').write_text('{"report":"new identity gap"}')
        self.controller.planner=self.m.LLMPlanner(llm,SimpleNamespace(take=lambda:True));self.controller.tick()
        context=json.loads(captured[-1]['input'][0]['text'])['self_model']
        self.assertEqual(context['contexts'],{})

    def test_existing_artifact_never_dispatches(self):
        (self.root/'result.txt').write_text('done')
        self.controller.tick()
        self.assertEqual(self.runs.calls,0)
        self.assertEqual(self.ledger.goals()[0]['state'],'already_satisfied')

    def test_pause_and_zero_budget_still_reconcile_last_attempt(self):
        self.raw['max_attempts']=1;self.runs.lose=True;self.controller=self.build()
        self.controller.tick();self.controller.pause()
        self.raw['daily_runs']=0;self.now[0]+=121;self.controller=self.build()
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'succeeded')
        self.assertEqual(self.ledger.goals()[0]['attempts'],1);self.assertEqual(self.runs.calls,1)

    def test_interrupted_then_late_effect_does_not_replace(self):
        self.runs.run_state='interrupted';self.runs.complete_artifact=False
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'unknown_result')
        self.assertFalse(self.ledger.goals()[0]['submission']['settled'])
        (self.root/'result.txt').write_text('done')
        self.controller.tick()
        self.assertEqual(self.runs.calls,1)

    def test_expired_replay_horizon_is_unknown(self):
        self.runs.lose=True;self.controller.tick()
        self.now[0]+=86401;self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'unknown_result');self.assertEqual(self.runs.calls,1)

    def test_namespace_change_prevents_unresolved_replay(self):
        self.runs.lose=True;self.controller.tick()
        self.raw['api_identity_version']='changed';self.controller=self.build();self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'unknown_result');self.assertEqual(self.runs.calls,1)

    def test_bad_model_json_retries_are_bounded(self):
        self.planner.plan=lambda *a:{'wrong':'unstructured'}
        for _ in range(8):self.controller.tick();self.now[0]+=61
        self.assertEqual(self.runs.calls,0)
        self.assertEqual(self.ledger.source_state('code-facts')['outcome']['attempts'],3)

    def test_missing_credentials_is_blocked_and_recovers(self):
        self.runs.capabilities=lambda:(_ for _ in ()).throw(RunsError('missing_credential'))
        self.controller.tick();self.assertEqual(self.ledger.goals()[0]['state'],'blocked')
        self.runs.capabilities=lambda:{'retention_seconds':86400,'durable':True}
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'succeeded')

    def test_model_feedback_changes_actual_selection(self):
        for i in range(3):
            g=make_goal(self.ledger,source_revision='history'+str(i));lease=self.ledger.claim('history',1000,20,ranked_goal_ids=(g['id'],))
            submission=self.ledger.prepare_submission(lease,{'input':'prior'},'prior',self.controller.execution_identity,1000,8,1,3,86400)['submission']
            self.ledger.finish(lease,evidence(g,False),'failed',True,1001,expected_submission_id=submission['id'])
        self.model.refresh()
        a=make_goal(self.ledger,source_revision='new',domain='code');b=make_goal(self.ledger,source_revision='new',domain='research')
        ranked=self.controller.rank_ready([a,b]);self.assertEqual(ranked[0]['id'],b['id'])
        original=self.model.expected_success;self.model.expected_success=lambda *a:0.5
        self.assertEqual(self.controller.rank_ready([a,b])[0]['id'],a['id']);self.model.expected_success=original

    def test_lifecycle_stop_prevents_new_ticks(self):
        calls=[];self.controller.tick=lambda:calls.append(1)
        self.controller.start(interval_seconds=0.01);self.controller.start(interval_seconds=0.01)
        time.sleep(0.03);self.controller.stop();n=len(calls);time.sleep(0.03)
        self.assertGreater(n,0);self.assertEqual(len(calls),n)

    def test_planner_budget_and_structured_validation(self):
        class Budget:
            def take(self):return False
        llm=SimpleNamespace(complete_structured=lambda **kw:self.fail('zero budget invoked model'))
        with self.assertRaises(self.m.PlannerError):self.m.LLMPlanner(llm,Budget()).plan([],{},validate_config(self.raw,self.root))

    def test_cancel_intent_is_persistent_and_prevents_admission(self):
        goal=make_goal(self.ledger)
        lease=self.ledger.claim('busy',1000,20)
        self.assertTrue(self.ledger.request_cancel(goal['id']))
        result=self.ledger.prepare_submission(lease,{'input':'intent'},'session',self.controller.execution_identity,1000,8,1,3,86400)
        self.assertFalse(result['admitted']);self.assertEqual(result['reason'],'cancelled')

    def test_two_controllers_only_synthesize_once(self):
        other=self.build();threads=[threading.Thread(target=c.tick) for c in (self.controller,other)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertEqual(self.planner.calls,1);self.assertEqual(self.runs.calls,1)

    def test_shared_artifact_contract_cannot_run_concurrently(self):
        a=make_goal(self.ledger);b=make_goal(self.ledger,domain='research')
        first=self.ledger.claim('a',1000,20,ranked_goal_ids=(a['id'],))
        second=self.ledger.claim('b',1000,20,ranked_goal_ids=(b['id'],))
        identity=self.controller.execution_identity
        self.assertTrue(self.ledger.prepare_submission(first,{'input':'a'},'a',identity,1000,8,2,3,86400)['admitted'])
        response=self.ledger.prepare_submission(second,{'input':'b'},'b',identity,1000,8,2,3,86400)
        self.assertFalse(response['admitted']);self.assertEqual(response['reason'],'verification_resource_active')

    def test_safe_retry_is_bounded_and_separately_scored(self):
        self.raw['sources'][0]['contracts']['result']['safe_retry']=True
        self.runs.complete_artifact=False;self.controller=self.build()
        for _ in range(6):self.controller.tick();self.now[0]+=1
        self.assertEqual(self.runs.calls,3);self.assertEqual(self.ledger.goals()[0]['state'],'failed')
        stats=self.model.snapshot()['domains']['code']
        self.assertEqual(stats['verified_samples'],1);self.assertEqual(stats['attempts']['verified_samples'],3)

    def test_unknown_occupancy_allows_other_observation_and_verification(self):
        self.runs.run_state='interrupted';self.runs.complete_artifact=False
        self.controller.tick();self.controller.tick()
        source=copy.deepcopy(self.raw['sources'][0]);source.update(id='personal',domain='personal',path=str(self.root/'personal.json'))
        Path(source['path']).write_text('{"facts":"new opportunity"}')
        source['contracts']['result']['path']=str(self.root/'personal-result.txt');Path(source['contracts']['result']['path']).write_text('done')
        self.raw['sources'].append(source);self.controller=self.build();self.controller.tick()
        self.assertIn('already_satisfied',{g['state'] for g in self.ledger.goals()});self.assertEqual(self.runs.calls,1)

    def test_approval_wait_is_stopped_without_human_dependency(self):
        self.runs.run_state='waiting_for_approval';self.runs.complete_artifact=False
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.ledger.goals()[0]['state'],'blocked');self.assertEqual(self.runs.calls,1)

    def test_zero_benefit_is_not_replaced_with_default(self):
        a=make_goal(self.ledger,domain='code');b=make_goal(self.ledger,domain='research')
        a['expected_benefit']=0;b['expected_benefit']=0.1
        self.assertEqual(self.controller.rank_ready([a,b])[0]['id'],b['id'])

    def test_backlog_has_bounded_work_per_tick(self):
        from autonomy_checks import observe_sources
        revision=observe_sources(self.controller.policy)[0]['revision']
        for i in range(30):
            self.ledger.create_goal({'source_id':'code-facts','domain':'code','contract_id':str(i),
                'objective':'Create result','reason':'Missing result','confidence':None,'expected_benefit':0.5},
                revision,self.controller.policy['sources'][0]['contracts']['result'],{'verdict':False,'artifact_hash':None},1000,600)
        self.raw['daily_runs']=0;self.controller=self.build()
        count=[0];claim=self.ledger.claim
        def counted(*args,**kwargs):count[0]+=1;return claim(*args,**kwargs)
        self.ledger.claim=counted;self.controller.tick()
        self.assertLessEqual(count[0],20)

    def test_unload_during_planning_prevents_new_external_run(self):
        entered=threading.Event();release=threading.Event();plan=self.planner.plan
        def slow(*args):entered.set();release.wait(5);return plan(*args)
        self.planner.plan=slow
        worker=threading.Thread(target=self.controller.tick);worker.start()
        self.assertTrue(entered.wait(2));self.controller.stop();release.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(self.runs.calls,0)

    def test_stale_snapshot_cannot_settle_a_new_live_attempt(self):
        self.raw['sources'][0]['contracts']['result']['safe_retry']=True
        self.controller=self.build();other=self.build();self.runs.complete_artifact=False
        self.controller.tick();first=self.ledger.goals()[0]['submission']['id']
        self.runs.status=lambda s:{'run_id':s['run_id'],'status':'failed' if s['id']==first else 'running'}
        original=self.ledger.work_goals;injected=[False]
        def old_snapshot():
            snapshot=original()
            if not injected[0]:
                injected[0]=True;other.tick();other.tick()
            return snapshot
        self.ledger.work_goals=old_snapshot
        self.controller.tick();self.ledger.work_goals=original
        self.controller.tick()
        goal=self.ledger.goals()[0]
        self.assertEqual(goal['attempts'],2)
        self.assertFalse(goal['submission']['settled'])
        self.assertEqual(self.runs.calls,2)

    def test_mixed_argv_file_contracts_cannot_share_action_credit(self):
        self.raw['max_active']=2
        second=copy.deepcopy(self.raw['sources'][0]);second.update(id='research-facts',domain='research',path=str(self.root/'research.json'))
        Path(second['path']).write_text('{"facts":"missing report"}')
        second['contracts']['result']={'type':'argv','argv':[sys.executable,'-c',
            "from pathlib import Path; import sys; sys.exit(0 if Path('result.txt').exists() else 1)"],
            'cwd':str(self.root),'require_change':True}
        self.raw['sources'].append(second);self.controller=self.build()
        done=[False]
        def status(s):
            contract=json.loads(s['request']['input'])['acceptance_contract']
            if done[0] and contract['type']=='file_contains':Path(contract['path']).write_text('done')
            return {'run_id':s['run_id'],'status':'completed' if done[0] else 'running'}
        self.runs.status=status
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.runs.calls,1)
        (self.root/'result.txt').write_text('done');done[0]=True
        self.controller.tick();self.controller.tick()
        self.assertEqual(sum(v['success'] for v in self.model.snapshot()['domains'].values()),1)
        self.assertIn('already_satisfied',{g['state'] for g in self.ledger.goals()})

    def test_budget_and_runtime_prerequisites_do_not_exhaust_source_attempts(self):
        real=self.planner.plan
        for reason in ('auxiliary_budget_exhausted','planner_unavailable'):
            self.planner.plan=lambda *a:(_ for _ in ()).throw(self.m.PlannerError(reason))
            for _ in range(4):self.controller.tick();self.now[0]+=61
        self.planner.plan=real;self.now[0]+=86400;self.controller.tick()
        self.assertEqual(len(self.ledger.goals()),1)
        self.assertEqual(self.planner.calls,1)

    def test_source_lease_renews_during_slow_planning(self):
        self.raw['lease_seconds']=1;self.controller=self.build();self.controller.clock=time.time
        real=self.planner.plan;competitor=[]
        def slow(*args):
            time.sleep(1.15)
            observation=args[0][0]
            competitor.append(self.ledger.claim_source(observation['id'],observation['revision'],'competitor',time.time(),1,3))
            return real(*args)
        self.planner.plan=slow;self.controller.tick()
        self.assertEqual(competitor,[False])
        self.assertEqual(len(self.ledger.goals()),1)
        self.assertEqual(self.ledger.source_state('code-facts')['outcome']['status'],'processed')

    def test_approval_block_remains_blocked_after_terminal_stop(self):
        self.runs.complete_artifact=False;self.runs.run_state='waiting_for_approval'
        self.controller.tick();self.controller.tick()
        self.runs.run_state='cancelled';self.controller.tick()
        for _ in range(3):self.controller.tick()
        goal=self.ledger.goals()[0]
        self.assertEqual(goal['state'],'blocked');self.assertTrue(goal['submission']['settled'])
        self.assertEqual(goal['attempts'],1);self.assertEqual(self.runs.calls,1)
        self.controller.cancel(goal['id']);self.controller.tick()
        self.assertEqual(self.ledger.get_goal(goal['id'])['state'],'cancelled')


if __name__=='__main__':unittest.main()
