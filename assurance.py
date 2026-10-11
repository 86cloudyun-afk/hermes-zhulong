"""Finite, independent protocol assurance; this is not a general correctness proof.

The journal stores trusted transaction metadata, never requests or reasoning. Hooks
must use the same SQLite transaction as the operation they describe. The reference
checker imports no production admission, lease, verifier or publication decisions.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import sqlite3
import time
from collections import deque

PROTOCOL_VERSION = 1
MODEL_VERSION = 1
MAX_EVENT_BYTES = 4096
INVARIANTS = ('budget', 'quiet_before_admission', 'lease_fencing', 'operation_intent',
              'pause_admission', 'pause_publication', 'unknown_not_failure',
              'submission_binding', 'active_capacity')
MUTATIONS = {'budget_guard', 'stale_lease_guard', 'pause_publication_guard',
             'unsettled_guard', 'unknown_failure_guard', 'operation_intent_guard',
             'active_capacity_guard', 'pause_admission_guard'}
FIELDS = {
    'initial_checkpoint': ({'paused', 'budgets', 'goals', 'submissions'}, {'counts'}),
    'checkpoint_part': ({'budgets', 'goals', 'submissions'}, set()),
    'pause': ({'paused'}, set()),
    'lease': ({'goal_id', 'owner', 'generation', 'expires_at'}, set()),
    'renew': ({'goal_id', 'owner', 'generation', 'expires_at'}, set()),
    'release': ({'goal_id', 'owner', 'generation'}, set()),
    'admission': ({'goal_id', 'owner', 'generation', 'submission_id', 'day', 'daily_cap', 'max_active'},
                  {'operation_id', 'request_hash', 'intent_hash'}),
    'runtime': ({'goal_id', 'owner', 'generation', 'submission_id'}, {'settled', 'outcome'}),
    'transition': ({'goal_id', 'owner', 'generation', 'submission_id', 'settled', 'outcome'}, {'verdict'}),
    'settlement': ({'goal_id', 'owner', 'generation', 'submission_id', 'settled', 'outcome'}, {'verdict'}),
    'publication': ({'skill_id', 'positive'}, {'outcome'}),
    'operation': ({'operation_id', 'intent_hash'}, set()),
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_event(kind, payload, now):
    if kind not in FIELDS or type(payload) is not dict or not _finite(now):
        raise ValueError('invalid_protocol_event')
    required, optional = FIELDS[kind]
    if not required <= payload.keys() or not payload.keys() <= required | optional:
        raise ValueError('invalid_protocol_fields')
    for key, value in payload.items():
        if key in {'goal_id', 'owner', 'submission_id', 'day', 'skill_id', 'operation_id',
                   'request_hash', 'intent_hash', 'outcome'}:
            if key == 'submission_id' and value is None and kind in {'transition', 'settlement'}:
                continue
            if type(value) is not str or not value or len(value) > 256:
                raise ValueError('invalid_protocol_identity')
        elif key in {'generation', 'daily_cap', 'max_active'}:
            if type(value) is not int or value < 1:
                raise ValueError('invalid_protocol_bound')
        elif key in {'paused', 'positive'}:
            if type(value) is not bool:
                raise ValueError('invalid_protocol_boolean')
        elif key in {'settled', 'verdict'}:
            if value is not None and type(value) is not bool:
                raise ValueError('invalid_protocol_boolean')
        elif key == 'expires_at' and not _finite(value):
            raise ValueError('invalid_protocol_time')
    if kind in {'initial_checkpoint', 'checkpoint_part'}:
        if any(type(payload[key]) is not dict for key in ('budgets', 'goals', 'submissions')):
            raise ValueError('invalid_checkpoint')
        for day, runs in payload['budgets'].items():
            if type(day) is not str or not day or type(runs) is not int or runs < 0:
                raise ValueError('invalid_checkpoint_budget')
        for gid, goal in payload['goals'].items():
            required_goal = {'owner', 'generation', 'expires_at', 'submission_id', 'outcome'}
            if (type(gid) is not str or not gid or type(goal) is not dict or
                not required_goal <= goal.keys() or not goal.keys() <= required_goal | {'truth'} or
                type(goal['generation']) is not int or goal['generation'] < 0 or
                (goal['owner'] is not None and (type(goal['owner']) is not str or not goal['owner'])) or
                (goal['expires_at'] is not None and not _finite(goal['expires_at'])) or
                (goal['submission_id'] is not None and type(goal['submission_id']) is not str) or
                type(goal['outcome']) is not str or goal.get('truth') not in (None, 'succeeded', 'failed')):
                raise ValueError('invalid_checkpoint_goal')
        for sid, submission in payload['submissions'].items():
            if (type(sid) is not str or not sid or type(submission) is not dict or
                set(submission) != {'goal_id', 'settled'} or
                type(submission['goal_id']) is not str or not submission['goal_id'] or
                type(submission['settled']) is not bool):
                raise ValueError('invalid_checkpoint_submission')
        if 'counts' in payload:
            counts = payload['counts']
            if (type(counts) is not dict or set(counts) != {'budgets', 'goals', 'submissions'} or
                any(type(value) is not int or value < 0 for value in counts.values())):
                raise ValueError('invalid_checkpoint_counts')
        if kind == 'initial_checkpoint' and 'counts' not in payload:
            _complete_checkpoint(payload, None)
    encoded = _canonical(payload)
    limit = 1024 * 1024 if kind == 'initial_checkpoint' else MAX_EVENT_BYTES
    if len(encoded.encode('utf-8')) > limit:
        raise ValueError('protocol_event_too_large')
    return encoded


def _complete_checkpoint(state, expected_counts):
    if expected_counts is not None and any(len(state[key]) != value for key, value in expected_counts.items()):
        raise ValueError('incomplete_checkpoint')
    for sid, submission in state['submissions'].items():
        if submission['goal_id'] not in state['goals']:
            raise ValueError('invalid_checkpoint_binding')
    for gid, goal in state['goals'].items():
        sid = goal['submission_id']
        if sid is not None and (sid not in state['submissions'] or state['submissions'][sid]['goal_id'] != gid):
            raise ValueError('invalid_checkpoint_binding')


def _checkpoint_pages(snapshot):
    """All legacy metadata, in bounded pages; no row-count truncation."""
    empty = {'budgets': {}, 'goals': {}, 'submissions': {}}
    page = copy.deepcopy(empty)
    for collection in empty:
        for key, value in sorted(snapshot[collection].items()):
            candidate = {**page, collection: {**page[collection], key: value}}
            if len(_canonical(candidate).encode('utf-8')) > MAX_EVENT_BYTES:
                if any(page.values()):
                    yield page
                page = copy.deepcopy(empty)
                page[collection][key] = value
                if len(_canonical(page).encode('utf-8')) > MAX_EVENT_BYTES:
                    raise ValueError('checkpoint_record_too_large')
            else:
                page = candidate
    if any(page.values()):
        yield page


def _tables(c):
    return {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _checkpoint(c):
    tables = _tables(c)
    paused = False
    if 'settings' in tables:
        row = c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        paused = bool(json.loads(row[0])) if row else False
    budgets = {row[0]: row[1] for row in c.execute('SELECT day,runs FROM run_budget')} if 'run_budget' in tables else {}
    goals, submissions = {}, {}
    if 'goals' in tables:
        for row in c.execute('SELECT id,owner,generation,lease_until,submission_id,state FROM goals'):
            goals[row[0]] = {'owner': row[1], 'generation': row[2], 'expires_at': row[3],
                             'submission_id': row[4], 'outcome': row[5], 'truth': None}
    if 'evidence' in tables:
        for row in c.execute("SELECT goal_id,outcome FROM evidence WHERE outcome IN ('succeeded','failed')"):
            if row[0] in goals:
                goals[row[0]]['truth'] = row[1]
    if 'submissions' in tables:
        current = {g['submission_id'] for g in goals.values()}
        for row in c.execute('SELECT id,goal_id,settled FROM submissions'):
            if not row[2] or row[0] in current:
                submissions[row[0]] = {'goal_id': row[1], 'settled': bool(row[2])}
    return {'paused': paused, 'budgets': budgets, 'goals': goals, 'submissions': submissions}


def initialize(c):
    """Create an immutable journal and a complete paged legacy checkpoint; never commit."""
    for statement in (
        '''CREATE TABLE IF NOT EXISTS protocol_events(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, protocol_version INTEGER NOT NULL,
            event TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL)''',
        '''CREATE TRIGGER IF NOT EXISTS frozen_protocol_event_update BEFORE UPDATE ON protocol_events
            BEGIN SELECT RAISE(ABORT,'frozen_protocol_event'); END''',
        '''CREATE TRIGGER IF NOT EXISTS frozen_protocol_event_delete BEFORE DELETE ON protocol_events
            BEGIN SELECT RAISE(ABORT,'frozen_protocol_event'); END''',
        '''CREATE TABLE IF NOT EXISTS assurance_checks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, model_hash TEXT NOT NULL,
            executed_at REAL NOT NULL, report TEXT NOT NULL)''',
        '''CREATE TRIGGER IF NOT EXISTS frozen_assurance_check_update BEFORE UPDATE ON assurance_checks
            BEGIN SELECT RAISE(ABORT,'frozen_assurance_check'); END''',
        '''CREATE TRIGGER IF NOT EXISTS frozen_assurance_check_delete BEFORE DELETE ON assurance_checks
            BEGIN SELECT RAISE(ABORT,'frozen_assurance_check'); END''',
    ):
        c.execute(statement)
    if c.execute('SELECT 1 FROM protocol_events LIMIT 1').fetchone() is None:
        snapshot = _checkpoint(c)
        now = time.time()
        counts = {key: len(snapshot[key]) for key in ('budgets', 'goals', 'submissions')}
        record_event(c, 'initial_checkpoint', {'paused': snapshot['paused'], 'budgets': {},
                     'goals': {}, 'submissions': {}, 'counts': counts}, now)
        for page in _checkpoint_pages(snapshot):
            record_event(c, 'checkpoint_part', page, now)


def record_event(c, event, payload, now):
    """Append accepted-operation metadata inside its caller's transaction."""
    body = _validate_event(event, payload, now)
    return c.execute('INSERT INTO protocol_events(protocol_version,event,payload,created) VALUES(?,?,?,?)',
                     (PROTOCOL_VERSION, event, body, now)).lastrowid


