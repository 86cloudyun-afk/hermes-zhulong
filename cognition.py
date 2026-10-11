"""Bounded metadata workspace and context-delivery receipts.

Facts live only in transient observations (or the existing authorized task_input).
These records establish delivered context, never hidden model use or experience.
"""
from __future__ import annotations
import json
import math
import sqlite3
import uuid

try:
    from .autonomy_store import canonical, digest
except ImportError:
    from autonomy_store import canonical, digest

DEFAULTS={'enabled':False,'capacity':3,'ttl_seconds':120,'mask_consumer':None,'selection_mode':'adaptive'}
MECHANISM={'schema':1,'selection':'least_recent_source_then_stable_id','constant':'stable_id_prefix',
           'evidence':'delivered_context_only','hidden_activations':'unavailable','subjective_experience':'unidentified'}


def validate_cognition(raw):
    if raw is None:raw={}
    if not isinstance(raw,dict) or set(raw)-set(DEFAULTS):raise ValueError('invalid_cognition_fields')
    result={**DEFAULTS,**raw}
    if type(result['enabled']) is not bool:raise ValueError('invalid_cognition_enabled')
    for key,limit in (('capacity',8),('ttl_seconds',3600)):
        if type(result[key]) is not int or not 1<=result[key]<=limit:raise ValueError('invalid_cognition_'+key)
    if result['mask_consumer'] is not None and (not isinstance(result['mask_consumer'],str) or result['mask_consumer'] not in ('planner','executor','monitor')):
        raise ValueError('invalid_cognition_mask')
    if not isinstance(result['selection_mode'],str) or result['selection_mode'] not in ('adaptive','constant'):
        raise ValueError('invalid_cognition_selection')
    return result


def initialize(c):
    definitions={
        'cognition_frames':('seq INTEGER PRIMARY KEY AUTOINCREMENT, frame_id TEXT NOT NULL UNIQUE, frame TEXT NOT NULL, frame_hash TEXT NOT NULL',
                            'seq=NEW.seq OR frame_id=NEW.frame_id'),
        'cognition_bindings':('goal_id TEXT PRIMARY KEY REFERENCES goals(id), frame_id TEXT NOT NULL REFERENCES cognition_frames(frame_id)', 'goal_id=NEW.goal_id'),
        'cognition_receipts':('id TEXT PRIMARY KEY, frame_id TEXT NOT NULL REFERENCES cognition_frames(frame_id), receipt TEXT NOT NULL', 'id=NEW.id')}
    for table,(columns,collision) in definitions.items():
        c.execute(f'CREATE TABLE IF NOT EXISTS {table}({columns})')
        for action in ('UPDATE','DELETE'):
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_{table}_{action.lower()} BEFORE {action} ON {table}
                BEGIN SELECT RAISE(ABORT,'frozen_cognition'); END''')
        # REPLACE deletes do not fire DELETE triggers with recursive_triggers OFF.
        c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_{table}_collision BEFORE INSERT ON {table}
            WHEN EXISTS(SELECT 1 FROM {table} WHERE {collision})
            BEGIN SELECT RAISE(ABORT,'frozen_cognition_collision'); END''')


def _time(now):
    if type(now) not in (int,float) or not math.isfinite(now):raise ValueError('invalid_cognition_time')
    return float(now)


def _entry(o):
    if o.get('task_input') is not None:
        try:
            from .task_inputs import _validated
        except ImportError:
            from task_inputs import _validated
        value=_validated(o['task_input'])
        if value['source_id']!=o['id'] or value['source_revision']!=o['revision']:
            raise ValueError('cognition_input_scope_changed')
    return {'source_id':o['id'],'revision':o['revision'],'input_hash':(o.get('task_input') or {}).get('input_hash'),
            'facts_hash':digest(o.get('facts',''))}


def _frame(c,frame):
    if not isinstance(frame,dict):raise ValueError('cognition_frame_required')
    row=c.execute('SELECT frame,frame_hash FROM cognition_frames WHERE frame_id=?',(frame.get('frame_id'),)).fetchone()
    if row is None or row['frame_hash']!=digest(frame) or row['frame']!=canonical(frame):raise ValueError('cognition_frame_invalid')
    return json.loads(row['frame'])


def _packet(frame,consumer):
    masked=frame['policy']['mask_consumer']==consumer
    return {'schema':1,'frame_id':frame['frame_id'],'frame_hash':digest(frame),
            'identity_hash':frame['identity_hash'],'policy_hash':frame['policy_hash'],'mechanism_hash':frame['mechanism_hash'],
            'captured_at':frame['captured_at'],'expires_at':frame['expires_at'],
            'historical':consumer!='planner','consumer':consumer,'visibility':'masked' if masked else 'visible',
            'entries':[] if masked else frame['entries'],'forecast':None if masked else frame['forecast'],
            'limitations':dict(MECHANISM)}


