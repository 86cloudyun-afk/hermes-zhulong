"""Immutable preregistration and complete-denominator finite trial receipts.

The pilot mode never infers causal gains. paired_fixed_n implements a frozen
fixed-size paired endpoint analysis, conditional on independently trusted receipts
and independent pairs; hashes bind evidence but do not establish external truth.
Native pilot acceptance constructs receipts from verifier and transcript audits.
A live paired study requires a separate runner and is never automatically paid.
"""
from __future__ import annotations

import math
import json
import random
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

try:
    from .autonomy_store import canonical, digest
    from .skill_evaluator import strict_json
except ImportError:
    from autonomy_store import canonical, digest
    from skill_evaluator import strict_json


def _json(value):
    return strict_json(canonical(value), max_depth=40)


def validate_protocol(raw):
    p = _json(raw)
    if (not isinstance(p, dict) or type(p.get('version')) is not int or p['version'] != 1
            or type(p.get('seed')) is not int or p.get('mode') not in {'finite_usefulness_pilot', 'paired_fixed_n'}
            or p.get('max_attempts') != 1 or type(p.get('max_attempts')) is not int
            or type(p.get('deadline_seconds')) is not int or not 1 <= p['deadline_seconds'] <= 180):
        raise ValueError('invalid_trial_protocol')
    versions = p.get('versions')
    if not isinstance(versions, dict) or not all(k in versions and versions[k] for k in ('plugin', 'host', 'reference')):
        raise ValueError('trial_versions_required')
    arms, inputs = p.get('arms'), p.get('inputs')
    if not isinstance(arms, list) or not 1 <= len(arms) <= 2 or not isinstance(inputs, list) or not 1 <= len(inputs) <= (4096 if p['mode'] == 'paired_fixed_n' else 128):
        raise ValueError('invalid_trial_allocations')
    ids, hashes = set(), set()
    for item in inputs:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
                or not isinstance(item.get('input_hash'), str) or not re.fullmatch('[0-9a-f]{64}', item['input_hash'])):
            raise ValueError('invalid_trial_input')
        if item['id'] in ids or item['input_hash'] in hashes: raise ValueError('duplicate_input')
        ids.add(item['id']); hashes.add(item['input_hash'])
    arm_ids = set()
    for arm in arms:
        if (not isinstance(arm, dict) or not isinstance(arm.get('id'), str) or not arm['id']
                or arm['id'] in arm_ids or not isinstance(arm.get('mechanisms'), dict) or not arm['mechanisms']
                or any(type(v) is not bool for v in arm['mechanisms'].values())):
            raise ValueError('unqualified_trial_arm')
        scope = arm.get('scope')
        if not isinstance(scope, dict) or not all(scope.get(k) for k in ('goal', 'identity', 'input_scope', 'version')):
            raise ValueError('trial_scope_required')
        arm_ids.add(arm['id'])
    if len(arms) == 2:
        if any('learning_enabled' in a['mechanisms'] for a in arms): raise ValueError('broad_mechanism_switch_forbidden')
        if canonical(arms[0]['scope']) != canonical(arms[1]['scope']): raise ValueError('trial_scope_contamination')
        before, after = arms[0]['mechanisms'], arms[1]['mechanisms']
        if set(before) != set(after) or sum(before[k] != after[k] for k in before) != 1:
            raise ValueError('single_mechanism_required')
    if p['mode'] == 'paired_fixed_n':
        if (type(p.get('fixed_n')) is not int or p['fixed_n'] != len(inputs) or not 1 <= p['fixed_n'] <= 4096
                or len(arms) != 2 or p.get('stop_rule') != 'fixed_n_only'
                or p.get('endpoint') != 'qualified_success_by_deadline_v1'
                or type(p.get('alpha')) not in (int, float) or not 0 < p['alpha'] < 1
                or {p.get('control_arm'), p.get('treatment_arm')} != arm_ids):
            raise ValueError('invalid_fixed_n_protocol')
        mechanism = p.get('mechanism', {})
        changed = next(k for k in arms[0]['mechanisms'] if arms[0]['mechanisms'][k] != arms[1]['mechanisms'][k])
        if (not isinstance(mechanism, dict) or mechanism.get('id') != changed
                or not isinstance(mechanism.get('version'), str) or not mechanism['version']
                or versions.get('reference') != 1 or type(versions.get('reference')) is not int
                or not _hash(versions.get('reference_checker_sha256'))):
            raise ValueError('fixed_n_mechanism_or_reference_required')
        identity = arms[0]['scope']['identity']
        if (not isinstance(identity, dict) or not all(isinstance(identity.get(k),str) and identity[k] for k in ('provider','model','profile','identity_version'))):
            raise ValueError('fixed_n_identity_version_required')
        for arm in arms:
            role = 'control' if arm['id'] == p['control_arm'] else 'treatment'
            if (arm.get('mechanism_version') != mechanism['version']
                    or not _hash(arm.get('artifact_sha256'))
                    or arm['artifact_sha256'] != mechanism.get(role+'_artifact_sha256')):
                raise ValueError('fixed_n_mechanism_artifact_required')
        for item in inputs:
            if (not isinstance(item.get('reference_id'), str) or not item['reference_id']
                    or type(item.get('reference_version')) is not int or item['reference_version'] != versions['reference']):
                raise ValueError('fixed_n_reference_scope_required')
    return p


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _usage_known(value):
    pairs = (('input_tokens','output_tokens'), ('prompt_tokens','completion_tokens'))
    return isinstance(value,dict) and any(all(type(value.get(k)) is int and value[k]>=0 for k in pair) for pair in pairs)