def _empty_state():
    return {'paused': False, 'budgets': {}, 'goals': {}, 'submissions': {},
            'operations': {}, 'published': []}


def _goal(state, goal_id):
    return state['goals'].setdefault(goal_id, {'owner': None, 'generation': 0,
        'expires_at': None, 'submission_id': None, 'outcome': 'ready', 'truth': None})


def _fenced(goal, payload, now):
    return (goal['owner'] == payload['owner'] and goal['generation'] == payload['generation']
            and goal['expires_at'] is not None and goal['expires_at'] > now)


def _reference_step(state, item):
    """Independent monitor: return (next_state, violated invariant or None)."""
    kind, p, now = item['event'], item['payload'], item['created']
    if kind == 'checkpoint_part':
        next_state = dict(state)
        for collection in ('budgets', 'goals', 'submissions'):
            if state[collection].keys() & p[collection].keys():
                raise ValueError('duplicate_checkpoint_entry')
            next_state[collection] = {**state[collection], **copy.deepcopy(p[collection])}
        for goal in p['goals']:
            next_state['goals'][goal].setdefault('truth', None)
        return next_state, None
    next_state = copy.deepcopy(state)
    if kind == 'initial_checkpoint':
        next_state.update({key: copy.deepcopy(p[key]) for key in ('paused', 'budgets', 'goals', 'submissions')})
        for goal in next_state['goals'].values():
            goal.setdefault('truth', None)
        return next_state, None
    if kind == 'pause':
        next_state['paused'] = p['paused']
    elif kind in {'lease', 'renew', 'release'}:
        g = _goal(next_state, p['goal_id'])
        if kind == 'lease':
            if (p['generation'] != g['generation'] + 1 or p['expires_at'] <= now or
                (g['owner'] is not None and g['expires_at'] is not None and g['expires_at'] > now)):
                return state, 'lease_fencing'
            g.update(owner=p['owner'], generation=p['generation'], expires_at=p['expires_at'])
        else:
            if not _fenced(g, p, now):
                return state, 'lease_fencing'
            if kind == 'renew':
                if p['expires_at'] <= now:
                    return state, 'lease_fencing'
                g['expires_at'] = p['expires_at']
            else:
                g.update(owner=None, expires_at=None)
    elif kind == 'admission':
        g = _goal(next_state, p['goal_id'])
        if not _fenced(g, p, now):
            return state, 'lease_fencing'
        if state['paused']:
            return state, 'pause_admission'
        active = [s for s in state['submissions'].values() if not s['settled']]
        if any(s['goal_id'] == p['goal_id'] for s in active):
            return state, 'quiet_before_admission'
        if state['budgets'].get(p['day'], 0) >= p['daily_cap']:
            return state, 'budget'
        if len(active) >= p['max_active']:
            return state, 'active_capacity'
        if p['submission_id'] in state['submissions']:
            return state, 'submission_binding'
        if 'intent_hash' in p:
            op = p.get('operation_id', p['goal_id'])
            if op in state['operations'] and state['operations'][op] != p['intent_hash']:
                return state, 'operation_intent'
            next_state['operations'][op] = p['intent_hash']
        next_state['budgets'][p['day']] = state['budgets'].get(p['day'], 0) + 1
        next_state['submissions'][p['submission_id']] = {'goal_id': p['goal_id'], 'settled': False}
        g.update(submission_id=p['submission_id'], outcome='submitting')
    elif kind in {'runtime', 'transition', 'settlement'}:
        g = _goal(next_state, p['goal_id'])
        if not _fenced(g, p, now):
            return state, 'lease_fencing'
        sid = p['submission_id']
        if g['submission_id'] != sid or (sid is not None and
            (sid not in state['submissions'] or state['submissions'][sid]['goal_id'] != p['goal_id'])):
            return state, 'submission_binding'
        if kind != 'runtime':
            # A tracking transition carries no independently verified final receipt.
            # It may preserve prior truth; only settlement may establish new truth.
            if (kind == 'transition' and p['outcome'] in {'failed', 'succeeded'}
                and g.get('truth') != p['outcome']):
                return state, 'unknown_not_failure'
            if kind == 'settlement' and p['outcome'] in {'failed', 'succeeded'}:
                preserved_truth = g.get('truth') == p['outcome']
                expected = p['outcome'] == 'succeeded'
                if not preserved_truth and p.get('verdict') is not expected:
                    return state, 'unknown_not_failure'
                if g.get('truth') is not None and not preserved_truth:
                    return state, 'unknown_not_failure'
                g['truth'] = p['outcome']
            if sid is not None and p['settled'] is True:
                next_state['submissions'][sid]['settled'] = True
            g['outcome'] = p['outcome']
            if kind == 'settlement':
                g.update(owner=None, expires_at=None)
    elif kind == 'publication':
        if p['positive'] and state['paused']:
            return state, 'pause_publication'
        if p['positive'] and p['skill_id'] not in next_state['published']:
            next_state['published'].append(p['skill_id'])
    elif kind == 'operation':
        if (p['operation_id'] in state['operations'] and
            state['operations'][p['operation_id']] != p['intent_hash']):
            return state, 'operation_intent'
        next_state['operations'][p['operation_id']] = p['intent_hash']
    return next_state, None