def packet(c,goal_id,consumer):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cognition_bindings'").fetchone() is None:
        return {'schema':1,'visibility':'unavailable','consumer':consumer,'reason':'journal_unavailable',
                'historical':True,'limitations':dict(MECHANISM)}
    row=c.execute('SELECT f.frame FROM cognition_bindings b JOIN cognition_frames f USING(frame_id) WHERE b.goal_id=?',(goal_id,)).fetchone()
    if row is None:return {'schema':1,'visibility':'unavailable','consumer':consumer,'reason':'no_historical_binding',
                           'historical':True,'limitations':dict(MECHANISM)}
    return _packet(json.loads(row[0]),consumer)


def bind_frame(c,goal_id,frame,now):
    frame=_frame(c,frame);now=_time(now)
    if not frame['captured_at']<=now<frame['expires_at']:raise ValueError('cognition_frame_expired')
    goal=c.execute('SELECT candidate,source_revision FROM goals WHERE id=?',(goal_id,)).fetchone()
    if goal is None:raise ValueError('cognition_goal_missing')
    candidate=json.loads(goal['candidate'])
    entry=next((e for e in frame['entries'] if e['source_id']==candidate['source_id']),None)
    inputrow=c.execute('SELECT input_hash FROM task_inputs WHERE goal_id=?',(goal_id,)).fetchone()
    if entry is None or entry['revision']!=goal['source_revision'] or entry['input_hash']!=(inputrow[0] if inputrow else None):
        raise ValueError('cognition_goal_binding_mismatch')
    source=c.execute('SELECT fingerprint FROM sources WHERE id=?',(candidate['source_id'],)).fetchone()
    if source and source[0]!=entry['revision']:raise ValueError('cognition_source_changed')
    old=c.execute('SELECT frame_id FROM cognition_bindings WHERE goal_id=?',(goal_id,)).fetchone()
    if old:
        if old[0]!=frame['frame_id']:raise ValueError('cognition_binding_conflict')
        return
    c.execute('INSERT INTO cognition_bindings VALUES(?,?)',(goal_id,frame['frame_id']))


def receipt(c,frame_id,channel,payload,now,*,goal_id=None,submission_id=None,status='delivered_context_only'):
    if c.execute('SELECT 1 FROM cognition_frames WHERE frame_id=?',(frame_id,)).fetchone() is None:raise ValueError('cognition_receipt_frame_missing')
    value={'schema':1,'frame_id':frame_id,'channel':channel,'payload_hash':digest(payload),'created_at':_time(now),
           'goal_id':goal_id,'submission_id':submission_id,'status':status,'limitation':'delivered_context_only'}
    c.execute('INSERT INTO cognition_receipts VALUES(?,?,?)',(uuid.uuid4().hex,frame_id,canonical(value)))
    return value


def request_packet(request):
    try:return json.loads(request['input']).get('cognitive_workspace')
    except (ValueError,TypeError,KeyError,AttributeError):return None


def validate_request(c,goal_id,request):
    expected=packet(c,goal_id,'executor');provided=request_packet(request)
    if expected['visibility']!='unavailable' and provided!=expected:raise ValueError('cognition_request_binding')
    if provided is not None and provided!=expected:raise ValueError('cognition_request_binding')
    return expected


def prepared(c,goal_id,submission_id,request,now):
    p=validate_request(c,goal_id,request)
    if 'frame_id' in p:receipt(c,p['frame_id'],'executor_prepared',request,now,goal_id=goal_id,submission_id=submission_id,status='prepared_only')