def _paired_receipt(protocol, allocation, value):
    """Validate supplied trusted receipt bindings; hashes do not prove external truth."""
    fields = ('business', 'native', 'quiet', 'cleanup', 'arm')
    hashes = value.get('proof_hashes')
    if not isinstance(hashes, dict) or any(not isinstance(value.get(k+'_receipt'), dict) or k not in hashes for k in fields):
        return False, 'missing_proof', False
    for kind in fields:
        proof = value[kind+'_receipt']
        if not _hash(hashes[kind]) or hashes[kind] != digest(proof): raise ValueError('paired_proof_hash_mismatch')
        if any(proof.get(k) != allocation[k] for k in ('arm', 'input_hash', 'scope_hash')) or proof.get('allocation_id') != allocation['id']:
            raise ValueError('paired_proof_binding_mismatch')
    arm = next(a for a in protocol['arms'] if a['id'] == allocation['arm'])
    proof = value['arm_receipt']
    if (proof.get('arm_hash') != digest(arm) or proof.get('identity_hash') != digest(arm['scope']['identity'])
            or proof.get('mechanism_version') != arm['mechanism_version'] or proof.get('artifact_sha256') != arm['artifact_sha256']):
        raise ValueError('paired_arm_proof_mismatch')
    business, native, quiet, cleanup = (value[k+'_receipt'] for k in fields[:4])
    item = next(i for i in protocol['inputs'] if i['id'] == allocation['input_id'])
    if (business.get('reference_id') != item['reference_id'] or business.get('reference_version') != item['reference_version']
            or business.get('reference_checker_sha256') != protocol['versions']['reference_checker_sha256']):
        raise ValueError('paired_reference_proof_mismatch')
    if business.get('verdict') is not value['business'] or native.get('verdict') is not value['native']:
        raise ValueError('paired_proof_verdict_mismatch')
    times = [quiet.get(k) for k in ('started_at', 'completed_at', 'deadline_at')]
    if any(type(t) not in (int, float) or not math.isfinite(t) for t in times): return False, 'missing_trusted_timing', False
    start, completed, deadline = times
    if not 0 < start <= completed <= 253402300799 or deadline > 253402300799 or deadline != start+protocol['deadline_seconds']:
        raise ValueError('paired_deadline_binding_mismatch')
    if quiet.get('settled') is not True or value['settled'] is not True or cleanup.get('confirmed') is not True or value['cleanup'] is not True:
        return False, 'execution_or_cleanup_unconfirmed', False
    if completed > deadline: return False, 'deadline_missed', False
    if value['outcome'] not in {'succeeded', 'failed'} or type(value['business']) is not bool or type(value['native']) is not bool:
        return False, 'unknown_endpoint', False
    success = value['business'] is True and value['native'] is True and value['outcome'] == 'succeeded'
    return True, 'qualified', success


