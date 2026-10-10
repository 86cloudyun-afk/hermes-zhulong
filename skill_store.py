"""Immutable executable versions, independently checked publication, scoped rollback."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

try:
    from .autonomy_store import canonical, digest
    from .skill_evaluator import CODE_LIMIT
except ImportError:
    from autonomy_store import canonical, digest
    from skill_evaluator import CODE_LIMIT

LEASE_SECONDS = 120


def scope_for(task, identity):
    return {'schema': 1, 'source_id': task['source_id'], 'domain': task['domain'],
            'contract_hash': task['contract_hash'], 'execution_identity': identity,
            'task_id': task['id'], 'task_digest': task['task_digest']}


def binding_for(row):
    return {'id': row['id'], 'code': row['code'], 'code_hash': row['code_hash'],
            'scope': json.loads(row['scope']), 'interface': 'json-stdin-stdout-v1'}


def _matches(row, goal, identity):
    scope = json.loads(row['scope'])
    return all(scope[key] == value for key, value in
               {'source_id': goal['source_id'], 'domain': goal['domain'], 'contract_hash': goal['contract_hash'],
                'execution_identity': identity}.items())


def valid_bindings(connection, goal, identity, request):
    try: intent = json.loads(request['input'])
    except (KeyError, TypeError, ValueError): return True
    if not isinstance(intent, dict) or 'skills' not in intent: return True
    bindings = intent['skills']
    if not isinstance(bindings, list) or len(bindings) > 1: return False
    if not bindings: return True
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='skill_versions'").fetchone(): return False
    current = connection.execute("SELECT value FROM settings WHERE key='skill_manifests'").fetchone()
    if current is None: return False
    configured = json.loads(current[0])
    for binding in bindings:
        if not isinstance(binding, dict) or not isinstance(binding.get('id'), str): return False
        row = connection.execute('SELECT * FROM skill_versions WHERE id=?', (binding['id'],)).fetchone()
        if row is None or row['state'] != 'active' or binding != binding_for(row) or not _matches(row, goal, identity): return False
        scope = json.loads(row['scope'])
        if configured.get(scope['task_id']) != scope['task_digest']: return False
    return True


class SkillStore:
    def __init__(self, ledger, tasks, identity):
        self.ledger, self.tasks, self.identity = ledger, tasks, identity
        self.manifests = {task['id']: task['task_digest'] for task in tasks}
        self.config_digest = digest([self.manifests, identity])
        with ledger._connection(True) as c:
            for statement in (
                '''CREATE TABLE IF NOT EXISTS skill_jobs(
                    id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id),
                    task_digest TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, owner TEXT, generation INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL, next_retry REAL NOT NULL DEFAULT 0, candidate_id TEXT,
                    UNIQUE(submission_id,task_digest))''',
                '''CREATE TABLE IF NOT EXISTS skill_versions(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL REFERENCES skill_jobs(id), attempt INTEGER NOT NULL,
                    scope TEXT NOT NULL, code TEXT NOT NULL, code_hash TEXT NOT NULL,
                    token TEXT NOT NULL, created REAL NOT NULL, report TEXT,
                    state TEXT NOT NULL DEFAULT 'candidate', reason TEXT NOT NULL DEFAULT 'awaiting_evaluation',
                    UNIQUE(job_id,attempt))''',
                '''CREATE UNIQUE INDEX IF NOT EXISTS skill_single_head ON skill_versions(scope) WHERE state='active' ''',
                '''CREATE TABLE IF NOT EXISTS skill_scans(submission_id TEXT NOT NULL, config_digest TEXT NOT NULL,
                    PRIMARY KEY(submission_id,config_digest))''',
                '''CREATE TABLE IF NOT EXISTS skill_uses(version_id TEXT NOT NULL REFERENCES skill_versions(id),
                    submission_id TEXT NOT NULL REFERENCES submissions(id), verdict INTEGER NOT NULL,
                    evidence_hash TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(version_id,submission_id))''',
                '''CREATE TABLE IF NOT EXISTS skill_evaluation_budget(day TEXT PRIMARY KEY,evaluations INTEGER NOT NULL)''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_skill_content BEFORE UPDATE OF
                    id,job_id,attempt,scope,code,code_hash,token,created ON skill_versions
                    BEGIN SELECT RAISE(ABORT,'frozen_skill_content'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_skill_report BEFORE UPDATE OF report ON skill_versions
                    WHEN OLD.report IS NOT NULL BEGIN SELECT RAISE(ABORT,'frozen_skill_report'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_skill_job BEFORE UPDATE OF payload,submission_id,task_digest ON skill_jobs
                    BEGIN SELECT RAISE(ABORT,'frozen_skill_job'); END''',
            ): c.execute(statement)
            c.execute("INSERT INTO settings(key,value) VALUES('skill_manifests',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (canonical(self.manifests),))

    def _task(self, job):
        return next((task for task in self.tasks if task['task_digest'] == job['task_digest']), None)

    def sync(self, now):
        with self.ledger._connection(True) as c:
            rows = c.execute('''SELECT s.* FROM submissions s WHERE s.settled=1 AND s.evidence IS NOT NULL
                AND s.host_status IN ('completed','failed','cancelled') AND NOT EXISTS(
                    SELECT 1 FROM skill_scans x WHERE x.submission_id=s.id AND x.config_digest=?)
                ORDER BY s.created,s.id LIMIT 50''', (self.config_digest,)).fetchall()
            for row in rows:
                sub = self.ledger._submission(row)
                goal = self.ledger._goal(c, c.execute('SELECT * FROM goals WHERE id=?', (sub['goal_id'],)).fetchone())
                checked = sub['evidence']
                trustworthy = (type(checked.get('verdict')) is bool and checked.get('contract_hash') == goal['contract_hash']
                               and not goal.get('cancel_requested') and goal['state'] != 'cancelled')
                if trustworthy:
                    try: bindings = json.loads(sub['request']['input']).get('skills', [])
                    except (ValueError, AttributeError, KeyError): bindings = []
                    if not isinstance(bindings, list): bindings = []
                    for binding in bindings[:1]:
                        if not isinstance(binding, dict): continue
                        version = c.execute('SELECT * FROM skill_versions WHERE id=?', (binding.get('id'),)).fetchone()
                        if version is None or binding != binding_for(version) or not _matches(version, goal, sub['execution_identity']): continue
                        fresh = c.execute('INSERT OR IGNORE INTO skill_uses VALUES(?,?,?,?,?)',
                            (version['id'], sub['id'], int(checked['verdict']), digest(checked), now)).rowcount
                        if fresh and not checked['verdict'] and version['state'] in {'active', 'standby'}:
                            c.execute("UPDATE skill_versions SET state='retired',reason='verified_bound_goal_failure' WHERE id=?", (version['id'],))
                            if version['state'] == 'active':
                                fallback = c.execute("SELECT id FROM skill_versions WHERE scope=? AND state='standby' ORDER BY sequence DESC LIMIT 1", (version['scope'],)).fetchone()
                                if fallback: c.execute("UPDATE skill_versions SET state='active',reason='rollback_after_bound_failure' WHERE id=?", (fallback['id'],))
                    if not checked['verdict'] and sub['execution_identity'] == self.identity:
                        for task in self.tasks:
                            if task['source_id'] != goal['source_id'] or task['domain'] != goal['domain'] or task['contract_hash'] != goal['contract_hash']: continue
                            payload = {'objective': goal['objective'], 'scope': scope_for(task, self.identity),
                                       'receipt': digest([sub['id'], checked]), 'reason': str(checked.get('reason', ''))[:240]}
                            c.execute('INSERT OR IGNORE INTO skill_jobs(id,submission_id,task_digest,payload,state) VALUES(?,?,?,?,?)',
                                      (uuid.uuid4().hex, sub['id'], task['task_digest'], canonical(payload), 'pending'))
                c.execute('INSERT OR IGNORE INTO skill_scans VALUES(?,?)', (sub['id'], self.config_digest))

    def claim(self, now):
        with self.ledger._connection(True) as c:
            c.execute("UPDATE skill_jobs SET state='invalid',owner=NULL,lease_until=NULL WHERE attempts>=2 AND candidate_id IS NULL AND state IN ('claimed','generating') AND lease_until<=?", (now,))
            rows = c.execute('''SELECT * FROM skill_jobs WHERE next_retry<=? AND
                (state='pending' OR (state='evaluating' AND (lease_until IS NULL OR lease_until<=?))
                 OR (state IN ('claimed','generating') AND lease_until<=?)) ORDER BY next_retry,id''', (now, now, now)).fetchall()
            for row in rows:
                job = dict(row); task = self._task(job)
                if task is None or json.loads(job['payload'])['scope'] != scope_for(task, self.identity):
                    c.execute("UPDATE skill_jobs SET state='invalid',owner=NULL,lease_until=NULL WHERE id=?", (job['id'],)); continue
                owner = uuid.uuid4().hex; state = 'evaluating' if job['candidate_id'] else 'claimed'
                c.execute('UPDATE skill_jobs SET state=?,owner=?,generation=generation+1,lease_until=? WHERE id=?',
                          (state, owner, now+LEASE_SECONDS, job['id']))
                candidate = c.execute('SELECT * FROM skill_versions WHERE id=?', (job['candidate_id'],)).fetchone() if job['candidate_id'] else None
                return {**job, 'state': state, 'owner': owner, 'generation': job['generation']+1,
                        'payload': json.loads(job['payload']), 'task': task,
                        'code': candidate['code'] if candidate else None, 'token': candidate['token'] if candidate else None}
        return None

    @staticmethod
    def _owned(c, job, now):
        return c.execute('SELECT * FROM skill_jobs WHERE id=? AND owner=? AND generation=? AND lease_until>?',
                         (job['id'], job['owner'], job['generation'], now)).fetchone()

    def owned(self, job, now):
        with self.ledger._connection() as c: return self._owned(c, job, now) is not None

    def begin(self, job, now):
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None or row['state'] != 'claimed' or row['attempts'] >= 2: return False
            c.execute("UPDATE skill_jobs SET state='generating',attempts=attempts+1 WHERE id=?", (job['id'],)); return True

    def freeze(self, job, code, now):
        if not isinstance(code, str) or not code.strip() or '\x00' in code or len(code.encode()) > CODE_LIMIT: return False
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None or row['state'] != 'generating': return False
            vid, token = uuid.uuid4().hex, uuid.uuid4().hex
            c.execute('INSERT INTO skill_versions(id,job_id,attempt,scope,code,code_hash,token,created) VALUES(?,?,?,?,?,?,?,?)',
                      (vid, job['id'], row['attempts'], canonical(job['payload']['scope']), code, hashlib.sha256(code.encode()).hexdigest(), token, now))
            c.execute("UPDATE skill_jobs SET state='evaluating',candidate_id=? WHERE id=?", (vid, job['id']))
            job.update(code=code, token=token); return True

    def defer(self, job, now, reason):
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None: return False
            state = 'evaluating' if row['candidate_id'] else ('invalid' if row['attempts'] >= 2 else 'pending')
            c.execute('UPDATE skill_jobs SET state=?,owner=NULL,lease_until=NULL,next_retry=? WHERE id=?', (state, now+60, job['id'])); return True

    def finish(self, job, report, now):
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None or row['state'] != 'evaluating': return False
            version = c.execute('SELECT * FROM skill_versions WHERE id=?', (row['candidate_id'],)).fetchone()
            task = self._task(dict(row))
            if task is None or json.loads(version['scope']) != scope_for(task, self.identity): return False
            if (type(report.get('verdict')) is not bool or report.get('cleanup_confirmed') is not True
                or report.get('code_hash') != version['code_hash'] or report.get('task_digest') != task['task_digest']
                or report.get('image') != task['image']): return False
            if report['verdict']:
                cases = task['examples']+task['holdout']; receipts = report.get('cases')
                if (report.get('passed') != len(cases) or not isinstance(receipts, list) or len(receipts) != len(cases)
                    or any(r.get('passed') is not True or r.get('input_hash') != digest(case['input']) for r, case in zip(receipts, cases))): return False
                head = c.execute("SELECT * FROM skill_versions WHERE scope=? AND state='active'", (version['scope'],)).fetchone()
                state = 'standby' if head and head['sequence'] > version['sequence'] else 'active'
                if state == 'active': c.execute("UPDATE skill_versions SET state='standby',reason='superseded' WHERE scope=? AND state='active'", (version['scope'],))
                c.execute('UPDATE skill_versions SET report=?,state=?,reason=? WHERE id=?',
                          (canonical(report), state, 'trusted_cases_passed', version['id']))
                c.execute("UPDATE skill_jobs SET state='published',owner=NULL,lease_until=NULL WHERE id=?", (job['id'],))
            else:
                c.execute("UPDATE skill_versions SET report=?,state='rejected',reason='trusted_case_failure' WHERE id=?", (canonical(report), version['id']))
                c.execute('UPDATE skill_jobs SET state=?,owner=NULL,lease_until=NULL,next_retry=?,candidate_id=NULL WHERE id=?',
                          ('pending' if row['attempts'] < 2 else 'invalid', now+60, job['id']))
            return True

    def retrieve(self, goal, identity):
        if identity != self.identity: return []
        scopes = [canonical(scope_for(task, identity)) for task in self.tasks if task['source_id'] == goal['source_id']
                  and task['domain'] == goal['domain'] and task['contract_hash'] == goal['contract_hash']]
        if not scopes: return []
        with self.ledger._connection() as c:
            row = c.execute("SELECT * FROM skill_versions WHERE state='active' AND scope IN ("+','.join('?' for _ in scopes)+') ORDER BY sequence DESC LIMIT 1', scopes).fetchone()
            return [binding_for(row)] if row else []

    def needs_cleanup(self):
        with self.ledger._connection() as c:
            return c.execute("SELECT 1 FROM skill_versions WHERE state='candidate' LIMIT 1").fetchone() is not None

    def evaluation_available(self, now, cap):
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        with self.ledger._connection() as c:
            row = c.execute('SELECT evaluations FROM skill_evaluation_budget WHERE day=?', (day,)).fetchone()
            return cap > 0 and (row is None or row[0] < cap)

    def reserve_evaluation(self, now, cap):
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        with self.ledger._connection(True) as c:
            row = c.execute('SELECT evaluations FROM skill_evaluation_budget WHERE day=?', (day,)).fetchone()
            if cap <= 0 or row and row[0] >= cap: return False
            c.execute('INSERT INTO skill_evaluation_budget VALUES(?,1) ON CONFLICT(day) DO UPDATE SET evaluations=evaluations+1', (day,)); return True

    def summary(self):
        with self.ledger._connection() as c:
            states = {row['state']: row['n'] for row in c.execute('SELECT state,COUNT(*) n FROM skill_versions GROUP BY state')}
            jobs = {row['state']: row['n'] for row in c.execute('SELECT state,COUNT(*) n FROM skill_jobs GROUP BY state')}
            versions = [{'id': row['id'], 'code_hash': row['code_hash'], 'scope': json.loads(row['scope']),
                         'state': row['state'], 'reason': row['reason']} for row in c.execute('SELECT * FROM skill_versions ORDER BY sequence DESC LIMIT 20')]
            return {'states': states, 'jobs': jobs, 'versions': versions,
                    'claim': 'Trusted JSON case certification and bound-goal associations; no causal or general correctness claim'}