class Workspace:
    def __init__(self,ledger,policy,identity):
        self.ledger=ledger
        self.policy=validate_cognition(policy.get('cognition') if isinstance(policy,dict) and 'cognition' in policy else policy)
        self.identity_hash=digest(identity)
        self.receipt_unavailable=False

    def select(self,observations,now,*,source_owner=None,lease_seconds=120,max_attempts=3):
        now=_time(now)
        if not self.policy['enabled']:return None
        with self.ledger._connection(True) as c:
            eligible=[]
            for o in observations:
                if not o.get('available'):continue
                if source_owner is not None and o.get('task_input') is not None:
                    try:
                        from .task_inputs import _applicable, _setting
                    except ImportError:
                        from task_inputs import _applicable, _setting
                    used=c.execute('SELECT COALESCE(SUM(size),0) FROM task_inputs').fetchone()[0]
                    value=o['task_input']
                    if not _applicable(c,value) or used+value['size']>_setting(c,'input_snapshot_bytes',0):continue
                if source_owner is not None:
                    if not self.ledger._source_eligible(c,o['id'],o['revision'],now,max_attempts):continue
                eligible.append(o)
            history={}
            for row in c.execute('SELECT seq,frame FROM cognition_frames ORDER BY seq'):
                for e in json.loads(row['frame'])['entries']:history[e['source_id']]=row['seq']
            ordered=sorted(eligible,key=lambda o:((history.get(o['id'],0) if self.policy['selection_mode']=='adaptive' else 0),o['id']))
            # Forecast uses the old persisted history and full eligible source set.
            forecast={'source_ids':[o['id'] for o in ordered[:self.policy['capacity']]],
                      'prior_history_hash':digest(history),'eligible_hash':digest([_entry(o) for o in sorted(eligible,key=lambda o:o['id'])]),
                      'origin':'deterministic_schedule_before_selection'}
            selected=ordered[:self.policy['capacity']]
            if not selected:return None
            if source_owner is not None:
                for o in selected:
                    if not self.ledger._claim_source(c,o['id'],o['revision'],source_owner,now,lease_seconds,max_attempts):
                        raise ValueError('cognition_source_claim_changed')
            frame={'schema':1,'frame_id':uuid.uuid4().hex,'identity_hash':self.identity_hash,
                   'policy':dict(self.policy),'policy_hash':digest(self.policy),'mechanism_hash':digest(MECHANISM),
                   'captured_at':now,'expires_at':now+self.policy['ttl_seconds'],
                   'entries':[_entry(o) for o in selected],'forecast':forecast}
            c.execute('INSERT INTO cognition_frames(frame_id,frame,frame_hash) VALUES(?,?,?)',(frame['frame_id'],canonical(frame),digest(frame)))
            return frame

    def planner_view(self,frame,observations,now):
        with self.ledger._connection() as c:frame=_frame(c,frame)
        now=_time(now)
        if not frame['captured_at']<=now<frame['expires_at']:raise ValueError('cognition_frame_expired')
        known={o['id']:o for o in observations if o.get('available')};selected=[]
        for entry in frame['entries']:
            o=known.get(entry['source_id'])
            if o is None or _entry(o)!=entry:raise ValueError('cognition_observation_changed')
            safe={k:o[k] for k in ('id','domain','contract_ids','available','revision') if k in o}
            if frame['policy']['mask_consumer']!='planner':
                safe['facts']=o.get('facts','')
                if o.get('task_input') is not None:safe['task_input']=json.loads(canonical(o['task_input']))
            selected.append(safe)
        return {'observations':selected,'workspace':_packet(frame,'planner')}

    def bind_goal(self,goal_id,frame,now,*,connection=None):
        if connection is not None:return bind_frame(connection,goal_id,frame,now)
        with self.ledger._connection(True) as c:return bind_frame(c,goal_id,frame,now)

    def execution_packet(self,goal_id):
        with self.ledger._connection() as c:return packet(c,goal_id,'executor')

    def monitor_packet(self,goal_id):
        with self.ledger._connection() as c:return packet(c,goal_id,'monitor')

    def record(self,frame_id,channel,payload,now,*,source_owner=None,**binding):
        with self.ledger._connection(True) as c:
            if source_owner is not None:
                row=c.execute('SELECT frame FROM cognition_frames WHERE frame_id=?',(frame_id,)).fetchone()
                if row is None:raise ValueError('cognition_receipt_frame_missing')
                frame=json.loads(row[0])
                if not frame['captured_at']<=now<frame['expires_at']:raise ValueError('cognition_frame_expired')
                for entry in frame['entries']:
                    row=c.execute('SELECT outcome FROM sources WHERE id=? AND fingerprint=?',(entry['source_id'],entry['revision'])).fetchone()
                    claim=json.loads(row[0]) if row else {}
                    if claim.get('owner')!=source_owner or claim.get('until',0)<=now:raise ValueError('cognition_source_lease_lost')
            return receipt(c,frame_id,channel,payload,now,**binding)

    def runs_boundary(self,submission,channel,now,status):
        p=request_packet(submission['request'])
        if p and 'frame_id' in p:
            try:
                return self.record(p['frame_id'],channel,submission['request'],now,goal_id=submission['goal_id'],submission_id=submission['id'],status=status)
            except (sqlite3.DatabaseError,ValueError):
                # Instrumentation cannot block recovery of an immutable request.
                self.receipt_unavailable=True
                return {'visibility':'unavailable','reason':'receipt_journal_unavailable','remote_receipt':'unknown'}

    def summary(self):
        with self.ledger._connection() as c:
            result={'schema':1,'enabled':self.policy['enabled'],'policy':dict(self.policy),'limitations':dict(MECHANISM)}
            result['frames']=c.execute('SELECT COUNT(*) FROM cognition_frames').fetchone()[0]
            result['bindings']=c.execute('SELECT COUNT(*) FROM cognition_bindings').fetchone()[0]
            result['consumer_receipts']={}
            if self.receipt_unavailable or c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cognition_receipts'").fetchone() is None:
                result['receipt_logging']='unavailable'
                return result
            for row in c.execute('SELECT receipt FROM cognition_receipts'):
                channel=json.loads(row[0])['channel'];result['consumer_receipts'][channel]=result['consumer_receipts'].get(channel,0)+1
            return result
