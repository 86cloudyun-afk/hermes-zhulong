"""Provider-free verification of the pinned native model/worker boundary."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_policy import child_environment,inspect_worker,load_manifest


def check_names(schemas):
    names=sorted(s['function']['name'] for s in schemas)
    if names!=['process_manage','terminal']:raise ValueError('unexpected_model_tool_surface')
    return names


def check_plugins(plugins):
    loaded=[p for p in plugins if p['enabled'] and p.get('source')!='bundled']
    if len(loaded)!=1 or loaded[0]['name']!='zhulong' or loaded[0]['error']:raise ValueError('native_plugin_unavailable')


def probe(manifest):
    m,policy=load_manifest(manifest)
    env=child_environment(m,'probe',api_key=(Path(m['root'])/'api.key').read_text())
    env.update(ZHULONG_NO_AUTOSWEEP='1')
    env.pop('ZHULONG_SERVICE_DIR',None);env.pop('ZHULONG_BOOT_ID',None)
    os.environ.clear();os.environ.update(env)
    sys.path.insert(0,m['host'])
    import hermes_bootstrap
    from hermes_cli.plugins import get_plugin_manager
    from hermes_cli.tools_config import _get_platform_tools
    from run_agent import AIAgent
    from tools import terminal_tool as terminal
    manager=get_plugin_manager();manager.discover_and_load()
    plugins=manager.list_plugins()
    check_plugins(plugins)
    config=json.loads((Path(m['root'])/'profile/config.yaml').read_text())
    selected=sorted(_get_platform_tools(config,'api_server'))
    agent=AIAgent(model='deepseek-flash',provider='deepseek',api_key='offline-boundary-probe',
        enabled_toolsets=selected,platform='api_server',quiet_mode=True)
    environment=None
    try:
        names=check_names(agent.tools)
        if set(agent.valid_tool_names)!=set(names):raise ValueError('native_valid_names_drift')
        environment=terminal.ensure_task_env('zhulong-probe-'+uuid.uuid4().hex)
        if type(environment).__name__!='DockerEnvironment' or not environment._snapshot_ready:raise ValueError('native_docker_snapshot_unavailable')
        raw=subprocess.check_output(['docker','--host=unix:///var/run/docker.sock','inspect',environment._container_id],text=True)
        boundary=inspect_worker(m,policy,json.loads(raw)[0])
        # Reads only boolean facts and own test files, never credential contents.
        program='''import json,os,socket
from pathlib import Path
checks={}
checks['uid']=os.getuid()
checks['control_absent']=not Path(CONTROL).exists()
checks['docker_socket_absent']=not Path('/var/run/docker.sock').exists()
checks['provider_key_absent']='DEEPSEEK_API_KEY' not in os.environ
checks['capabilities_zero']=next(x.split(':',1)[1].strip() for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('CapEff:'))=='0000000000000000'
for name,path in [('root_readonly','/etc/zhulong-write-probe'),('facts_readonly',FACTS)]:
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT,0o600);os.close(fd);checks[name]=False
    except OSError:checks[name]=True
try:
    socket.create_connection(('127.0.0.1',PORT),timeout=0.2).close();checks['control_api_unreachable']=False
except OSError:checks['control_api_unreachable']=True
checks['no_external_interface']=set(os.listdir('/sys/class/net'))=={'lo'}
artifact=Path(WORK)/ARTIFACT;artifact.write_text('native-docker-verified');checks['work_writable']=artifact.read_text()=='native-docker-verified'
print(json.dumps(checks,sort_keys=True))
'''
        replacements={'CONTROL':str(Path(m['root'])/'profile/zhulong/autonomy.db'),
            'FACTS':policy['sources'][0]['path'],'PORT':m['port'],'WORK':m['work'],
            'ARTIFACT':'.zhulong-probe-'+uuid.uuid4().hex}
        prefix='\n'.join(k+'='+repr(v) for k,v in replacements.items())+'\n'
        result=environment.execute('python -c '+shlex.quote(prefix+program),timeout=30)
        if result.get('returncode')!=0:raise ValueError('worker_execution_probe_failed')
        checks=json.loads(result['output'].strip())
        artifact=Path(m['work'])/replacements['ARTIFACT']
        try:
            if checks.pop('uid')!=os.getuid() or not all(v is True for v in checks.values()):raise ValueError('worker_denial_probe_failed')
            if artifact.read_text()!='native-docker-verified':raise ValueError('worker_bind_write_missing')
        finally:artifact.unlink(missing_ok=True)
        return {'ok':True,'native_revision':m['host_revision'],'model_tools':names,
            'docker':boundary,'denied_action_checks':checks,'external_llm_calls':0}
    finally:
        if environment is not None:environment.cleanup(force_remove=True)
        agent.close()
        manager.unload('zhulong')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(probe(args.deployment),sort_keys=True))
