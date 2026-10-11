"""Durable goal, submission and evidence truth. No model or HTTP call belongs here."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


try:
    from . import refinement
except ImportError:
    import refinement


def _refine(c,action,lease,now,**payload):
    if lease is not None:payload={'goal_id':lease.goal_id,'owner':lease.owner,'generation':lease.generation,**payload}
    return refinement.record(c,action,payload,now)


def _protocol(c,event,lease,now,**payload):
    try:
        from .assurance import record_event
    except ImportError:
        from assurance import record_event
    if lease is not None:payload={'goal_id':lease.goal_id,'owner':lease.owner,'generation':lease.generation,**payload}
    record_event(c,event,payload,now)


@dataclass(frozen=True)
class GoalLease:
    goal_id: str
    owner: str
    generation: int
    expires_at: float


STATES = {'ready','submitting','running','verifying','succeeded','already_satisfied',
          'failed','blocked','unknown_result','cancelled'}


class Ledger:
    def __init__(self, path: Path, timeout_seconds: float = 5.0):
        self.path, self.timeout = Path(path), timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(True) as c:
            statements = [
                '''CREATE TABLE IF NOT EXISTS goals(
                    id TEXT PRIMARY KEY, dedupe TEXT NOT NULL UNIQUE, candidate TEXT NOT NULL,
                    source_revision TEXT NOT NULL, contract TEXT NOT NULL, contract_hash TEXT NOT NULL,
                    baseline TEXT NOT NULL, created REAL NOT NULL, deadline REAL NOT NULL,
                    state TEXT NOT NULL DEFAULT 'ready', attempts INTEGER NOT NULL DEFAULT 0,
                    owner TEXT, generation INTEGER NOT NULL DEFAULT 0, lease_until REAL,
                    submission_id TEXT, reason TEXT NOT NULL DEFAULT '')''',
                '''CREATE TABLE IF NOT EXISTS submissions(
                    id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id),
                    attempt INTEGER NOT NULL, request TEXT NOT NULL, session_key TEXT NOT NULL,
                    execution_identity TEXT NOT NULL, created REAL NOT NULL, retention_seconds INTEGER NOT NULL,
                    run_id TEXT, host_status TEXT, settled INTEGER NOT NULL DEFAULT 0,
                    forecast REAL, evidence TEXT, UNIQUE(goal_id,attempt))''',
                '''CREATE TABLE IF NOT EXISTS evidence(
                    id INTEGER PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id),
                    receipt TEXT NOT NULL UNIQUE, outcome TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL)''',
                "CREATE UNIQUE INDEX IF NOT EXISTS final_truth ON evidence(goal_id) WHERE outcome IN ('succeeded','failed')",
                'CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, fingerprint TEXT, outcome TEXT, updated REAL)',
                'CREATE TABLE IF NOT EXISTS run_budget(day TEXT PRIMARY KEY, runs INTEGER NOT NULL)',
                'CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS model_versions(version INTEGER PRIMARY KEY AUTOINCREMENT, snapshot TEXT NOT NULL)',
                '''CREATE TRIGGER IF NOT EXISTS frozen_goal BEFORE UPDATE OF
                    dedupe,candidate,source_revision,contract,contract_hash,baseline,created,deadline ON goals
                    BEGIN SELECT RAISE(ABORT,'frozen_goal'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_submission BEFORE UPDATE OF
                    goal_id,attempt,request,session_key,execution_identity,created,retention_seconds,forecast ON submissions
                    BEGIN SELECT RAISE(ABORT,'frozen_submission'); END''',
            ]
            for statement in statements: c.execute(statement)
            columns={r[1] for r in c.execute('PRAGMA table_info(goals)')}
            if 'cancel_requested' not in columns:c.execute('ALTER TABLE goals ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0')
            columns={r[1] for r in c.execute('PRAGMA table_info(submissions)')}
            for name in ('usage','runtime'):
                if name not in columns:c.execute(f'ALTER TABLE submissions ADD COLUMN {name} TEXT')
            for name in ('evidence_created','settled_at'):
                if name not in columns:c.execute(f'ALTER TABLE submissions ADD COLUMN {name} REAL')
            try:
                from .task_inputs import initialize
            except ImportError:
                from task_inputs import initialize
            initialize(c)
            try:
                from . import workflow,metacognition,assurance,cognition
            except ImportError:
                import workflow,metacognition,assurance,cognition
            for module in (workflow,metacognition,assurance,cognition):module.initialize(c)
            refinement.initialize(c)

    @contextmanager
    def _connection(self, write=False):
        c=sqlite3.connect(str(self.path), timeout=self.timeout, isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA synchronous=FULL')
        try:
            c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally: c.close()

    @staticmethod
    def _submission(row):
        if row is None: return None
        result=dict(row)
        for key in ('request','execution_identity','evidence','usage','runtime'):
            if result.get(key) is not None: result[key]=json.loads(result[key])
        result['settled']=bool(result['settled'])
        return result

    def _goal(self,c,row):
        if row is None: return None
        result=dict(row)
        for key in ('candidate','contract','baseline'):result[key]=json.loads(result[key])
        result['operation_id']=result['id']
        result.update({key:result['candidate'].get(key) for key in ('domain','objective','reason','source_id','contract_id','confidence','expected_benefit')})
        result['recovery_reason']=row['reason']
        result['submission']=self._submission(c.execute('SELECT * FROM submissions WHERE id=?',(row['submission_id'],)).fetchone()) if row['submission_id'] else None
        try:
            from .task_inputs import binding
        except ImportError:
            from task_inputs import binding
        result['task_input']=binding(c,row['id'])
        try:
            from .workflow import binding as workflow_binding
        except ImportError:
            from workflow import binding as workflow_binding
        metadata=workflow_binding(c,row['id'])
        if metadata is not None:result.update(metadata)
        return result

    def create_goal(self,candidate,source_revision,contract,baseline,now,deadline_seconds,*,source_owner=None,task_input=None,cognition_frame=None):
        key=digest([candidate['source_id'],source_revision,candidate['contract_id'],contract])
        with self._connection(True) as c:
            if source_owner is not None:
                source=c.execute('SELECT outcome FROM sources WHERE id=? AND fingerprint=?',(candidate['source_id'],source_revision)).fetchone()
                state=json.loads(source[0]) if source else {}
                if state.get('owner')!=source_owner or state.get('until',0)<=now:return None
            inserted=c.execute('INSERT OR IGNORE INTO goals(id,dedupe,candidate,source_revision,contract,contract_hash,baseline,created,deadline) VALUES(?,?,?,?,?,?,?,?,?)',
                (uuid.uuid4().hex,key,canonical(candidate),source_revision,canonical(contract),digest(contract),canonical(baseline),now,now+deadline_seconds))
            goal=c.execute('SELECT * FROM goals WHERE dedupe=?',(key,)).fetchone()
            try:
                from .task_inputs import bind_goal,binding
            except ImportError:
                from task_inputs import bind_goal,binding
            if inserted.rowcount:
                bind_goal(c,goal['id'],candidate['source_id'],source_revision,task_input)
                if cognition_frame is not None:
                    try:
                        from .cognition import bind_frame
                    except ImportError:
                        from cognition import bind_frame
                    bind_frame(c,goal['id'],cognition_frame,now)
                _refine(c,'create',None,now,id=goal['id'],dedupe=key,candidate_hash=digest(candidate),source_revision=source_revision,
                    contract_hash=digest(contract),baseline_hash=digest(baseline),task_input_hash=digest(task_input),deadline=now+deadline_seconds)
            elif task_input is not None:
                original=binding(c,goal['id'])
                if original is None:raise ValueError('input_snapshot_legacy_unavailable')
                if canonical(original)!=canonical(task_input):raise ValueError('input_snapshot_conflict')
            return self._goal(c,goal)

    @staticmethod
    def _owned(c,lease,now):
        if lease is None:return False
        return c.execute('SELECT 1 FROM goals WHERE id=? AND owner=? AND generation=? AND lease_until>?',
            (lease.goal_id,lease.owner,lease.generation,now)).fetchone() is not None

    @classmethod
    def _current(cls,c,lease,now,submission_id):
        if not cls._owned(c,lease,now):return False
        return c.execute('SELECT submission_id FROM goals WHERE id=?',(lease.goal_id,)).fetchone()[0]==submission_id

    def owned_goal(self,lease,now):
        with self._connection() as c:
            if not self._owned(c,lease,now):return None
            return self._goal(c,c.execute('SELECT * FROM goals WHERE id=?',(lease.goal_id,)).fetchone())

    def claim(self,owner,now,lease_seconds,ranked_goal_ids=()):
        with self._connection(True) as c:
            rows=c.execute('''SELECT g.* FROM goals g LEFT JOIN submissions s ON s.id=g.submission_id
                WHERE (g.owner IS NULL OR g.lease_until<=?) AND
                (g.state IN ('ready','blocked','submitting','running','verifying','unknown_result')
                 OR s.settled=0) ORDER BY CASE WHEN g.submission_id IS NOT NULL THEN 0 ELSE 1 END,g.deadline,g.id''',(now,)).fetchall()
            if ranked_goal_ids:
                by_id={r['id']:r for r in rows}
                rows=[by_id[i] for i in ranked_goal_ids if i in by_id]
            if not rows:return None
            row=rows[0]
            generation=row['generation']+1
            c.execute('UPDATE goals SET owner=?,generation=?,lease_until=? WHERE id=?',(owner,generation,now+lease_seconds,row['id']))
            lease=GoalLease(row['id'],owner,generation,now+lease_seconds)
            _protocol(c,'lease',lease,now,expires_at=lease.expires_at)
            _refine(c,'claim',None,now,goal_id=lease.goal_id,owner=owner,lease_seconds=lease_seconds)
            return lease

    def renew(self,lease,now,lease_seconds):
        with self._connection(True) as c:
            if not self._owned(c,lease,now):return False
            c.execute('UPDATE goals SET lease_until=? WHERE id=?',(now+lease_seconds,lease.goal_id))
            _protocol(c,'renew',lease,now,expires_at=now+lease_seconds)
            _refine(c,'renew',lease,now,lease_seconds=lease_seconds)
            return True

    def release(self,lease,now):
        with self._connection(True) as c:
            if not self._owned(c,lease,now):return False
            c.execute('UPDATE goals SET owner=NULL,lease_until=NULL WHERE id=?',(lease.goal_id,))
            _protocol(c,'release',lease,now)
            _refine(c,'release',lease,now)
            return True

    def prepare_submission(self,lease,request,session_key,execution_identity,now,daily_cap,max_active,max_attempts,retention_seconds,*,expected_submission_id=None,monitoring_policy=None,monitoring_capture=None,monitoring_recheck=None):
        body,identity=canonical(request),canonical(execution_identity)
        with self._connection(True) as c:
            before=refinement.audit(c)
            if before['status']!='valid_within_scope':
                c.execute("INSERT OR REPLACE INTO settings VALUES('refinement_last_blocked',?)",(canonical(before),))
                return {'admitted':False,'reason':'refinement_blocked','refinement':before}
            if not self._owned(c,lease,now):return {'admitted':False,'reason':'stale_lease'}
            goal=c.execute('SELECT * FROM goals WHERE id=?',(lease.goal_id,)).fetchone()
            if goal['submission_id']!=expected_submission_id:return {'admitted':False,'reason':'stale_submission'}
            existing=c.execute('SELECT * FROM submissions WHERE id=?',(goal['submission_id'],)).fetchone()
            if existing is not None and not existing['settled']:
                return {'admitted':False,'reason':'reconcile_existing','submission':self._submission(existing)}
            paused=c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            if paused and json.loads(paused[0]):return {'admitted':False,'reason':'paused'}
            if goal['cancel_requested']:return {'admitted':False,'reason':'cancelled'}
            if goal['state']!='ready':return {'admitted':False,'reason':'not_ready'}
            if goal['attempts']>=max_attempts:return {'admitted':False,'reason':'max_attempts'}
            try:
                from .workflow import admission_reason
                from . import metacognition
            except ImportError:
                from workflow import admission_reason
                import metacognition
            blocked=admission_reason(c,goal['id'])
            if blocked:return {'admitted':False,'reason':blocked}
            try:
                from .task_inputs import valid_binding
            except ImportError:
                from task_inputs import valid_binding
            if not valid_binding(c,self._goal(c,goal),request):
                return {'admitted':False,'reason':'input_snapshot_no_longer_applicable'}
            try:
                from .certified_bindings import valid_program_binding
            except ImportError:
                from certified_bindings import valid_program_binding
            if not valid_program_binding(c,self._goal(c,goal),json.loads(identity),json.loads(body)):
                return {'admitted':False,'reason':'certified_program_no_longer_applicable'}
            try:
                from .experience_store import valid_bindings
            except ImportError:
                from experience_store import valid_bindings
            if not valid_bindings(c,self._goal(c,goal),execution_identity,request):
                return {'admitted':False,'reason':'strategy_no_longer_applicable'}
            try:
                from .skill_store import valid_bindings as valid_skill_bindings
            except ImportError:
                from skill_store import valid_bindings as valid_skill_bindings
            if not valid_skill_bindings(c,self._goal(c,goal),execution_identity,request):
                return {'admitted':False,'reason':'skill_no_longer_applicable'}
            if c.execute('SELECT COUNT(*) FROM submissions WHERE settled=0').fetchone()[0]>=max_active:
                return {'admitted':False,'reason':'max_active'}
            contract=json.loads(goal['contract'])
            resource=contract.get('path') or contract.get('cwd')
            if resource:
                for active in c.execute('SELECT g.contract FROM submissions s JOIN goals g ON g.id=s.goal_id WHERE s.settled=0'):
                    other=json.loads(active[0])
                    # Arbitrary argv can inspect outside cwd; conservatively serialize
                    # its evidence scope against every execution in this ledger.
                    if contract.get('type')=='argv' or other.get('type')=='argv' or resource==(other.get('path') or other.get('cwd')):
                        return {'admitted':False,'reason':'verification_resource_active'}
            day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
            used=c.execute('SELECT runs FROM run_budget WHERE day=?',(day,)).fetchone()
            if daily_cap<=0 or (used and used[0]>=daily_cap):return {'admitted':False,'reason':'daily_cap'}
            try:
                prediction=metacognition.prepare(c,self._goal(c,goal),execution_identity,request,now,
                    monitoring_policy or {},capture=monitoring_capture,recheck=monitoring_recheck)
            except ValueError:return {'admitted':False,'reason':'monitoring_binding_invalid'}
            try:
                from . import cognition
            except ImportError:
                import cognition
            cognition.validate_request(c,goal['id'],request)
            sid=uuid.uuid4().hex
            c.execute('INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds,forecast) VALUES(?,?,?,?,?,?,?,?,?)',
                (sid,goal['id'],goal['attempts']+1,body,session_key,identity,now,retention_seconds,prediction['probability']))
            metacognition.record(c,sid,prediction)
            cognition.prepared(c,goal['id'],sid,request,now)
            c.execute('INSERT INTO run_budget(day,runs) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET runs=runs+1',(day,))
            c.execute("UPDATE goals SET attempts=attempts+1,submission_id=?,state='submitting' WHERE id=?",(sid,goal['id']))
            _protocol(c,'admission',lease,now,submission_id=sid,day=day,daily_cap=daily_cap,max_active=max_active,
                operation_id=self._goal(c,goal)['operation_id'],request_hash=digest(request),
                intent_hash=digest([goal['contract_hash'],goal['source_revision']]))
            _refine(c,'prepare',lease,now,submission_id=sid,expected_submission_id=expected_submission_id,
                request_hash=digest(request),session_hash=digest(session_key),identity_hash=digest(execution_identity),retention_seconds=retention_seconds,
                daily_cap=daily_cap,max_active=max_active,max_attempts=max_attempts)
            after=refinement.audit(c)
            if after['status']!='valid_within_scope':
                # Explicit rollback: returning from the connection context alone commits.
                c.rollback()
                c.execute('BEGIN IMMEDIATE')
                c.execute("INSERT OR REPLACE INTO settings VALUES('refinement_last_blocked',?)",(canonical(after),))
                return {'admitted':False,'reason':'refinement_blocked','refinement':after}
            return {'admitted':True,'reason':'prepared','submission':self._submission(c.execute('SELECT * FROM submissions WHERE id=?',(sid,)).fetchone())}

    def record_admission(self,lease,submission_id,run_id,host_status,now):
        with self._connection(True) as c:
            if not self._current(c,lease,now,submission_id):return False
            row=c.execute('SELECT * FROM submissions WHERE id=? AND goal_id=?',(submission_id,lease.goal_id)).fetchone()
            if not row or (row['run_id'] is not None and row['run_id']!=run_id):return False
            c.execute('UPDATE submissions SET run_id=?,host_status=? WHERE id=?',(run_id,str(host_status)[:64],submission_id))
            c.execute("UPDATE goals SET state='running' WHERE id=?",(lease.goal_id,))
            _protocol(c,'runtime',lease,now,submission_id=submission_id,settled=False)
            _refine(c,'admit',lease,now,submission_id=submission_id,run_id=run_id,host_status=str(host_status)[:64])
            return True

    def transition(self,lease,state,reason,now,execution_settled=None,*,expected_submission_id=None):
        if state not in STATES:raise ValueError('invalid_state')
        with self._connection(True) as c:
            if not self._current(c,lease,now,expected_submission_id):return False
            if state in ('succeeded','failed'):
                truth=c.execute("SELECT outcome FROM evidence WHERE goal_id=? AND outcome IN ('succeeded','failed')",(lease.goal_id,)).fetchone()
                if truth is None or truth['outcome']!=state:raise ValueError('terminal_transition_requires_verified_truth')
            c.execute('UPDATE goals SET state=?,reason=? WHERE id=?',(state,str(reason)[:240],lease.goal_id))
            if execution_settled is not None:
                c.execute('UPDATE submissions SET settled=MAX(settled,?),settled_at=CASE WHEN ? THEN COALESCE(settled_at,?) ELSE settled_at END WHERE id=(SELECT submission_id FROM goals WHERE id=?)',
                    (int(execution_settled),int(execution_settled),now,lease.goal_id))
            _protocol(c,'transition',lease,now,submission_id=expected_submission_id,settled=execution_settled,outcome=state)
            _refine(c,'transition',lease,now,submission_id=expected_submission_id,state=state,settled=execution_settled)
            return True

    def record_attempt_result(self,lease,submission_id,evidence,now):
        with self._connection(True) as c:
            if not self._current(c,lease,now,submission_id):return False
            goal=c.execute('SELECT contract_hash FROM goals WHERE id=?',(lease.goal_id,)).fetchone()
            if evidence.get('contract_hash')!=goal[0]:raise ValueError('changed_contract')
            c.execute('UPDATE submissions SET evidence=?,evidence_created=? WHERE id=? AND goal_id=? AND evidence IS NULL',(canonical(evidence),now,submission_id,lease.goal_id))
            _refine(c,'result',lease,now,submission_id=submission_id,evidence=evidence)
            return True

    def finish(self,lease,evidence,outcome,execution_settled,now,*,expected_submission_id=None):
        if outcome not in {'succeeded','failed','already_satisfied','blocked','unknown_result','cancelled'}:raise ValueError('invalid_outcome')
        with self._connection(True) as c:
            if not self._current(c,lease,now,expected_submission_id):return False
            goal=c.execute('SELECT * FROM goals WHERE id=?',(lease.goal_id,)).fetchone()
            if evidence.get('contract_hash')!=goal['contract_hash']:raise ValueError('changed_contract')
            if outcome=='succeeded':
                try:
                    from .workflow import finalizable
                except ImportError:
                    from workflow import finalizable
                if evidence.get('verdict') is not True or (not goal['attempts'] and not finalizable(c,goal['id'])):raise ValueError('unverified_success')
            if outcome=='failed' and evidence.get('verdict') is not False:raise ValueError('unverified_failure')
            requested_outcome=outcome
            receipt=digest([lease.goal_id,outcome,evidence])
            c.execute('INSERT OR IGNORE INTO evidence(goal_id,receipt,outcome,data,created) VALUES(?,?,?,?,?)',(lease.goal_id,receipt,outcome,canonical(evidence),now))
            truth=c.execute("SELECT outcome FROM evidence WHERE goal_id=? AND outcome IN ('succeeded','failed')",(lease.goal_id,)).fetchone()
            if truth is not None:outcome=truth['outcome']
            c.execute('UPDATE goals SET state=?,reason=?,owner=NULL,lease_until=NULL WHERE id=?',(outcome,str(evidence.get('reason',''))[:240],lease.goal_id))
            c.execute('UPDATE submissions SET settled=MAX(settled,?),settled_at=CASE WHEN ? THEN COALESCE(settled_at,?) ELSE settled_at END WHERE id=?',
                (int(execution_settled),int(execution_settled),now,goal['submission_id']))
            _protocol(c,'settlement',lease,now,submission_id=goal['submission_id'],settled=bool(execution_settled),outcome=outcome,
                verdict=evidence.get('verdict') if type(evidence.get('verdict')) is bool else None)
            _refine(c,'finish',lease,now,submission_id=goal['submission_id'],evidence=evidence,outcome=requested_outcome,settled=bool(execution_settled))
            return True

    def request_cancel(self,goal_id):
        with self._connection(True) as c:
            changed=bool(c.execute('UPDATE goals SET cancel_requested=1 WHERE id=?',(goal_id,)).rowcount)
            if changed:
                import time
                _refine(c,'cancel',None,time.time(),goal_id=goal_id)
            return changed

    def work_goals(self):
        with self._connection() as c:
            rows=c.execute("SELECT g.* FROM goals g LEFT JOIN submissions s ON s.id=g.submission_id WHERE g.state IN ('ready','blocked','submitting','running','verifying','unknown_result') OR s.settled=0 ORDER BY g.deadline,g.id").fetchall()
            return [self._goal(c,r) for r in rows]

    def record_runtime(self,lease,submission_id,result,now):
        with self._connection(True) as c:
            if not self._current(c,lease,now,submission_id):return False
            c.execute('UPDATE submissions SET usage=?,runtime=? WHERE id=? AND goal_id=?',
                (canonical(result.get('usage')),canonical(result.get('runtime',{})),submission_id,lease.goal_id))
            _refine(c,'runtime',lease,now,submission_id=submission_id)
            return True

    @staticmethod
    def _source_prior(c,id,fingerprint,now):
        row=c.execute('SELECT * FROM sources WHERE id=?',(id,)).fetchone()
        prior=json.loads(row['outcome']) if row and row['fingerprint']==fingerprint else {}
        if not isinstance(prior,dict):prior={}
        if prior.get('status')=='planning' and prior.get('accounting')!='completed_plans' and prior.get('until',0)<=now:
            prior['attempts']=max(0,prior.get('attempts',0)-1)
        return prior

    @classmethod
    def _source_eligible(cls,c,id,fingerprint,now,max_attempts):
        prior=cls._source_prior(c,id,fingerprint,now)
        return not ((prior.get('status')=='planning' and prior.get('until',0)>now)
                    or prior.get('status')=='processed' or prior.get('attempts',0)>=max_attempts
                    or prior.get('next_retry',0)>now)

    @classmethod
    def _claim_source(cls,c,id,fingerprint,owner,now,lease_seconds,max_attempts):
        if not cls._source_eligible(c,id,fingerprint,now,max_attempts):return False
        prior=cls._source_prior(c,id,fingerprint,now)
        outcome={'status':'planning','owner':owner,'until':now+lease_seconds,'attempts':prior.get('attempts',0),'accounting':'completed_plans'}
        c.execute('INSERT INTO sources VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint,outcome=excluded.outcome,updated=excluded.updated',(id,fingerprint,canonical(outcome),now))
        return True

    def claim_source(self,id,fingerprint,owner,now,lease_seconds,max_attempts):
        with self._connection(True) as c:return self._claim_source(c,id,fingerprint,owner,now,lease_seconds,max_attempts)

    def renew_source(self,id,fingerprint,owner,now,lease_seconds):
        with self._connection(True) as c:
            row=c.execute('SELECT outcome FROM sources WHERE id=? AND fingerprint=?',(id,fingerprint)).fetchone()
            old=json.loads(row[0]) if row else {}
            if old.get('owner')!=owner or old.get('until',0)<=now:return False
            old['until']=now+lease_seconds
            c.execute('UPDATE sources SET outcome=?,updated=? WHERE id=?',(canonical(old),now,id))
            return True

    def complete_source(self,id,fingerprint,owner,success,now,*,deferred_reason=None):
        with self._connection(True) as c:
            row=c.execute('SELECT * FROM sources WHERE id=? AND fingerprint=?',(id,fingerprint)).fetchone()
            if not row:return False
            old=json.loads(row['outcome'])
            if old.get('owner')!=owner or old.get('until',0)<=now:return False
            outcome={'status':'deferred' if deferred_reason else ('processed' if success else 'failed'),
                     'attempts':old['attempts']+int(not bool(deferred_reason)),'next_retry':now+60,'accounting':'completed_plans'}
            if deferred_reason:outcome['reason']=deferred_reason
            c.execute('UPDATE sources SET outcome=?,updated=? WHERE id=?',(canonical(outcome),now,id))
            return True

    def get_goal(self,id):
        with self._connection() as c:return self._goal(c,c.execute('SELECT * FROM goals WHERE id=?',(id,)).fetchone())

    def goals(self,limit=20):
        with self._connection() as c:return [self._goal(c,r) for r in c.execute('SELECT * FROM goals ORDER BY created DESC,id LIMIT ?',(limit,)).fetchall()]

    def submission(self,id):
        with self._connection() as c:return self._submission(c.execute('SELECT * FROM submissions WHERE id=?',(id,)).fetchone())

    def source_state(self,id):
        with self._connection() as c:
            row=c.execute('SELECT * FROM sources WHERE id=?',(id,)).fetchone()
            if not row:return None
            result=dict(row);result['outcome']=json.loads(result['outcome']);return result

    def mark_source(self,id,fingerprint,outcome,now):
        with self._connection(True) as c:c.execute('INSERT INTO sources VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint,outcome=excluded.outcome,updated=excluded.updated',(id,fingerprint,canonical(outcome),now))

    def set_pause(self,value):
        import time
        with self._connection(True) as c:
            c.execute("INSERT INTO settings VALUES('paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(canonical(bool(value)),))
            _protocol(c,'pause',None,time.time(),paused=bool(value))
            _refine(c,'pause',None,time.time(),paused=bool(value))

    def paused(self):
        with self._connection() as c:
            row=c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            return bool(row and json.loads(row[0]))

    def model_records(self):
        try:
            from .metacognition import predictions
        except ImportError:
            from metacognition import predictions
        with self._connection() as c:
            return {'goals':[self._goal(c,r) for r in c.execute('SELECT * FROM goals').fetchall()],
                    'submissions':[self._submission(r) for r in c.execute('SELECT * FROM submissions').fetchall()],
                    'evidence':[{**dict(r),'data':json.loads(r['data'])} for r in c.execute('SELECT * FROM evidence').fetchall()],
                    'predictions':predictions(c)}

    def save_model(self,snapshot):
        with self._connection(True) as c:
            cursor=c.execute('INSERT INTO model_versions(snapshot) VALUES(?)',(canonical(snapshot),))
            result={**snapshot,'version':cursor.lastrowid}
            c.execute('UPDATE model_versions SET snapshot=? WHERE version=?',(canonical(result),cursor.lastrowid))
            return result

    def model_versions(self,limit=20):
        with self._connection() as c:return [json.loads(r[0]) for r in c.execute('SELECT snapshot FROM model_versions ORDER BY version DESC LIMIT ?',(limit,))]
