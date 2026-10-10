"""Finite actual native/Docker lifecycle test; --paid adds one DeepSeek goal."""
import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from autonomy_store import Ledger, canonical
from autonomy_checks import Verifier, validate_config, observe_sources
from experience_store import ExperienceStore
from hermes_runs import RunsClient
from runtime_channel import read_json
from runtime_policy import create_deployment
from skill_store import SkillStore
from scripts.skill_smoke_evidence import runner_command, audit_native_skill
import task_inputs


def wait_for(predicate,timeout,process):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        if process.poll() is not None:raise RuntimeError('supervisor_exited_before_evidence')
        time.sleep(0.1)
    raise RuntimeError('smoke_deadline_expired')


def seed_learning_failure(ledger, policy, now):
    """Validation-only settled executor fixture; the verifier itself is real.

    This is explicitly not an observed provider/tool failure. One synthetic
    submission consumes a run reservation, so the learning smoke allows two.
    """
    source=policy['sources'][0];contract_id=next(iter(source['contracts']))
    contract=source['contracts'][contract_id];checked=Verifier(policy).capture(contract)
    if checked['verdict'] is not False:raise RuntimeError('learning_fixture_not_false')
    task_inputs.configure(ledger,policy['sources'],policy['input_snapshot_bytes'])
    observation=observe_sources(policy)[0]
    snapshot=observation.get('task_input')
    goal=ledger.create_goal({'source_id':source['id'],'contract_id':contract_id,'domain':source['domain'],
        'objective':'Create the missing local report according to the configured acceptance.',
        'reason':'Validation fixture: executor deliberately produced no output.','confidence':0.5},
        observation['revision'] if snapshot else 'validation-fixture-before-live-source',contract,checked,now,600,
        task_input=snapshot)
    lease=ledger.claim('validation-fixture',now,20,(goal['id'],))
    identity={'api_url':policy['api_url'],'credential_env':policy['api_key_env'],
        'identity_version':policy['api_identity_version'],'profile':policy['api_profile']}
    submission=ledger.prepare_submission(lease,{'input':canonical({'fixture':'no external execution',**({'task_input':snapshot} if snapshot else {})})},'fixture',
        identity,now,2,1,1,86400)['submission']
    ledger.record_admission(lease,submission['id'],'validation-fixture-no-native-run','completed',now)
    ledger.record_attempt_result(lease,submission['id'],checked,now)
    ledger.finish(lease,checked,'failed',True,now,expected_submission_id=submission['id'])
    return goal['id']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root',required=True,type=Path)
    parser.add_argument('--hermes-command')
    parser.add_argument('--image',required=True)
    parser.add_argument('--paid',action='store_true')
    parser.add_argument('--learning',action='store_true',help='With --paid: real strategy generation plus one real Docker goal from a labeled failure fixture')
    parser.add_argument('--skills',action='store_true',help='With --paid: independently evaluated program and transcript-verified native execution')
    parser.add_argument('--replay',action='store_true',help='With --paid --skills: frozen input and original-goal field regression')
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    if args.learning and not args.paid:parser.error('--learning requires --paid')
    if args.skills and not args.paid:parser.error('--skills requires --paid')
    if args.replay and not (args.paid and args.skills):parser.error('--replay requires --paid --skills')
    if args.paid and not os.environ.get('DEEPSEEK_API_KEY'):raise RuntimeError('provider_binding_missing')
    revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.run(['git','-C',str(ROOT),'diff','--quiet'],check=False).returncode!=0
    report={'scenario':'finite-native-supervised-runtime','paid':args.paid,'provider_validation':'not_called',
        'code_revision':revision,'code_dirty':dirty,'learning':args.learning,'skills':args.skills,'replay_origin':args.replay}
    with tempfile.TemporaryDirectory(prefix='zhulong-runtime-smoke-') as tmp:
        base=Path(tmp);work=base/'work';work.mkdir()
        (work/'facts.json').write_text(json.dumps({'component':'isolated-runtime-demo','report_status':'missing','observations':[2,4] if args.replay else [1,2,3]}))
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        policy={'mission':'Discover the missing local engineering report from source facts. Create one report using terminal tools and the configured acceptance contract. Do only this local demo work.',
            'daily_runs':2 if args.learning or args.skills else 1,'max_attempts':1,'tick_interval_seconds':2,'lease_seconds':20,'run_deadline_seconds':180,
            'request_timeout_seconds':5,'sources':[{'id':'runtime-demo','domain':'code','path':str(work/'facts.json'),
                'contracts':{'report':{'type':'file_contains','path':str(work/'report.txt'),'text':'verified-runtime-report','require_change':True}}}]}
        if args.skills:
            policy['sources'][0]['contracts']['report']={'type':'json_equals','path':str(work/'report.txt'),'field':'sum','value':6,'require_change':True}
            policy['executable_skills']=[{'id':'sum-observations','source_id':'runtime-demo','contract_id':'report',
                'description':'Input is a JSON object with an observations list of integers and possibly unrelated metadata. Output exactly a JSON object with sum equal to their sum; an empty list has sum 0.',
                'image':args.image,'examples':[{'input':{'observations':[1,2]},'output':{'sum':3}}],
                'holdout':[{'input':{'observations':[]},'output':{'sum':0}},
                           {'input':{'observations':[-5,2]},'output':{'sum':-3}}]}]
            if args.replay:
                policy['sources'][0].update(input_fields=['observations'],persist_input_fields=['observations'])
                policy['executable_skills'][0]['replay_origin']=True
            source=work/'.zhulong-input-INPUT_HASH.json' if args.replay else work/'facts.json'
            template=runner_command('CODE_HASH',source,work/'report.txt',input_hash='INPUT_HASH' if args.replay else None)
            policy['mission']='Create the missing JSON report using the published skills binding. Copy its code exactly to .zhulong-skill-<code_hash>.py. '+(
                'Copy task_input.data as compact canonical JSON (sorted keys, no spaces or newline) to .zhulong-input-<input_hash>.json. ' if args.replay else '')+(
                'Then use a separate foreground terminal call containing EXACTLY this command, replacing CODE_HASH with skills code_hash'+
                (' and INPUT_HASH with task_input.input_hash' if args.replay else '')+'. No changes to the command or additional shell commands. Do this once:\n')+template
        command=[args.hermes_command] if args.hermes_command else [sys.executable,str(args.hermes_root/'hermes')]
        manifest=create_deployment(base/'service',work,args.hermes_root,args.image,
            command+['gateway','run','--no-supervise'],policy,port=port)
        deployment=manifest.parent;ledger=Ledger(deployment/'profile/zhulong/autonomy.db')
        fixture_id=None
        if args.learning or args.skills:
            policy=validate_config(read_json(deployment/'profile/zhulong/config.json')['autonomy'],deployment/'profile/zhulong')
            fixture_id=seed_learning_failure(ledger,policy,time.time())
            if args.replay:
                # A new observation of the same inode makes the live goal distinct;
                # the fixture retains its genuine authorized [2,4] projection.
                (work/'facts.json').write_text(json.dumps({'component':'isolated-runtime-demo','report_status':'missing','observations':[1,2,3]}))
            report['learning_origin']='Real mechanical failure of a synthetic settled no-output executor fixture; no provider failure claimed'
        ledger.set_pause(True)
        checked=subprocess.run([sys.executable,str(ROOT/'scripts/runtime.py'),'check','--deployment',str(manifest)],
            capture_output=True,text=True,timeout=150)
        if checked.returncode or json.loads(checked.stdout).get('ok') is not True:raise RuntimeError('standalone_native_check_failed')
        if read_json(deployment/'service/launches.json').get('used',0)!=0:raise RuntimeError('check_reserved_gateway_launch')
        report['standalone_check_passed']=True
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts/runtime.py'),'run','--deployment',str(manifest)],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        success=False
        try:
            status=wait_for(lambda:(s if (s:=read_json(deployment/'service/status.json')).get('state')=='running' else None),180,process)
            health=read_json(deployment/'service/health.json')
            report.update(boundary=read_json(deployment/'service/boundary.json'),
                readiness={'matching_boot':health['boot_id']==status['boot_id'],'controller_live':health['progress']['thread_alive'],'paused':health['status']['paused']})
            duplicate=subprocess.run([sys.executable,str(ROOT/'scripts/runtime.py'),'run','--deployment',str(manifest)],capture_output=True,text=True,timeout=15)
            if duplicate.returncode!=1 or 'deployment_already_locked' not in duplicate.stderr:raise RuntimeError('duplicate_gate_failed')
            report['duplicate_launch_blocked']=True
            if args.paid:
                ledger.set_pause(False)
                def completed():
                    goals=ledger.goals()
                    if goals and goals[0]['state'] in {'failed','blocked','unknown_result'} and goals[0]['id']!=fixture_id:raise RuntimeError('autonomous_goal_'+goals[0]['state']+':'+goals[0]['recovery_reason'])
                    return goals[0] if goals and goals[0]['state']=='succeeded' and goals[0]['submission']['settled'] else None
                goal=wait_for(completed,210,process)
                submission=goal['submission'];identity=submission['execution_identity']
                original=os.environ.get('API_SERVER_KEY')
                try:
                    os.environ['API_SERVER_KEY']=(deployment/'api.key').read_text()
                    replay=RunsClient(identity['api_url'],'API_SERVER_KEY',identity['identity_version']).submit(submission)
                finally:
                    if original is None:os.environ.pop('API_SERVER_KEY',None)
                    else:os.environ['API_SERVER_KEY']=original
                if replay['run_id']!=submission['run_id']:raise RuntimeError('native_replay_changed_run')
                record=ledger.model_records()
                if args.skills:
                    programs=json.loads(submission['request']['input']).get('skills',[])
                    if len(programs)!=1:raise RuntimeError('native_goal_missing_certified_program')
                    program=programs[0];store=SkillStore(ledger,policy['executable_skills'],identity)
                    with ledger._connection() as c:
                        row=c.execute('SELECT report,state FROM skill_versions WHERE id=?',(program['id'],)).fetchone()
                        evaluations=c.execute('SELECT COALESCE(SUM(evaluations),0) FROM skill_evaluation_budget').fetchone()[0]
                    if row is None or row['state']!='active':raise RuntimeError('native_program_not_published')
                    certified=json.loads(row['report'])
                    if certified['verdict'] is not True or certified['passed']!=(4 if args.replay else 3) or not certified['cleanup_confirmed']:raise RuntimeError('native_program_certification_missing')
                    snapshot=goal.get('task_input') if args.replay else None
                    if args.replay and (snapshot is None or certified.get('origin_replay',{}).get('passed') is not True):raise RuntimeError('native_original_regression_missing')
                    source=work/('.zhulong-input-'+snapshot['input_hash']+'.json') if snapshot else work/'facts.json'
                    audited=audit_native_skill(deployment/'profile',submission,program,
                        runner_command(program['code_hash'],source,work/'report.txt',input_hash=snapshot['input_hash'] if snapshot else None),
                        work/('.zhulong-skill-'+program['code_hash']+'.py'),{'sum':6},task_input=snapshot)
                    report['executable_skill']={'code_hash':program['code_hash'],'test_digest':program['scope']['task_digest'],
                        'state':row['state'],'passed_cases':certified['passed'],'cleanup_confirmed':certified['cleanup_confirmed'],
                        'daily_evaluations_reserved':evaluations,'generation_jobs':store.summary()['jobs'],**audited}
                    if args.replay:report['executable_skill'].update(origin_replay=certified['origin_replay'],evaluation_digest=certified['evaluation_digest'])
                if args.learning:
                    binding=json.loads(submission['request']['input']).get('experience',[])
                    summary=ExperienceStore(ledger).summary()
                    if len(binding)!=1 or not summary['strategies']:raise RuntimeError('native_goal_missing_learned_strategy')
                    report['experience']={'binding_count':len(binding),'status':summary['strategies'][0]['status'],
                        'guidance_hash':binding[0]['body_hash'],'heldout_successes':summary['strategies'][0]['heldout_successes'],
                        'generation_jobs':summary['jobs'],'paid_goal_first_attempt':submission['attempt']==1,
                        'claim':'One prospective use, not activation or causal improvement'}
                report.update(provider_validation='verified_native_run',goal={'state':goal['state'],'attempts':goal['attempts'],
                    'settled':submission['settled'],'runtime':submission['runtime'],'usage':submission['usage'],
                    'native_replay_same_run':True,'verified_receipts':sum(e['outcome']=='succeeded' for e in record['evidence']),
                    'artifact_sha256':hashlib.sha256((work/'report.txt').read_bytes()).hexdigest()})
            with sqlite3.connect(deployment/'profile/zhulong/zhulong.db') as connection:
                report['auxiliary_budget_calls']=connection.execute('SELECT COALESCE(SUM(calls),0) FROM llm_daily').fetchone()[0]
            success=True
        finally:
            stop=subprocess.run([sys.executable,str(ROOT/'scripts/runtime.py'),'stop','--deployment',str(manifest)],capture_output=True,timeout=15)
            try:_,error=process.communicate(timeout=75)
            except subprocess.TimeoutExpired:
                process.kill();process.communicate(timeout=5);raise RuntimeError('supervisor_stop_timeout')
            report['shutdown']=read_json(deployment/'service/status.json')
            # No PIDs/boot IDs or paths needed in shareable evidence.
            for key in ('supervisor_pid','child_pid','supervisor_identity','child_identity','boot_id','updated'):report['shutdown'].pop(key,None)
            report['supervisor_exit_code']=process.returncode
            if success and (stop.returncode!=0 or process.returncode!=0 or report['shutdown'].get('state')!='stopped'):raise RuntimeError('native_shutdown_failed')
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
