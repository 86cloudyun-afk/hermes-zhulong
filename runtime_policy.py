"""Protected native deployment policy; model tools cannot edit these controls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
from pathlib import Path

from autonomy_checks import validate_config
from runtime_channel import atomic_json

HOST_REVISION='73162b00eefde3794bed0afb53d84a19c0eed230'
PLUGIN_FILES=('plugin.yaml','__init__.py','storage.py','sensor.py','commands.py',
    'calibrate.py','reflect.py','probes.py','autonomy_store.py','autonomy_checks.py',
    'hermes_runs.py','self_model.py','autonomy.py','runtime_channel.py','experience_store.py','experience.py')
DOCKER_ENV_KEYS=('DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')
CACHE_PATHS=('cache/documents','cache/images','cache/audio','cache/videos','cache/screenshots',
    'cache/web','cache/delegation','cache/spillover','cache/generated','images','attachments','composer-pastes')
OTHER_PLATFORMS=('local','telegram','discord','whatsapp','whatsapp_cloud','slack','signal',
    'mattermost','matrix','email','sms','dingtalk','webhook','msgraph_webhook','feishu','wecom',
    'wecom_callback','weixin','bluebubbles','qqbot','yuanbao','relay')
TMPFS_POLICY={'/tmp':'rw,nosuid,size=512m','/var/tmp':'rw,noexec,nosuid,size=256m',
    '/run':'rw,noexec,nosuid,size=64m','/home':'rw,exec,size=1g',
    '/root':'rw,exec,size=1g','/workspace':'rw,exec,size=10g'}


def overlaps(a,b):
    a,b=Path(a).resolve(),Path(b).resolve()
    return a==b or a.is_relative_to(b) or b.is_relative_to(a)


def validate_manifest(m):
    if m.get('version')!=1 or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',m.get('deployment_id','')):raise ValueError('invalid_deployment')
    if not re.fullmatch(r'[a-zA-Z0-9./_:-]+@sha256:[0-9a-f]{64}',m.get('image','')):raise ValueError('image_digest_required')
    for key in ('root','work','host','plugin_root'):
        path=m.get(key,'')
        if not isinstance(path,str) or not Path(path).is_absolute() or any(c in path for c in ':\r\n\x00'):raise ValueError('invalid_'+key)
        if str(Path(path).resolve())!=path:raise ValueError('unresolved_'+key)
    if not Path(m['work']).is_dir():raise ValueError('work_unavailable')
    for key in ('root','host','plugin_root'):
        if overlaps(m['work'],m[key]):raise ValueError('protected_work_overlap')
    if not isinstance(m.get('command'),list) or not m['command'] or any(not isinstance(s,str) or not s or '\x00' in s for s in m['command']):raise ValueError('invalid_command')
    if not Path(m['command'][0]).is_absolute():raise ValueError('absolute_command_required')
    for key in ('port','max_launches','startup_seconds','shutdown_seconds','progress_seconds'):
        if type(m.get(key)) is not int or m[key]<=0:raise ValueError('invalid_'+key)
    if m['port']>65535:raise ValueError('invalid_port')
    return m


def source_topology(m,sources,base=None):
    work=Path(m['work'])
    if work.is_symlink() or str(work.resolve())!=str(work) or not work.is_dir():raise ValueError('work_topology_changed')
    metadata=work.stat();topology={'work':[metadata.st_dev,metadata.st_ino],'sources':{}}
    for source in sources:
        value=source.get('path') if isinstance(source,dict) else None
        if not isinstance(value,str) or not value or '..' in Path(value).parts:raise ValueError('invalid_source_path')
        path=Path(value)
        if not path.is_absolute():path=Path(base or '.')/path
        if path.parent!=work:raise ValueError('source_must_be_direct_child')
        try:metadata=path.lstat()
        except OSError:raise ValueError('source_file_required') from None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1 or path.resolve()!=path:raise ValueError('source_topology_forbidden')
        topology['sources'][str(path)]=[metadata.st_dev,metadata.st_ino]
    return topology


def validate_worker_policy(m,policy):
    if policy['workspace_roots']!=[m['work']]:raise ValueError('one_authorized_work_root_required')
    topology=source_topology(m,policy['sources'])
    if m.get('source_topology') is not None and topology!=m['source_topology']:raise ValueError('source_topology_changed')
    sources={s['path'] for s in policy['sources']}
    for source in policy['sources']:
        path=Path(source['path'])
        if not path.is_relative_to(Path(m['work'])):raise ValueError('source_outside_work')
        for contract in source['contracts'].values():
            if contract['type'] not in {'file_contains','json_equals'}:raise ValueError('host_code_verification_forbidden')
            if contract['path'] in sources:raise ValueError('source_output_overlap')
    return policy


def native_config(m,policy,boot_id='preflight'):
    volumes=[f"{m['work']}:{m['work']}:rw"]
    volumes += [f"{p}:{p}:ro" for p in sorted({s['path'] for s in policy['sources']})]
    terminal={'backend':'docker','cwd':m['work'],'timeout':30,'docker_image':m['image'],
        'docker_volumes':volumes,'docker_forward_env':[],'docker_env':{'HOME':'/home'},
        'docker_mount_cwd_to_workspace':False,'docker_run_as_host_user':True,
        'docker_network':False,'container_persistent':False,'docker_persist_across_processes':False,
        'docker_shared_container_key':'','docker_orphan_reaper':False,'docker_snap_compat':False,
        'docker_shm_size':'64m','container_cpu':0,'container_memory':0,'container_disk':0,
        'docker_extra_args':['--read-only','--cpus','1','--memory','512m','--memory-swap','512m',
            '--pids-limit','128','--label','zhulong.runtime='+m['deployment_id'],
            '--label','zhulong.boot='+boot_id]}
    return {'model':{'provider':'deepseek','default':'deepseek-flash'},
        'plugins':{'enabled':['zhulong'],'load_timeout_seconds':10},
        'platform_toolsets':{'api_server':['terminal','no_mcp']},
        'known_plugin_toolsets':{'api_server':['zhulong']},'mcp_servers':{},
        'tools':{'tool_search':{'enabled':'off'}},
        'context':{'engine':'compressor'},'credential_files':{},
        'memory':{'memory_enabled':False,'user_profile_enabled':False},
        'agent':{'max_turns':8,'disabled_toolsets':['file','web','code_execution','delegation'],
            'cron_drain_timeout':10},
        'platforms':{**{name:{'enabled':False} for name in OTHER_PLATFORMS},
            'api_server':{'enabled':True,'host':'127.0.0.1','port':m['port']}},
        'gateway':{'multiplex_profiles':False,'api_server':{'max_concurrent_runs':1}},'terminal':terminal}


def child_environment(m,boot_id,inherited=None,*,api_key):
    env=dict(os.environ if inherited is None else inherited)
    for name in list(env):
        if name.startswith('TERMINAL_') or name in DOCKER_ENV_KEYS:env.pop(name,None)
    policy=json.loads((Path(m['root'])/'profile/zhulong/config.json').read_text())['autonomy'] if (Path(m['root'])/'profile/zhulong/config.json').exists() else {'sources':[]}
    for key,value in native_config(m,policy,boot_id)['terminal'].items():
        name='TERMINAL_ENV' if key=='backend' else 'TERMINAL_'+key.upper()
        env[name]=json.dumps(value) if isinstance(value,(list,dict)) else str(value)
    profile=Path(m['root'])/'profile'
    env.update(HERMES_HOME=str(profile),HERMES_RUNTIME_DIR=str(profile/'tools'),
        ZHULONG_NO_AUTOSWEEP='',ZHULONG_SERVICE_DIR=str(Path(m['root'])/'service'),ZHULONG_BOOT_ID=boot_id,
        API_SERVER_KEY=api_key,API_SERVER_HOST='127.0.0.1',API_SERVER_PORT=str(m['port']),
        DOCKER_HOST='unix:///var/run/docker.sock')
    env.pop('HERMES_SAFE_MODE',None)
    return env


def inspect_worker(m,policy,worker):
    config,host=worker['Config'],worker['HostConfig']
    required={'ReadonlyRootfs':True,'NetworkMode':'none','Privileged':False,'PidMode':'',
        'IpcMode':'private','Memory':536870912,'MemorySwap':536870912,'ShmSize':67108864,
        'NanoCpus':1000000000,'PidsLimit':128}
    if any(host.get(k)!=v for k,v in required.items()):raise ValueError('worker_isolation_drift')
    if config.get('User')!=f'{os.getuid()}:{os.getgid()}' or os.getuid()==0:raise ValueError('nonroot_worker_required')
    if config.get('Labels',{}).get('zhulong.runtime')!=m['deployment_id']:raise ValueError('worker_ownership_missing')
    if 'no-new-privileges' not in host.get('SecurityOpt',[]) or 'ALL' not in host.get('CapDrop',[]):raise ValueError('worker_privilege_drift')
    if {s.removeprefix('CAP_') for s in host.get('CapAdd') or []}-{'DAC_OVERRIDE','CHOWN','FOWNER'}:raise ValueError('worker_capability_drift')
    tmpfs=host.get('Tmpfs')
    if (not isinstance(tmpfs,dict) or set(tmpfs)!=set(TMPFS_POLICY)
        or any(not isinstance(tmpfs[p],str) or set(tmpfs[p].split(','))!=set(options.split(','))
            for p,options in TMPFS_POLICY.items())):raise ValueError('worker_tmpfs_drift')
    for item in config.get('Env',[]):
        name=item.split('=',1)[0]
        if name!='GPG_KEY' and re.search(r'KEY|TOKEN|SECRET|PASSWORD|PROXY|DOCKER_HOST',name):raise ValueError('worker_secret_environment')
    expected={(m['work'],m['work'],True)}|{(s['path'],s['path'],False) for s in policy['sources']}
    actual={(v['Source'],v['Destination'],v['RW']) for v in worker.get('Mounts',[]) if v['Type']=='bind'}
    extras=actual-expected;allowed=set()
    for relative in CACHE_PATHS:
        src=Path(m['root'])/'profile'/relative
        if src.is_dir() and str(src.resolve())==str(src):allowed.add((str(src),'/root/.hermes/'+relative,False))
    skills=Path(m['root'])/'profile/skills'
    if skills.is_dir() and not any(skills.iterdir()):allowed.add((str(skills),'/root/.hermes/skills',False))
    if not expected.issubset(actual) or extras-allowed or any(v['Type'] not in {'bind','tmpfs'} for v in worker.get('Mounts',[])):raise ValueError('worker_mount_drift')
    return {'network':'none','uid':os.getuid(),'readonly_root':True,'cpu':1,'memory_bytes':536870912,
        'pids':128,'memory_plus_swap_bytes':536870912,'shm_bytes':67108864,'tmpfs_checked':True,
        'bind_mounts':len(actual),'bind_disk_quota':'not_enforced'}


def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_control_manifest(path):
    """Observation and stop must work when execution inputs are unavailable."""
    path=Path(path);m=json.loads(path.read_text());root=m.get('root')
    if (m.get('version')!=1 or not isinstance(root,str) or not Path(root).is_absolute()
        or Path(root).resolve()!=Path(root) or Path(root)!=path.resolve().parent
        or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',m.get('deployment_id',''))):raise ValueError('invalid_control_manifest')
    return m


def load_manifest(path,verify=True):
    m=validate_manifest(json.loads(Path(path).read_text()))
    profile=Path(m['root'])/'profile'
    raw=json.loads((profile/'zhulong/config.json').read_text())
    policy=validate_worker_policy(m,validate_config(raw['autonomy'],profile/'zhulong'))
    if not raw.get('scheduler') or not policy['enabled']:raise ValueError('background_scheduler_required')
    if verify:
        if subprocess.check_output(['git','-C',m['host'],'rev-parse','HEAD'],text=True).strip()!=m['host_revision']:raise ValueError('host_revision_changed')
        subprocess.run(['git','-C',m['host'],'diff','--quiet'],check=True)
        subprocess.run(['git','-C',m['host'],'diff','--cached','--quiet'],check=True)
        for name,expected in m['hashes'].items():
            if file_hash(name)!=expected:raise ValueError('protected_file_changed')
        if {p.name for p in (profile/'plugins').iterdir()}!={'zhulong'}:raise ValueError('unexpected_plugin')
    return m,policy


def create_deployment(root,work,host,image,command,autonomy,*,port=8642,max_launches=6):
    root,work,host=map(lambda p:Path(p).resolve(),(root,work,host))
    plugin=Path(__file__).resolve().parent
    m={'version':1,'deployment_id':'zhulong-'+secrets.token_hex(8),'root':str(root),'work':str(work),
        'host':str(host),'host_revision':HOST_REVISION,'plugin_root':str(plugin),'image':image,
        'command':command,'port':port,'max_launches':max_launches,'startup_seconds':120,
        'shutdown_seconds':60,'progress_seconds':120,'hashes':{}}
    validate_manifest(m)
    raw=dict(autonomy)
    raw.update(api_url=f'http://127.0.0.1:{port}',api_key_env='API_SERVER_KEY',api_profile='default',
        api_identity_version=m['deployment_id']+'-v1',workspace_roots=[str(work)],enabled=True)
    m['source_topology']=source_topology(m,raw.get('sources',[]),root/'profile/zhulong')
    policy=validate_worker_policy(m,validate_config(raw,root/'profile/zhulong'))
    if any(not Path(s['path']).is_file() for s in policy['sources']):raise ValueError('source_file_required')
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    profile=root/'profile';profile.mkdir(mode=0o700);(root/'service').mkdir(mode=0o700)
    installed=profile/'plugins/zhulong';installed.mkdir(parents=True)
    for name in PLUGIN_FILES:shutil.copyfile(plugin/name,installed/name)
    (profile/'zhulong').mkdir()
    # Empty .env prevents native project-secret fallback; local API key is private.
    (profile/'.env').touch(mode=0o600)
    keyfile=root/'api.key';keyfile.touch(mode=0o600);keyfile.write_text(secrets.token_urlsafe(32))
    atomic_json(profile/'config.yaml',native_config(m,policy))
    atomic_json(profile/'zhulong/config.json',{'scheduler':True,'narrative':False,'probe_weekday':-1,
        'llm_daily_cap':4,'autonomy':raw})
    protected=[profile/'config.yaml',profile/'zhulong/config.json']
    protected += [installed/name for name in PLUGIN_FILES]
    protected += [plugin/name for name in ('runtime_policy.py','runtime_supervisor.py','runtime_channel.py','scripts/runtime_probe.py') if (plugin/name).exists()]
    m['hashes']={str(p):file_hash(p) for p in protected}
    atomic_json(root/'deployment.json',m)
    return root/'deployment.json'
