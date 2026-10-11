"""Protected host-only creation observation for explicitly frozen paired trials.

The daemon is observed before its new container ID is returned to Hermes. No
worker-supplied verdict, configuration assertion or later cleanup is authority.
"""
from __future__ import annotations
from contextlib import closing
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

from cohort import Journal,digest,durable_bytes,durable_json,host_clock,stamp,strict_read
from runtime_policy import file_hash,inspect_worker,native_config,paired_bootstrap
from runtime_channel import process_identity,read_json

ROOT=Path(__file__).resolve().parent


def real_docker_identity():
    # Never resolve a caller's PATH/HERMES_DOCKER_BINARY wrapper recursively.
    for name in ('/usr/bin/docker','/usr/local/bin/docker','/bin/docker'):
        path=Path(name).resolve()
        if path.is_file() and os.access(path,os.X_OK):return dict(path=str(path),sha256=file_hash(path))
    raise ValueError('protected_real_docker_unavailable')


def install(trial,allocation,manifest):
    manifest=Path(manifest);m=strict_read(manifest);directory=manifest.parent
    scope_path=directory/'worker-observer-scope.json';wrapper=directory/'docker-observer'
    scope=dict(version=1,manifest=str(manifest),trial_root=str(trial.root),allocation_id=allocation['id'],
               endpoint=str(trial.base(allocation)/'worker-endpoint.json'),docker=trial.protocol['worker_capture']['docker'])
    durable_json(scope_path,scope,exclusive=True)
    body=f'#!{sys.executable}\nimport sys\nsys.path.insert(0,{str(ROOT)!r})\nfrom native_worker_capture import main\nmain({str(scope_path)!r})\n'
    durable_bytes(wrapper,body.encode(),exclusive=True);wrapper.chmod(0o500)
    parent=directory/'paired-bootstrap';parent.mkdir(mode=0o500)
    (directory/'profile/skills').mkdir(mode=0o700,exist_ok=True)
    m['paired_bootstrap']={'version':1,'bundled_source':str(parent/'absent-bundled-skills')}
    paired_bootstrap(m)
    m['docker_observer']={'path':str(wrapper),'scope':str(scope_path)}
    for path in (scope_path,wrapper,ROOT/'native_worker_capture.py',ROOT/'cohort.py'):m['hashes'][str(path)]=file_hash(path)
    durable_json(manifest,m)


def remaining(record,clock):
    now=stamp(clock());origin=stamp(record['origin'])
    if record.get('seconds')!=180 or record.get('deadline_utc')!=origin['utc']+180:raise ValueError('observer_endpoint_changed')
    if now['boot_id']!=origin['boot_id'] or now['monotonic']<origin['monotonic'] or abs(now['utc']-origin['utc']-(now['monotonic']-origin['monotonic']))>2:raise ValueError('observer_clock_discontinuity')
    value=180-(now['monotonic']-origin['monotonic'])
    if value<=0:raise TimeoutError('observer_endpoint_expired')
    return value


def _call(record,clock,operation):
    result=operation(remaining(record,clock));remaining(record,clock);return result


def _session(profile,timeout):
    with closing(sqlite3.connect((profile/'zhulong/autonomy.db').as_uri()+'?mode=ro',uri=True,timeout=min(.1,timeout))) as c:
        c.row_factory=sqlite3.Row;rows=c.execute('SELECT id,run_id,session_key,request FROM submissions').fetchall()
    if len(rows)!=1 or not rows[0]['run_id']:raise ValueError('observer_submission_unavailable')
    sub=dict(rows[0]);request=json.loads(sub['request'])
    with closing(sqlite3.connect((profile/'runs_idempotency.db').as_uri()+'?mode=ro',uri=True,timeout=min(.1,timeout))) as c:
        rows=c.execute('SELECT fingerprint,status_json FROM run_idempotency WHERE idempotency_key=? AND run_id=?',(sub['id'],sub['run_id'])).fetchall()
    if len(rows)!=1 or rows[0][0]!=digest({'body':request,'gateway_session_key':sub['session_key']}):raise ValueError('observer_runs_binding_changed')
    status=json.loads(rows[0][1]);session=status.get('session_id')
    # Fresh one-attempt explicit session, safe under the pinned label sanitizer:
    # no truncation, escaping, aliases or profile qualification is accepted.
    if status.get('run_id')!=sub['run_id'] or session!=sub['session_key'] or not isinstance(session,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,63}',session):raise ValueError('observer_session_ambiguous')
    return dict(submission_id=sub['id'],run_id=sub['run_id'],session_id=session)


