"""Explicit JSON projections; private immutable bindings and atomic payload quota."""
from __future__ import annotations

import json
import re

try:
    from .autonomy_store import canonical, digest
    from .skill_evaluator import strict_json
except ImportError:
    from autonomy_store import canonical, digest
    from skill_evaluator import strict_json

# Business projection depth stays 32; intent.task_input.data adds two levels.
INPUT_ENVELOPE_DEPTH = 34


def rule_for(source):
    if 'persist_input_fields' not in source: return None
    fields = source['persist_input_fields']
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 32
        or any(not isinstance(f, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', f) for f in fields)
        or len(set(fields)) != len(fields)
        or not isinstance(source.get('input_fields'), list) or not set(fields) <= set(source['input_fields'])):
        raise ValueError('invalid_persist_input_fields')
    return {'schema': 1, 'source_id': source['id'], 'fields': sorted(fields)}


def project(source, parsed):
    rule = rule_for(source)
    if rule is None: return None
    if not isinstance(parsed, dict): raise ValueError('input_snapshot_object_required')
    try: data = {field: parsed[field] for field in rule['fields']}
    except KeyError: raise ValueError('input_snapshot_missing_field') from None
    data = strict_json(canonical(data)); size = len(canonical(data).encode())
    if size > 4096: raise ValueError('input_snapshot_too_large')
    return {'schema': 1, 'source_id': source['id'], 'rule_hash': digest(rule),
            'input_hash': digest(data), 'size': size, 'data': data}


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS task_inputs(
        goal_id TEXT PRIMARY KEY REFERENCES goals(id), schema INTEGER NOT NULL CHECK(schema=1),
        source_id TEXT NOT NULL, source_revision TEXT NOT NULL, rule_hash TEXT NOT NULL,
        input_hash TEXT NOT NULL, payload TEXT NOT NULL, size INTEGER NOT NULL CHECK(size BETWEEN 2 AND 4096))''')
    for action in ('UPDATE', 'DELETE'):
        c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_task_input_{action.lower()}
            BEFORE {action} ON task_inputs BEGIN SELECT RAISE(ABORT,'frozen_task_input'); END''')


def configure(ledger, sources, cap):
    if type(cap) is not int or cap < 0: raise ValueError('invalid_input_snapshot_bytes')
    rules = {s['id']: rule for s in sources if (rule := rule_for(s)) is not None}
    with ledger._connection(True) as c:
        for key, value in (('input_rules', rules), ('input_snapshot_bytes', cap)):
            c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      (key, canonical(value)))


def _setting(c, key, default):
    row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _validated(value):
    fields = {'schema','source_id','source_revision','rule_hash','input_hash','size','data'}
    if not isinstance(value, dict) or set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('invalid_input_snapshot')
    if not isinstance(value['source_id'], str) or not value['source_id'] or not isinstance(value['source_revision'], str) or not value['source_revision']:
        raise ValueError('invalid_input_snapshot_scope')
    data = strict_json(canonical(value['data']))
    if not isinstance(data, dict) or not 1 <= len(data) <= 32 or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', k) for k in data):
        raise ValueError('invalid_input_snapshot_fields')
    size = len(canonical(data).encode())
    rule = {'schema':1,'source_id':value['source_id'],'fields':sorted(data)}
    if (size > 4096 or type(value['size']) is not int or size != value['size']
        or digest(data) != value['input_hash'] or digest(rule) != value['rule_hash']):
        raise ValueError('invalid_input_snapshot_digest')
    return value


def binding(c, goal_id):
    row = c.execute('SELECT * FROM task_inputs WHERE goal_id=?', (goal_id,)).fetchone()
    if row is None: return None
    return _validated({key: row[key] for key in ('schema','source_id','source_revision','rule_hash','input_hash','size')}
                      | {'data': strict_json(row['payload'])})


def _applicable(c, value):
    rule = _setting(c, 'input_rules', {}).get(value['source_id'])
    return rule is not None and digest(rule) == value['rule_hash']


def bind_goal(c, goal_id, source_id, revision, value):
    if value is None:
        if source_id in _setting(c, 'input_rules', {}): raise ValueError('input_snapshot_required')
        return
    _validated(value)
    if value['source_id'] != source_id or value['source_revision'] != revision or not _applicable(c, value):
        raise ValueError('input_snapshot_scope_changed')
    used = c.execute('SELECT COALESCE(SUM(size),0) FROM task_inputs').fetchone()[0]
    if used + value['size'] > _setting(c, 'input_snapshot_bytes', 0):
        raise ValueError('input_snapshot_budget_exhausted')
    c.execute('INSERT INTO task_inputs VALUES(?,?,?,?,?,?,?,?)',
              (goal_id,1,source_id,revision,value['rule_hash'],value['input_hash'],canonical(value['data']),value['size']))


def valid_binding(c, goal, request):
    value = goal.get('task_input')
    required = goal['source_id'] in _setting(c, 'input_rules', {})
    try: intent = strict_json(request['input'],max_depth=INPUT_ENVELOPE_DEPTH)
    except (KeyError, TypeError, ValueError, UnicodeError):
        return value is None and not required
    if value is None:
        return not required and (not isinstance(intent, dict) or 'task_input' not in intent)
    return (_applicable(c, value) and isinstance(intent, dict) and intent.get('task_input') == value
            and canonical(intent['task_input']) == canonical(value))


def available(ledger, value):
    if value is None: return True
    with ledger._connection() as c:
        used = c.execute('SELECT COALESCE(SUM(size),0) FROM task_inputs').fetchone()[0]
        return _applicable(c, value) and used + value['size'] <= _setting(c, 'input_snapshot_bytes', 0)


def summary(ledger):
    with ledger._connection() as c:
        used, count = c.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM task_inputs').fetchone()
        return {'stored':count,'used_bytes':used,'limit_bytes':_setting(c,'input_snapshot_bytes',0),
                'configured_sources':len(_setting(c,'input_rules',{})),'scope':'Canonical input payload bytes only'}


def public_goals(ledger):
    result = []
    for goal in ledger.goals(20):
        item = {key:goal[key] for key in ('id','domain','objective','state','attempts','deadline','recovery_reason')}
        value = goal.get('task_input')
        item['input_snapshot'] = ({'available':True, **{k:value[k] for k in ('schema','input_hash','rule_hash','size')}}
                                  if value else {'available':False,'reason':'snapshot_unavailable'})
        result.append(item)
    return result
