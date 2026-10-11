"""Bounded trusted interventions on frozen failed skill evaluations.

Configured programs are data passed only to DockerEvaluator. These receipts
support an intervention in the stated finite test scope, never an arbitrary
root cause or an input-minimization claim.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone

try:
    from .autonomy_store import canonical, digest
    from .skill_evaluator import CODE_LIMIT, DockerError, strict_json
    from .skill_replay import evaluation_task
    from .task_inputs import valid_binding
except ImportError:
    from autonomy_store import canonical, digest
    from skill_evaluator import CODE_LIMIT, DockerError, strict_json
    from skill_replay import evaluation_task
    from task_inputs import valid_binding


def _subsets(factors):
    return [list(s) for n in range(len(factors)+1) for s in itertools.combinations(factors,n)]


def _code_hash(code): return hashlib.sha256(code.encode()).hexdigest()


def validate_diagnostics(raw, policy):
    """Normalize a trusted, complete factorial catalogue (baseline is frozen code)."""
    if not isinstance(raw,list) or len(raw)>4: raise ValueError('invalid_diagnostics')
    tasks=policy.get('executable_skills',[]); result=[]; ids=set()
    for entry in raw:
        if not isinstance(entry,dict) or set(entry)!={'id','skill_id','factors','variants','negative_controls'}:
            raise ValueError('invalid_diagnostic_manifest')
        ident=entry['id']; factors=entry['factors']
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in ids:
            raise ValueError('invalid_diagnostic_id')
        ids.add(ident)
        task=next((t for t in tasks if t['id']==entry['skill_id']),None)
        if task is None: raise ValueError('invalid_diagnostic_skill')
        if (not isinstance(factors,list) or not 1<=len(factors)<=3
            or any(not isinstance(f,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',f) for f in factors)
            or len(set(factors))!=len(factors)): raise ValueError('invalid_diagnostic_factors')
        factors=sorted(factors); variants=entry['variants']; expected={tuple(s) for s in _subsets(factors)[1:]}
        if not isinstance(variants,list) or len(variants)!=len(expected): raise ValueError('incomplete_diagnostic_factorial')
        seen=set()
        for variant in variants:
            if not isinstance(variant,dict) or set(variant)!={'enabled','code'}: raise ValueError('invalid_diagnostic_variant')
            enabled=variant['enabled']; code=variant['code']
            if (not isinstance(enabled,list) or any(not isinstance(f,str) for f in enabled)
                or len(set(enabled))!=len(enabled)): raise ValueError('invalid_diagnostic_variant')
            key=tuple(sorted(enabled))
            if key not in expected or key in seen: raise ValueError('incomplete_diagnostic_factorial')
            seen.add(key)
            if not isinstance(code,str) or not code.strip() or '\x00' in code or len(code.encode())>CODE_LIMIT:
                raise ValueError('invalid_diagnostic_code')
        controls=entry['negative_controls']
        if not isinstance(controls,list) or not 1<=len(controls)<=4: raise ValueError('invalid_diagnostic_controls')
        inputs=set()
        for case in controls:
            if not isinstance(case,dict) or set(case)!={'input','output'}: raise ValueError('invalid_diagnostic_control')
            for value in case.values():
                strict_json(canonical(value))
                if len(canonical(value).encode())>4096: raise ValueError('diagnostic_control_too_large')
            if digest(case['input']) in inputs: raise ValueError('duplicate_diagnostic_control')
            inputs.add(digest(case['input']))
        # Wrapper depth differs from each business value's independently checked depth.
        normalized=json.loads(canonical(entry)); normalized['factors']=factors
        normalized['variants']=[{'enabled':sorted(v['enabled']),'code':v['code']} for v in variants]
        normalized['skill_task']=json.loads(canonical(task))
        normalized['plan_digest']=digest([normalized,1])
        result.append(normalized)
    return result


def _report_valid(report, code, task):
    """Require exact independent evaluator binding and a full successful/prefix failed trace."""
    if not isinstance(report,dict): return False
    if (type(report.get('verdict')) is not bool or report.get('cleanup_confirmed') is not True
        or report.get('code_hash')!=_code_hash(code) or report.get('task_digest')!=task['task_digest']
        or report.get('image')!=task['image']): return False
    if task.get('replay_origin'):
        replay=report.get('origin_replay')
        if (not isinstance(replay,dict) or type(replay.get('passed')) is not bool
            or report.get('evaluation_digest')!=task['evaluation_digest']
            or canonical({k:v for k,v in replay.items() if k!='passed'})!=canonical(task['origin_replay'])): return False
    cases=task.get('_evaluation_cases',task['examples']+task['holdout']); receipts=report.get('cases')
    if not isinstance(receipts,list) or not 1<=len(receipts)<=len(cases): return False
    for receipt,case in zip(receipts,cases):
        if (not isinstance(receipt,dict) or type(receipt.get('passed')) is not bool
            or receipt.get('input_hash')!=digest(case['input'])
            or not isinstance(receipt.get('output_hash'),str)
            or not re.fullmatch('[0-9a-f]{64}',receipt['output_hash'])): return False
    passed=sum(r['passed'] for r in receipts)
    if type(report.get('passed')) is not int or report['passed']!=passed: return False
    if report['verdict']:
        valid=len(receipts)==len(cases) and passed==len(cases)
    else:
        valid=passed==len(receipts)-1 and receipts[-1]['passed'] is False and all(r['passed'] for r in receipts[:-1])
    if not valid: return False
    if task.get('replay_origin'):
        index=task['origin_replay']['case_index']
        actual=receipts[index]['passed'] if index<len(receipts) else False
        if report['origin_replay']['passed'] is not actual: return False
    return True


class DiagnosticStore:
    def __init__(self, ledger, catalogue):
        self.ledger=ledger; self.catalogue=json.loads(canonical(catalogue))
        self.manifests={p['id']:p['plan_digest'] for p in self.catalogue}
        with ledger._connection(True) as c:
            for statement in (
                '''CREATE TABLE IF NOT EXISTS diagnostic_plans(
                    id TEXT PRIMARY KEY,version_id TEXT NOT NULL,catalogue_id TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,
                    state TEXT NOT NULL,reason TEXT NOT NULL,
                    UNIQUE(version_id,plan_digest))''',
                '''CREATE TABLE IF NOT EXISTS diagnostic_cells(
                    id TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES diagnostic_plans(id),
                    ordinal INTEGER NOT NULL,enabled TEXT NOT NULL,code TEXT NOT NULL,code_hash TEXT NOT NULL,
                    task TEXT NOT NULL,token TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
                    report TEXT,last_unknown TEXT,quiescent INTEGER NOT NULL DEFAULT 1,UNIQUE(plan_id,ordinal))''',
                '''CREATE TABLE IF NOT EXISTS diagnostic_budget(day TEXT PRIMARY KEY,evaluations INTEGER NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS diagnostic_reservations(
                    id TEXT PRIMARY KEY,cell_id TEXT NOT NULL REFERENCES diagnostic_cells(id),
                    created REAL NOT NULL,day TEXT NOT NULL,code_hash TEXT NOT NULL,
                    task_hash TEXT NOT NULL,token TEXT NOT NULL,report TEXT,execution_seconds REAL)''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_diagnostic_plan BEFORE UPDATE OF
                    id,version_id,catalogue_id,plan_digest,payload,created ON diagnostic_plans
                    BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_plan'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_diagnostic_cell BEFORE UPDATE OF
                    id,plan_id,ordinal,enabled,code,code_hash,task,token ON diagnostic_cells
                    BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_cell'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_diagnostic_report BEFORE UPDATE OF report ON diagnostic_cells
                    WHEN OLD.report IS NOT NULL BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_report'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_diagnostic_reservation BEFORE UPDATE OF
                    id,cell_id,created,day,code_hash,task_hash,token ON diagnostic_reservations
                    BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_reservation'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_diagnostic_reservation_delete BEFORE DELETE ON diagnostic_reservations
                    BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_reservation'); END''',
            ): c.execute(statement)
            for column,definition in (('report','TEXT'),('execution_seconds','REAL')):
                if column not in {r['name'] for r in c.execute('PRAGMA table_info(diagnostic_reservations)')}:
                    c.execute(f'ALTER TABLE diagnostic_reservations ADD COLUMN {column} {definition}')
            c.execute('''CREATE TRIGGER IF NOT EXISTS frozen_diagnostic_attempt_report BEFORE UPDATE OF
                report,execution_seconds ON diagnostic_reservations WHEN OLD.report IS NOT NULL
                BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_attempt_report'); END''')
            if 'quiescent' not in {r['name'] for r in c.execute('PRAGMA table_info(diagnostic_cells)')}:
                c.execute('ALTER TABLE diagnostic_cells ADD COLUMN quiescent INTEGER NOT NULL DEFAULT 0')
            for table in ('diagnostic_plans','diagnostic_cells'):
                c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_{table}_delete BEFORE DELETE ON {table}
                    BEGIN SELECT RAISE(ABORT,'frozen_diagnostic_content'); END''')
            c.execute("INSERT INTO settings VALUES('diagnostic_manifests',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (canonical(self.manifests),))

    @staticmethod
    def _setting(c,key):
        row=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _configured(self,c,plan):
        payload=json.loads(plan['payload']); task=payload.get('skill_task')
        return (self._setting(c,'diagnostic_manifests').get(plan['catalogue_id'])==plan['plan_digest']
            and task is not None and self._setting(c,'skill_manifests').get(task['id'])==task['task_digest'])

    def _origin(self,c,version,manifest):
        task=manifest['skill_task']; scope=json.loads(version['scope'])
        if (scope.get('task_id')!=task['id'] or scope.get('task_digest')!=task['task_digest']
            or scope.get('source_id')!=task['source_id'] or scope.get('contract_hash')!=task['contract_hash']
            or scope.get('domain')!=task['domain'] or version['code_hash']!=_code_hash(version['code'])
            or self._setting(c,'skill_manifests').get(task['id'])!=task['task_digest']):
            raise ValueError('origin_scope_unavailable')
        row=c.execute('SELECT * FROM submissions WHERE id=?',(version['submission_id'],)).fetchone()
        if row is None or not row['settled'] or row['host_status'] not in {'completed','failed','cancelled'}:
            raise ValueError('origin_unsettled')
        sub=self.ledger._submission(row)
        goal=self.ledger._goal(c,c.execute('SELECT * FROM goals WHERE id=?',(sub['goal_id'],)).fetchone())
        checked=sub.get('evidence')
        if (goal is None or not isinstance(checked,dict) or checked.get('verdict') is not False
            or checked.get('contract_hash')!=task['contract_hash'] or goal['contract_hash']!=task['contract_hash']
            or sub['execution_identity']!=scope.get('execution_identity')
            or goal.get('cancel_requested') or goal['state']=='cancelled'
            or not task.get('replay_origin') or not valid_binding(c,goal,sub['request'])):
            raise ValueError('origin_provenance_unavailable')
        evaluated=evaluation_task(task,goal,sub); report=json.loads(version['report'])
        if not _report_valid(report,version['code'],evaluated) or report['verdict'] is not False:
            raise ValueError('origin_report_unavailable')
        index=evaluated['origin_replay']['case_index']
        # A default false flag for an unexecuted origin case is not a failure receipt.
        if index>=len(report['cases']) or report['cases'][index]['passed'] is not False:
            raise ValueError('origin_failure_not_reproduced')
        origin={'schema':1,'version_id':version['id'],'submission_id':sub['id'],
                'goal_id':goal['id'],'code_hash':version['code_hash'],'report_hash':digest(report),
                'receipt_hash':digest(checked),'input_hash':goal['task_input']['input_hash'],
                'rule_hash':goal['task_input']['rule_hash'],'evaluation_digest':evaluated['evaluation_digest'],
                'image_hash':task['image'].split('@sha256:')[1]}
        return evaluated,origin,report

    def _invalidate_unconfigured(self,c):
        # Removal never substitutes for cleanup of an experiment that may still run.
        rows=c.execute("""SELECT p.* FROM diagnostic_plans p WHERE p.state!='unavailable'
            AND NOT EXISTS(SELECT 1 FROM diagnostic_cells x WHERE x.plan_id=p.id
            AND x.state IN ('running','exhausted') AND x.quiescent=0)""").fetchall()
        for row in rows:
            if not self._configured(c,row):
                c.execute("UPDATE diagnostic_plans SET state='unavailable',reason='trusted_configuration_changed' WHERE id=?",(row['id'],))

    def sync(self,now):
        with self.ledger._connection(True) as c:
            if not all(c.execute("SELECT 1 FROM sqlite_master WHERE name=?",(name,)).fetchone() for name in ('skill_versions','skill_jobs')): return
            self._invalidate_unconfigured(c)
            for manifest in self.catalogue:
                # Exclude already scanned versions so an old bounded page cannot starve new failures.
                rows=c.execute('''SELECT v.*,j.submission_id FROM skill_versions v JOIN skill_jobs j ON j.id=v.job_id
                    WHERE v.state='rejected' AND NOT EXISTS(SELECT 1 FROM diagnostic_plans p
                    WHERE p.version_id=v.id AND p.plan_digest=?) ORDER BY v.sequence''',(manifest['plan_digest'],))
                scanned=0
                for version in rows:
                    scope=json.loads(version['scope'])
                    if scope.get('task_id')!=manifest['skill_id']: continue
                    if c.execute('SELECT 1 FROM diagnostic_plans WHERE version_id=? AND plan_digest=?',
                                 (version['id'],manifest['plan_digest'])).fetchone(): continue
                    if scanned>=50: break
                    scanned+=1
                    ident=uuid.uuid4().hex; payload=json.loads(canonical(manifest)); state='pending'; reason='awaiting_interventions'
                    try:
                        evaluated,origin,report=self._origin(c,version,manifest)
                        payload.update(origin=origin,original_report=report,evaluation_task=evaluated)
                    except (ValueError,KeyError,TypeError):
                        state='unavailable';reason='missing_trusted_origin_provenance'
                    c.execute('INSERT INTO diagnostic_plans VALUES(?,?,?,?,?,?,?,?)',
                              (ident,version['id'],manifest['id'],manifest['plan_digest'],canonical(payload),now,state,reason))
                    if state=='unavailable': continue
                    controls=manifest['negative_controls']; cases=controls+evaluated['_evaluation_cases']
                    origin_replay=dict(evaluated['origin_replay'],case_index=evaluated['origin_replay']['case_index']+len(controls))
                    task=dict(evaluated,_evaluation_cases=cases,origin_replay=origin_replay)
                    task['evaluation_digest']=digest([manifest['plan_digest'],origin,cases,origin_replay])
                    codes={tuple(v['enabled']):v['code'] for v in manifest['variants']};codes[()]=version['code']
                    for index,enabled in enumerate(_subsets(manifest['factors'])):
                        code=codes[tuple(enabled)]
                        c.execute('INSERT INTO diagnostic_cells(id,plan_id,ordinal,enabled,code,code_hash,task,token) VALUES(?,?,?,?,?,?,?,?)',
                                  (uuid.uuid4().hex,ident,index,canonical(enabled),code,_code_hash(code),canonical(task),uuid.uuid4().hex))

    def reserve(self,now,cap):
        if type(cap) is not int or not 0<=cap<=16: raise ValueError('invalid_diagnostic_budget')
        day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
        with self.ledger._connection(True) as c:
            if self._setting(c,'paused'): return None
            # A frozen unknown cell is reconciled before any other admission.
            rows=c.execute('''SELECT x.*,p.catalogue_id,p.plan_digest,p.payload,p.state AS plan_state
                              FROM diagnostic_cells x JOIN diagnostic_plans p ON p.id=x.plan_id
                              WHERE x.state IN ('pending','running') AND p.state='pending'
                              ORDER BY CASE x.state WHEN 'running' THEN 0 ELSE 1 END,p.created,p.id,x.ordinal''').fetchall()
            for row in rows:
                if not self._configured(c,row):
                    c.execute("UPDATE diagnostic_plans SET state='unavailable',reason='trusted_configuration_changed' WHERE id=?",(row['plan_id'],));continue
                attempts=c.execute('SELECT COUNT(*) FROM diagnostic_reservations WHERE cell_id=?',(row['id'],)).fetchone()[0]
                if attempts>=3:
                    c.execute("UPDATE diagnostic_cells SET state='exhausted' WHERE id=?",(row['id'],))
                    c.execute("UPDATE diagnostic_plans SET state='inconclusive',reason='bounded_attempts_exhausted' WHERE id=?",(row['plan_id'],));continue
                # Do not advance within a plan until all earlier cells are final.
                if c.execute("SELECT 1 FROM diagnostic_cells WHERE plan_id=? AND ordinal<? AND state!='complete'",
                             (row['plan_id'],row['ordinal'])).fetchone(): continue
                used=c.execute('SELECT evaluations FROM diagnostic_budget WHERE day=?',(day,)).fetchone()
                if cap==0 or used and used[0]>=cap: return None
                c.execute('INSERT INTO diagnostic_budget VALUES(?,1) ON CONFLICT(day) DO UPDATE SET evaluations=evaluations+1',(day,))
                reservation=uuid.uuid4().hex
                c.execute('INSERT INTO diagnostic_reservations(id,cell_id,created,day,code_hash,task_hash,token) VALUES(?,?,?,?,?,?,?)',
                          (reservation,row['id'],now,day,row['code_hash'],digest(json.loads(row['task'])),row['token']))
                c.execute("UPDATE diagnostic_cells SET state='running',quiescent=0 WHERE id=?",(row['id'],))
                return {**dict(row),'task':json.loads(row['task']),'reservation_id':reservation}
        return None

    def finish(self,cell,report,now,execution_seconds=None):
        with self.ledger._connection(True) as c:
            row=c.execute('''SELECT x.*,p.catalogue_id,p.plan_digest,p.payload FROM diagnostic_cells x
                             JOIN diagnostic_plans p ON p.id=x.plan_id WHERE x.id=?''',(cell['id'],)).fetchone()
            if row is None or row['state']!='running': return False
            reservation=c.execute('SELECT * FROM diagnostic_reservations WHERE id=? AND cell_id=?',
                                  (cell['reservation_id'],cell['id'])).fetchone()
            latest=c.execute('SELECT id FROM diagnostic_reservations WHERE cell_id=? ORDER BY rowid DESC LIMIT 1',(cell['id'],)).fetchone()
            if reservation is None or reservation['report'] is not None or latest is None or latest[0]!=cell['reservation_id']: return False
            valid=_report_valid(report,row['code'],json.loads(row['task']))
            try: receipt=strict_json(canonical(report),max_depth=64)
            except (ValueError,TypeError): receipt={'verdict':'unknown','reason':'unbound_report'}
            attempt={'outcome':report['verdict'] if valid else 'unknown','receipt':receipt}
            duration=execution_seconds if type(execution_seconds) in (int,float) and math.isfinite(execution_seconds) and execution_seconds>=0 else None
            c.execute('UPDATE diagnostic_reservations SET report=?,execution_seconds=? WHERE id=?',
                      (canonical(attempt),duration,cell['reservation_id']))
            if not valid:
                c.execute("UPDATE diagnostic_cells SET last_unknown='receipt_or_cleanup_unknown' WHERE id=?",(row['id'],));return False
            # Configuration drift cannot convert an old experiment into current support.
            if not self._configured(c,row):
                c.execute("UPDATE diagnostic_plans SET state='unavailable',reason='trusted_configuration_changed' WHERE id=?",(row['plan_id'],))
            c.execute("UPDATE diagnostic_cells SET report=?,state='complete',last_unknown=NULL,quiescent=1 WHERE id=?",(canonical(report),row['id']))
            return True

    def reconcile_cleanup(self,confirmed):
        """Persist real Docker cleanup separately from the missing experiment result."""
        with self.ledger._connection(True) as c:
            c.execute("UPDATE diagnostic_cells SET quiescent=? WHERE state IN ('running','exhausted')",(int(confirmed is True),))
            if confirmed is True: self._invalidate_unconfigured(c)

    def needs_cleanup(self):
        with self.ledger._connection() as c:
            return c.execute("SELECT 1 FROM diagnostic_cells WHERE state IN ('running','exhausted') AND quiescent=0 LIMIT 1").fetchone() is not None

    def requires_quiescence(self):
        return self.needs_cleanup()

    def summary(self):
        with self.ledger._connection() as c:
            diagnoses=[]
            for plan in c.execute('SELECT * FROM diagnostic_plans ORDER BY created DESC,id LIMIT 20'):
                payload=json.loads(plan['payload']); cells=c.execute('SELECT * FROM diagnostic_cells WHERE plan_id=? ORDER BY ordinal',(plan['id'],)).fetchall()
                final=[x for x in cells if x['state']=='complete']; count=len(payload['negative_controls'])
                reports=[json.loads(x['report']) for x in final]; repairs=[];interactions=[]
                grade='hypothesis' if not final and not any(x['state']=='running' for x in cells) else 'inconclusive'
                if plan['state']=='inconclusive': grade='inconclusive'
                if plan['state']=='unavailable' or not self._configured(c,plan): grade='unavailable'
                elif cells and len(final)==len(cells):
                    controls_ok=all(len(r['cases'])>=count and all(x['passed'] for x in r['cases'][:count]) for r in reports)
                    baseline=reports[0]['verdict'] is False
                    successful=[json.loads(x['enabled']) for x,r in zip(final,reports) if r['verdict'] is True]
                    if controls_ok and baseline and successful:
                        repairs=[s for s in successful if not any(set(t)<set(s) for t in successful)]
                        # Joint sets are explicit finite interactions: all proper subsets fail.
                        outcomes={tuple(json.loads(x['enabled'])):r['verdict'] for x,r in zip(final,reports)}
                        interactions=[s for s in repairs if len(s)>1 and all(outcomes[tuple(t)] is False for t in _subsets(s)[:-1])]
                        grade='intervention_supported'
                diagnoses.append({'id':plan['id'],'catalogue_id':plan['catalogue_id'],'plan_digest':plan['plan_digest'],
                                  'grade':grade,'reason':plan['reason'],'origin':payload.get('origin'),
                                  'completed_cells':len(final),'total_cells':len(cells),
                                  'pending_reconciliation':sum(x['state']=='running' for x in cells),
                                  'cleanup_unknown':sum(x['state'] in {'running','exhausted'} and not x['quiescent'] for x in cells),
                                  'exhausted_cells':sum(x['state']=='exhausted' for x in cells),
                                  'minimal_repair_sets':repairs,'interactions':interactions,
                                  'cell_receipts':[{'enabled':json.loads(x['enabled']),'code_hash':x['code_hash'],
                                      'task_hash':digest(json.loads(x['task'])),'report_hash':digest(json.loads(x['report'])),
                                      'verdict':json.loads(x['report'])['verdict']} for x in final]})
            budget={r['day']:r['evaluations'] for r in c.execute('SELECT * FROM diagnostic_budget ORDER BY day DESC LIMIT 7')}
            attempts=c.execute('SELECT report,execution_seconds FROM diagnostic_reservations').fetchall()
            receipts={'reserved':len(attempts),'known':sum(r['report'] is not None and type(json.loads(r['report'])['outcome']) is bool for r in attempts),
                      'unknown':sum(r['report'] is None or json.loads(r['report'])['outcome']=='unknown' for r in attempts),
                      'missing_execution_seconds':sum(r['execution_seconds'] is None for r in attempts),
                      'execution_seconds':sum(r['execution_seconds'] or 0 for r in attempts),'cost_scope':'Local evaluator wall time; no paid model calls'}
            return {'enabled':bool(self.catalogue),'diagnoses':diagnoses,'daily_evaluations':budget,'evaluation_receipts':receipts,
                    'claim':'Finite configured intervention support only; no arbitrary root cause, ddmin cause, or general correctness claim'}


class DiagnosticRunner:
    def __init__(self,store,evaluator,clock=None,daily_budget=2):
        if type(daily_budget) is not int or not 0<=daily_budget<=16: raise ValueError('invalid_diagnostic_budget')
        self.store,self.evaluator=store,evaluator;self.clock=clock or time.time;self.daily_budget=daily_budget

    def tick(self,now,admissible):
        self.store.sync(now)
        if not self.store.catalogue and not self.store.requires_quiescence(): return
        def gate(): return bool(admissible()) and not self.store.ledger.paused()
        with self.evaluator.locked() as acquired:
            if not acquired: return
            # Reconcile surviving containers before any budget reservation or trial.
            if self.store.needs_cleanup():
                clean=self.evaluator.cleanup();self.store.reconcile_cleanup(clean)
                if not clean: return
                if not self.store.catalogue: return
            # Cleanup may be done while paused, but never launch a new trial then.
            if not gate(): self.evaluator.cleanup();return
            cell=self.store.reserve(now,self.daily_budget)
            if cell is None: return
            started=time.monotonic()
            try: report=self.evaluator.evaluate(cell['code'],cell['task'],cell['token'],gate)
            except (DockerError,OSError,ValueError): report={'verdict':'unknown','cleanup_confirmed':False}
            if not self.store.finish(cell,report,self.clock(),execution_seconds=time.monotonic()-started):
                self.store.reconcile_cleanup(self.evaluator.cleanup())

    def summary(self):
        return {**self.store.summary(),'max_evaluations_per_day':self.daily_budget}
