"""Frozen native paired adapter. Expected answers remain on the trusted host.

Qualification is derived from actual protected artifacts, not supplied verdicts.
The three-pair pilot supports integration only; provider billing may remain unknown.
"""
from __future__ import annotations
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from autonomy_store import canonical,digest,Ledger
from autonomy_checks import validate_config,DEFAULTS,observe_sources
from causal_trial import TrialLedger
from cohort import Journal,durable_json,durable_bytes,strict_read,host_clock,stamp
from runtime_policy import PLUGIN_FILES,HOST_REVISION,create_deployment,native_config,protected_native_config,paired_bootstrap,load_manifest
from scripts import native_work_acceptance as native
from skill_evaluator import strict_json

ROOT=Path(__file__).resolve().parent
ARMS=('planner_masked','planner_visible')
MONITORING=dict(enabled=True,mode='normal',max_rechecks=1,threshold=.6,constant_probability=.5)
COGNITION=dict(enabled=True,capacity=1,selection_mode='adaptive',ttl_seconds=300,attention_mode='off',attention_constant_probability=.5,attention_max_wait=8,attention_switch_penalty=0.)
CONTROL_FILES=tuple(sorted(set(PLUGIN_FILES)|{'native_trial.py','native_worker_capture.py','cohort.py','runtime_policy.py','runtime_supervisor.py','runtime_channel.py','scripts/runtime.py','scripts/runtime_probe.py','scripts/native_work_acceptance.py','scripts/native_paired_trial.py','scripts/skill_smoke_evidence.py'}))


def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_manifest():return {name:file_sha(ROOT/name) for name in CONTROL_FILES if (ROOT/name).is_file()}


def host_identity(host):
    revision=subprocess.check_output(['git','-C',str(host),'rev-parse','HEAD'],text=True,timeout=10).strip()
    if revision!=HOST_REVISION:raise ValueError('unpinned_native_host')
    for args in (['diff','--quiet'],['diff','--cached','--quiet']):subprocess.run(['git','-C',str(host),*args],check=True,timeout=10)
    names=subprocess.check_output(['git','-C',str(host),'ls-files','-z','*.py','pyproject.toml','uv.lock'],timeout=10).decode().split('\0')
    return {'revision':revision,'files':{name:file_sha(host/name) for name in names if name}}