def requested_task(args):
    """Parse only Docker options before the image; duplicates never choose a role."""
    flags={'-d','--detach','--init','--read-only','--rm'}
    valued={'--name','-w','--workdir','--cap-drop','--cap-add','--tmpfs','--security-opt','--user','-u',
            '--pids-limit','--shm-size','--network','--memory','--memory-swap','--cpus','--ipc','--pid',
            '--ulimit','--storage-opt','-v','--volume','-e','--env','--hostname','-h','--label','-l'}
    labels={};i=1
    while i<len(args):
        item=args[i]
        if not isinstance(item,str):raise ValueError('observer_requested_labels_invalid')
        if not item.startswith('-'):break
        key,equals,value=item.partition('=')
        if key in flags and not equals:i+=1;continue
        if key not in valued:raise ValueError('observer_requested_labels_invalid')
        if not equals:
            i+=1
            if i>=len(args):raise ValueError('observer_requested_labels_invalid')
            value=args[i]
        if key in ('--label','-l'):
            name,sep,label=value.partition('=')
            if not sep or name in labels:raise ValueError('observer_requested_labels_invalid')
            labels[name]=label
        i+=1
    if i>=len(args) or not labels.get('hermes-task-id'):raise ValueError('observer_requested_labels_invalid')
    return labels['hermes-task-id']


def invoke(scope_path,args,*,clock=host_clock,transport=subprocess.run):
    scope_path=Path(scope_path);scope=strict_read(scope_path);docker=scope['docker']
    if file_hash(docker['path'])!=docker['sha256']:raise ValueError('observer_real_docker_changed')
    command=[docker['path'],*args]
    if not args or args[0]!='run' or '-d' not in args:
        return transport(command,capture_output=True)
    boot=os.environ.get('ZHULONG_BOOT_ID')
    record=strict_read(scope['endpoint']);remaining(record,clock)
    m=strict_read(scope['manifest']);directory=Path(m['root']);base=directory.parent;profile=directory/'profile'
    if m.get('docker_observer')!={'path':str(directory/'docker-observer'),'scope':str(scope_path)}:raise ValueError('observer_scope_changed')
    for name,expected in m['hashes'].items():
        if file_hash(name)!=expected:raise ValueError('observer_protected_file_changed')
    source=paired_bootstrap(m)
    if source is None or os.environ.get('HERMES_BUNDLED_SKILLS')!=source:raise ValueError('observer_bootstrap_changed')
    policy=strict_read(profile/'zhulong/config.json')['autonomy'];config=strict_read(profile/'config.yaml')
    if 'docker_extra_args' in config['terminal'] or config['gateway'].get('multiplex_profiles') is not False:raise ValueError('observer_launch_config_changed')
    expected_args=native_config(m,policy,boot)['terminal']['docker_extra_args']
    if json.loads(os.environ.get('TERMINAL_DOCKER_EXTRA_ARGS','null'))!=expected_args:raise ValueError('observer_effective_launch_args_changed')
    status=read_json(directory/'service/status.json');health=read_json(directory/'service/health.json');owner=status.get('child_identity')
    if (not boot or boot in ('preflight','probe') or status.get('state')!='running' or status.get('boot_id')!=boot or health.get('boot_id')!=boot
            or not isinstance(owner,dict) or process_identity(owner.get('pid'))!=owner or health.get('pid')!=owner.get('pid')):raise ValueError('observer_service_owner_changed')
    session=_call(record,clock,lambda timeout: _session(profile,timeout))
    task=requested_task(args)
    purpose='session' if task==session['session_id'] else 'prompt_probe' if task=='prompt-backend-probe' else None
    if purpose is None:raise ValueError('observer_requested_task_unknown')
    session.update(purpose=purpose,task_label=task)
    journal=Journal(scope['trial_root'],'native_trial');launch=uuid.uuid4().hex
    with journal.transaction(timeout=remaining(record,clock)) as c:
        origins=[row['payload'] for row in journal.rows(c,'endpoint_origin') if row['key']==scope['allocation_id']]
        prepared=[row['payload'] for row in journal.rows(c,'prepared') if row['key']==scope['allocation_id']]
        if origins!=[record] or len(prepared)!=1 or prepared[0]['manifest_sha256']!=file_hash(scope['manifest']):raise ValueError('observer_frozen_binding_changed')
        journal.add(c,'worker_launch',launch,dict(allocation_id=scope['allocation_id'],clock=stamp(clock()),service_boot_id=boot,owner=owner,**session))
    stage='create'
    try:
        remaining(record,clock)
        stage='create'
        result=_call(record,clock,lambda timeout:transport(command,capture_output=True,timeout=timeout))
        if result.returncode:
            rejection(journal,scope,record,clock,launch,stage,'daemon_exit')
            return result
        cid=result.stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}',cid):raise ValueError('observer_container_id_invalid')
        stage='inspect'
        inspected=_call(record,clock,lambda timeout:transport([docker['path'],'inspect',cid],capture_output=True,timeout=min(timeout,3)))
        if inspected.returncode:raise ValueError('observer_inspect_failed')
        values=json.loads(inspected.stdout)
        if not isinstance(values,list) or len(values)!=1:raise ValueError('observer_inspect_ambiguous')
        raw=values[0]
        if not isinstance(raw,dict):raise ValueError('observer_inspect_ambiguous')
        stage='boundary'
        labels=raw.get('Config',{}).get('Labels',{})
        if (raw.get('Id')!=cid or raw.get('Config',{}).get('Hostname')!=cid[:12] or labels.get('zhulong.boot')!=boot
                or labels.get('hermes-task-id')!=task or labels.get('hermes-agent')!='1' or raw.get('Config',{}).get('Image')!=m['image']):raise ValueError('observer_actual_container_changed')
        paired_bootstrap(m)
        inspect_worker(m,policy,raw)
        observed=stamp(clock());created=datetime.datetime.fromisoformat(raw['Created'].replace('Z','+00:00')).timestamp()
        if not record['origin']['utc']<=created<=observed['utc']:raise ValueError('observer_container_time_changed')
        if read_json(directory/'service/status.json').get('boot_id')!=boot or process_identity(owner['pid'])!=owner:raise ValueError('observer_service_owner_changed')
        stage='persist'
        captures=base/'worker-captures';captures.mkdir(mode=0o700,exist_ok=True)
        path=captures/(cid+'.json')
        _call(record,clock,lambda _:durable_json(path,raw,exclusive=True))
        value=dict(allocation_id=scope['allocation_id'],container_id=cid,worker_sha256=digest(raw),clock=stamp(clock()),
                   service_boot_id=boot,owner=owner,created_utc=created,manifest_sha256=file_hash(scope['manifest']),**session)
        with journal.transaction(timeout=remaining(record,clock)) as c:journal.add(c,'worker',launch,value)
        remaining(record,clock)
        return result
    except (OSError,ValueError,KeyError,TypeError,TimeoutError,sqlite3.Error,subprocess.SubprocessError) as exc:
        allowed={'observer_container_id_invalid','observer_inspect_failed','observer_inspect_ambiguous','observer_actual_container_changed',
                 'worker_isolation_drift','worker_mount_drift','worker_secret_environment','worker_privilege_drift','worker_capability_drift',
                 'worker_tmpfs_drift','nonroot_worker_required','worker_ownership_missing','observer_container_time_changed','observer_service_owner_changed',
                 'paired_bootstrap_changed','paired_bootstrap_parent_changed','paired_bundled_source_present','paired_skills_not_empty'}
        code=str(exc) if isinstance(exc,ValueError) and str(exc) in allowed else 'timeout' if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)) else 'observation_unavailable'
        rejection(journal,scope,record,clock,launch,stage,code)
        raise


