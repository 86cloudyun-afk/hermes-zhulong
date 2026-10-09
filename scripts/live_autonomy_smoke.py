"""Bounded paid DeepSeek + actual Zhulong + public Hermes Runs validation.

Use the host PM Python. Generates an isolated test profile and starts only its
own foreground gateway. Does not install a permanent service or write secrets.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root',required=True,type=Path)
    parser.add_argument('--hermes-command',help='Optional external launcher; default uses the current PM interpreter')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();host=args.hermes_root.resolve();repo=Path(__file__).resolve().parents[1]
    if not os.environ.get('DEEPSEEK_API_KEY'):raise RuntimeError('DEEPSEEK_API_KEY binding absent')
    sys.path.insert(0,str(host))
    from gateway.config import Platform
    from toolsets import TOOLSETS
    with tempfile.TemporaryDirectory(prefix='zhulong-live-') as td:
        case=Path(td);home=case/'home';work=case/'work';home.mkdir(mode=0o700);work.mkdir()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=os.environ.copy()
        env.update(HERMES_HOME=str(home),ZHULONG_NO_AUTOSWEEP='1',PYTHONDONTWRITEBYTECODE='1',
            API_SERVER_ENABLED='true',API_SERVER_HOST='127.0.0.1',API_SERVER_PORT=str(port),
            API_SERVER_KEY=secrets.token_urlsafe(32),HERMES_MAX_ITERATIONS='6',HERMES_API_TIMEOUT='60',
            HERMES_RESTART_DRAIN_TIMEOUT='10',HERMES_CRON_DRAIN_TIMEOUT='10')
        platforms={p.value:{'enabled':False} for p in Platform};platforms['api_server']={'enabled':True}
        config={'model':{'provider':'deepseek','default':'deepseek-flash'},
            'providers':{'deepseek':{'api_key_env':'DEEPSEEK_API_KEY','request_timeout_seconds':60,
                'stale_timeout_seconds':60,'models':{'deepseek-flash':{'timeout_seconds':60,'stale_timeout_seconds':60}}}},
            'agent':{'max_turns':6,'run_budget_seconds':120,'restart_drain_timeout':10,'cron_drain_timeout':10},
            'gateway':{'multiplex_profiles':False,'signal_interrupt_grace_timeout':5,'api_server':{'enabled':True,'max_concurrent_runs':1}},
            'platforms':platforms,'terminal':{'backend':'local','cwd':str(work),'timeout':30},
            'platform_toolsets':{'api_server':['file'],'cli':[]},'known_builtin_toolsets':{'api_server':list(TOOLSETS)},
            'approvals':{'mode':'manual','unattended_mode':'deny','timeout':10},'plugins':{'enabled':['zhulong']}}
        (home/'config.yaml').write_text(json.dumps(config))
        marker='verified-'+secrets.token_hex(12)
        (work/'facts.json').write_text(json.dumps({'component':'local-demo','verification_report':'absent','observed_samples':[1,2,3]}))
        data=home/'zhulong';data.mkdir()
        policy={'enabled':True,'mission':'Observe the local demo facts, discover the missing verification report and create it with Hermes tools using its configured contract. Do only this local demo work.',
            'workspace_roots':[str(work)],'api_url':f'http://127.0.0.1:{port}','api_identity_version':'isolated-test-v1',
            'daily_runs':1,'max_attempts':1,'run_deadline_seconds':180,'request_timeout_seconds':10,
            'sources':[{'id':'demo-facts','domain':'code','path':str(work/'facts.json'),
                'contracts':{'verification-report':{'type':'file_contains','path':str(work/'report.txt'),'text':marker,'require_change':True}}}]}
        (data/'config.json').write_text(json.dumps({'scheduler':False,'narrative':False,'llm_daily_cap':2,'autonomy':policy}))
        subprocess.run(['bash',str(repo/'scripts'/'install.sh')],env=env,check=True,capture_output=True)
        driver='''import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import hermes_bootstrap
from hermes_cli.plugins import get_plugin_manager
from tools.registry import registry
manager=get_plugin_manager();manager.discover_and_load()
plugin=next(p for p in manager.list_plugins() if p['name']=='zhulong')
assert plugin['error'] is None and (plugin['hooks'],plugin['tools'],plugin['commands'])==(11,4,1)
sys.path.insert(0,str(Path(sys.argv[2])/'plugins'/'zhulong'))
from autonomy_store import Ledger
from hermes_runs import RunsClient
ledger=Ledger(Path(sys.argv[2])/'zhulong'/'autonomy.db')
deadline=time.monotonic()+180
while time.monotonic()<deadline:
    result=registry.dispatch('zhulong_autonomy',{'action':'tick'},session_id='live-validation')
    result=json.loads(result) if isinstance(result,str) else result
    assert result['ok'],result
    goals=ledger.goals()
    if goals and goals[0]['state']=='succeeded':break
    if goals and goals[0]['state'] in ('failed','blocked','unknown_result'):raise RuntimeError('goal blocked/unknown/failed: '+goals[0]['recovery_reason'])
    time.sleep(.5)
else:raise RuntimeError('autonomy deadline expired')
goal=ledger.goals()[0];submission=goal['submission']
assert goal['attempts']==1 and submission['runtime']['provider']=='deepseek'
client=RunsClient(sys.argv[3],'API_SERVER_KEY','isolated-test-v1',10)
assert client.submit(submission)['run_id']==submission['run_id']
model=json.loads(registry.dispatch('zhulong_model',{},session_id='live-validation'))['model']
assert model['domains']['code']['verified_samples']==1
print(json.dumps({'goal_state':goal['state'],'attempts':goal['attempts'],'runtime':submission['runtime'],
    'usage':submission['usage'],'same_submission_replayed':True,'self_model_samples':model['domains']['code']['verified_samples']}))
'''
        process=None;summary=None
        def caps():
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            try:
                conn.request('GET','/v1/capabilities',headers={'Authorization':'Bearer '+env['API_SERVER_KEY']})
                response=conn.getresponse();body=response.read(65536)
                return response.status,json.loads(body)
            finally:conn.close()
        try:
            with (case/'gateway.log').open('wb') as log:
                launcher=[args.hermes_command] if args.hermes_command else [sys.executable,str(host/'hermes')]
                process=subprocess.Popen([*launcher,'gateway','run'],env=env,cwd=work,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('gateway exited before readiness')
                    try:
                        code,capabilities=caps()
                        if code==200 and capabilities['features']['runs_idempotency']['durable'] is True:break
                    except (OSError,http.client.HTTPException,ValueError):pass
                    time.sleep(.25)
                else:raise RuntimeError('API readiness deadline expired')
                result=subprocess.run([sys.executable,'-B','-c',driver,str(host),str(home),policy['api_url']],
                    env=env,cwd=work,capture_output=True,text=True,timeout=240)
                if result.returncode:
                    # Diagnostic text remains local; provider/API secrets are never serialized.
                    if args.report:
                        args.report.parent.mkdir(parents=True,exist_ok=True)
                        args.report.with_suffix('.driver.log').write_text(result.stdout+result.stderr)
                        args.report.with_suffix('.gateway.log').write_bytes((case/'gateway.log').read_bytes())
                    raise RuntimeError('live controller failed; inspect saved local logs')
                summaries=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                summary=summaries[-1]
                assert (work/'report.txt').is_file() and marker in (work/'report.txt').read_text()
                summary.update(tool_artifact_verified=True,planning='native ctx.llm.complete_structured',
                    provider='deepseek',configured_model='deepseek-flash',host_commit=subprocess.check_output(['git','-C',str(host),'rev-parse','HEAD'],text=True).strip(),
                    limits={'auxiliary_calls':2,'daily_runs':1,'agent_max_turns':6,'provider_timeout_seconds':60,'test_supervisor_seconds':240},
                    scope='One real local code-domain contract; three-domain recovery scenarios covered separately by deterministic tests')
        except Exception:
            if args.report and (case/'gateway.log').exists():
                args.report.parent.mkdir(parents=True,exist_ok=True)
                args.report.with_suffix('.gateway.log').write_bytes((case/'gateway.log').read_bytes())
            raise
        finally:
            if process is not None:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:process.wait(timeout=40)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGTERM)
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                if summary is not None:summary['gateway_exit_code']=process.returncode
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