def paired_analysis(protocol, allocations, stopped=False, *, frozen=False):
    """Fixed-N endpoint analysis conditional on trusted evidence and independent pairs.

    The exact two-sided paired sign test equals McNemar's discordant-pair test.
    Hoeffding uses differences in [-1,1]; failures, unknown and unrun score zero
    in descriptive totals, while incomplete/unqualified pairs prohibit inference.
    """
    grouped = {i['id']: {} for i in protocol['inputs']}
    for item in allocations: grouped[item['allocation']['input_id']][item['allocation']['arm']] = item['receipt']
    n = protocol['fixed_n']; control_only = treatment_only = complete = qualified = ties = 0
    for pair in grouped.values():
        before, after = pair.get(protocol['control_arm']), pair.get(protocol['treatment_arm'])
        complete += int(before is not None and after is not None)
        qualified += int(bool(before and after and before.get('paired_qualified') is True and after.get('paired_qualified') is True))
        a = int(bool(before and before.get('paired_endpoint') is True))
        b = int(bool(after and after.get('paired_endpoint') is True))
        control_only += int(a == 1 and b == 0); treatment_only += int(a == 0 and b == 1); ties += int(a == b)
    discordant = control_only+treatment_only
    p = min(1., 2*sum(math.comb(discordant, k) for k in range(min(control_only,treatment_only)+1))/(1 << discordant)) if discordant else 1.
    effect = (treatment_only-control_only)/n
    radius = math.sqrt(2*math.log(2/protocol['alpha'])/n)
    interval = [max(-1., effect-radius), min(1., effect+radius)]
    exclusions = []
    if not frozen: exclusions.append('protocol_not_frozen')
    if complete != n: exclusions.append('incomplete')
    if qualified != n: exclusions.append('unqualified')
    if n < 30: exclusions.append('small_n')
    if stopped: exclusions.append('protocol_stopped')
    supported = not exclusions and p <= protocol['alpha'] and interval[0] > 0
    return {'pairs': n, 'complete_pairs': complete, 'qualified_pairs': qualified, 'ties': ties,
            'control_only': control_only, 'treatment_only': treatment_only, 'discordant_pairs': discordant,
            'paired_effect': effect, 'exact_mcnemar_p': p, 'hoeffding_interval': interval,
            'alpha': protocol['alpha'], 'endpoint': protocol['endpoint'], 'disqualifications': exclusions,
            'causal_gain_supported': supported,
            'scope': 'Frozen endpoint and identity/mechanism scope only; conditional on trusted receipts and independent pairs; no cost-effectiveness assertion',
            'inference_qualified': not exclusions}


class TrialLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connection() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS trial_protocol(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trial_allocations(id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trial_receipts(allocation_id TEXT PRIMARY KEY REFERENCES trial_allocations(id), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trial_stop(id INTEGER PRIMARY KEY CHECK(id=1), reason TEXT NOT NULL);
            ''')
            for table in ('trial_protocol', 'trial_allocations', 'trial_receipts', 'trial_stop'):
                for operation in ('UPDATE', 'DELETE'):
                    c.execute(f"CREATE TRIGGER IF NOT EXISTS freeze_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'trial_frozen'); END")

    @contextmanager
    def _connection(self):
        c = sqlite3.connect(self.path, timeout=10); c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()

    def preregister(self, protocol):
        p = validate_protocol(protocol); protocol_hash = digest(p)
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT hash FROM trial_protocol WHERE id=1').fetchone()
            if existing:
                if existing['hash'] != protocol_hash: raise ValueError('protocol_frozen')
            else:
                c.execute('INSERT INTO trial_protocol VALUES(1,?,?)', (canonical(p), protocol_hash))
                cells = [(item, arm) for item in p['inputs'] for arm in p['arms']]
                random.Random(p['seed']).shuffle(cells)
                for ordinal, (item, arm) in enumerate(cells):
                    allocation = {'id': digest({'protocol': protocol_hash, 'input': item['id'], 'arm': arm['id']}),
                                  'ordinal': ordinal, 'input_id': item['id'], 'input_hash': item['input_hash'],
                                  'arm': arm['id'], 'scope_hash': digest(arm['scope']), 'protocol_hash': protocol_hash}
                    c.execute('INSERT INTO trial_allocations VALUES(?,?,?)', (allocation['id'], ordinal, canonical(allocation)))
            return [json.loads(r['payload']) for r in c.execute('SELECT payload FROM trial_allocations ORDER BY ordinal')]

    def record(self, allocation_id, receipt):
        value = _json(receipt)
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM trial_allocations WHERE id=?', (allocation_id,)).fetchone()
            if not row: raise ValueError('allocation_missing')
            allocation = json.loads(row['payload'])
            if (not isinstance(value, dict) or value.get('input_hash') != allocation['input_hash']
                    or value.get('arm') != allocation['arm'] or value.get('scope_hash') != allocation['scope_hash'] or value.get('outcome') not in {'succeeded', 'failed', 'unknown'}):
                raise ValueError('receipt_binding_mismatch')
            if c.execute('SELECT 1 FROM trial_receipts WHERE allocation_id=?', (allocation_id,)).fetchone():
                raise ValueError('receipt_frozen')
            for field in ('business', 'native', 'settled', 'cleanup'):
                if field not in value or (value[field] is not None and type(value[field]) is not bool):
                    raise ValueError('typed_receipt_required')
            for field in ('main_usage', 'auxiliary_calls', 'billing'):
                if field not in value: raise ValueError('cost_receipt_required')
            if value['main_usage'] is not None and not isinstance(value['main_usage'], dict): raise ValueError('invalid_usage')
            if value['auxiliary_calls'] is not None and (type(value['auxiliary_calls']) is not int or value['auxiliary_calls'] < 0):
                raise ValueError('invalid_auxiliary_calls')
            if value['billing'] is not None and (type(value['billing']) not in (int, float) or value['billing'] < 0):
                raise ValueError('invalid_billing')
            if value['outcome'] == 'succeeded' and not all(value[k] is True for k in ('business', 'native', 'settled', 'cleanup')):
                value['outcome'] = 'unknown'; value['qualification'] = 'incomplete_success_receipts'
            if value['outcome'] == 'failed' and (value['settled'] is not True or value['cleanup'] is not True):
                value['outcome'] = 'unknown'; value['qualification'] = 'execution_or_cleanup_unconfirmed'
            protocol = json.loads(c.execute('SELECT payload FROM trial_protocol WHERE id=1').fetchone()[0])
            if protocol['mode'] == 'paired_fixed_n':
                qualified, reason, endpoint = _paired_receipt(protocol, allocation, value)
                value.update(paired_qualified=qualified, paired_qualification=reason, paired_endpoint=endpoint)
            c.execute('INSERT INTO trial_receipts VALUES(?,?)', (allocation_id, canonical(value)))

    def stop(self, reason):
        if not isinstance(reason, str) or not re.fullmatch('[a-z][a-z0-9_]{0,95}', reason): raise ValueError('invalid_trial_stop')
        with self._connection() as c:
            if not c.execute('SELECT 1 FROM trial_protocol').fetchone(): raise ValueError('protocol_not_frozen')
            c.execute('INSERT OR IGNORE INTO trial_stop VALUES(1,?)', (reason,))

    def summary(self):
        with self._connection() as c:
            c.execute('BEGIN')
            protocol = c.execute('SELECT payload,hash FROM trial_protocol WHERE id=1').fetchone()
            stopped = c.execute('SELECT reason FROM trial_stop WHERE id=1').fetchone()
            rows = c.execute('SELECT a.payload allocation,r.payload receipt FROM trial_allocations a LEFT JOIN trial_receipts r ON r.allocation_id=a.id ORDER BY ordinal').fetchall()
        report = {'allocated': len(rows), 'succeeded': 0, 'failed': 0, 'unknown': 0, 'unrun': 0,
                  'missing_main_usage': 0, 'missing_token_counts': 0, 'auxiliary_calls': 0,
                  'missing_auxiliary_calls': 0, 'billing_unknown': 0, 'known_billing': 0,
                  'missing_auxiliary_usage': 0, 'missing_auxiliary_billing': 0,
                  'missing_training_usage': 0, 'missing_training_billing': 0,
                  'causal_gain_supported': False,
                  'claim': 'Finite usefulness pilot; no statistical or causal gain assertion',
                  'allocations': []}
        if protocol: report.update(protocol_hash=protocol['hash'], protocol=json.loads(protocol['payload']))
        for row in rows:
            receipt = json.loads(row['receipt']) if row['receipt'] else None
            report['allocations'].append({'allocation': json.loads(row['allocation']), 'receipt': receipt})
            report[receipt['outcome'] if receipt else 'unrun'] += 1
            usage = receipt.get('main_usage') if receipt else None
            if usage is None: report['missing_main_usage'] += 1
            if not _usage_known(usage):
                report['missing_token_counts'] += 1
            auxiliary = receipt.get('auxiliary_calls') if receipt else None
            if auxiliary is None: report['missing_auxiliary_calls'] += 1
            else: report['auxiliary_calls'] += auxiliary
            for component in ('auxiliary', 'training'):
                absent = component != 'auxiliary' or auxiliary != 0
                for field in ('usage', 'billing'):
                    component_value = receipt.get(component+'_'+field) if receipt else None
                    known = _usage_known(component_value) if field=='usage' else type(component_value) in (int,float) and component_value>=0
                    if absent and not known: report['missing_'+component+'_'+field] += 1
            billing = receipt.get('billing') if receipt else None
            if billing is None: report['billing_unknown'] += 1
            else: report['known_billing'] += billing
        report['protocol_stopped'] = bool(stopped)
        report['stop_reason'] = stopped['reason'] if stopped else None
        if protocol and report['protocol']['mode'] == 'paired_fixed_n':
            analysis = paired_analysis(report['protocol'], report['allocations'], bool(stopped), frozen=protocol['hash'] == digest(report['protocol']))
            report.update(paired_analysis=analysis, causal_gain_supported=analysis['causal_gain_supported'],
                          claim='Frozen paired endpoint analysis; real paired execution is a separate operation')
        return report
