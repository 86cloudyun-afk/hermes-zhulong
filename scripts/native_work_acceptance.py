"""Retained finite native Hermes useful-work pilot; provider calls require --paid.

Each allocation has a separate private gateway profile and Docker work directory.
All allocations are durable before launches. Expected reference answers remain in
trusted host verification; requests contain only business input and task rules.
Unconfirmed settlement or cleanup stops launches; remaining allocations stay unrun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autonomy_store import Ledger, canonical, digest
from autonomy_checks import Verifier, validate_config, observe_sources
from causal_trial import TrialLedger
from runtime_channel import read_json, atomic_json
from runtime_policy import create_deployment
from runtime_supervisor import docker
from scripts.skill_smoke_evidence import runner_command, audit_native_skill
from work_reference import reference_output, reference_instructions
import task_inputs


TRUSTED_RUNNER_RELATIVE = 'cache/generated/zhulong-work-runner.py'
TRUSTED_RUNNER_COMMAND = 'python3 /root/.hermes/'+TRUSTED_RUNNER_RELATIVE

def business_inputs(count=3):
    if type(count) is not int or not 1 <= count <= 3: raise ValueError('allocations_must_be_1_to_3')
    return [
        {'id': 'workload', 'reference_id': 'workload_summary_v1', 'data': {'tasks': [
            {'id': 'design', 'team': 'engineering', 'minutes': 150, 'done': True},
            {'id': 'implementation', 'team': 'engineering', 'minutes': 240, 'done': False},
            {'id': 'review', 'team': 'operations', 'minutes': 45, 'done': False},
            {'id': 'handover', 'team': 'operations', 'minutes': 30, 'done': True}]}},
        {'id': 'ticket-queue', 'reference_id': 'ticket_priority_v1', 'data': {'tickets': [
            {'id': 'invoice-export', 'severity': 3, 'age_hours': 20, 'blocked': False},
            {'id': 'login-incident', 'severity': 5, 'age_hours': 2, 'blocked': True},
            {'id': 'documentation', 'severity': 1, 'age_hours': 230, 'blocked': False},
            {'id': 'invoice-audit', 'severity': 3, 'age_hours': 20, 'blocked': False}]}},
        {'id': 'source-index', 'reference_id': 'source_index_v1', 'data': {'sources': [
            {'id': 'runtime', 'title': 'Runtime deployment guide', 'url': 'https://example.org/runtime', 'tags': ['operations', 'engineering']},
            {'id': 'billing', 'title': 'Billing reconciliation procedure', 'url': 'https://example.org/billing', 'tags': ['operations', 'finance']},
            {'id': 'release', 'title': 'Release review checklist', 'url': 'https://example.org/release', 'tags': ['engineering']}]}},
    ][:count]


def work_command(source, output, input_hash):
    # Preserve the established exact-command transcript auditor's receipt shape.
    # This pilot audits a model-written program rather than a published skill.
    command = runner_command('WORK_CODE_HASH', source, output, input_hash=input_hash)
    command = command.replace("expected='WORK_CODE_HASH'\nprogram=Path('.zhulong-skill-'+expected+'.py')",
                              "program=Path('.zhulong-work.py')\nexpected=hashlib.sha256(program.read_bytes()).hexdigest()")
    return command


def trusted_runner_body(input_hash, *, worker_identity=False):
    """Existing bounded runner as a protected file; never includes an answer."""
    if not isinstance(input_hash,str) or not re.fullmatch('[0-9a-f]{64}',input_hash):
        raise ValueError('invalid_frozen_input_hash')
    wrapped = work_command(Path('facts.json'),Path('result.json'),input_hash)
    body = wrapped.split('\n',1)[1].rsplit('\nZHULONG_SKILL_SMOKE',1)[0]
    old = "expected=hashlib.sha256(program.read_bytes()).hexdigest()\ncode=program.read_bytes()"
    if body.count(old) != 1: raise ValueError('trusted_runner_template_changed')
    body=body.replace(old,"code=program.read_bytes()\nexpected=hashlib.sha256(code).hexdigest()")
    if worker_identity:
        body=body.replace("'input_hash':input_hash,'value':value}","'input_hash':input_hash,'value':value,'worker_hostname':__import__('os').uname().nodename}")
    return body+'\n'


def prepare_trusted_runner(manifest, input_hash, *, worker_identity=False):
    """Prepare this new deployment before startup; preserve native guard floors.

    Hermes' permanent command allowlist is a top-level list. The pinned host
    evaluates hardline/runtime-deletion/user-deny floors before this exact
    literal match. Its generated-cache Docker bind is already read-only.
    """
    body=trusted_runner_body(input_hash,worker_identity=worker_identity);manifest=Path(manifest).resolve()
    m=read_json(manifest);root=manifest.parent;profile=root/'profile'
    if m.get('root') != str(root) or not isinstance(m.get('hashes'),dict):
        raise ValueError('trusted_runner_deployment_binding_missing')
    if read_json(root/'service/launches.json').get('used',0) or (root/'gateway.log').exists():
        raise ValueError('trusted_runner_requires_unstarted_deployment')
    config_path=profile/'config.yaml'
    if m['hashes'].get(str(config_path)) != digest_bytes(config_path.read_bytes()):
        raise ValueError('trusted_runner_config_hash_changed')
    config=read_json(config_path)
    if config.get('command_allowlist',[]) not in ([],[TRUSTED_RUNNER_COMMAND]):
        raise ValueError('trusted_runner_existing_allowlist_conflict')
    runner=profile/TRUSTED_RUNNER_RELATIVE
    if runner.parent.resolve() != runner.parent: raise ValueError('trusted_runner_cache_symlink')
    runner.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with runner.open('x',encoding='utf-8') as stream:
        stream.write(body);stream.flush();os.fsync(stream.fileno())
    runner.chmod(0o444)
    config['command_allowlist']=[TRUSTED_RUNNER_COMMAND]
    atomic_json(config_path,config)
    m['hashes'][str(runner)]=digest_bytes(runner.read_bytes())
    m['hashes'][str(config_path)]=digest_bytes(config_path.read_bytes())
    atomic_json(manifest,m)
    return {'command':TRUSTED_RUNNER_COMMAND,'runner_sha256':m['hashes'][str(runner)],
            'approval_scope':'One authorized bounded JSON-input/output program entry; other actions retain native approval requirements'}


CERTIFIED_RUNNER_RELATIVE = 'cache/generated/zhulong-certified-runner.py'
CERTIFIED_RUNNER_COMMAND = 'python3 -I /root/.hermes/'+CERTIFIED_RUNNER_RELATIVE
CERTIFIED_FILES = ('zhulong-certified-runner.py','certified_ticket.py',
                   'zhulong-ticket-bundle.json','zhulong-ticket-scope.json')


def certified_runner_body():
    """Fixed trusted bridge; the only candidate material is non-executable JSON."""
    return '''import hashlib,json,os,stat,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
scope=json.loads((root/'zhulong-ticket-scope.json').read_bytes())
def sha(data):return hashlib.sha256(data).hexdigest()
if Path.cwd().resolve()!=Path(scope['work']):raise ValueError('certified_work_directory_changed')
if sha((root/'certified_ticket.py').read_bytes())!=scope['kernel_hash']:raise ValueError('certified_kernel_changed')
sys.path.insert(0,str(root))
from certified_ticket import strict_load,canonical_bytes,execute_ticket_program
bundle_bytes=(root/'zhulong-ticket-bundle.json').read_bytes()
if sha(bundle_bytes)!=scope['bundle_hash']:raise ValueError('certified_bundle_changed')
bundle=strict_load(bundle_bytes,6000)
fd=os.open('facts.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
try:
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):raise ValueError('certified_input_not_regular')
    with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(4097)
finally:os.close(fd)
if len(data)>4096 or sha(data)!=scope['input_hash']:raise ValueError('certified_input_changed')
value=execute_ticket_program(canonical_bytes(bundle['program']),canonical_bytes(bundle['certificate']),strict_load(data,4096,32))
output=canonical_bytes(value)+b'\\n'
if Path('result.json').is_symlink():raise ValueError('certified_output_symlink')
fd,name=tempfile.mkstemp(prefix='.zhulong-certified-',dir='.')
try:
    with os.fdopen(fd,'wb') as stream:
        stream.write(output);stream.flush();os.fsync(stream.fileno())
    os.replace(name,'result.json')
finally:
    if os.path.exists(name):os.unlink(name)
print(json.dumps({'schema':1,'runner_hash':sha(Path(__file__).read_bytes()),
                  'kernel_hash':scope['kernel_hash'],'bundle_hash':scope['bundle_hash'],
                  'input_hash':scope['input_hash'],'output_hash':sha(output),
                  'execution_identity_hash':scope['execution_identity_hash'],'value':value},sort_keys=True))
'''


def _certified_deployment_scope(manifest,input_hash,program_bundle):
    from certified_bindings import normalize_program_bundle
    from certified_ticket import validate_ticket_input
    manifest=Path(manifest).resolve();m=read_json(manifest);root=manifest.parent;profile=root/'profile'
    if m.get('root')!=str(root) or not isinstance(m.get('hashes'),dict):raise ValueError('certified_deployment_binding_missing')
    for path in (profile/'config.yaml',profile/'zhulong/config.json'):
        if m['hashes'].get(str(path))!=digest_bytes(path.read_bytes()):raise ValueError('certified_config_changed')
    policy=validate_config(read_json(profile/'zhulong/config.json')['autonomy'],profile/'zhulong')
    if len(policy['sources'])!=1:raise ValueError('certified_single_source_required')
    source=policy['sources'][0]
    if set(source['contracts'])!={'result'}:raise ValueError('certified_result_contract_required')
    contract=source['contracts']['result'];bundle=normalize_program_bundle(program_bundle,contract=contract)
    if canonical(contract.get('program_bundle'))!=canonical(bundle):raise ValueError('certified_installed_contract_mismatch')
    work=Path(m['work'])
    if source['path']!=str(work/'facts.json') or contract['path']!=str(work/'result.json'):raise ValueError('certified_fixed_paths_required')
    data=(work/'facts.json').read_bytes()
    if not re.fullmatch('[0-9a-f]{64}',input_hash) or digest_bytes(data)!=input_hash:raise ValueError('certified_input_hash_mismatch')
    from certified_ticket import strict_load
    validate_ticket_input(strict_load(data,4096,32))
    identity={'api_url':policy['api_url'],'credential_env':policy['api_key_env'],
              'identity_version':policy['api_identity_version'],'profile':policy['api_profile']}
    scope={'schema':1,'work':str(work),'source_id':source['id'],'contract_id':'result',
           'contract_hash':digest(contract),'execution_identity_hash':digest(identity),
           'input_hash':input_hash,'bundle_hash':digest(bundle),
           'kernel_hash':digest_bytes((ROOT/'certified_ticket.py').read_bytes())}
    return m,profile,bundle,scope


def prepare_certified_runner(manifest,input_hash,program_bundle):
    """Bind an unstarted deployment to the same bundle its authority will admit."""
    m,profile,bundle,scope=_certified_deployment_scope(manifest,input_hash,program_bundle)
    root=Path(m['root']);manifest=Path(manifest)
    if read_json(root/'service/launches.json').get('used',0) or (root/'gateway.log').exists():
        raise ValueError('certified_runner_requires_unstarted_deployment')
    config_path=profile/'config.yaml';config=read_json(config_path)
    if config.get('command_allowlist',[])!=[]:raise ValueError('certified_runner_allowlist_conflict')
    cache=profile/'cache/generated'
    if cache.resolve()!=cache:raise ValueError('certified_cache_symlink')
    cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    contents=(certified_runner_body().encode(),(ROOT/'certified_ticket.py').read_bytes(),
              canonical(bundle).encode(),canonical(scope).encode())
    if any((cache/name).exists() or (cache/name).is_symlink() for name in CERTIFIED_FILES):raise ValueError('certified_runner_already_exists')
    for name,content in zip(CERTIFIED_FILES,contents):
        path=cache/name
        with path.open('xb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
        path.chmod(0o444);m['hashes'][str(path)]=digest_bytes(content)
    config['command_allowlist']=[CERTIFIED_RUNNER_COMMAND];atomic_json(config_path,config)
    m['hashes'][str(config_path)]=digest_bytes(config_path.read_bytes());atomic_json(manifest,m)
    return {'command':CERTIFIED_RUNNER_COMMAND,'runner_sha256':digest_bytes(contents[0]),
            **{k:scope[k] for k in ('bundle_hash','kernel_hash','input_hash','execution_identity_hash')},
            'approval_scope':'Exact foreground protected ticket interpreter; candidate JSON has no effects or Python code'}


def audit_native_certified(manifest,submission):
    """Check actual immutable admission, protected files, native invocation and artifact."""
    from scripts.skill_smoke_evidence import read_db
    from skill_evaluator import strict_json
    from certified_bindings import program_binding,normalize_program_bundle
    from task_inputs import INPUT_ENVELOPE_DEPTH
    try:
        manifest=Path(manifest).resolve();m=read_json(manifest);profile=manifest.parent/'profile';cache=profile/'cache/generated'
        if m.get('root')!=str(manifest.parent):raise ValueError('deployment_root')
        for path in [cache/name for name in CERTIFIED_FILES]+[profile/'config.yaml',profile/'zhulong/config.json']:
            if path.resolve()!=path or m['hashes'].get(str(path))!=digest_bytes(path.read_bytes()):raise ValueError('protected_file_changed')
        scope=strict_json((cache/'zhulong-ticket-scope.json').read_bytes())
        installed=strict_json((cache/'zhulong-ticket-bundle.json').read_bytes())
        if digest(installed)!=scope['bundle_hash'] or digest_bytes((cache/'certified_ticket.py').read_bytes())!=scope['kernel_hash']:raise ValueError('installed_hash_mismatch')
        if scope['work']!=m['work']:raise ValueError('installed_work_mismatch')
        if read_json(profile/'config.yaml').get('command_allowlist')!=[CERTIFIED_RUNNER_COMMAND]:raise ValueError('installed_allowlist_mismatch')
        with read_db(profile/'zhulong/autonomy.db') as c:
            row=c.execute('SELECT * FROM submissions WHERE id=?',(submission['id'],)).fetchone()
            if row is None:raise ValueError('admitted_submission_missing')
            actual=Ledger._submission(row)
            for key in ('id','goal_id','request','session_key','execution_identity','run_id'):
                if canonical(actual[key])!=canonical(submission[key]):raise ValueError('admitted_submission_mismatch')
            goal=dict(c.execute('SELECT * FROM goals WHERE id=?',(actual['goal_id'],)).fetchone())
            goal['contract']=json.loads(goal['contract']);goal.update(json.loads(goal['candidate']))
            goal['task_input']=task_inputs.binding(c,goal['id'])
        intent=strict_json(actual['request']['input'],max_depth=INPUT_ENVELOPE_DEPTH)
        metadata=program_binding(goal,actual['execution_identity'])
        if metadata is None or canonical(intent.get('program_binding'))!=canonical(metadata):raise ValueError('admitted_metadata_mismatch')
        if (canonical(intent.get('acceptance_contract'))!=canonical(goal['contract'])
            or canonical(intent.get('task_input'))!=canonical(goal['task_input'])
            or canonical(goal['contract']['program_bundle'])!=canonical(installed)):raise ValueError('admitted_bundle_mismatch')
        normalize_program_bundle(installed,contract=goal['contract'])
        if (goal['source_id']!=scope['source_id'] or goal['contract_id']!=scope['contract_id']
            or goal['contract_hash']!=scope['contract_hash'] or metadata['input_hash']!=scope['input_hash']
            or metadata['execution_identity_hash']!=scope['execution_identity_hash']
            or metadata['checker_hash']!=scope['kernel_hash']):raise ValueError('admitted_scope_mismatch')
        work=Path(m['work']);artifact=work/'result.json';source=work/'facts.json'
        if artifact.is_symlink() or source.is_symlink():raise ValueError('artifact_symlink')
        if digest_bytes(source.read_bytes())!=scope['input_hash']:raise ValueError('source_hash_mismatch')
        output=artifact.read_bytes()
        if len(output)>16384:raise ValueError('artifact_size')
        expected=reference_output('ticket_priority_v1',goal['task_input']['data'])
        if canonical(strict_json(output))!=canonical(expected):raise ValueError('business_artifact_mismatch')
        receipt={'schema':1,'runner_hash':digest_bytes((cache/CERTIFIED_FILES[0]).read_bytes()),
                 'kernel_hash':scope['kernel_hash'],'bundle_hash':scope['bundle_hash'],
                 'input_hash':scope['input_hash'],'output_hash':digest_bytes(output),
                 'execution_identity_hash':scope['execution_identity_hash'],'value':expected}
        with read_db(profile/'runs_idempotency.db') as c:
            records=c.execute('SELECT fingerprint,status_json FROM run_idempotency WHERE idempotency_key=? AND run_id=?',
                              (actual['id'],actual['run_id'])).fetchall()
        if len(records)!=1 or records[0]['fingerprint']!=digest({'body':actual['request'],'gateway_session_key':actual['session_key']}):raise ValueError('native_request_mapping')
        status=strict_json(records[0]['status_json'])
        if status.get('run_id')!=actual['run_id'] or status.get('status')!='completed' or not status.get('session_id'):raise ValueError('native_session_mapping')
        with read_db(profile/'state.db') as c:
            rows=c.execute('SELECT id,role,content,tool_calls,tool_call_id FROM messages WHERE session_id=? ORDER BY id',(status['session_id'],)).fetchall()
        successful=[]
        for row in rows:
            if row['role']!='assistant' or not row['tool_calls']:continue
            for call in strict_json(row['tool_calls']):
                function=call.get('function',{});arguments=function.get('arguments',{})
                if isinstance(arguments,str):arguments=strict_json(arguments)
                if function.get('name')!='terminal' or arguments.get('command')!=CERTIFIED_RUNNER_COMMAND or arguments.get('background',False) is not False:continue
                results=[r for r in rows if r['role']=='tool' and r['tool_call_id']==call.get('id') and r['id']>row['id']]
                if len(results)!=1:raise ValueError('native_result_mapping')
                result=strict_json(results[0]['content'])
                if type(result.get('exit_code')) is not int or result['exit_code']!=0 or result.get('error') is not None or 'session_id' in result:continue
                if canonical(strict_json(result['output']))==canonical(receipt):successful.append(call['id'])
        if len(successful)!=1:raise ValueError('native_certified_invocation_unverified')
        return {'execution_command_observed':True,'execution_result_successful':True,'admitted_request_binding_verified':True,
                'submission_id':actual['id'],'request_hash':digest(actual['request']),
                'invocation_hash':digest_bytes(CERTIFIED_RUNNER_COMMAND.encode()),
                **{k:v for k,v in receipt.items() if k not in ('schema','value')},
                'claim':'Observed protected execution of a checked ticket program within its declared finite input domain'}
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as exc:
        raise RuntimeError('native_certified_audit_failed') from exc


def work_policy(work, fixture, *, program_bundle=None):
    source_id = 'business-' + fixture['id']; fields = sorted(fixture['data'])
    command = TRUSTED_RUNNER_COMMAND
    mission = (reference_instructions(fixture['reference_id'])+'\nWrite .zhulong-work.py reading stdin JSON and emitting the result JSON. Then issue EXACTLY this foreground terminal command once, with no extra commands:\n'+command)
    if program_bundle is not None:
        if fixture['reference_id']!='ticket_priority_v1':raise ValueError('unsupported_certified_fixture')
        mission=(reference_instructions(fixture['reference_id'])+'\nExecute EXACTLY this foreground terminal command once, with no extra commands:\n'+CERTIFIED_RUNNER_COMMAND)
    if len(mission) > 2000: raise ValueError('trusted_mission_too_long')
    result={'mission': mission,
            'daily_runs': 1, 'max_attempts': 1, 'tick_interval_seconds': 2, 'lease_seconds': 20,
            'run_deadline_seconds': 180, 'request_timeout_seconds': 5, 'learning_enabled': False,
            'input_snapshot_bytes': 8192,
            'sources': [{'id': source_id, 'domain': 'code', 'path': str(work/'facts.json'),
                         'direction': 'Generate the business result from these facts according to the trusted reference rules.',
                         'input_fields': fields, 'persist_input_fields': fields,
                         'contracts': {'result': {'type': 'json_reference', 'path': str(work/'result.json'),
                             'reference_id': fixture['reference_id'], 'reference_version': 1,
                             'require_change': True, 'safe_retry': False}}}]}
    if program_bundle is not None:
        from certified_bindings import normalize_program_bundle
        contract=result['sources'][0]['contracts']['result']
        contract['program_bundle']=normalize_program_bundle(program_bundle,contract=contract)
    return result


def _revision(path):
    result = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'unavailable'


def _wait(predicate, timeout, process):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        if process.poll() is not None: raise RuntimeError('supervisor_exited')
        time.sleep(.2)
    raise RuntimeError('allocation_deadline_expired')


def _error_metadata(exc):
    metadata = {'error_type': type(exc).__name__}
    code = str(exc)
    if re.fullmatch(r'[a-z][a-z0-9_]{0,95}', code): metadata['error_code'] = code
    return metadata


def _blank_receipt(allocation):
    return {'input_hash': allocation['input_hash'], 'scope_hash': allocation['scope_hash'], 'arm': allocation['arm'], 'outcome': 'unknown',
            'business': None, 'native': None, 'settled': None, 'cleanup': None,
            'main_usage': None, 'auxiliary_calls': None, 'billing': None}


def completed_goal(ledger, goal_id):
    item = ledger.get_goal(goal_id)
    submission = item.get('submission')
    return item if submission and submission['settled'] and item['state'] in {'succeeded', 'failed', 'blocked', 'unknown_result', 'cancelled'} else None


def execute_allocation(base, host, image, fixture, allocation, hermes_command=None, *, program_bundle=None, explicit_policy=None, strict_trial=None):
    if strict_trial is not None:
        # New paired protocol has its own durable endpoint/cleanup lifecycle.
        # The legacy and certified paths below retain their existing defaults.
        from native_trial import FrozenTrial,arm_policy
        if (not isinstance(strict_trial,FrozenTrial) or program_bundle is not None
                or allocation!=strict_trial.allocation(allocation['id'])
                or Path(base)!=strict_trial.base(allocation) or Path(host)!=Path(strict_trial.protocol['host'])
                or image!=strict_trial.protocol['image'] or fixture!=strict_trial.fixture(allocation)
                or explicit_policy!=arm_policy(Path(base)/'work',fixture,allocation['arm'])):
            raise ValueError('strict_trial_context_mismatch')
        return strict_trial._run_allocation(allocation['id'])
    if explicit_policy is not None:raise ValueError('explicit_policy_requires_frozen_strict_trial')
    receipt = _blank_receipt(allocation); receipt['discovery_mode'] = 'native_llm'; work = base/'work'
    work.mkdir(mode=0o700, parents=True)
    frozen = canonical(fixture['data']).encode()
    if hashlib.sha256(frozen).hexdigest() != allocation['input_hash']: raise ValueError('preregistered_input_changed')
    (work/'facts.json').write_bytes(frozen)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    launcher = [str(Path(hermes_command).resolve())] if hermes_command else [sys.executable, str(host/'hermes')]
    manifest = create_deployment(base/'deployment', work, host, image,
                                 launcher+['gateway', 'run', '--no-supervise'], work_policy(work, fixture, program_bundle=program_bundle), port=port, max_launches=1)
    deployment = manifest.parent; profile = deployment/'profile'
    prepared = (prepare_trusted_runner(manifest,allocation['input_hash']) if program_bundle is None else
                prepare_certified_runner(manifest,allocation['input_hash'],program_bundle))
    receipt.update(runner_sha256=prepared['runner_sha256'],approval_scope=prepared['approval_scope'])
    ledger = Ledger(profile/'zhulong/autonomy.db'); ledger.set_pause(True)
    process = None; goal_id = None
    runtime = [sys.executable, str(ROOT/'scripts/runtime.py')]
    with (base/'supervisor.log').open('wb') as log:
        os.chmod(base/'supervisor.log', 0o600)
        try:
            checked = subprocess.run(runtime+['check', '--deployment', str(manifest)], stdout=log, stderr=log, timeout=150)
            if checked.returncode != 0: raise RuntimeError('native_preflight_failed')
            process = subprocess.Popen(runtime+['run', '--deployment', str(manifest)], stdout=log, stderr=log)
            status = _wait(lambda: (s if (s := read_json(deployment/'service/status.json')).get('state') == 'running' else None), 150, process)
            health = read_json(deployment/'service/health.json')
            if health.get('boot_id') != status.get('boot_id') or health.get('progress', {}).get('thread_alive') is not True:
                raise RuntimeError('native_readiness_missing')
            raw = read_json(profile/'zhulong/config.json')['autonomy']
            policy = validate_config(raw, profile/'zhulong')
            task_inputs.configure(ledger, policy['sources'], policy['input_snapshot_bytes'])
            observation = observe_sources(policy)[0]; snapshot = observation.get('task_input')
            if not snapshot or snapshot['input_hash'] != allocation['input_hash']: raise RuntimeError('frozen_input_missing')
            contract = policy['sources'][0]['contracts']['result']; baseline = Verifier(policy).capture(contract, task_input=snapshot)
            command = TRUSTED_RUNNER_COMMAND
            ledger.set_pause(False)
            def discovered():
                matches = [item for item in ledger.goals() if item['source_id'] == observation['id'] and item['contract_id'] == 'result']
                if len(matches) > 1: raise RuntimeError('multiple_unregistered_goals')
                if not matches: return None
                item = matches[0]
                if not item.get('task_input') or item['task_input']['input_hash'] != allocation['input_hash']:
                    raise RuntimeError('discovered_input_mismatch')
                return item
            goal = _wait(discovered, 75, process)
            goal_id = goal['id']; receipt['discovered_goal_id'] = goal_id
            goal = _wait(lambda: completed_goal(ledger, goal_id), 185, process)
            submission = goal['submission']; receipt.update(main_usage=submission.get('usage'), settled=bool(submission['settled']),
                                                         goal_state=goal['state'], attempts=goal['attempts'])
            checked = Verifier(policy).check(contract, baseline, task_input=snapshot)
            receipt['business'] = checked['verdict'] if type(checked['verdict']) is bool else None
            receipt['business_receipt'] = checked
            if checked['verdict'] is True and goal['state'] == 'succeeded':
                if program_bundle is not None:
                    audit=audit_native_certified(manifest,submission)
                    receipt.update(native=True,native_receipt=audit,artifact_sha256=digest_bytes((work/'result.json').read_bytes()),outcome='succeeded')
                else:
                    code = (work/'.zhulong-work.py').read_text()
                    binding = {'code': code, 'code_hash': digest_bytes(code.encode())}
                    if digest_bytes((work/'facts.json').read_bytes()) != snapshot['input_hash']: raise RuntimeError('frozen_source_changed')
                    audit = audit_native_skill(profile, submission, binding, command, work/'.zhulong-work.py',
                                               reference_output(fixture['reference_id'], snapshot['data']), task_input=snapshot)
                    audit['claim'] = 'Observed model-written business program execution in this finite pilot'
                    receipt.update(native=True, native_receipt=audit, code_sha256=binding['code_hash'],
                                   artifact_sha256=digest_bytes((work/'result.json').read_bytes()), outcome='succeeded')
            else:
                receipt.update(native=False, outcome='failed' if checked['verdict'] is False and submission['settled'] else 'unknown')
        except Exception as exc:
            # Raw provider errors and transcripts remain in the private deployment.
            receipt.update(outcome='unknown', **_error_metadata(exc))
        finally:
            if process is not None:
                try:
                    ledger.set_pause(True)
                    stopped = subprocess.run(runtime+['stop', '--deployment', str(manifest)], stdout=log, stderr=log, timeout=15)
                    try: process.wait(timeout=75)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try: process.wait(timeout=10)
                        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                    state = read_json(deployment/'service/status.json')
                    containers = docker(read_json(manifest), ['ps', '-aq', '--filter', 'label=zhulong.runtime='+read_json(manifest)['deployment_id']])
                    receipt['cleanup'] = stopped.returncode == 0 and process.returncode == 0 and state.get('state') == 'stopped' and containers.returncode == 0 and not containers.stdout.strip()
                    receipt['shutdown'] = {'state': state.get('state'), 'supervisor_exit_code': process.returncode,
                                           'owned_containers_absent': containers.returncode == 0 and not containers.stdout.strip()}
                except Exception as exc:
                    receipt['cleanup'] = None; receipt['cleanup_error_type'] = type(exc).__name__
            else:
                # A failed preflight can have unresolved workers; require inspection.
                receipt['cleanup'] = None
            if goal_id:
                final_goal = ledger.get_goal(goal_id); final_submission = final_goal.get('submission')
                if final_submission:
                    receipt.update(settled=bool(final_submission['settled']), main_usage=final_submission.get('usage'))
            db = profile/'zhulong/zhulong.db'
            if db.exists():
                try:
                    with sqlite3.connect(db) as c:
                        receipt['auxiliary_calls'] = c.execute('SELECT COALESCE(SUM(calls),0) FROM llm_daily').fetchone()[0]
                except sqlite3.Error: pass
    atomic_json(base/'receipt.json', receipt)
    return receipt


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def run(root, host, image, *, count=3, paid=False, seed=20261011, hermes_command=None):
    root, host = Path(root).resolve(), Path(host).resolve()
    fixtures = business_inputs(count)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = TrialLedger(root/'trial.db')
    versions = {'plugin': _revision(ROOT), 'host': _revision(host), 'reference': 1, 'image': image,
                'provider': 'deepseek', 'model': 'deepseek-flash',
                'implementation_hashes': {name: digest_bytes((ROOT/name).read_bytes()) for name in
                     ('causal_trial.py', 'scripts/native_work_acceptance.py', 'scripts/skill_smoke_evidence.py', 'work_reference.py')}}
    protocol = {'version': 1, 'mode': 'finite_usefulness_pilot', 'seed': seed, 'versions': versions,
                'max_attempts': 1, 'deadline_seconds': 180,
                'arms': [{'id': 'baseline', 'scope': {'goal': 'trusted-business-references-v1',
                    'identity': {'provider': 'deepseek', 'model': 'deepseek-flash', 'profile_kind': 'isolated-per-allocation'},
                    'input_scope': 'immutable-authorized-business-facts-v1', 'version': 1},
                    'mechanisms': {'learned_skill': False}}],
                'inputs': [{'id': f['id'], 'input_hash': digest(f['data']), 'reference_id': f['reference_id']} for f in fixtures]}
    allocations = ledger.preregister(protocol)
    atomic_json(root/'protocol.json', protocol)
    # Freeze every authorized input before the first potentially paid operation.
    private = root/'inputs'; private.mkdir(mode=0o700)
    for fixture in fixtures: (private/(fixture['id']+'.json')).write_bytes(canonical(fixture['data']).encode())
    report = ledger.summary(); report.update(paid=paid, retained_private_root=str(root))
    atomic_json(root/'report.json', report)
    if paid:
        for allocation in allocations:
            allocation_root = root/('allocation-'+str(allocation['ordinal']))
            allocation_root.mkdir(mode=0o700)
            fixture = next(f for f in fixtures if f['id'] == allocation['input_id'])
            try:
                receipt = execute_allocation(allocation_root, host, image, fixture, allocation, hermes_command)
            except Exception as exc:
                receipt = _blank_receipt(allocation); receipt.update(_error_metadata(exc))
            if receipt['outcome'] == 'succeeded' and not all(receipt[k] is True for k in ('business', 'native', 'settled', 'cleanup')):
                receipt['outcome'] = 'unknown'; receipt['qualification'] = 'incomplete_success_receipts'
            if receipt['outcome'] == 'failed' and (receipt['settled'] is not True or receipt['cleanup'] is not True):
                receipt['outcome'] = 'unknown'; receipt['qualification'] = 'execution_or_cleanup_unconfirmed'
            atomic_json(allocation_root/'receipt.json', receipt)
            ledger.record(allocation['id'], receipt)
            quiescence_unconfirmed = receipt['settled'] is not True or receipt['cleanup'] is not True
            if quiescence_unconfirmed: ledger.stop('unconfirmed_execution_quiescence')
            report = ledger.summary(); report.update(paid=paid, retained_private_root=str(root))
            atomic_json(root/'report.json', report)
            if quiescence_unconfirmed: break
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='New private retained directory; never automatically deleted')
    parser.add_argument('--hermes-root', required=True, type=Path)
    parser.add_argument('--hermes-command', help='External managed host launcher')
    parser.add_argument('--image', required=True, help='Digest-pinned Docker worker image')
    parser.add_argument('--allocations', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--seed', type=int, default=20261011)
    parser.add_argument('--paid', action='store_true', help='Authorize this finite pilot to make real provider calls')
    args = parser.parse_args()
    report = run(args.root, args.hermes_root, args.image, count=args.allocations, paid=args.paid,
                 seed=args.seed, hermes_command=args.hermes_command)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if not args.paid or report['succeeded'] == report['allocated'] else 1


if __name__ == '__main__': sys.exit(main())