def _events(source):
    if isinstance(source, sqlite3.Connection):
        return [{'seq': row[0], 'protocol_version': row[1], 'event': row[2],
                 'payload': json.loads(row[3]), 'created': row[4]}
                for row in source.execute('SELECT seq,protocol_version,event,payload,created FROM protocol_events ORDER BY seq')]
    return list(source)


def validate_trace(source):
    """Project committed events into the independent reference monitor.

    An initial checkpoint establishes a trusted observation, not a certification
    of operations before instrumentation. A valid trace covers only events stored.
    """
    state, trace = _empty_state(), []
    try:
        items = _events(source)
    except (ValueError, TypeError, sqlite3.DatabaseError) as exc:
        return {'valid': False, 'events': 0, 'counterexample': {'invariant': 'protocol_schema', 'reason': str(exc), 'trace': []}}
    previous_seq, checkpoint_seen, operational_seen = 0, False, False
    expected_counts = None
    for index, item in enumerate(items):
        try:
            if type(item) is not dict or item.get('protocol_version') != PROTOCOL_VERSION:
                raise ValueError('unsupported_protocol_version')
            _validate_event(item['event'], item['payload'], item['created'])
            if item['event'] == 'initial_checkpoint':
                if index != 0:
                    raise ValueError('checkpoint_must_be_first')
                checkpoint_seen = True
                expected_counts = item['payload'].get('counts')
            elif item['event'] == 'checkpoint_part':
                if not checkpoint_seen or operational_seen:
                    raise ValueError('checkpoint_part_outside_initialization')
            else:
                if checkpoint_seen and not operational_seen:
                    _complete_checkpoint(state, expected_counts)
                operational_seen = True
            if 'seq' in item:
                if type(item['seq']) is not int or item['seq'] <= previous_seq:
                    raise ValueError('invalid_commit_order')
                previous_seq = item['seq']
            trace.append(item)
            next_state, violation = _reference_step(state, item)
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            return {'valid': False, 'events': index, 'counterexample':
                    {'invariant': 'protocol_schema', 'index': index, 'reason': str(exc), 'trace': trace + ([item] if not trace or trace[-1] is not item else [])}}
        if violation:
            return {'valid': False, 'events': index + 1, 'counterexample':
                    {'invariant': violation, 'index': index, 'trace': trace}}
        state = next_state
    if checkpoint_seen and not operational_seen:
        try:
            _complete_checkpoint(state, expected_counts)
        except ValueError as exc:
            return {'valid': False, 'events': len(items), 'counterexample':
                    {'invariant': 'protocol_schema', 'reason': str(exc), 'trace': trace}}
    return {'valid': True, 'events': len(items), 'state': state, 'counterexample': None,
            'scope': 'recorded protocol events from initial checkpoint; no pre-checkpoint proof'}


