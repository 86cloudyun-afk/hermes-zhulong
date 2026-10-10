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
            try:
                from .task_inputs import initialize
            except ImportError:
                from task_inputs import initialize
            initialize(c)

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
        return result

    def create_goal(self,candidate,source_revision,contract,baseline,now,deadline_seconds,*,source_owner=None,task_input=None):
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
            if inserted.rowcount:bind_goal(c,goal['id'],candidate['source_id'],source_revision,task_input)
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
            return GoalLease(row['id'],owner,generation,now+lease_seconds)

    def renew(self,lease,now,lease_seconds):
        with self._connection(True) as c:
            if not self._owned(c,lease,now):return False
            c.execute('UPDATE goals SET lease_until=? WHERE id=?',(now+lease_seconds,lease.goal_id))
            return True

    def release(self,lease,now):
        with self._connection(True) as c:
            if not self._owned(c,lease,now):return False
            c.execute('UPDATE goals SET owner=NULL,lease_until=NULL WHERE id=?',(lease.goal_id,))
            return True

    def prepare_submission(self,lease,request,session_key,execution_identity,now,daily_cap,max_active,max_attempts,retention_seconds,*,expected_submission_id=None):
        body,identity=canonical(request),canonical(execution_identity)
        with self._connection(True) as c:
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
                from .task_inputs import valid_binding
            except ImportError:
                from task_inputs import valid_binding
            if not valid_binding(c,self._goal(c,goal),request):
                return {'admitted':False,'reason':'input_snapshot_no_longer_applicable'}
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
            sid=uuid.uuid4().hex
            c.execute('INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds,forecast) VALUES(?,?,?,?,?,?,?,?,?)',
                (sid,goal['id'],goal['attempts']+1,body,session_key,identity,now,retention_seconds,json.loads(goal['candidate']).get('confidence')))
            c.execute('INSERT INTO run_budget(day,runs) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET runs=runs+1',(day,))
            c.execute("UPDATE goals SET attempts=attempts+1,submission_id=?,state='submitting' WHERE id=?",(sid,goal['id']))
            return {'admitted':True,'reason':'prepared','submission':self._submission(c.execute('SELECT * FROM submissions WHERE id=?',(sid,)).fetchone())}

    def record_admission(self,lease,submission_id,run_id,host_status,now):
        with self._connection(True) as c:
            if not self._current(c,lease,now,submission_id):return False
            row=c.execute('SELECT * FROM submissions WHERE id=? AND goal_id=?',(submission_id,lease.goal_id)).fetchone()
            if not row or (row['run_id'] is not None and row['run_id']!=run_id):return False
            c.execute('UPDATE submissions SET run_id=?,host_status=? WHERE id=?',(run_id,str(host_status)[:64],submission_id))
            c.execute("UPDATE goals SET state='running' WHERE id=?",(lease.goal_id,))
            return True

    def transition(self,lease,state,reason,now,execution_settled=None,*,expected_submission_id=None):
        if state not in STATES:raise ValueError('invalid_state')
        with self._connection(True) as c:
            if not self._current(c,lease,now,expected_submission_id):return False
            c.execute('UPDATE goals SET state=?,reason=? WHERE id=?',(state,str(reason)[:240],lease.goal_id))
            if execution_settled is not None:
                c.execute('UPDATE submissions SET settled=MAX(settled,?) WHERE id=(SELECT submission_id FROM goals WHERE id=?)',(int(execution_settled),lease.goal_id))
            return True

    def record_attempt_result(self,lease,submission_id,evidence,now):
        with self._connection(True) as c:
            if not self._current(c,lease,now,submission_id):return False
            goal=c.execute('SELECT contract_hash FROM goals WHERE id=?',(lease.goal_id,)).fetchone()
            if evidence.get('contract_hash')!=goal[0]:raise ValueError('changed_contract')
            c.execute('UPDATE submissions SET evidence=? WHERE id=? AND goal_id=? AND evidence IS NULL',(canonical(evidence),submission_id,lease.goal_id))
            return True

    def finish(self,lease,evidence,outcome,execution_settled,now,*,expected_submission_id=None):
        if outcome not in {'succeeded','failed','already_satisfied','blocked','unknown_result','cancelled'}:raise ValueError('invalid_outcome')
        with self._connection(True) as c:
            if not self._current(c,lease,now,expected_submission_id):return False
            goal=c.execute('SELECT * FROM goals WHERE id=?',(lease.goal_id,)).fetchone()
            if evidence.get('contract_hash')!=goal['contract_hash']:raise ValueError('changed_contract')
            if outcome=='succeeded' and (evidence.get('verdict') is not True or not goal['attempts']):raise ValueError('unverified_success')
            if outcome=='failed' and evidence.get('verdict') is not False:raise ValueError('unverified_failure')
            receipt=digest([lease.goal_id,outcome,evidence])
            c.execute('INSERT OR IGNORE INTO evidence(goal_id,receipt,outcome,data,created) VALUES(?,?,?,?,?)',(lease.goal_id,receipt,outcome,canonical(evidence),now))
            truth=c.execute("SELECT outcome FROM evidence WHERE goal_id=? AND outcome IN ('succeeded','failed')",(lease.goal_id,)).fetchone()
            if truth is not None:outcome=truth['outcome']
            c.execute('UPDATE goals SET state=?,reason=?,owner=NULL,lease_until=NULL WHERE id=?',(outcome,str(evidence.get('reason',''))[:240],lease.goal_id))
            c.execute('UPDATE submissions SET settled=MAX(settled,?) WHERE id=?',(int(execution_settled),goal['submission_id']))
            return True

    def request_cancel(self,goal_id):
        with self._connection(True) as c:
            return bool(c.execute('UPDATE goals SET cancel_requested=1 WHERE id=?',(goal_id,)).rowcount)

    def work_goals(self):
        with self._connection() as c:
            rows=c.execute("SELECT g.* FROM goals g LEFT JOIN submissions s ON s.id=g.submission_id WHERE g.state IN ('ready','blocked','submitting','running','verifying','unknown_result') OR s.settled=0 ORDER BY g.deadline,g.id").fetchall()
            return [self._goal(c,r) for r in rows]

    def record_runtime(self,lease,submission_id,result,now):
        with self._connection(True) as c:
            if not self._current(c,lease,now,submission_id):return False
            c.execute('UPDATE submissions SET usage=?,runtime=? WHERE id=? AND goal_id=?',
                (canonical(result.get('usage')),canonical(result.get('runtime',{})),submission_id,lease.goal_id))
            return True

    def claim_source(self,id,fingerprint,owner,now,lease_seconds,max_attempts):
        with self._connection(True) as c:
            row=c.execute('SELECT * FROM sources WHERE id=?',(id,)).fetchone()
            prior=json.loads(row['outcome']) if row and row['fingerprint']==fingerprint else {}
            if not isinstance(prior,dict):prior={}
            if prior.get('status')=='planning' and prior.get('until',0)>now:return False
            attempts=prior.get('attempts',0)
            # v0.4 counted claims. Only the expired in-flight legacy claim is
            # refundable; completed failures remain counted through migration.
            if prior.get('status')=='planning' and prior.get('accounting')!='completed_plans':attempts=max(0,attempts-1)
            if prior.get('status')=='processed' or attempts>=max_attempts:return False
            if prior.get('next_retry',0)>now:return False
            outcome={'status':'planning','owner':owner,'until':now+lease_seconds,'attempts':attempts,'accounting':'completed_plans'}
            c.execute('INSERT INTO sources VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint,outcome=excluded.outcome,updated=excluded.updated',(id,fingerprint,canonical(outcome),now))
            return True

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
        with self._connection(True) as c:c.execute("INSERT INTO settings VALUES('paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(canonical(bool(value)),))

    def paused(self):
        with self._connection() as c:
            row=c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            return bool(row and json.loads(row[0]))

    def model_records(self):
        with self._connection() as c:
            return {'goals':[self._goal(c,r) for r in c.execute('SELECT * FROM goals').fetchall()],
                    'submissions':[self._submission(r) for r in c.execute('SELECT * FROM submissions').fetchall()],
                    'evidence':[{**dict(r),'data':json.loads(r['data'])} for r in c.execute('SELECT * FROM evidence').fetchall()]}

    def save_model(self,snapshot):
        with self._connection(True) as c:
            cursor=c.execute('INSERT INTO model_versions(snapshot) VALUES(?)',(canonical(snapshot),))
            result={**snapshot,'version':cursor.lastrowid}
            c.execute('UPDATE model_versions SET snapshot=? WHERE version=?',(canonical(result),cursor.lastrowid))
            return result

    def model_versions(self,limit=20):
        with self._connection() as c:return [json.loads(r[0]) for r in c.execute('SELECT snapshot FROM model_versions ORDER BY version DESC LIMIT ?',(limit,))]
