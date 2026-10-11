"""Trusted bounded DAGs and local effect receipts, without remote delivery claims."""
from __future__ import annotations

import json
import uuid

try:
    from .autonomy_store import canonical, digest
    from . import task_inputs, assurance
except ImportError:
    from autonomy_store import canonical, digest
    import task_inputs, assurance

MODES = {'read_only', 'opaque_nonretryable', 'local_outbox'}
SUCCESS = {'succeeded', 'already_satisfied'}
TERMINAL = SUCCESS | {'failed', 'cancelled'}


def _text(value, label, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid_workflow_' + label)
    return value


def validate_workflows(raw, policy):
    """Only configured same-source contracts can become immutable step intents."""
    if not isinstance(raw, list) or len(raw) > 32:
        raise ValueError('invalid_workflows')
    sources = {source['id']: source for source in policy.get('sources', [])}
    result, identities, selectors = [], set(), set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {'id', 'source_id', 'contract_id', 'steps'}:
            raise ValueError('invalid_workflow_fields')
        wid = _text(item['id'], 'id')
        sid = _text(item['source_id'], 'source_id')
        cid = _text(item['contract_id'], 'contract_id')
        source = sources.get(sid)
        if source is None or cid not in source['contracts']:
            raise ValueError('workflow_contract_not_configured')
        if wid in identities or (sid, cid) in selectors:
            raise ValueError('duplicate_workflow')
        identities.add(wid); selectors.add((sid, cid))
        steps = item['steps']
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise ValueError('invalid_workflow_step_count')
        normalized, ids = [], set()
        for step in steps:
            required = {'id', 'contract_id', 'objective'}
            if not isinstance(step, dict) or not required <= set(step) or set(step) - required - {'depends_on', 'effect_mode'}:
                raise ValueError('invalid_workflow_step_fields')
            step_id = _text(step['id'], 'step_id')
            if step_id in ids: raise ValueError('duplicate_workflow_step')
            ids.add(step_id)
            step_cid = _text(step['contract_id'], 'step_contract_id')
            if step_cid not in source['contracts']:
                raise ValueError('workflow_contract_not_configured')
            deps = step.get('depends_on', [])
            if (not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps)
                    or len(deps) != len(set(deps))):
                raise ValueError('invalid_workflow_dependencies')
            mode = step.get('effect_mode', 'opaque_nonretryable')
            if not isinstance(mode, str) or mode not in MODES:
                raise ValueError('invalid_workflow_effect_mode')
            normalized.append({'id':step_id, 'contract_id':step_cid,
                'objective':_text(step['objective'], 'objective', 500), 'depends_on':sorted(deps),
                'effect_mode':mode, 'contract':json.loads(canonical(source['contracts'][step_cid]))})
        by_id = {step['id']:step for step in normalized}
        visiting, visited = set(), set()
        def visit(step_id):
            if step_id not in by_id: raise ValueError('unknown_workflow_dependency')
            if step_id in visiting: raise ValueError('cyclic_workflow')
            if step_id in visited: return
            visiting.add(step_id)
            for dependency in by_id[step_id]['depends_on']:visit(dependency)
            visiting.remove(step_id); visited.add(step_id)
        for step_id in by_id: visit(step_id)
        result.append({'schema':1, 'id':wid, 'source_id':sid, 'contract_id':cid,
                       'contract':json.loads(canonical(source['contracts'][cid])), 'steps':normalized})
    return result


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS workflows(
        parent_goal_id TEXT PRIMARY KEY REFERENCES goals(id), manifest_id TEXT NOT NULL,
        plan TEXT NOT NULL, plan_hash TEXT NOT NULL, source_revision TEXT NOT NULL,
        original_input TEXT NOT NULL, created REAL NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_steps(
        parent_goal_id TEXT NOT NULL REFERENCES workflows(parent_goal_id), step_id TEXT NOT NULL,
        intent TEXT NOT NULL, intent_hash TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
        child_goal_id TEXT UNIQUE REFERENCES goals(id), PRIMARY KEY(parent_goal_id,step_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_effects(
        operation_id TEXT PRIMARY KEY REFERENCES workflow_steps(operation_id), intent_hash TEXT NOT NULL,
        intent TEXT NOT NULL, mode TEXT NOT NULL, receipt TEXT NOT NULL, created REAL NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_outbox(
        operation_id TEXT PRIMARY KEY REFERENCES workflow_effects(operation_id), intent_hash TEXT NOT NULL,
        payload TEXT NOT NULL, created REAL NOT NULL)''')
    for table in ('workflows', 'workflow_effects', 'workflow_outbox'):
        for action in ('UPDATE', 'DELETE'):
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_{table}_{action.lower()}
                BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'frozen_workflow'); END''')
    c.execute('''CREATE TRIGGER IF NOT EXISTS frozen_workflow_steps
        BEFORE UPDATE OF parent_goal_id,step_id,intent,intent_hash,operation_id ON workflow_steps
        BEGIN SELECT RAISE(ABORT,'frozen_workflow_step'); END''')
    c.execute('''CREATE TRIGGER IF NOT EXISTS frozen_workflow_child
        BEFORE UPDATE OF child_goal_id ON workflow_steps WHEN OLD.child_goal_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT,'frozen_workflow_child'); END''')
    c.execute('''CREATE TRIGGER IF NOT EXISTS frozen_workflow_step_delete
        BEFORE DELETE ON workflow_steps BEGIN SELECT RAISE(ABORT,'frozen_workflow_step'); END''')
    c.execute('''CREATE TRIGGER IF NOT EXISTS workflow_submission_guard BEFORE INSERT ON submissions
        WHEN EXISTS(SELECT 1 FROM workflows WHERE parent_goal_id=NEW.goal_id)
          OR (NEW.attempt>1 AND EXISTS(SELECT 1 FROM workflow_steps
              WHERE child_goal_id=NEW.goal_id AND json_extract(intent,'$.effect_mode')='opaque_nonretryable'))
        BEGIN SELECT RAISE(ABORT,'workflow_admission_denied'); END''')


def binding(c, goal_id):
    row = c.execute('SELECT * FROM workflow_steps WHERE child_goal_id=?', (goal_id,)).fetchone()
    if row is None:return None
    plan = c.execute('SELECT plan_hash FROM workflows WHERE parent_goal_id=?', (row['parent_goal_id'],)).fetchone()
    intent = json.loads(row['intent'])
    return {'operation_id':row['operation_id'], 'workflow':{
        'parent_id':row['parent_goal_id'], 'step_id':row['step_id'], 'plan_hash':plan[0],
        'intent_hash':row['intent_hash'], 'effect_mode':intent['effect_mode']}}


def _settled(c, goal):
    if goal['submission_id'] is None:return True
    row = c.execute('SELECT settled FROM submissions WHERE id=?', (goal['submission_id'],)).fetchone()
    return row is not None and bool(row[0])


def _accepted(c, goal):
    if goal['state'] not in SUCCESS or not _settled(c, goal):return False
    rows = c.execute('SELECT data FROM evidence WHERE goal_id=? AND outcome=?', (goal['id'],goal['state']))
    return any((receipt := json.loads(row[0])).get('verdict') is True
               and receipt.get('contract_hash') == goal['contract_hash'] for row in rows)


def finalizable(c, parent_id):
    if c.execute('SELECT 1 FROM workflows WHERE parent_goal_id=?', (parent_id,)).fetchone() is None:return False
    steps = c.execute('SELECT child_goal_id FROM workflow_steps WHERE parent_goal_id=?', (parent_id,)).fetchall()
    if not steps or any(row[0] is None for row in steps):return False
    return all((goal := c.execute('SELECT * FROM goals WHERE id=?', (row[0],)).fetchone()) is not None
               and _accepted(c, goal) for row in steps)


def admission_reason(c, goal_id):
    if c.execute('SELECT 1 FROM workflows WHERE parent_goal_id=?', (goal_id,)).fetchone():return 'workflow_parent'
    meta = binding(c, goal_id)
    if meta is None:return None
    row = c.execute('SELECT * FROM goals WHERE id=?', (goal_id,)).fetchone()
    if meta['workflow']['effect_mode'] == 'opaque_nonretryable' and row['attempts']:
        return 'opaque_effect_nonretryable'
    parent = c.execute('SELECT * FROM goals WHERE id=?', (meta['workflow']['parent_id'],)).fetchone()
    if parent['cancel_requested'] or parent['state'] in TERMINAL:return 'workflow_parent_closed'
    step = json.loads(c.execute('SELECT intent FROM workflow_steps WHERE child_goal_id=?', (goal_id,)).fetchone()[0])
    for dependency in step['depends_on']:
        child = c.execute('SELECT g.* FROM workflow_steps w LEFT JOIN goals g ON g.id=w.child_goal_id '
                          'WHERE w.parent_goal_id=? AND w.step_id=?', (parent['id'],dependency)).fetchone()
        if child is None or child['id'] is None or not _accepted(c, child):return 'workflow_dependency_unsettled'
    return None


class WorkflowStore:
    def __init__(self, ledger, manifests):
        self.ledger = ledger
        # Copy trusted normalization; callers cannot mutate a live plan by retaining a dict.
        self.manifests = json.loads(canonical(manifests))
        self.capture = None
        with ledger._connection(True) as c:initialize(c)

    def sync(self, now):
        registered = 0
        with self.ledger._connection(True) as c:
            for manifest in self.manifests:
                rows = c.execute('''SELECT g.* FROM goals g
                    LEFT JOIN workflow_steps s ON s.child_goal_id=g.id
                    LEFT JOIN workflows w ON w.parent_goal_id=g.id
                    WHERE s.child_goal_id IS NULL AND w.parent_goal_id IS NULL
                      AND g.attempts=0 AND g.state IN ('ready','blocked')''').fetchall()
                for row in rows:
                    candidate = json.loads(row['candidate'])
                    if (candidate.get('source_id'),candidate.get('contract_id'),row['contract_hash']) != (
                            manifest['source_id'],manifest['contract_id'],digest(manifest['contract'])):continue
                    original = task_inputs.binding(c,row['id'])
                    plan = manifest | {'source_revision':row['source_revision'], 'original_input':original,
                                       'parent_goal_id':row['id']}
                    c.execute('INSERT INTO workflows VALUES(?,?,?,?,?,?,?)',
                              (row['id'],manifest['id'],canonical(plan),digest(plan),row['source_revision'],canonical(original),now))
                    for step in manifest['steps']:
                        c.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?,NULL)',
                                  (row['id'],step['id'],canonical(step),digest(step),digest(['workflow-operation-v1',row['id'],step['id']])))
                    registered += 1
        return registered

    def is_parent(self, goal_id):
        with self.ledger._connection() as c:
            if c.execute('SELECT 1 FROM workflows WHERE parent_goal_id=?',(goal_id,)).fetchone():return True
            row = c.execute('SELECT candidate,contract_hash FROM goals WHERE id=?',(goal_id,)).fetchone()
            if row is None:return False
            if c.execute('SELECT 1 FROM workflow_steps WHERE child_goal_id=?',(goal_id,)).fetchone():return False
            candidate = json.loads(row['candidate'])
            return any((candidate.get('source_id'),candidate.get('contract_id'),row['contract_hash']) ==
                       (m['source_id'],m['contract_id'],digest(m['contract'])) for m in self.manifests)

    def dispatchable(self, goal_id):
        if self.is_parent(goal_id):return False
        with self.ledger._connection() as c:
            row = c.execute('SELECT * FROM goals WHERE id=?',(goal_id,)).fetchone()
            if row is None:return False
            if binding(c,goal_id) is None:return True
            if row['state'] not in {'ready','blocked'} or not _settled(c,row):return False
            # The Controller settles this cancellation before capture or HTTP admission.
            if row['cancel_requested']:return True
            return admission_reason(c,goal_id) is None

    def retry_allowed(self, goal_id):
        with self.ledger._connection() as c:
            meta = binding(c,goal_id)
            return meta is None or meta['workflow']['effect_mode'] != 'opaque_nonretryable'

    def operation_id(self, goal_id):
        with self.ledger._connection() as c:
            meta = binding(c,goal_id)
            return meta['operation_id'] if meta else goal_id

    @staticmethod
    def _blocking_reason(c, parent, now):
        children = c.execute('SELECT g.* FROM workflow_steps w JOIN goals g ON g.id=w.child_goal_id WHERE w.parent_goal_id=?',(parent['id'],)).fetchall()
        return ('workflow_dependency_failed' if any(child['state'] in {'failed','cancelled'} for child in children)
                else 'workflow_dependency_unknown' if any(child['state'] == 'unknown_result' for child in children)
                else 'workflow_child_verification_unavailable' if any(child['state'] in SUCCESS and _settled(c,child) and not _accepted(c,child) for child in children)
                else 'workflow_deadline_expired' if now >= parent['deadline'] else None)

    @staticmethod
    def _dependencies_ready(c, parent_id, step):
        for dependency in step['depends_on']:
            goal = c.execute('SELECT g.* FROM workflow_steps w LEFT JOIN goals g ON g.id=w.child_goal_id '
                             'WHERE w.parent_goal_id=? AND w.step_id=?',(parent_id,dependency)).fetchone()
            if goal is None or goal['id'] is None or not _accepted(c,goal):return False
        return True

    @staticmethod
    def _uncertain_execution(c):
        return c.execute("SELECT 1 FROM goals g JOIN submissions s ON s.id=g.submission_id WHERE g.state='unknown_result' AND s.settled=0 LIMIT 1").fetchone() is not None

    def _capture_candidate(self, now):
        candidate = None
        # Close the read snapshot before any verifier filesystem/argv work.
        with self.ledger._connection() as c:
            paused = c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            if (paused and json.loads(paused[0])) or self._uncertain_execution(c):return None
            parents = c.execute('SELECT g.* FROM workflows w JOIN goals g ON g.id=w.parent_goal_id ORDER BY w.created,g.id').fetchall()
            for parent in parents:
                if parent['cancel_requested'] or parent['state'] in TERMINAL or self._blocking_reason(c,parent,now):continue
                for row in c.execute('SELECT * FROM workflow_steps WHERE parent_goal_id=? AND child_goal_id IS NULL ORDER BY rowid',(parent['id'],)):
                    step = json.loads(row['intent'])
                    if not self._dependencies_ready(c,parent['id'],step):continue
                    candidate = {'parent_id':parent['id'],'step_id':row['step_id'],'intent_hash':row['intent_hash'],
                                 'step':step,'original_input':task_inputs.binding(c,parent['id'])}
                    break
                if candidate:break
        if candidate is not None:
            candidate['baseline'] = self.capture(candidate['step']['contract'],candidate['original_input'])
        return candidate

    def _sync_cancellations(self, c):
        for parent in c.execute('SELECT g.* FROM workflows w JOIN goals g ON g.id=w.parent_goal_id WHERE g.cancel_requested=1').fetchall():
            c.execute('UPDATE goals SET cancel_requested=1 WHERE id IN '
                      '(SELECT child_goal_id FROM workflow_steps WHERE parent_goal_id=?)',(parent['id'],))
            pending = c.execute('SELECT 1 FROM workflow_steps w JOIN goals g ON g.id=w.child_goal_id '
                                'JOIN submissions s ON s.id=g.submission_id WHERE w.parent_goal_id=? AND s.settled=0 LIMIT 1',
                                (parent['id'],)).fetchone()
            if parent['state'] in SUCCESS | {'failed'}:continue
            reason = 'workflow_cancel_requested_children_pending' if pending else 'workflow_cancelled'
            c.execute("UPDATE goals SET state='cancelled',reason=? WHERE id=?",(reason,parent['id']))

    def sync_cancellations(self, now=None):
        """Flag children for normal Controller stop/recovery, without settling them."""
        with self.ledger._connection(True) as c:self._sync_cancellations(c)

    def advance(self, now, admissible):
        result = {'created':None, 'finalizable':[]}
        allowed = admissible() is True if callable(admissible) else admissible is True
        candidate = self._capture_candidate(now) if allowed and self.capture is not None else None
        # Recheck service admission after potentially slow verification.
        allowed = allowed and (admissible() is True if callable(admissible) else admissible is True)
        with self.ledger._connection(True) as c:
            self._sync_cancellations(c)
            self._sync_effects(c,now)
            paused = c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            allowed = allowed and not (paused and json.loads(paused[0]))
            parents = c.execute('SELECT g.* FROM workflows w JOIN goals g ON g.id=w.parent_goal_id ORDER BY w.created,g.id').fetchall()
            for parent in parents:
                if parent['state'] in TERMINAL or parent['cancel_requested']:continue
                if finalizable(c,parent['id']):
                    result['finalizable'].append(parent['id']);continue
                reason = self._blocking_reason(c,parent,now)
                if reason:
                    c.execute("UPDATE goals SET state='blocked',reason=? WHERE id=?",(reason,parent['id']))
                    continue
                if not allowed or candidate is None or parent['id'] != candidate['parent_id'] or self._uncertain_execution(c):continue
                row = c.execute('SELECT * FROM workflow_steps WHERE parent_goal_id=? AND step_id=?',
                                (parent['id'],candidate['step_id'])).fetchone()
                if row is None or row['child_goal_id'] is not None or row['intent_hash'] != candidate['intent_hash']:continue
                step = json.loads(row['intent'])
                if not self._dependencies_ready(c,parent['id'],step):continue
                original = task_inputs.binding(c,parent['id'])
                frozen = json.loads(c.execute('SELECT original_input FROM workflows WHERE parent_goal_id=?',(parent['id'],)).fetchone()[0])
                if canonical(original) != canonical(frozen) or canonical(original) != canonical(candidate['original_input']):
                    raise ValueError('workflow_original_input_changed')
                child_candidate = json.loads(parent['candidate']) | {'contract_id':step['contract_id'],
                    'objective':step['objective'], 'reason':'Trusted workflow step '+step['id']}
                child_id = uuid.uuid4().hex
                key = digest(['workflow-child-v1',parent['id'],row['operation_id']])
                c.execute('INSERT INTO goals(id,dedupe,candidate,source_revision,contract,contract_hash,baseline,created,deadline) VALUES(?,?,?,?,?,?,?,?,?)',
                          (child_id,key,canonical(child_candidate),parent['source_revision'],canonical(step['contract']),
                           digest(step['contract']),canonical(candidate['baseline']),now,parent['deadline']))
                task_inputs.bind_goal(c,child_id,child_candidate['source_id'],parent['source_revision'],original)
                c.execute('UPDATE workflow_steps SET child_goal_id=? WHERE parent_goal_id=? AND step_id=? AND child_goal_id IS NULL',
                          (child_id,parent['id'],step['id']))
                result['created'] = child_id
        return result

    def _record_effect(self, c, operation_id, intent, now, *, lease=None):
        payload, intent_hash = canonical(intent), digest(intent)
        step = c.execute('SELECT * FROM workflow_steps WHERE operation_id=?',(operation_id,)).fetchone()
        if step is None:raise ValueError('unknown_operation')
        if lease is not None and (lease.goal_id != step['child_goal_id'] or not self.ledger._owned(c,lease,now)):
            raise ValueError('stale_lease')
        mode = json.loads(step['intent'])['effect_mode']
        if mode == 'read_only':raise ValueError('read_only_effect_disallowed')
        prior = c.execute('SELECT * FROM workflow_effects WHERE operation_id=?',(operation_id,)).fetchone()
        if prior:
            if prior['intent_hash'] != intent_hash:raise ValueError('effect_intent_conflict')
            return json.loads(prior['receipt'])
        receipt = {'schema':1, 'operation_id':operation_id, 'intent_hash':intent_hash,
                   'status':'recorded_local' if mode == 'local_outbox' else 'unknown_remote_effects',
                   'delivered':False, 'created':now}
        c.execute('INSERT INTO workflow_effects VALUES(?,?,?,?,?,?)',
                  (operation_id,intent_hash,payload,mode,canonical(receipt),now))
        if mode == 'local_outbox':
            c.execute('INSERT INTO workflow_outbox VALUES(?,?,?,?)',(operation_id,intent_hash,payload,now))
        assurance.initialize(c)
        # Execution and its completion notification have different immutable intents.
        assurance.record_event(c,'operation',{'operation_id':'effect:'+operation_id,'intent_hash':intent_hash},now)
        return receipt

    def record_effect(self, operation_id, intent, now, *, lease=None):
        """Atomically record one intent; local outbox insertion never means delivery."""
        with self.ledger._connection(True) as c:
            return self._record_effect(c,operation_id,intent,now,lease=lease)

    def _sync_effects(self, c, now):
        recorded = 0
        rows = c.execute('SELECT w.*,p.plan_hash,p.source_revision,p.original_input FROM workflow_steps w '
                         'JOIN workflows p ON p.parent_goal_id=w.parent_goal_id WHERE w.child_goal_id IS NOT NULL').fetchall()
        for row in rows:
            step = json.loads(row['intent'])
            mode = step['effect_mode']
            if mode == 'read_only':continue
            goal = c.execute('SELECT * FROM goals WHERE id=?',(row['child_goal_id'],)).fetchone()
            if goal is None or not _settled(c,goal):continue
            accepted = _accepted(c,goal)
            if mode == 'local_outbox' and not accepted:continue
            if mode == 'opaque_nonretryable' and (not goal['attempts'] or goal['state'] in {'ready','submitting','running','verifying'}):continue
            evidence, evidence_hash = None, None
            for item in c.execute('SELECT receipt,data FROM evidence WHERE goal_id=? AND outcome=? ORDER BY id', (goal['id'],goal['state'])):
                candidate = json.loads(item['data'])
                if candidate.get('contract_hash') == goal['contract_hash'] and (not accepted or candidate.get('verdict') is True):
                    evidence, evidence_hash = candidate, item['receipt'];break
            original = json.loads(row['original_input'])
            intent = {'schema':1, 'notification':'verified_workflow_step' if mode == 'local_outbox' else 'opaque_workflow_attempt',
                      'parent_goal_id':row['parent_goal_id'], 'child_goal_id':goal['id'], 'step_id':row['step_id'],
                      'operation_id':row['operation_id'], 'plan_hash':row['plan_hash'], 'step_intent_hash':row['intent_hash'],
                      'source_revision':row['source_revision'], 'input_hash':original['input_hash'] if original else None,
                      'outcome':goal['state'], 'receipt_hash':evidence_hash,
                      'artifact_hash':evidence.get('artifact_hash') if evidence else None}
            exists = c.execute('SELECT intent FROM workflow_effects WHERE operation_id=?',(row['operation_id'],)).fetchone()
            if exists:
                frozen = json.loads(exists[0])
                immutable = ('schema','notification','parent_goal_id','child_goal_id','step_id','operation_id',
                             'plan_hash','step_intent_hash','source_revision','input_hash')
                if any(canonical(frozen.get(key)) != canonical(intent[key]) for key in immutable):
                    raise ValueError('effect_intent_conflict')
                # Later reconciliation never rewrites the first settled observation.
                continue
            self._record_effect(c,row['operation_id'],intent,now)
            recorded += 1
        return recorded

    def sync_effects(self, now):
        """Reconcile settled steps even after pause, completion, or restart."""
        with self.ledger._connection(True) as c:
            return self._sync_effects(c,now)

    def summary(self):
        with self.ledger._connection() as c:
            workflows = []
            for parent in c.execute('SELECT w.*,g.state,g.cancel_requested FROM workflows w JOIN goals g ON g.id=w.parent_goal_id ORDER BY w.created LIMIT 20'):
                steps = []
                rows = c.execute('SELECT w.*,g.state,g.attempts,g.submission_id FROM workflow_steps w LEFT JOIN goals g ON g.id=w.child_goal_id WHERE w.parent_goal_id=? ORDER BY w.rowid',(parent['parent_goal_id'],)).fetchall()
                by_id = {row['step_id']:row for row in rows}
                for row in rows:
                    intent = json.loads(row['intent'])
                    state = row['state'] or 'pending'
                    reason = None
                    if row['child_goal_id'] is None:
                        deps = [by_id[dep] for dep in intent['depends_on']]
                        if any(dep['state'] in {'failed','cancelled'} for dep in deps):reason='dependency_failed'
                        elif any(dep['state'] == 'unknown_result' for dep in deps):reason='dependency_unknown'
                    effect_row = c.execute('SELECT receipt FROM workflow_effects WHERE operation_id=?',(row['operation_id'],)).fetchone()
                    effect = (json.loads(effect_row[0])['status'] if effect_row else
                              'unknown_remote_effects_unsettled' if intent['effect_mode'] == 'opaque_nonretryable' and row['attempts']
                              else 'not_recorded')
                    steps.append({'id':row['step_id'], 'goal_id':row['child_goal_id'], 'state':state,
                                  'reason':reason, 'operation_id':row['operation_id'], 'effect_mode':intent['effect_mode'], 'effect_state':effect})
                workflows.append({'parent_id':parent['parent_goal_id'], 'manifest_id':parent['manifest_id'],
                                  'plan_hash':parent['plan_hash'], 'state':parent['state'],
                                  'finalizable':finalizable(c,parent['parent_goal_id']), 'steps':steps})
            count = c.execute('SELECT COUNT(*) FROM workflows').fetchone()[0]
            records = c.execute('SELECT COUNT(*) FROM workflow_outbox').fetchone()[0]
            return {'enabled':bool(self.manifests or count), 'configured':len(self.manifests), 'registered':count,
                    'workflows':workflows, 'outbox':{'records':records, 'delivery':'unavailable',
                    'scope':'Atomic local intent records only; remote effects are not exactly-once.'}}