def _item(kind, payload):
    return {'protocol_version': PROTOCOL_VERSION, 'event': kind, 'payload': payload, 'created': 1}


def _model_candidates(state, bounds, mutation):
    """Finite reference transition generator, separate from the monitor."""
    yield _item('pause', {'paused': not state['paused']})
    if 'head' not in state['published'] and (not state['paused'] or mutation == 'pause_publication_guard'):
        yield _item('publication', {'skill_id': 'head', 'positive': True})
    op = state['operations'].get('op')
    if op is None:
        yield _item('operation', {'operation_id': 'op', 'intent_hash': 'first'})
    elif mutation == 'operation_intent_guard':
        yield _item('operation', {'operation_id': 'op', 'intent_hash': 'changed'})
    active = [s for s in state['submissions'].values() if not s['settled']]
    for n in range(bounds['goals']):
        gid = 'g' + str(n)
        g = state['goals'].get(gid, {'owner': None, 'generation': 0, 'expires_at': None,
                                    'submission_id': None, 'outcome': 'ready'})
        if g['owner'] is None and g['generation'] < bounds['generations']:
            yield _item('lease', {'goal_id': gid, 'owner': 'worker', 'generation': g['generation'] + 1, 'expires_at': 10})
        if g['owner'] is None:
            continue
        base = {'goal_id': gid, 'owner': 'worker', 'generation': g['generation']}
        yield _item('release', base)
        used = state['budgets'].get('day', 0)
        has_active = any(s['goal_id'] == gid for s in active)
        budget_ok = used < bounds['budget'] or mutation == 'budget_guard'
        quiet_ok = not has_active or mutation == 'unsettled_guard'
        # At most budget+1 admissions, including deliberately unsafe transitions.
        pause_ok = not state['paused'] or mutation == 'pause_admission_guard'
        capacity_ok = (len(active) < bounds['max_active'] or
                       mutation in {'active_capacity_guard', 'unsettled_guard'})
        if pause_ok and budget_ok and quiet_ok and capacity_ok and used <= bounds['budget']:
            candidate = {**base, 'submission_id': gid + '-s' + str(used), 'day': 'day',
                         'daily_cap': bounds['budget'], 'max_active': bounds['max_active']}
            yield _item('admission', candidate)
            if mutation == 'stale_lease_guard' and g['generation'] > 1:
                yield _item('admission', {**candidate, 'generation': g['generation'] - 1})
        sid = g['submission_id']
        if sid is not None and not state['submissions'][sid]['settled']:
            bound = {**base, 'submission_id': sid}
            if g['outcome'] != 'unknown_result':
                yield _item('transition', {**bound, 'outcome': 'unknown_result', 'settled': False})
            yield _item('transition', {**bound, 'outcome': 'ready', 'settled': True})
            if mutation == 'unknown_failure_guard' and g['outcome'] == 'unknown_result':
                yield _item('settlement', {**bound, 'outcome': 'failed', 'settled': False, 'verdict': None})