def validate_fixture(f):
    if not isinstance(f,dict) or set(f)!={'id','reference_id','data'} or not isinstance(f['id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',f['id']):raise ValueError('invalid_fixture')
    # Independently validate the stated input domain. Never execute product oracle.
    refs={'workload_summary_v1':('tasks',{'id','team','minutes','done'}),'ticket_priority_v1':('tickets',{'id','severity','age_hours','blocked'}),'source_index_v1':('sources',{'id','title','url','tags'})}
    if f['reference_id'] not in refs:raise ValueError('unsupported_reference')
    data=f['data'];key,fields=refs[f['reference_id']]
    if not isinstance(data,dict) or set(data)!={key} or not isinstance(data[key],list) or len(data[key])>64 or len(canonical(data).encode())>4096:raise ValueError('invalid_input_domain')
    strict_json(canonical(data));ids=set()
    def text(value,limit=200):
        if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('invalid_input_text')
    def integer(value,low,high):
        if type(value) is not int or not low<=value<=high:raise ValueError('invalid_input_integer')
    for item in data[key]:
        if not isinstance(item,dict) or set(item)!=fields:raise ValueError('invalid_input_fields')
        text(item['id'])
        if item['id'] in ids:raise ValueError('duplicate_input_record')
        ids.add(item['id'])
        if key=='tasks':
            text(item['team']);integer(item['minutes'],0,1000000)
            if type(item['done']) is not bool:raise ValueError('invalid_input_boolean')
        elif key=='tickets':
            integer(item['severity'],1,5);integer(item['age_hours'],0,87600)
            if type(item['blocked']) is not bool:raise ValueError('invalid_input_boolean')
        else:
            text(item['title']);text(item['url'],500)
            if not isinstance(item['tags'],list) or len(item['tags'])>16:raise ValueError('invalid_input_tags')
            for tag in item['tags']:text(tag)
            if len(set(item['tags']))!=len(item['tags']):raise ValueError('duplicate_tag')
    return copy.deepcopy(f)


def independent_oracle(path,fixtures):
    value=strict_read(path)
    if not isinstance(value,dict) or set(value)!={'schema','written_utc','method','fixtures'} or type(value['schema']) is not int or value['schema']!=1 or not all(isinstance(value[k],str) and value[k].strip() for k in ('written_utc','method')):raise ValueError('invalid_independent_oracle')
    if not isinstance(value['fixtures'],list) or len(value['fixtures'])!=len(fixtures):raise ValueError('oracle_scope_mismatch')
    entries={}
    for row in value['fixtures']:
        if not isinstance(row,dict) or set(row)!={'id','reference_id','input_hash','expected','expected_hash'} or row['id'] in entries:raise ValueError('invalid_oracle_entry')
        if not isinstance(row['expected'],dict) or digest(row['expected'])!=row['expected_hash']:raise ValueError('oracle_answer_hash_mismatch')
        strict_json(canonical(row['expected']));entries[row['id']]=row
    for f in fixtures:
        row=entries.get(f['id'],{})
        if row.get('reference_id')!=f['reference_id'] or row.get('input_hash')!=digest(f['data']):raise ValueError('oracle_input_mismatch')
    return value


def arm_policy(work,fixture,arm):
    if arm not in ARMS:raise ValueError('unknown_arm')
    p={**DEFAULTS,**native.work_policy(Path(work),fixture),
       'monitoring':dict(MONITORING),'cognition':dict(COGNITION,mask_consumer='planner' if arm==ARMS[0] else None),
       'diagnostic_daily_evaluations':0,'skill_daily_evaluations':0,'executable_skills':[],'diagnostics':[],'workflows':[]}
    return p


def normalize_policy(policy,m):
    p=copy.deepcopy(policy);work=m['work'];base=str(Path(m['root'])/'profile/zhulong')
    expected={'base':base,'workspace_roots':[work],'api_url':f"http://127.0.0.1:{m['port']}",'api_identity_version':m['deployment_id']+'-v1','api_profile':'default','api_key_env':'API_SERVER_KEY'}
    if any(p.get(k)!=v for k,v in expected.items()):raise ValueError('policy_instance_binding_changed')
    if len(p.get('sources',[]))!=1:raise ValueError('one_frozen_source_required')
    source=p['sources'][0]
    if source.get('path')!=str(Path(work)/'facts.json') or set(source.get('contracts',{}))!={'result'} or source['contracts']['result'].get('path')!=str(Path(work)/'result.json'):raise ValueError('source_role_binding_changed')
    p.update(base='@base',workspace_roots=['@work'],api_url='@loopback',api_identity_version='@deployment-v1')
    source['path']='@work/facts.json';source['contracts']['result']['path']='@work/result.json'
    return p


def normalize_native(config,m):
    value=copy.deepcopy(config);terminal=value.get('terminal',{})
    work=m['work'];expected=[f'{work}:{work}:rw',f'{work}/facts.json:{work}/facts.json:ro']
    if terminal.get('cwd')!=work or terminal.get('docker_volumes')!=expected or value.get('platforms',{}).get('api_server',{}).get('port')!=m['port']:raise ValueError('native_instance_binding_changed')
    if 'docker_extra_args' in terminal or value.get('gateway',{}).get('multiplex_profiles') is not False:raise ValueError('launch_owned_terminal_args_required')
    terminal['cwd']='@work';terminal['docker_volumes']=['@work:@work:rw','@work/facts.json:@work/facts.json:ro']
    value['platforms']['api_server']['port']='@port'
    return value


def declared_launch_args(m,policy):
    args=native_config(m,policy,'@service_boot')['terminal']['docker_extra_args']
    label='zhulong.runtime='+m['deployment_id']
    if args.count(label)!=1:raise ValueError('native_deployment_label_changed')
    args[args.index(label)]='zhulong.runtime=@deployment'
    return args


def declared_controls(fixtures):
    result={}
    with tempfile.TemporaryDirectory(prefix='zhulong-declarations-') as temporary:
        work=Path(temporary);m=dict(root=str(work/'deployment'),work=str(work),deployment_id='declaration',port=8642,image='@image')
        for f in fixtures:
            result[f['id']]={}
            for arm in ARMS:
                p=arm_policy(work,f,arm);p.update(enabled=True,workspace_roots=[str(work)],api_url='http://127.0.0.1:8642',api_key_env='API_SERVER_KEY',api_profile='default',api_identity_version='declaration-v1')
                p=validate_config(p,Path(m['root'])/'profile/zhulong');config=protected_native_config(m,p);config['command_allowlist']=[native.TRUSTED_RUNNER_COMMAND]
                result[f['id']][arm]=dict(policy=normalize_policy(p,m),native=normalize_native(config,m),launch_args=declared_launch_args(m,p),bootstrap='paired_absent_bundled_source_empty_skills',container_purposes={'session':'actual_registered_session','prompt_probe':'prompt-backend-probe'})
    return result


class Deadline:
    def __init__(self,origin,seconds=180,*,clock=host_clock):
        self.origin=stamp(origin);self.seconds=seconds;self.clock=clock
        if type(seconds) not in (int,float) or not 0<seconds<=3600:raise ValueError('invalid_deadline')
    @classmethod
    def start(cls,seconds=180,*,clock=host_clock):return cls(clock(),seconds,clock=clock)
    def remaining(self):
        now=stamp(self.clock());o=self.origin
        if now['boot_id']!=o['boot_id'] or now['monotonic']<o['monotonic'] or abs((now['utc']-o['utc'])-(now['monotonic']-o['monotonic']))>2:raise ValueError('deadline_clock_discontinuity')
        return max(0.,self.seconds-(now['monotonic']-o['monotonic']))
    def call(self,operation):
        remaining=self.remaining()
        if remaining<=0:raise TimeoutError('endpoint_deadline')
        result=operation(remaining)
        if self.remaining()<=0:raise TimeoutError('endpoint_deadline')
        return result
    def record(self):return dict(origin=self.origin,deadline_utc=self.origin['utc']+self.seconds,seconds=self.seconds)


class FrozenTrial:
    @classmethod
    def freeze(cls,root,*,host,image,oracle,fixtures=None,seed=20261011,hermes_command=None):
        fixtures=[validate_fixture(f) for f in (native.business_inputs() if fixtures is None else fixtures)]
        if not 1<=len(fixtures)<=4096 or len({f['id'] for f in fixtures})!=len(fixtures) or len({digest(f['data']) for f in fixtures})!=len(fixtures):raise ValueError('invalid_frozen_inputs')
        if not isinstance(image,str) or not re.fullmatch(r'[a-zA-Z0-9./_:-]+@sha256:[0-9a-f]{64}',image):raise ValueError('image_digest_required')
        oracle=Path(oracle).resolve();answers=independent_oracle(oracle,fixtures);host=Path(host).resolve();host_info=host_identity(host)
        controls=declared_controls(fixtures)
        for arms in controls.values():
            for control in arms.values():control['native']['terminal']['docker_image']=image
        code=code_manifest();scope=dict(goal='three-frozen-business-rules-v1',identity=dict(provider='deepseek',model='deepseek-flash',profile='isolated-default-role',identity_version='actual-per-deployment-v1'),input_scope=digest(fixtures),version=1)
        artifacts={arm:digest({f['id']:controls[f['id']][arm] for f in fixtures}) for arm in ARMS}
        protocol=dict(version=1,mode='paired_fixed_n',seed=seed,fixed_n=len(fixtures),max_attempts=1,deadline_seconds=180,cleanup_grace_seconds=120,
            alpha=.05,stop_rule='fixed_n_only',endpoint='qualified_success_by_deadline_v1',control_arm=ARMS[0],treatment_arm=ARMS[1],
            mechanism=dict(id='planner_visible',version='planner-context-v1',control_artifact_sha256=artifacts[ARMS[0]],treatment_artifact_sha256=artifacts[ARMS[1]]),
            versions=dict(plugin=native._revision(ROOT),host=host_info['revision'],reference=1,reference_checker_sha256=file_sha(__file__),code=code,host_files=host_info['files'],python=dict(version=sys.version,implementation=sys.implementation.name)),
            arms=[dict(id=arm,scope=scope,mechanisms=dict(planner_visible=arm==ARMS[1]),mechanism_version='planner-context-v1',artifact_sha256=artifacts[arm]) for arm in ARMS],
            inputs=[dict(id=f['id'],input_hash=digest(f['data']),reference_id=f['reference_id'],reference_version=1) for f in fixtures],
            declared_controls=controls,host=str(host),image=image,
            runtime_identity_rule=dict(version=1,allowed=[dict(provider='deepseek',model='deepseek-flash')],
                comparison='exact_native_agent_runtime_identity',response_model_equivalence='unasserted',
                basis='Pinned api_server_runs._served_runtime reads actual agent.model/provider and _finish persists runtime; api_server._turn_runtime_metadata uses the same actual pair; no alias remapping is authorized',
                basis_sha256=host_info['files']['gateway/platforms/api_server.py'],
                runs_basis_sha256=host_info['files']['gateway/platforms/api_server_runs.py']),
            launcher=[str(Path(hermes_command).resolve())] if hermes_command else [sys.executable,str(host/'hermes')],
            oracle=dict(schema=1,byte_sha256=file_sha(oracle),canonical_sha256=digest(answers),author_scope=answers['method'],written_utc=answers['written_utc']),
            input_artifacts=[dict(id=f['id'],byte_sha256=hashlib.sha256(canonical(f['data']).encode()).hexdigest(),canonical_sha256=digest(f['data'])) for f in fixtures],
            normalization=dict(version=1,roles=['exact_work','exact_profile_base','exact_deployment_identity','bound_loopback_port'],physical_match='matched logical authorization with distinct physical deployments'),
            safety_stop='unresolved_settlement_or_cleanup',hidden_provider_retries='unknown',preflight_outside_endpoint=True)
        protocol['launcher_sha256']={name:file_sha(name) for name in protocol['launcher']}
        protocol['preflight_budget_seconds']=300
        from native_worker_capture import real_docker_identity
        protocol['worker_capture']=dict(version=2,bootstrap='paired_absent_bundled_source_empty_skills',purposes={'session':'actual_registered_session','prompt_probe':'prompt-backend-probe'},mode='synchronous_creation_inspect',docker=real_docker_identity(),foreground_binding='protected_runner_hostname_and_native_session')
        if len(canonical(protocol).encode())>16*1024*1024:raise ValueError('frozen_protocol_too_large')
        # TrialLedger validates the statistical envelope before any root allocation.
        from causal_trial import validate_protocol
        validate_protocol(protocol)
        journal=Journal.create(root,'native_trial',protocol);root=journal.root
        (root/'inputs').mkdir(mode=0o700)
        durable_json(root/'protocol.json',protocol,exclusive=True)
        durable_bytes(root/'oracle.json',oracle.read_bytes(),exclusive=True)
        for f in fixtures:durable_bytes(root/'inputs'/f"{f['id']}.json",canonical(f['data']).encode(),exclusive=True)
        durable_json(root/'fixtures.json',{'schema':1,'fixtures':fixtures},exclusive=True)
        allocations=TrialLedger(root/'trial.db').preregister(protocol)
        files={str(p.relative_to(root)):file_sha(p) for p in [root/'protocol.json',root/'oracle.json',root/'fixtures.json',*(root/'inputs').iterdir()]}
        with journal.transaction() as c:
            journal.add(c,'files','frozen',files)
            info=(root/'trial.db').stat();journal.add(c,'ledger_identity','frozen',dict(device=info.st_dev,inode=info.st_ino))
            for allocation in allocations:journal.add(c,'allocation',allocation['id'],allocation)
        return cls(root)

    def __init__(self,root):
        self.journal=Journal(root,'native_trial');self.root=self.journal.root
        with self.journal.transaction() as c:
            self.protocol=self.journal.rows(c,'protocol')[0]['payload'];files=self.journal.rows(c,'files')
            if len(files)!=1:raise ValueError('incomplete_freeze')
            self.files=files[0]['payload'];self.allocations=[r['payload'] for r in self.journal.rows(c,'allocation')]
        self.verify_frozen()
        self.fixtures=strict_read(self.root/'fixtures.json')['fixtures']
        self.oracle=independent_oracle(self.root/'oracle.json',self.fixtures)
        identity=self._event('ledger_identity','frozen');info=(self.root/'trial.db').stat()
        if identity!={'device':info.st_dev,'inode':info.st_ino}:raise ValueError('trial_ledger_identity_changed')
        self.ledger=TrialLedger(self.root/'trial.db')
        if self.ledger.preregister(self.protocol)!=self.allocations:raise ValueError('allocation_schedule_changed')

    def verify_frozen(self):
        if any(file_sha(self.root/name)!=value for name,value in self.files.items()):raise ValueError('frozen_file_changed')
        if code_manifest()!=self.protocol['versions']['code']:raise ValueError('frozen_code_changed')
        if self.protocol['versions']['python']!={'version':sys.version,'implementation':sys.implementation.name}:raise ValueError('frozen_python_changed')
        if any(file_sha(name)!=value for name,value in self.protocol['launcher_sha256'].items()):raise ValueError('frozen_launcher_changed')
        if strict_read(self.root/'protocol.json')!=self.protocol:raise ValueError('frozen_protocol_changed')

    def _event(self,kind,key):
        with self.journal.transaction() as c:
            return next((r['payload'] for r in self.journal.rows(c,kind) if r['key']==key),None)
    def _append(self,kind,key,value,*,timeout=5):
        with self.journal.transaction(timeout=timeout) as c:return self.journal.add(c,kind,key,value)
    def allocation(self,allocation_id):
        return next(a for a in self.allocations if a['id']==allocation_id)
    def fixture(self,a):return next(f for f in self.fixtures if f['id']==a['input_id'])
    def base(self,a):return self.root/('allocation-'+str(a['ordinal']))

    def prepare(self,allocation_id):
        self.verify_frozen();a=self.allocation(allocation_id);f=self.fixture(a)
        if self._event('prepared',allocation_id):raise ValueError('allocation_already_prepared')
        base=self.base(a);base.mkdir(mode=0o700,exist_ok=False);work=base/'work';work.mkdir(mode=0o700)
        durable_bytes(work/'facts.json',(self.root/'inputs'/f"{f['id']}.json").read_bytes(),exclusive=True)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        manifest=create_deployment(base/'deployment',work,Path(self.protocol['host']),self.protocol['image'],self.protocol['launcher']+['gateway','run','--no-supervise'],arm_policy(work,f,a['arm']),port=port,max_launches=1)
        native.prepare_trusted_runner(manifest,a['input_hash'],worker_identity=True)
        from native_worker_capture import install
        install(self,a,manifest)
        Ledger(manifest.parent/'profile/zhulong/autonomy.db').set_pause(True)
        value=dict(manifest=str(manifest),manifest_sha256=file_sha(manifest),allocation_id=allocation_id,clock=host_clock())
        self._append('prepared',allocation_id,value);return value

    def inspect_controls(self,allocation_id):
        self.verify_frozen();a=self.allocation(allocation_id);prepared=self._event('prepared',allocation_id)
        if not prepared:raise ValueError('allocation_not_prepared')
        path=Path(prepared['manifest'])
        if path!=self.base(a)/'deployment/deployment.json' or file_sha(path)!=prepared['manifest_sha256']:raise ValueError('actual_manifest_changed')
        m,policy=load_manifest(path)
        if m['host']!=self.protocol['host'] or m['host_revision']!=self.protocol['versions']['host'] or m['plugin_root']!=str(ROOT) or m['image']!=self.protocol['image'] or m['command']!=self.protocol['launcher']+['gateway','run','--no-supervise'] or m['max_launches']!=1:raise ValueError('deployment_scope_changed')
        if m['root']!=str(self.base(a)/'deployment') or m['work']!=str(self.base(a)/'work'):raise ValueError('physical_binding_changed')
        if paired_bootstrap(m) is None:raise ValueError('paired_bootstrap_missing')
        profile=path.parent/'profile';config=strict_read(profile/'config.yaml');plugin=strict_read(profile/'zhulong/config.json')
        if {k:v for k,v in plugin.items() if k!='autonomy'}!={'scheduler':True,'narrative':False,'probe_weekday':-1,'llm_daily_cap':4}:raise ValueError('plugin_controls_changed')
        declared=self.protocol['declared_controls'][a['input_id']][a['arm']]
        actual=dict(policy=normalize_policy(policy,m),native=normalize_native(config,m),launch_args=declared_launch_args(m,policy),bootstrap='paired_absent_bundled_source_empty_skills',container_purposes={'session':'actual_registered_session','prompt_probe':'prompt-backend-probe'})
        if canonical(actual)!=canonical(declared):raise ValueError('actual_arm_controls_changed')
        expected={str(profile/'config.yaml'),str(profile/'zhulong/config.json'),str(profile/native.TRUSTED_RUNNER_RELATIVE)}
        expected.update(str(profile/'plugins/zhulong'/name) for name in PLUGIN_FILES)
        expected.update(str(ROOT/name) for name in ('runtime_policy.py','runtime_supervisor.py','runtime_channel.py','scripts/runtime_probe.py'))
        expected.update({str(ROOT/'native_worker_capture.py'),str(ROOT/'cohort.py'),str(path.parent/'docker-observer'),str(path.parent/'worker-observer-scope.json')})
        if set(m['hashes'])!=expected:raise ValueError('protected_control_set_changed')
        if any(file_sha(profile/'plugins/zhulong'/name)!=self.protocol['versions']['code'][name] for name in PLUGIN_FILES):raise ValueError('installed_control_changed')
        if (profile/native.TRUSTED_RUNNER_RELATIVE).read_text()!=native.trusted_runner_body(a['input_hash'],worker_identity=True):raise ValueError('runner_changed')
        if file_sha(Path(m['work'])/'facts.json')!=a['input_hash']:raise ValueError('actual_input_changed')
        current_host=host_identity(Path(m['host']))
        if current_host['files']!=self.protocol['versions']['host_files']:raise ValueError('host_code_changed')
        return dict(qualified=True,actual_policy_sha256=digest(policy),normalized_controls_sha256=digest(actual),native_config_sha256=file_sha(profile/'config.yaml'),manifest_sha256=file_sha(path),policy=policy,manifest=m)

    def launch_intent(self,allocation_id):
        with self.journal.transaction() as c:
            if any(r['key']==allocation_id for r in self.journal.rows(c,'launch_intent')):raise ValueError('launch_reconciliation_required')
            if not any(r['key']==allocation_id for r in self.journal.rows(c,'prepared')):raise ValueError('allocation_not_prepared')
            a=self.allocation(allocation_id);finished={r['key'] for r in self.journal.rows(c,'receipt')}
            if any(before['id'] not in finished for before in self.allocations[:a['ordinal']]):raise ValueError('allocation_order_not_replayed')
            if self.ledger.summary()['protocol_stopped']:raise ValueError('trial_already_stopped')
            value=dict(allocation_id=allocation_id,attempt=1,clock=host_clock(),owner_pid=os.getpid())
            self.journal.add(c,'launch_intent',allocation_id,value);return value
    def freeze_endpoint(self,allocation_id,value):
        if any(value.get(k) is not None for k in ('business','native','settled','arm_qualified')):
            with self.journal.transaction() as c:
                captures=[r['payload'] for r in self.journal.rows(c,'capture')]
            if not any(x['allocation_id']==allocation_id and x['endpoint_sha256']==digest(value) for x in captures):raise ValueError('untrusted_endpoint_snapshot')
        self._append('endpoint',allocation_id,value)
    def endpoint(self,allocation_id):return self._event('endpoint',allocation_id)
    def append_reconciliation(self,allocation_id,value):self._append('reconciliation',uuid.uuid4().hex,dict(allocation_id=allocation_id,**value))

    def record_result(self,allocation_id,cleanup):
        if cleanup.get('confirmed') is True:
            with self.journal.transaction() as c:captures=[r['payload'] for r in self.journal.rows(c,'cleanup_capture')]
            if not any(x['allocation_id']==allocation_id and x['cleanup_sha256']==digest(cleanup) for x in captures):raise ValueError('untrusted_cleanup_snapshot')
        cleanup_verdict=cleanup.get('confirmed')
        if cleanup_verdict is True:
            try:
                origin=self._event('cleanup_origin',allocation_id)
                if origin is None or cleanup.get('origin')!=origin or cleanup.get('within_grace') is not True:raise ValueError('cleanup_timing_unconfirmed')
                observed=stamp(cleanup['observed'])
                if Deadline(origin,self.protocol['cleanup_grace_seconds'],clock=lambda:observed).remaining()<=0:raise ValueError('cleanup_observed_late')
            except (ValueError,KeyError,TypeError):cleanup_verdict=None
        a=self.allocation(allocation_id);e=self.endpoint(allocation_id)
        if e is None:raise ValueError('endpoint_snapshot_missing')
        arm=next(x for x in self.protocol['arms'] if x['id']==a['arm']);f=self.fixture(a)
        bind={k:a[k] for k in ('arm','input_hash','scope_hash')};bind['allocation_id']=a['id']
        receipt=native._blank_receipt(a);receipt.update(business=e.get('business'),native=e.get('native'),settled=e.get('settled'),cleanup=cleanup_verdict,
            main_usage=e.get('main_usage'),configured_model='deepseek-flash',observed_model=e.get('observed_model'),underlying_model_version='unknown',
            endpoint_sha256=digest(e),qualifiers=e.get('reasons',[]),auxiliary_calls=None,billing=None)
        qualified=e.get('arm_qualified') is True and e.get('timely') is True
        if qualified and type(receipt['business']) is bool and type(receipt['native']) is bool and receipt['settled'] is True and receipt['cleanup'] is True:
            receipt['outcome']='succeeded' if receipt['business'] and receipt['native'] else 'failed'
        proofs={'business':dict(bind,verdict=receipt['business'],reference_id=f['reference_id'],reference_version=1,reference_checker_sha256=self.protocol['versions']['reference_checker_sha256'],oracle_sha256=self.protocol['oracle']['byte_sha256']),
                'native':dict(bind,verdict=receipt['native'],evidence_sha256=digest(e.get('native_evidence'))),
                'quiet':dict(bind,scope='Registered Ledger and Runs settlement observed by endpoint; OS/container absence is separate cleanup',settled=receipt['settled'],started_at=e['origin']['utc'],completed_at=max(e['origin']['utc'],e['observed']['utc']),deadline_at=e['origin']['utc']+180),
                'cleanup':dict(bind,confirmed=cleanup_verdict,evidence_sha256=digest(cleanup)),
                'arm':dict(bind,arm_hash=digest(arm),identity_hash=digest(arm['scope']['identity']),mechanism_version=arm['mechanism_version'],artifact_sha256=arm['artifact_sha256'],actual=e.get('controls'))}
        if qualified:
            receipt.update({key+'_receipt':value for key,value in proofs.items()});receipt['proof_hashes']={key:digest(value) for key,value in proofs.items()}
        self._append('receipt',allocation_id,receipt);self.ledger.record(allocation_id,receipt)
        if receipt['settled'] is not True or receipt['cleanup'] is not True:self.ledger.stop('unconfirmed_execution_quiescence')
        return receipt

    def summary(self):
        self.verify_frozen();self._repair_receipts(repair=False);r=self.ledger.summary()
        # Portable report excludes raw controls, source documents, private paths
        # and oracle answers. Full protocol remains private in protocol.json.
        r['protocol']={k:v for k,v in r['protocol'].items() if k in ('version','mode','seed','fixed_n','alpha','control_arm','treatment_arm','endpoint','deadline_seconds','cleanup_grace_seconds','stop_rule','mechanism','arms','inputs')}
        r.update(estimand='planner_visible minus planner_masked',physical_match=self.protocol['normalization']['physical_match'],underlying_model_version='unknown',claim='Native integration only for three pairs; no usefulness, significance, or continuous-liveness assertion')
        return r

    def qualify_artifacts(self,allocation_id):
        """Reread actual evidence. No caller success booleans enter qualification."""
        a=self.allocation(allocation_id);result=dict(business=None,native=None,settled=None,planner_qualified=None,arm_qualified=None,main_usage=None,billing=None,auxiliary_calls=None,observed_model=None,response_observed_model=None,reasons=[])
        try:controls=self.inspect_controls(allocation_id)
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            result['reasons'].append(error_code(exc,'controls_unavailable'));return result
        m=controls['manifest'];policy=controls['policy'];profile=Path(m['root'])/'profile';work=Path(m['work'])
        result['controls']={k:v for k,v in controls.items() if k not in ('policy','manifest')}
        result['configured_model']='deepseek-flash'
        from scripts.skill_smoke_evidence import read_db,audit_native_skill
        try:
            with read_db(profile/'zhulong/autonomy.db') as c:
                c.execute('BEGIN')
                rows=c.execute('SELECT * FROM goals').fetchall()
                if len(rows)!=1:raise ValueError('one_goal_required')
                obj=object.__new__(Ledger);goal=obj._goal(c,rows[0]);sub=goal.get('submission')
                if not sub or c.execute('SELECT COUNT(*) FROM submissions').fetchone()[0]!=1:raise ValueError('one_submission_required')
                expected_identity=dict(api_url=policy['api_url'],credential_env=policy['api_key_env'],identity_version=policy['api_identity_version'],profile=policy['api_profile'])
                if sub['execution_identity']!=expected_identity or sub['session_key']!='zhulong-'+goal['id'] or sub['attempt']!=1:raise ValueError('actual_execution_identity_changed')
                observed=observe_sources(policy)[0];snapshot=observed.get('task_input')
                if snapshot is None or snapshot!=goal['task_input'] or snapshot['input_hash']!=a['input_hash'] or goal['source_id']!=observed['id'] or goal['source_revision']!=observed['revision'] or goal['contract']!=policy['sources'][0]['contracts']['result']:raise ValueError('actual_frozen_binding_changed')
                intent=strict_json(sub['request']['input'],max_depth=34)
                if (intent.get('task_input')!=snapshot or intent.get('acceptance_contract')!=goal['contract'] or intent.get('mission')!=policy['mission']
                        or intent.get('source_path')!=str(work/'facts.json') or intent.get('workspace_roots')!=[str(work)]
                        or any(k in intent for k in ('program_binding','skills','experience','workflow_step'))
                        or 'program_bundle' in goal['contract']):raise ValueError('actual_prepared_request_changed')
                result['binding']={k:sub[k] for k in ('id','run_id','session_key','goal_id')}
                result['binding'].update(normalized_contract_sha256=digest(normalize_policy(policy,m)['sources'][0]['contracts']['result']),normalized_identity_sha256=digest(dict(api_url='@loopback',credential_env='API_SERVER_KEY',identity_version='@deployment-v1',profile='default')),rule_sha256=snapshot['rule_hash'],request_sha256=digest(sub['request']),identity_sha256=digest(sub['execution_identity']),input_sha256=snapshot['input_hash'],source_revision=observed['revision'],contract_sha256=digest(goal['contract']))
                registered=self._event('endpoint_origin',allocation_id)
                if registered is not None and not registered['origin']['utc']<=sub['created']<=registered['deadline_utc']:raise ValueError('submission_outside_registered_endpoint')
                result['main_usage']=sub.get('usage');runtime=sub.get('runtime') or {};result['observed_model']=runtime.get('model');result['native_runtime_provider']=runtime.get('provider');result['observed_model_source']='native_runs_runtime_metadata'
                # Runtime metadata is not a provider response version assertion.
                result['response_observed_model']=None
                if runtime.get('provider') not in (None,'deepseek'):raise ValueError('actual_provider_changed')
                runtime_qualified={k:runtime.get(k) for k in ('provider','model')} in self.protocol['runtime_identity_rule']['allowed']
                if runtime.get('model') is not None and not runtime_qualified:result['reasons'].append('actual_model_changed')
                frame_row=c.execute('SELECT f.frame,f.frame_hash FROM cognition_bindings b JOIN cognition_frames f USING(frame_id) WHERE b.goal_id=?',(goal['id'],)).fetchone()
                receipts=[json.loads(r[0]) for r in c.execute('SELECT receipt FROM cognition_receipts')]
                try:
                    if frame_row is None:raise ValueError('planner_frame_missing')
                    frame=json.loads(frame_row[0])
                    from cognition import MECHANISM
                    entry=dict(source_id=observed['id'],revision=observed['revision'],input_hash=snapshot['input_hash'],facts_hash=digest(observed['facts']))
                    if registered is not None and not registered['origin']['utc']<=frame['captured_at']<=registered['deadline_utc']:raise ValueError('planner_outside_registered_endpoint')
                    if (digest(frame)!=frame_row[1] or frame['entries']!=[entry] or frame['identity_hash']!=digest(expected_identity)
                            or frame['policy']!=policy['cognition'] or frame['policy_hash']!=digest(policy['cognition']) or frame['mechanism_hash']!=digest(MECHANISM)
                            or frame['expires_at']!=frame['captured_at']+300):raise ValueError('planner_frame_binding_changed')
                    def packet(consumer):
                        masked=frame['policy']['mask_consumer']==consumer
                        return dict(schema=1,frame_id=frame['frame_id'],frame_hash=digest(frame),identity_hash=frame['identity_hash'],policy_hash=frame['policy_hash'],mechanism_hash=frame['mechanism_hash'],captured_at=frame['captured_at'],expires_at=frame['expires_at'],historical=consumer!='planner',consumer=consumer,visibility='masked' if masked else 'visible',entries=[] if masked else frame['entries'],forecast=None if masked else frame['forecast'],limitations=dict(MECHANISM))
                    delivered={k:observed[k] for k in ('id','domain','contract_ids','available','revision')}
                    if a['arm']=='planner_visible':delivered.update(facts=observed['facts'],task_input=snapshot)
                    payload=dict(observations=[delivered],context=dict(current_execution_identity=expected_identity,workspace=packet('planner')),policy=policy)
                    planners=[r for r in receipts if r['channel']=='planner_method']
                    if len(planners)!=1 or planners[0]['frame_id']!=frame['frame_id'] or planners[0]['payload_hash']!=digest(payload) or not frame['captured_at']<=planners[0]['created_at']<frame['expires_at']:raise ValueError('planner_delivery_mismatch')
                    prepared=[r for r in receipts if r['channel']=='executor_prepared' and r['submission_id']==sub['id'] and r['goal_id']==goal['id']]
                    if len(prepared)!=1 or prepared[0]['frame_id']!=frame['frame_id'] or prepared[0]['payload_hash']!=digest(sub['request']) or intent.get('cognitive_workspace')!=packet('executor'):raise ValueError('executor_delivery_mismatch')
                    result.update(planner_qualified=True,planner_payload_sha256=digest(payload),executor_request_sha256=digest(sub['request']))
                except (ValueError,KeyError,TypeError) as exc:result['reasons'].append(error_code(exc,'planner_evidence_unavailable'))
            # Read an actual terminal artifact, never a supplied verifier verdict.
            try:
                output=bounded_regular(work/'result.json',65536);value=strict_json(output.decode())
                expected=next(x['expected'] for x in self.oracle['fixtures'] if x['id']==a['input_id'])
                result.update(business=canonical(value)==canonical(expected),artifact_sha256=hashlib.sha256(output).hexdigest(),artifact_canonical_sha256=digest(value))
            except (OSError,ValueError,UnicodeError) as exc:result['reasons'].append(error_code(exc,'business_artifact_unavailable'));value=None
            try:
                # Runs settlement requires actual durable native record, not ACK.
                with read_db(profile/'runs_idempotency.db') as c:
                    rows=c.execute('SELECT fingerprint,status_json FROM run_idempotency WHERE idempotency_key=? AND run_id=?',(sub['id'],sub['run_id'])).fetchall()
                if len(rows)!=1 or rows[0]['fingerprint']!=digest({'body':sub['request'],'gateway_session_key':sub['session_key']}):raise ValueError('native_run_binding_missing')
                status=strict_json(rows[0]['status_json'])
                runs_runtime=status.get('runtime')
                if runs_runtime:
                    if not isinstance(runs_runtime,dict) or any(runs_runtime.get(k)!=runtime.get(k) for k in ('provider','model')):
                        runtime_qualified=False
                        raise ValueError('runs_runtime_identity_mismatch')
                terminal=status.get('run_id')==sub['run_id'] and status.get('status') in ('completed','failed','cancelled','interrupted')
                result['settled']=True if terminal and sub['settled'] is True else None
                result['runs_status_sha256']=digest(status)
                if result['settled'] is not True:result['reasons'].append('runs_settlement_unconfirmed')
                if value is not None:
                    code=bounded_regular(work/'.zhulong-work.py',1048576)
                    result['native_evidence']=audit_native_skill(profile,sub,{'code':code.decode(),'code_hash':hashlib.sha256(code).hexdigest()},native.TRUSTED_RUNNER_COMMAND,work/'.zhulong-work.py',value,task_input=snapshot,worker_identity=True)
                    result['native']=True
            except (OSError,ValueError,RuntimeError,sqlite3.Error,UnicodeError) as exc:result['reasons'].append(error_code(exc,'native_transcript_unavailable'))
            with self.journal.transaction() as c:
                launches={r['key']:r['payload'] for r in self.journal.rows(c,'worker_launch') if r['payload']['allocation_id']==allocation_id}
                workers={r['key']:r['payload'] for r in self.journal.rows(c,'worker') if r['payload']['allocation_id']==allocation_id}
            try:
                if not workers:raise ValueError('actual_worker_unobserved')
                if set(launches)!=set(workers):raise ValueError('actual_worker_capture_incomplete')
                from runtime_policy import inspect_worker
                matches=[];seen=set()
                for key,worker in workers.items():
                    cid=worker['container_id']
                    if not isinstance(cid,str) or not re.fullmatch('[a-f0-9]{64}',cid) or cid in seen:raise ValueError('actual_worker_identity_ambiguous')
                    seen.add(cid)
                    raw=strict_read(self.base(a)/'worker-captures'/(worker['container_id']+'.json'));labels=raw['Config']['Labels']
                    launch=launches[key]
                    if (digest(raw)!=worker['worker_sha256'] or raw.get('Id')!=worker['container_id'] or labels.get('zhulong.boot')!=worker['service_boot_id']
                            or worker['service_boot_id'] in ('probe','preflight') or worker.get('purpose') not in ('session','prompt_probe')
                            or worker.get('task_label')!=(sub['session_key'] if worker['purpose']=='session' else 'prompt-backend-probe')
                            or labels.get('hermes-task-id')!=worker['task_label']
                            or worker['session_id']!=sub['session_key'] or worker['submission_id']!=sub['id'] or worker['run_id']!=sub['run_id']
                            or worker['manifest_sha256']!=file_sha(self.base(a)/'deployment/deployment.json')
                            or any(launch.get(k)!=worker.get(k) for k in ('service_boot_id','owner','session_id','submission_id','run_id','purpose','task_label'))):raise ValueError('actual_worker_binding_changed')
                    if raw.get('Config',{}).get('Image')!=m['image']:raise ValueError('actual_worker_image_changed')
                    if registered is None or not registered['origin']['utc']<=worker['created_utc']<=worker['clock']['utc']<=registered['deadline_utc']:raise ValueError('actual_worker_capture_late')
                    for observed in (launch['clock'],worker['clock']):
                        if Deadline(registered['origin'],180,clock=lambda:observed).remaining()<=0:raise ValueError('actual_worker_capture_late')
                    if launch['clock']['monotonic']>worker['clock']['monotonic'] or raw['Config'].get('Hostname')!=cid[:12]:raise ValueError('actual_worker_binding_changed')
                    boundary=inspect_worker(m,policy,raw)
                    if worker['purpose']=='session' and raw['Config'].get('Hostname')==result.get('native_evidence',{}).get('worker_hostname'):
                        matches.append(dict(container_id=worker['container_id'],worker_sha256=worker['worker_sha256'],**boundary))
                if len(matches)!=1:raise ValueError('foreground_worker_binding_missing')
                result['worker_boundary']=matches[0]
            except (OSError,ValueError,KeyError) as exc:result['reasons'].append(error_code(exc,'actual_worker_unavailable'))
            if result['observed_model'] is None:result['reasons'].append('native_runtime_model_unknown')
            if runtime.get('provider') is None:result['reasons'].append('native_runtime_provider_unknown')
            if result['planner_qualified'] is True and 'worker_boundary' in result and runtime_qualified:result['arm_qualified']=True
        except (OSError,ValueError,RuntimeError,sqlite3.Error,KeyError,TypeError) as exc:result['reasons'].append(error_code(exc,'native_evidence_unavailable'))
        return result

    def capture_endpoint(self,allocation_id,deadline):
        """Bound the entire audit process and timestamp after completion.

        This child is a local read-only artifact inspector, never a native agent.
        A timeout or overrun discards all positive axes from that late audit.
        """
        output=self.base(self.allocation(allocation_id))/('audit-'+uuid.uuid4().hex+'.json')
        blank=dict(origin=deadline.origin,observed=host_clock(),business=None,native=None,settled=None,arm_qualified=None,timely=False,reasons=[])
        try:
            registered=self._event('endpoint_origin',allocation_id)
            if registered!=deadline.record() or deadline.seconds!=180:raise ValueError('endpoint_origin_changed')
            command=[sys.executable,str(ROOT/'scripts/native_paired_trial.py'),'_audit','--root',str(self.root),'--allocation',allocation_id,'--output',str(output)]
            def audit(timeout):
                result=subprocess.run(command,capture_output=True,timeout=timeout)
                if result.returncode:raise ValueError('local_artifact_audit_failed')
                return strict_read(output)
            value=deadline.call(audit)
            observed=stamp(deadline.clock())
            if deadline.remaining()<=0:raise TimeoutError('endpoint_deadline')
            value.update(origin=deadline.origin,observed=observed,timely=True,audit_file_sha256=file_sha(output))
            deadline.call(lambda remaining:self._append('capture',output.name,dict(allocation_id=allocation_id,endpoint_sha256=digest(value),audit_file_sha256=file_sha(output)),timeout=remaining))
            return value
        except (OSError,ValueError,TimeoutError,subprocess.SubprocessError) as exc:
            blank.update(observed=stamp(deadline.clock()),reasons=[error_code(exc,'audit_deadline_or_unavailable')]);return blank

    def _docker(self,args,deadline):
        from runtime_policy import DOCKER_ENV_KEYS
        env=dict(os.environ)
        for key in DOCKER_ENV_KEYS:env.pop(key,None)
        env['DOCKER_HOST']='unix:///var/run/docker.sock'
        return deadline.call(lambda remaining:subprocess.run(['docker','--host=unix:///var/run/docker.sock',*args],env=env,capture_output=True,text=True,check=True,timeout=min(remaining,3)))

    def _poll_settlement(self,a,deadline):
        from scripts.skill_smoke_evidence import read_db
        # The read-only connection has its timeout clamped to the SAME budget.
        def poll(remaining):
            with read_db(self.base(a)/'deployment/profile/zhulong/autonomy.db') as c:
                c.execute('PRAGMA busy_timeout='+str(max(1,int(min(remaining,.1)*1000))))
                goals=c.execute('SELECT id,state FROM goals').fetchall()
                submissions=c.execute('SELECT id,run_id,settled FROM submissions').fetchall()
            if len(goals)>1 or len(submissions)>1:raise ValueError('multiple_unregistered_runs')
            return bool(goals and submissions and submissions[0]['settled'] and goals[0]['state'] in ('succeeded','failed','blocked','unknown_result','cancelled'))
        return deadline.call(poll)

    def _cleanup_observation(self,a,deadline):
        from runtime_channel import read_json,process_identity
        m=strict_read(self.base(a)/'deployment/deployment.json');state=read_json(Path(m['root'])/'service/status.json')
        runtime_ids=self._docker(['ps','-aq','--filter','label=zhulong.runtime='+m['deployment_id']],deadline).stdout.split()
        namespace=hashlib.sha256(str(Path(m['root'])/'profile/zhulong/autonomy.db').encode()).hexdigest()[:20]
        evaluator_ids=self._docker(['ps','-aq','--filter','label=zhulong.eval='+namespace],deadline).stdout.split()
        identities={name:state.get(name) for name in ('supervisor_identity','child_identity')}
        owner=self._event('process',a['id'])
        if owner:identities['allocated_supervisor']=owner['identity']
        actual={name:process_identity(identity.get('pid')) if isinstance(identity,dict) else 'unknown' for name,identity in identities.items()}
        absent=bool(owner) and all(value is None or value!=identities[name] for name,value in actual.items() if value!='unknown') and all(value!='unknown' for value in actual.values())
        confirmed=state.get('state')=='stopped' and absent and not runtime_ids and not evaluator_ids
        return dict(confirmed=confirmed if confirmed else None,clock=host_clock(),scope='Actual owned supervisor/child identities and runtime/evaluator containers after shutdown',service_state=state.get('state'),processes_absent=absent,owned_runtime_count=len(runtime_ids),owned_evaluator_count=len(evaluator_ids),status_sha256=digest(state))

    def _cleanup(self,a,process=None):
        from runtime_channel import read_json,process_identity
        existing=self._event('cleanup_origin',a['id'])
        if existing is None:
            now=host_clock();endpoint=self.endpoint(a['id']);start=self._event('endpoint_origin',a['id'])
            if start:
                ceiling=dict(start['origin']);ceiling['utc']+=180;ceiling['monotonic']+=180
                observed=(endpoint or {}).get('observed',now)
                existing=observed if observed['boot_id']==ceiling['boot_id'] and observed['monotonic']<=ceiling['monotonic'] else ceiling
            else:
                # Startup is outside the endpoint but still has a frozen bound.
                intent=self._event('launch_intent',a['id']);ceiling=dict(intent['clock'])
                ceiling['utc']+=300;ceiling['monotonic']+=300
                existing=now if now['boot_id']==ceiling['boot_id'] and now['monotonic']<=ceiling['monotonic'] else ceiling
            self._append('cleanup_origin',a['id'],existing)
        deadline=Deadline(existing,self.protocol['cleanup_grace_seconds']);result=dict(confirmed=None,origin=existing,reasons=[])
        manifest=self.base(a)/'deployment/deployment.json'
        try:
            # Stop addresses one protected deployment. It requests admission close
            # and runtime cancellation; ACK is never itself cleanup evidence.
            deadline.call(lambda remaining:subprocess.run([sys.executable,str(ROOT/'scripts/runtime.py'),'stop','--deployment',str(manifest)],capture_output=True,check=True,timeout=min(remaining,5)))
            if process is not None:
                try:deadline.call(lambda remaining:process.wait(timeout=max(.001,remaining-5)))
                except subprocess.TimeoutExpired:
                    owner=self._event('process',a['id'])
                    if owner and process_identity(process.pid)==owner['identity'] and deadline.remaining()>0:
                        process.terminate();deadline.call(lambda remaining:process.wait(timeout=remaining))
            else:
                while deadline.remaining()>0:
                    state=read_json(manifest.parent/'service/status.json')
                    if state.get('state') in ('stopped','failed') or not self._event('process',a['id']):break
                    time.sleep(min(.2,deadline.remaining()))
            result.update(self._cleanup_observation(a,deadline))
            result['observed']=host_clock()
            if deadline.remaining()<=0:
                result['late_observation']={k:v for k,v in result.items() if k not in ('origin','reasons')}
                raise TimeoutError('cleanup_observed_late')
            result['within_grace']=True
        except (OSError,ValueError,TimeoutError,subprocess.SubprocessError) as exc:
            result['reasons'].append(error_code(exc,'cleanup_unavailable'))
            if result.get('confirmed') is True:
                result.setdefault('late_observation',{k:v for k,v in result.items() if k not in ('origin','reasons','late_observation')})
            # Late local reconciliation gets a bounded status/stop read; it does
            # not replenish the original grace or qualify its cleanup endpoint.
            try:
                late=Deadline(host_clock(),10)
                late.call(lambda remaining:subprocess.run([sys.executable,str(ROOT/'scripts/runtime.py'),'stop','--deployment',str(manifest)],capture_output=True,check=True,timeout=min(remaining,3)))
                result['late_reconciliation']=self._cleanup_observation(a,late)
            except (OSError,ValueError,TimeoutError,subprocess.SubprocessError):result['late_reconciliation']={'confirmed':None}
            result['confirmed']=None;result['within_grace']=False
        result.setdefault('observed',host_clock())
        self._append('cleanup_capture',uuid.uuid4().hex,dict(allocation_id=a['id'],cleanup_sha256=digest(result)))
        self.append_reconciliation(a['id'],dict(kind='cleanup',**result))
        return result

    def _run_allocation(self,allocation_id):
        a=self.allocation(allocation_id);prepared=self._event('prepared',allocation_id)
        if prepared is None:prepared=self.prepare(allocation_id)
        controls=self.inspect_controls(allocation_id);m=controls['manifest'];policy=controls['policy'];manifest=Path(prepared['manifest'])
        self.launch_intent(allocation_id);process=None;endpoint=None;deadline=None
        log_path=self.base(a)/'supervisor.log'
        with log_path.open('xb') as log:
            os.chmod(log_path,0o600)
            try:
                runtime=[sys.executable,str(ROOT/'scripts/runtime.py')]
                checked=subprocess.run(runtime+['check','--deployment',str(manifest)],stdout=log,stderr=log,timeout=150)
                if checked.returncode:raise ValueError('native_preflight_failed')
                process=subprocess.Popen(runtime+['run','--deployment',str(manifest)],stdout=log,stderr=log,start_new_session=True)
                from runtime_channel import read_json,process_identity
                self._append('process',allocation_id,dict(identity=process_identity(process.pid),clock=host_clock()))
                readiness=Deadline.start(150)
                def ready():
                    status=read_json(manifest.parent/'service/status.json');health=read_json(manifest.parent/'service/health.json')
                    return status.get('state')=='running' and status.get('boot_id')==health.get('boot_id') and health.get('progress',{}).get('thread_alive') is True
                while not readiness.call(lambda _:ready()):
                    if process.poll() is not None:raise ValueError('supervisor_exited_before_endpoint')
                    time.sleep(min(.2,readiness.remaining()))
                # Persist origin BEFORE unpause. Every operation from here consumes
                # the same monotonic bound, including discovery and final audit.
                deadline=Deadline.start(180);self._append('endpoint_origin',allocation_id,deadline.record(),timeout=deadline.remaining())
                deadline.call(lambda _:durable_json(self.base(a)/'worker-endpoint.json',deadline.record(),exclusive=True))
                ledger=object.__new__(Ledger);ledger.path=manifest.parent/'profile/zhulong/autonomy.db';ledger.timeout=min(.1,deadline.remaining())
                deadline.call(lambda _:ledger.set_pause(False))
                while deadline.remaining()>0:
                    if self._poll_settlement(a,deadline):break
                    if process.poll() is not None:raise ValueError('supervisor_exited_at_endpoint')
                    time.sleep(min(.2,deadline.remaining()))
                endpoint=self.capture_endpoint(allocation_id,deadline)
            except (OSError,ValueError,TimeoutError,subprocess.SubprocessError) as exc:
                origin=deadline.origin if deadline else (self._event('launch_intent',allocation_id) or {})['clock']
                endpoint=dict(origin=origin,observed=host_clock(),business=None,native=None,settled=None,arm_qualified=None,timely=False,reasons=[error_code(exc,'native_execution_unavailable')])
            finally:
                if endpoint is None:endpoint=dict(origin=deadline.origin if deadline else host_clock(),observed=host_clock(),business=None,native=None,settled=None,arm_qualified=None,timely=False,reasons=['interrupted_native_controller'])
                try:self.freeze_endpoint(allocation_id,endpoint)
                finally:cleanup=self._cleanup(a,process)
                self.record_result(allocation_id,cleanup)
        return self._event('receipt',allocation_id)

    def _repair_receipts(self,*,repair=True):
        identity=self._event('ledger_identity','frozen');info=(self.root/'trial.db').stat()
        if identity!={'device':info.st_dev,'inode':info.st_ino}:raise ValueError('trial_ledger_identity_changed')
        # Recover only a receipt already durably written by this adapter. No
        # endpoint is recomputed and no launch is admitted by this operation.
        with self.journal.transaction() as c:receipts={r['key']:r['payload'] for r in self.journal.rows(c,'receipt')}
        current={r['allocation']['id']:r['receipt'] for r in self.ledger.summary()['allocations']}
        for key,value in receipts.items():
            if current.get(key) is None:
                if not repair:raise ValueError('trial_receipt_reconciliation_required')
                self.ledger.record(key,value)
            elif any(current[key].get(k)!=v for k,v in value.items()):raise ValueError('trial_receipt_changed')
        if any(value is not None and key not in receipts for key,value in current.items()):raise ValueError('untrusted_trial_receipt')
        if repair and any(value.get('settled') is not True or value.get('cleanup') is not True for value in receipts.values()):self.ledger.stop('unconfirmed_execution_quiescence')

    @contextmanager
    def _lifecycle_owner(self):
        with (self.root/'execute.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('trial_executor_already_owned') from None
            yield

    def reconcile(self):
        with self._lifecycle_owner():return self._reconcile_owned()

    def _reconcile_owned(self):
        self.verify_frozen();self._repair_receipts()
        for a in self.allocations:
            intent=self._event('launch_intent',a['id'])
            if intent is None or self._event('receipt',a['id']):continue
            if self.endpoint(a['id']) is None:
                origin=self._event('endpoint_origin',a['id'])
                self.freeze_endpoint(a['id'],dict(origin=origin['origin'] if origin else intent['clock'],observed=host_clock(),business=None,native=None,settled=None,arm_qualified=None,timely=False,reasons=['ambiguous_launch_reconciled_without_replay']))
            cleanup=self._cleanup(a)
            self.record_result(a['id'],cleanup)
        return self.summary()

    def execute(self,*,paid=False):
        if not paid:raise ValueError('explicit_paid_required')
        with self._lifecycle_owner():
            self.verify_frozen();self._repair_receipts()
            # Any ambiguous previous launch is recovery-only for this invocation.
            if any(self._event('launch_intent',a['id']) and not self._event('receipt',a['id']) for a in self.allocations):return self._reconcile_owned()
            prior_model=None
            for a in self.allocations:
                if self.ledger.summary()['protocol_stopped']:break
                previous=self._event('receipt',a['id'])
                if previous:
                    if previous.get('observed_model') is not None:prior_model=previous['observed_model']
                    if (self.endpoint(a['id']) or {}).get('arm_qualified') is not True:
                        self.ledger.stop('arm_qualification_unconfirmed');break
                    continue
                f=self.fixture(a)
                receipt=native.execute_allocation(self.base(a),Path(self.protocol['host']),self.protocol['image'],f,a,explicit_policy=arm_policy(self.base(a)/'work',f,a['arm']),strict_trial=self)
                observed=receipt.get('observed_model')
                if prior_model is not None and observed is not None and prior_model!=observed:self.ledger.stop('observed_model_drift')
                if observed is not None:prior_model=observed
                # Runtime qualification drift is itself a launch stop; absence of
                # evidence is not permission to spend the remaining allocations.
                endpoint=self.endpoint(a['id'])
                if endpoint.get('arm_qualified') is not True:self.ledger.stop('arm_qualification_unconfirmed')
            return self.summary()



def error_code(exc,fallback):
    value=str(exc)
    return value if re.fullmatch('[a-z][a-z0-9_]{0,95}',value) else fallback


def bounded_regular(path,limit):
    import stat
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor,'rb') as stream:
        metadata=os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1 or metadata.st_size>limit:raise ValueError('artifact_file_forbidden')
        value=stream.read(limit+1)
        if len(value)>limit:raise ValueError('artifact_too_large')
        return value
