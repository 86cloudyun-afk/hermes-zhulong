"""Independent, bounded correspondence for the production SQLite ledger.

Journal operations (strict payload keys are specified in FIELDS): create freezes
candidate/revision/contract/baseline/task input/created/deadline via operand hashes; claim derives
lease generation; renew/release fence ownership; prepare derives attempt and UTC
budget debit from admission guards and freezes submission inputs; admit records
host identity/status; runtime stutters; transition derives state and monotonic
settlement; result freezes first attempt evidence; finish derives receipt/final
truth and releases ownership; cancel/pause set flags; workflow_state covers
trusted workflow block/cancel writes. Workflow decisions themselves are excluded.

Actual projection reads authoritative columns directly, independently of replay
and production guards. Intent identity covers dedupe, candidate, source revision,
contract content, baseline, task-input binding/payload, created and deadline.
Submission identity covers request, session, execution identity, created and
retention; request/identity and fixed evidence are also hashed independently.
Creation and preparation journal only operand digests, not duplicate private input
payloads. These digests are computed from call inputs, never actual post-state.
The checkpoint is a trusted observation boundary, not proof of prior history.
SQLite/checker/authorized hooks are trusted; a writer able to replace code or
both journal and marker is outside scope. Settled is a ledger flag, not an OS
quiescence certificate. No provider or verifier I/O occurs here.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
MAX_EVENTS = 100000
MAX_BYTES = 33554432
PAGE_SIZE = 128
COVERAGE = ['paused', 'run_budget', 'goals', 'lease_fencing',
            'admission_pause/budget/cancel/ready/lease/current/attempts/active_guards',
            'submissions', 'fixed_intent_identity', 'fixed_evidence', 'final_truth']
EXCLUSIONS = ['reason', 'runtime/usage', 'source_planning', 'model_versions',
              'workflow_decisions/effects', 'diagnostic_budget', 'skill_internal_state',
              'verifier_correctness', 'OS_quiescence', 'history_before_checkpoint', 'evidence_created/settled_at/final_evidence_created',
              'forecast/monitoring', 'settings_other_than_paused',
              'workflow/skill/input_applicability_and_verification_resource_guards']
STATES = {'ready','submitting','running','verifying','succeeded','already_satisfied',
          'failed','blocked','unknown_result','cancelled'}
FIELDS = {
    'create': {'id','dedupe','candidate_hash','source_revision','contract_hash','baseline_hash','task_input_hash','deadline'},
    'claim': {'goal_id','owner','lease_seconds'},
    'renew': {'goal_id','owner','generation','lease_seconds'},
    'release': {'goal_id','owner','generation'},
    'prepare': {'goal_id','owner','generation','submission_id','expected_submission_id','request_hash','session_hash',
                'identity_hash','retention_seconds','daily_cap','max_active','max_attempts'},
    'admit': {'goal_id','owner','generation','submission_id','run_id','host_status'},
    'runtime': {'goal_id','owner','generation','submission_id'},
    'transition': {'goal_id','owner','generation','submission_id','state','settled'},
    'result': {'goal_id','owner','generation','submission_id','evidence'},
    'finish': {'goal_id','owner','generation','submission_id','evidence','outcome','settled'},
    'cancel': {'goal_id'}, 'pause': {'paused'}, 'workflow_state': {'goal_id','state'},
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _decode(raw):
    if not isinstance(raw,str):raise ValueError('json_text_required')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    def constant(value): raise ValueError('nonfinite_json')
    def number(value):
        parsed=float(value)
        if not math.isfinite(parsed):raise ValueError('nonfinite_json')
        return parsed
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


class _Unavailable(Exception): pass
class _Violation(Exception): pass


def _require(condition, field):
    if not condition: raise _Violation(field)


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _identity(dedupe, candidate_hash, revision, contract_hash, baseline_hash, task_input_hash, created, deadline):
    return _hash([dedupe,candidate_hash,revision,contract_hash,baseline_hash,task_input_hash,float(created),float(deadline)])


def _valid_hash(value):
    return isinstance(value,str) and len(value)==64 and all(ch in '0123456789abcdef' for ch in value)


def _input(c, goal_id):
    row = c.execute('SELECT * FROM task_inputs WHERE goal_id=?',(goal_id,)).fetchone()
    if row is None: return None
    return {key: row[key] for key in ('schema','source_id','source_revision','rule_hash','input_hash','size')} | {'data':_decode(row['payload'])}


def _actual_items(c):
    """Authoritative projection; never invokes event semantics or domain helpers."""
    row = c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
    yield ['paused','value',_decode(row[0]) if row else False]
    for row in c.execute('SELECT day,runs FROM run_budget ORDER BY day'):
        yield ['run_budget',row['day'],row['runs']]
    for row in c.execute('SELECT id,dedupe,candidate,source_revision,contract,contract_hash,baseline,created,deadline,'
                         'state,owner,generation,lease_until,attempts,submission_id,cancel_requested FROM goals ORDER BY id'):
        fixed = [row['dedupe'],_hash(_decode(row['candidate'])),row['source_revision'],_hash(_decode(row['contract'])),
                 _hash(_decode(row['baseline'])),_hash(_input(c,row['id'])),row['created'],row['deadline']]
        goal = {key:row[key] for key in ('state','owner','generation','lease_until','attempts','submission_id','cancel_requested','contract_hash')}
        goal.update(intent_hash=_hash(fixed), contract_content_hash=_hash(_decode(row['contract'])), deadline=row['deadline'])
        yield ['goals',row['id'],goal]
    for row in c.execute('SELECT id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds,'
                         'run_id,host_status,settled,evidence FROM submissions ORDER BY id'):
        request = _decode(row['request']); identity = _decode(row['execution_identity'])
        sub = {key:row[key] for key in ('goal_id','attempt','run_id','host_status','settled')}
        sub.update(request_hash=_hash(request), identity_hash=_hash(identity),
                   fixed_hash=_hash([_hash(request),_hash(row['session_key']),_hash(identity),row['created'],row['retention_seconds']]),
                   evidence_hash=None if row['evidence'] is None else _hash(_decode(row['evidence'])))
        yield ['submissions',row['id'],sub]
    for row in c.execute('SELECT goal_id,receipt,outcome,data FROM evidence ORDER BY receipt'):
        data = _decode(row['data'])
        if not isinstance(data,dict):raise ValueError('evidence_object_required')
        yield ['evidence',row['receipt'],{'goal_id':row['goal_id'],'outcome':row['outcome'],
               'evidence_hash':_hash(data),'contract_hash':data.get('contract_hash'),'verdict':data.get('verdict')}]


def _state(items):
    state = {'paused':{},'run_budget':{},'goals':{},'submissions':{},'evidence':{}}
    for section,key,value in items:
        if section not in state or key in state[section]: raise ValueError('checkpoint_duplicate_or_section')
        state[section][key] = value
    if set(state['paused']) != {'value'}: raise ValueError('checkpoint_pause_missing')
    return state


def _raw_bytes(c):
    """Preflight covered column bytes in SQLite before Python JSON decoding.

    Byte scope includes numeric/text encodings, not SQLite storage overhead.
    Queries have no independent CPU or wall-time bound.
    """
    covered = {
        'settings': ('value',), 'run_budget': ('day','runs'),
        'goals': ('id','dedupe','candidate','source_revision','contract','contract_hash','baseline','created','deadline',
                  'state','owner','generation','lease_until','attempts','submission_id','cancel_requested'),
        'submissions': ('id','goal_id','attempt','request','session_key','execution_identity','created','retention_seconds',
                        'run_id','host_status','settled','evidence'),
        'evidence': ('goal_id','receipt','outcome','data'),
        'task_inputs': ('goal_id','schema','source_id','source_revision','rule_hash','input_hash','payload','size'),
    }
    size = 0
    for table, fields in covered.items():
        terms = '+'.join('COALESCE(length(CAST('+field+' AS BLOB)),0)' for field in fields)
        condition = " WHERE key='paused'" if table=='settings' else ''
        size += c.execute('SELECT COALESCE(SUM('+terms+'),0) FROM '+table+condition).fetchone()[0]
    return size


def initialize(c):
    """One atomic bounded migration, only when no durable marker exists."""
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='refinement_marker'").fetchone(): return
    if (c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='refinement_journal'").fetchone()
        or c.execute("SELECT 1 FROM settings WHERE key='refinement_journal_fault'").fetchone()):
        c.execute("INSERT OR REPLACE INTO settings VALUES('refinement_journal_fault','marker_missing')")
        return
    items=[]; size=_raw_bytes(c)
    if size>MAX_BYTES:
        c.execute("INSERT OR REPLACE INTO settings VALUES('refinement_journal_fault','checkpoint_budget')")
        return
    for item in _actual_items(c):
        size += len(_json(item).encode())
        if len(items)>=MAX_EVENTS or size>MAX_BYTES:
            c.execute("INSERT OR REPLACE INTO settings VALUES('refinement_journal_fault','checkpoint_budget')")
            return
        items.append(item)
    pages = [items[i:i+PAGE_SIZE] for i in range(0,len(items),PAGE_SIZE)]
    c.execute('CREATE TABLE refinement_marker(id INTEGER PRIMARY KEY CHECK(id=1),schema INTEGER NOT NULL,page_count INTEGER NOT NULL,item_count INTEGER NOT NULL,checkpoint_hash TEXT NOT NULL)')
    c.execute('CREATE TABLE refinement_journal(seq INTEGER PRIMARY KEY AUTOINCREMENT,schema INTEGER NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,now REAL NOT NULL)')
    for index,page in enumerate(pages):
        c.execute('INSERT INTO refinement_journal(schema,action,payload,now) VALUES(?,?,?,0)',(SCHEMA,'checkpoint',_json({'page':index,'items':page})))
    c.execute('INSERT INTO refinement_marker VALUES(1,?,?,?,?)',(SCHEMA,len(pages),len(items),_hash(items)))
    for table in ('refinement_marker','refinement_journal'):
        for operation in ('update','delete'):
            c.execute(f"CREATE TRIGGER frozen_{table}_{operation} BEFORE {operation.upper()} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_refinement'); END")


def _schema(c):
    expected = {
        'refinement_marker':[('id','INTEGER',0,1),('schema','INTEGER',1,0),('page_count','INTEGER',1,0),
                             ('item_count','INTEGER',1,0),('checkpoint_hash','TEXT',1,0)],
        'refinement_journal':[('seq','INTEGER',0,1),('schema','INTEGER',1,0),('action','TEXT',1,0),
                              ('payload','TEXT',1,0),('now','REAL',1,0)]}
    for table,columns in expected.items():
        actual=[(r[1],r[2],r[3],r[5]) for r in c.execute('PRAGMA table_info('+table+')')]
        if actual != columns: raise _Unavailable('journal_schema_or_missing')
    rows = c.execute('SELECT * FROM refinement_marker').fetchall()
    if len(rows)!=1 or rows[0]['id']!=1 or rows[0]['schema']!=SCHEMA: raise _Unavailable('marker_schema')
    marker=rows[0]
    if type(marker['page_count']) is not int or marker['page_count']<1 or type(marker['item_count']) is not int or marker['item_count']<1:
        raise _Unavailable('checkpoint_metadata')
    return marker


def record(c, action, payload, now):
    """Write intent inside caller transaction; journal loss never blocks recovery."""
    if action not in FIELDS or not isinstance(payload,dict) or set(payload)!=FIELDS[action] or not _finite(now):
        raise ValueError('refinement_event_schema')
    body=_json(payload)
    try:
        _schema(c)
        c.execute('INSERT INTO refinement_journal(schema,action,payload,now) VALUES(?,?,?,?)',(SCHEMA,action,body,now))
        return True
    except (sqlite3.Error,_Unavailable):
        try:c.execute("INSERT OR REPLACE INTO settings VALUES('refinement_journal_fault','journal_unavailable')")
        except sqlite3.Error:pass  # A diagnostic failure must not roll back cleanup.
        return False


def _owned(state,p,now,current=False):
    g=state['goals'].get(p['goal_id'])
    _require(g is not None,'goal_id')
    _require(g['owner']==p['owner'] and g['generation']==p['generation'] and g['lease_until'] is not None and g['lease_until']>now,'lease_fencing')
    if current: _require(g['submission_id']==p['submission_id'],'current_submission')
    return g


def _settle(state,g,value):
    _require(value is None or type(value) is bool,'settled')
    if value is not None and g['submission_id'] in state['submissions']:
        s=state['submissions'][g['submission_id']];s['settled']=max(s['settled'],int(value))


def _truth(state,goal_id):
    return [e for e in state['evidence'].values() if e['goal_id']==goal_id and e['outcome'] in {'succeeded','failed'}]


def _apply(state,action,p,now):
    goals=state['goals'];subs=state['submissions']
    if action=='create':
        _require(isinstance(p['id'],str) and p['id'] not in goals,'goal_id')
        _require(_finite(p['deadline']),'deadline')
        for field in ('candidate_hash','contract_hash','baseline_hash','task_input_hash'):
            if not _valid_hash(p[field]):raise ValueError('immutable_operand_hash')
        goals[p['id']]={'state':'ready','owner':None,'generation':0,'lease_until':None,'attempts':0,
            'submission_id':None,'cancel_requested':0,'contract_hash':p['contract_hash'],
            'contract_content_hash':p['contract_hash'],'deadline':float(p['deadline']),
            'intent_hash':_identity(p['dedupe'],p['candidate_hash'],p['source_revision'],p['contract_hash'],p['baseline_hash'],p['task_input_hash'],now,p['deadline'])}
    elif action=='pause':
        _require(type(p['paused']) is bool,'paused');state['paused']['value']=p['paused']
    elif action=='cancel':
        _require(p['goal_id'] in goals,'goal_id');goals[p['goal_id']]['cancel_requested']=1
    elif action=='workflow_state':
        _require(p['goal_id'] in goals and p['state'] in {'blocked','cancelled'},'workflow_state')
        g=goals[p['goal_id']];_require(not _truth(state,p['goal_id']),'final_truth');g['state']=p['state']
    elif action=='claim':
        g=goals.get(p['goal_id']);_require(g is not None,'goal_id')
        _require(isinstance(p['owner'],str) and _finite(p['lease_seconds']) and p['lease_seconds']>0,'owner/lease_until')
        _require(g['owner'] is None or g['lease_until']<=now,'lease_fencing')
        active=g['submission_id'] in subs and not subs[g['submission_id']]['settled']
        _require(g['state'] in {'ready','blocked','submitting','running','verifying','unknown_result'} or active,'claim_state')
        g['owner']=p['owner'];g['generation']+=1;g['lease_until']=now+p['lease_seconds']
    elif action in {'renew','release'}:
        g=_owned(state,p,now)
        if action=='release':g['owner']=None;g['lease_until']=None
        else:
            _require(_finite(p['lease_seconds']) and p['lease_seconds']>0,'lease_until');g['lease_until']=now+p['lease_seconds']
    elif action=='prepare':
        g=_owned(state,p,now)
        for field in ('request_hash','session_hash','identity_hash'):
            if not _valid_hash(p[field]):raise ValueError('immutable_operand_hash')
        _require(g['submission_id']==p['expected_submission_id'],'current_submission')
        _require(not state['paused']['value'],'paused');_require(not g['cancel_requested'],'cancel_requested')
        _require(g['state']=='ready','state')
        for key in ('max_attempts','max_active','daily_cap','retention_seconds'):_require(type(p[key]) is int and p[key]>0,key)
        _require(g['attempts']<p['max_attempts'],'attempts')
        _require(g['submission_id'] not in subs or subs[g['submission_id']]['settled'],'settled')
        _require(sum(not s['settled'] for s in subs.values())<p['max_active'],'max_active')
        day=datetime.fromtimestamp(now,timezone.utc).date().isoformat();used=state['run_budget'].get(day,0)
        _require(used<p['daily_cap'],'run_budget')
        sid=p['submission_id'];_require(isinstance(sid,str) and sid not in subs,'submission_id')
        g['attempts']+=1;g['submission_id']=sid;g['state']='submitting';state['run_budget'][day]=used+1
        subs[sid]={'goal_id':p['goal_id'],'attempt':g['attempts'],'run_id':None,'host_status':None,'settled':0,
            'request_hash':p['request_hash'],'identity_hash':p['identity_hash'],
            'fixed_hash':_hash([p['request_hash'],p['session_hash'],p['identity_hash'],float(now),p['retention_seconds']]),'evidence_hash':None}
    else:
        g=_owned(state,p,now,current=True);sid=p['submission_id'];s=subs.get(sid)
        if action in {'admit','runtime','result'}:_require(s is not None and s['goal_id']==p['goal_id'],'submission_id')
        if action=='admit':
            _require(s['run_id'] is None or s['run_id']==p['run_id'],'run_id')
            s['run_id']=p['run_id'];s['host_status']=p['host_status'];g['state']='running'
        elif action=='runtime':pass
        elif action=='result':
            _require(isinstance(p['evidence'],dict) and p['evidence'].get('contract_hash')==g['contract_hash'],'evidence.contract_hash')
            if s['evidence_hash'] is None:s['evidence_hash']=_hash(p['evidence'])
        elif action=='transition':
            _require(p['state'] in STATES,'state')
            if p['state'] in {'succeeded','failed'}:_require(any(t['outcome']==p['state'] for t in _truth(state,p['goal_id'])),'final_truth')
            g['state']=p['state'];_settle(state,g,p['settled'])
        elif action=='finish':
            e=p['evidence'];outcome=p['outcome']
            _require(isinstance(e,dict) and e.get('contract_hash')==g['contract_hash'],'evidence.contract_hash')
            _require(outcome in {'succeeded','failed','already_satisfied','blocked','unknown_result','cancelled'},'outcome')
            if outcome in {'succeeded','failed'}:_require(e.get('verdict') is (outcome=='succeeded'),'final_truth.verdict')
            receipt=_hash([p['goal_id'],outcome,e]);truth=_truth(state,p['goal_id'])
            if not (outcome in {'succeeded','failed'} and truth):
                state['evidence'].setdefault(receipt,{'goal_id':p['goal_id'],'outcome':outcome,'evidence_hash':_hash(e),
                                                      'contract_hash':e.get('contract_hash'),'verdict':e.get('verdict')})
            g['state']=truth[0]['outcome'] if truth else outcome
            _settle(state,g,p['settled']);g['owner']=None;g['lease_until']=None


def _invariants(state):
    _require(type(state['paused']['value']) is bool,'paused')
    for runs in state['run_budget'].values():_require(type(runs) is int and runs>=0,'run_budget')
    grouped={}
    for sub in state['submissions'].values():grouped.setdefault(sub['goal_id'],[]).append(sub['attempt'])
    truths={}
    for item in state['evidence'].values():
        if item['outcome'] in {'succeeded','failed'}:truths.setdefault(item['goal_id'],[]).append(item)
    for gid,g in state['goals'].items():
        _require(g['state'] in STATES,'state')
        _require(type(g['attempts']) is int and g['attempts']>=0,'attempts')
        _require(type(g['generation']) is int and g['generation']>=0,'generation')
        _require(type(g['cancel_requested']) is int and g['cancel_requested'] in (0,1),'cancel_requested')
        _require((g['owner'] is None)==(g['lease_until'] is None),'owner/lease_until')
        _require(g['owner'] is None or (isinstance(g['owner'],str) and _finite(g['lease_until'])),'lease_until')
        _require(g['contract_hash']==g['contract_content_hash'],'contract_hash')
        attempts=sorted(grouped.get(gid,[]))
        _require(len(attempts)==g['attempts'] and all(value==index for index,value in enumerate(attempts,1)),'attempts')
        if g['submission_id'] is not None:
            s=state['submissions'].get(g['submission_id'])
            _require(s is not None and s['goal_id']==gid and s['attempt']==g['attempts'],'current_submission')
        else:_require(g['attempts']==0,'current_submission')
        truth=truths.get(gid,[]);_require(len(truth)<=1,'final_truth.unique')
        if truth:
            t=truth[0];_require(t['contract_hash']==g['contract_hash'] and t['verdict'] is (t['outcome']=='succeeded'),'final_truth.verdict/contract_hash')
        if g['state'] in {'succeeded','failed'}:_require(bool(truth) and truth[0]['outcome']==g['state'],'final_truth.state')
    for s in state['submissions'].values():
        _require(s['goal_id'] in state['goals'],'submission.goal_id')
        _require(type(s['attempt']) is int and s['attempt']>=1,'attempt')
        _require(type(s['settled']) is int and s['settled'] in (0,1),'settled')
    for e in state['evidence'].values():_require(e['goal_id'] in state['goals'],'evidence.goal_id')


def _brief(value):
    body=_json(value).encode()
    return value if len(body)<=1024 else {'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)}


def _difference(expected,actual,path=''):
    if isinstance(expected,dict) and isinstance(actual,dict):
        for key in sorted(set(expected)|set(actual)):
            field=(path+'.' if path else '')+str(key)
            if key not in expected or key not in actual:return {'field':field,'expected':_brief(expected.get(key)),'actual':_brief(actual.get(key))}
            difference=_difference(expected[key],actual[key],field)
            if difference:return difference
        return None
    if type(expected)!=type(actual) or expected!=actual:return {'field':path,'expected':_brief(expected),'actual':_brief(actual)}
    return None


def audit(c, *, max_events=MAX_EVENTS, max_bytes=MAX_BYTES):
    """One snapshot; budget raw covered SQL bytes, journal and projection bytes.

    This is a bounded correspondence claim, not a time or query CPU bound.
    """
    owns_transaction=not c.in_transaction
    if owns_transaction:c.execute('BEGIN')
    result={'schema':SCHEMA,'checker_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'coverage':COVERAGE,'exclusions':EXCLUSIONS,'through_seq':0,'snapshot_hash':None,'checkpoint_boundary':None}
    try:
        if type(max_events) is not int or type(max_bytes) is not int or max_events<0 or max_bytes<0:raise _Unavailable('scan_budget')
        if c.execute("SELECT 1 FROM settings WHERE key='refinement_journal_fault'").fetchone():raise _Unavailable('journal_unavailable')
        marker=_schema(c);items=[];state=None;size=_raw_bytes(c);count=0
        if size>max_bytes:raise _Unavailable('scan_budget')
        for row in c.execute('SELECT * FROM refinement_journal ORDER BY seq'):
            count+=1;size+=sum(len(str(row[key]).encode()) for key in ('seq','schema','action','payload','now'))
            if count>max_events or size>max_bytes:raise _Unavailable('scan_budget')
            if row['seq']!=count or row['schema']!=SCHEMA or not _finite(row['now']):raise _Unavailable('sequence_or_schema')
            payload=_decode(row['payload']);result['through_seq']=count
            if count<=marker['page_count']:
                if row['action']!='checkpoint' or set(payload)!={'page','items'} or type(payload['page']) is not int or payload['page']!=count-1:
                    raise _Unavailable('checkpoint_pages')
                page=payload['items']
                if not isinstance(page,list) or not 1<=len(page)<=PAGE_SIZE or (count<marker['page_count'] and len(page)!=PAGE_SIZE):raise _Unavailable('checkpoint_pages')
                items.extend(page)
                if count==marker['page_count']:
                    if len(items)!=marker['item_count'] or _hash(items)!=marker['checkpoint_hash']:raise _Unavailable('checkpoint_integrity')
                    state=_state(items);result['checkpoint_boundary']=count;_invariants(state)
            else:
                if row['action'] not in FIELDS or not isinstance(payload,dict) or set(payload)!=FIELDS[row['action']]:raise _Unavailable('event_schema')
                _apply(state,row['action'],payload,row['now'])
        if state is None:raise _Unavailable('checkpoint_missing')
        _invariants(state)
        actual_items=[]
        for item in _actual_items(c):
            size+=len(_json(item).encode())
            if len(actual_items)>=max_events or size>max_bytes:raise _Unavailable('scan_budget')
            actual_items.append(item)
        actual=_state(actual_items);result['snapshot_hash']=_hash(actual)
        difference=_difference(state,actual)
        if difference:result.update(status='counterexample',difference=difference)
        else:
            _invariants(actual);result['status']='valid_within_scope'
    except _Violation as exc:
        result.update(status='counterexample',difference={'field':str(exc),'expected':'domain_invariant','actual':'violated'})
    except (sqlite3.Error,_Unavailable,ValueError,TypeError,KeyError,OverflowError,RecursionError) as exc:
        result.update(status='unavailable',reason=str(exc))
    finally:
        if owns_transaction:c.rollback()
    return result