def model_hash():
    """Bind reports to the actual reference code, schema and protocol version."""
    contents = '\n'.join(inspect.getsource(f) for f in
        (_validate_event, _complete_checkpoint, _empty_state, _goal, _fenced, _reference_step, _item,
         _model_candidates, validate_trace, bounded_check))
    return hashlib.sha256((contents + _canonical({'version': MODEL_VERSION,
        'protocol': PROTOCOL_VERSION, 'invariants': INVARIANTS,
        'fields': {k: [sorted(v[0]), sorted(v[1])] for k, v in FIELDS.items()}})).encode()).hexdigest()


def bounded_check(*, goals=2, generations=2, budget=2, depth=8, max_active=1, mutation=None, ledger=None):
    """Actually execute finite BFS, optionally saving an immutable trusted report.

    Limits deliberately keep the default model small. Clocks use one abstract
    instant; leases can be released/reclaimed. Real expired leases are separately
    checked by trace validation. No filesystem, network or opaque effects modeled.
    """
    bounds = {'goals': goals, 'generations': generations, 'budget': budget, 'depth': depth, 'max_active': max_active}
    maxima = {'goals': 2, 'generations': 2, 'budget': 2, 'depth': 8, 'max_active': 2}
    if any(type(value) is not int or value < 1 or value > maxima[key] for key, value in bounds.items()):
        raise ValueError('unsupported_assurance_bounds')
    if mutation is not None and mutation not in MUTATIONS:
        raise ValueError('unknown_assurance_mutation')
    start = _empty_state()
    queue = deque([(start, [])])
    visited = {_canonical(start)}
    transitions, counterexample = 0, None
    while queue:
        state, trace = queue.popleft()
        if len(trace) >= depth:
            continue
        for item in _model_candidates(state, bounds, mutation):
            transitions += 1
            next_state, violation = _reference_step(state, item)
            if violation:
                counterexample = {'invariant': violation, 'trace': trace + [item]}
                break
            key = _canonical(next_state)
            if key not in visited:
                visited.add(key)
                queue.append((next_state, trace + [item]))
        if counterexample:
            break
    result = {'status': 'counterexample' if counterexample else 'no_counterexample_within_bounds',
              'model_version': MODEL_VERSION, 'protocol_version': PROTOCOL_VERSION,
              'model_hash': model_hash(), 'scope': {**bounds, 'clock': 'one abstract instant',
                'publication_heads': 1, 'operation_ids': 1,
                'admission_domain': 'Ledger Run submissions only; diagnostic budgets excluded'},
              'states': len(visited), 'transitions': transitions, 'counterexample': counterexample,
              'invariants': list(INVARIANTS), 'mutation': mutation, 'general_proof': False,
              'limitations': ['finite depth and domains only', 'no opaque effects, network or filesystem model',
                              'trace validity covers only recorded events after instrumentation'],
              'executed_at': time.time()}
    if ledger is not None:
        with ledger._connection(True) as c:
            initialize(c)
            c.execute('INSERT INTO assurance_checks(model_hash,executed_at,report) VALUES(?,?,?)',
                      (result['model_hash'], result['executed_at'], _canonical(result)))
    return result


def check_status(ledger):
    """Report executed checks for this model; never imply an unrun proof passed."""
    with ledger._connection() as c:
        if 'assurance_checks' not in _tables(c):
            return {'status': 'unrun', 'general_proof': False}
        row = c.execute('SELECT report FROM assurance_checks WHERE model_hash=? ORDER BY id DESC LIMIT 1',
                        (model_hash(),)).fetchone()
    if row is None:
        return {'status': 'unrun', 'general_proof': False}
    report = json.loads(row[0])
    # Mutation runs test the checker, and are never the operational safety status.
    if report.get('mutation') is not None:
        return {'status': 'mutation_check_only', 'general_proof': False,
                'model_hash': report['model_hash'], 'executed_at': report['executed_at']}
    return report
