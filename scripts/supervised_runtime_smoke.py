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
from autonomy_store import Ledger
from hermes_runs import RunsClient
from runtime_channel import read_json
from runtime_policy import create_deployment


def wait_for(predicate,timeout,process):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        if process.poll() is not None:raise RuntimeError('supervisor_exited_before_evidence')
        time.sleep(0.1)
    raise RuntimeError('smoke_deadline_expired')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root',required=True,type=Path)
    parser.add_argument('--hermes-command')
    parser.add_argument('--image',required=True)
    parser.add_argument('--paid',action='store_true')
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    if args.paid and not os.environ.get('DEEPSEEK_API_KEY'):raise RuntimeError('provider_binding_missing')
    revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.run(['git','-C',str(ROOT),'diff','--quiet'],check=False).returncode!=0
    report={'scenario':'finite-native-supervised-runtime','paid':args.paid,'provider_validation':'not_called',
        'code_revision':revision,'code_dirty':dirty}
    with tempfile.TemporaryDirectory(prefix='zhulong-runtime-smoke-') as tmp:
        base=Path(tmp);work=base/'work';work.mkdir()
        (work/'facts.json').write_text(json.dumps({'component':'isolated-runtime-demo','report_status':'missing','observations':[1,2,3]}))
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        policy={'mission':'Discover the missing local engineering report from source facts. Create one report using terminal tools and the configured acceptance contract. Do only this local demo work.',
            'daily_runs':1,'max_attempts':1,'tick_interval_seconds':2,'lease_seconds':20,'run_deadline_seconds':180,
            'request_timeout_seconds':5,'sources':[{'id':'runtime-demo','domain':'code','path':str(work/'facts.json'),
                'contracts':{'report':{'type':'file_contains','path':str(work/'report.txt'),'text':'verified-runtime-report','require_change':True}}}]}
        command=[args.hermes_command] if args.hermes_command else [sys.executable,str(args.hermes_root/'hermes')]
        manifest=create_deployment(base/'service',work,args.hermes_root,args.image,
            command+['gateway','run','--no-supervise'],policy,port=port)
        deployment=manifest.parent;ledger=Ledger(deployment/'profile/zhulong/autonomy.db');ledger.set_pause(True)
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
                    if goals and goals[0]['state'] in {'failed','blocked','unknown_result'}:raise RuntimeError('autonomous_goal_'+goals[0]['state']+':'+goals[0]['recovery_reason'])
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
