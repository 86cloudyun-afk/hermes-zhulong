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


def trusted_runner_body(input_hash):
    """Existing bounded runner as a protected file; never includes an answer."""
    if not isinstance(input_hash,str) or not re.fullmatch('[0-9a-f]{64}',input_hash):
        raise ValueError('invalid_frozen_input_hash')
    wrapped = work_command(Path('facts.json'),Path('result.json'),input_hash)
    body = wrapped.split('\n',1)[1].rsplit('\nZHULONG_SKILL_SMOKE',1)[0]
    old = "expected=hashlib.sha256(program.read_bytes()).hexdigest()\ncode=program.read_bytes()"
    if body.count(old) != 1: raise ValueError('trusted_runner_template_changed')
    return body.replace(old,"code=program.read_bytes()\nexpected=hashlib.sha256(code).hexdigest()")+'\n'


def prepare_trusted_runner(manifest, input_hash):
    """Prepare this new deployment before startup; preserve native guard floors.

    Hermes' permanent command allowlist is a top-level list. The pinned host
    evaluates hardline/runtime-deletion/user-deny floors before this exact
    literal match. Its generated-cache Docker bind is already read-only.
    """
    body=trusted_runner_body(input_hash);manifest=Path(manifest).resolve()
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


def work_policy(work, fixture):
    source_id = 'business-' + fixture['id']; fields = sorted(fixture['data'])
    command = TRUSTED_RUNNER_COMMAND
    mission = (reference_instructions(fixture['reference_id'])+'\nWrite .zhulong-work.py reading stdin JSON and emitting the result JSON. Then issue EXACTLY this foreground terminal command once, with no extra commands:\n'+command)
    if len(mission) > 2000: raise ValueError('trusted_mission_too_long')
    return {'mission': mission,
            'daily_runs': 1, 'max_attempts': 1, 'tick_interval_seconds': 2, 'lease_seconds': 20,
            'run_deadline_seconds': 180, 'request_timeout_seconds': 5, 'learning_enabled': False,
            'input_snapshot_bytes': 8192,
            'sources': [{'id': source_id, 'domain': 'code', 'path': str(work/'facts.json'),
                         'direction': 'Generate the business result from these facts according to the trusted reference rules.',
                         'input_fields': fields, 'persist_input_fields': fields,
                         'contracts': {'result': {'type': 'json_reference', 'path': str(work/'result.json'),
                             'reference_id': fixture['reference_id'], 'reference_version': 1,
                             'require_change': True, 'safe_retry': False}}}]}


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


def execute_allocation(base, host, image, fixture, allocation, hermes_command=None):
    receipt = _blank_receipt(allocation); receipt['discovery_mode'] = 'native_llm'; work = base/'work'
    work.mkdir(mode=0o700, parents=True)
    frozen = canonical(fixture['data']).encode()
    if hashlib.sha256(frozen).hexdigest() != allocation['input_hash']: raise ValueError('preregistered_input_changed')
    (work/'facts.json').write_bytes(frozen)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    launcher = [str(Path(hermes_command).resolve())] if hermes_command else [sys.executable, str(host/'hermes')]
    manifest = create_deployment(base/'deployment', work, host, image,
                                 launcher+['gateway', 'run', '--no-supervise'], work_policy(work, fixture), port=port, max_launches=1)
    deployment = manifest.parent; profile = deployment/'profile'
    prepared = prepare_trusted_runner(manifest,allocation['input_hash'])
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