def rejection(journal,scope,record,clock,launch,stage,code):
    # Diagnostic failure is not evidence; never manufacture capture or refill time.
    try:
        with journal.transaction(timeout=remaining(record,clock)) as c:
            remaining(record,clock)
            journal.add(c,'worker_rejection',launch,dict(allocation_id=scope['allocation_id'],stage=stage,code=code,clock=stamp(clock())))
        remaining(record,clock)
    except (OSError,ValueError,TimeoutError,sqlite3.Error):pass


def main(scope_path):
    try:
        scope=strict_read(scope_path);args=sys.argv[1:]
        if not args or args[0]!='run' or '-d' not in args:
            if file_hash(scope['docker']['path'])!=scope['docker']['sha256']:raise ValueError('observer_real_docker_changed')
            os.execv(scope['docker']['path'],[scope['docker']['path'],*args])
        result=invoke(scope_path,args)
        sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr)
        if result.returncode<0:
            import signal
            if -result.returncode not in (signal.SIGKILL,signal.SIGSTOP):signal.signal(-result.returncode,signal.SIG_DFL)
            os.kill(os.getpid(),-result.returncode)
        raise SystemExit(result.returncode)
    except (OSError,ValueError,KeyError,TypeError,TimeoutError,sqlite3.Error,subprocess.SubprocessError):
        # Raw errors/config stay private. A failed launch intent remains durable
        # and disqualifies the allocation even if a later tool call succeeds.
        print('protected_worker_observation_failed',file=sys.stderr)
        raise SystemExit(125)
