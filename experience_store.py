"""Scoped strategy hypotheses; only immutable verifier evidence evaluates reuse."""
from __future__ import annotations

import json
import uuid

try:
    from .autonomy_store import canonical, digest
except ImportError:
    from autonomy_store import canonical, digest

SCHEMA = 1
LEASE_SECONDS = 120


def scope_for(goal, identity):
    return {'schema': SCHEMA, 'source_id': goal['source_id'], 'domain': goal['domain'],
            'contract_hash': goal['contract_hash'], 'execution_identity': identity}


class ExperienceStore:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger._connection(True) as c:
            for statement in (
                '''CREATE TABLE IF NOT EXISTS learning_jobs(
                    submission_id TEXT PRIMARY KEY REFERENCES submissions(id), payload TEXT NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, owner TEXT,
                    generation INTEGER NOT NULL DEFAULT 0, lease_until REAL, next_retry REAL NOT NULL DEFAULT 0)''',
                '''CREATE TABLE IF NOT EXISTS strategies(
                    id TEXT PRIMARY KEY, origin_submission TEXT NOT NULL UNIQUE REFERENCES submissions(id),
                    origin_goal TEXT NOT NULL REFERENCES goals(id), scope TEXT NOT NULL,
                    guidance TEXT NOT NULL, body_hash TEXT NOT NULL, created REAL NOT NULL,
                    state TEXT NOT NULL DEFAULT 'candidate', reason TEXT NOT NULL DEFAULT 'unvalidated_hypothesis')''',
                '''CREATE TABLE IF NOT EXISTS strategy_evaluations(
                    strategy_id TEXT NOT NULL REFERENCES strategies(id), submission_id TEXT NOT NULL REFERENCES submissions(id),
                    goal_id TEXT NOT NULL, verdict INTEGER NOT NULL, heldout INTEGER NOT NULL,
                    evidence_hash TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(strategy_id,submission_id))''',
                '''CREATE TABLE IF NOT EXISTS experience_scans(submission_id TEXT PRIMARY KEY REFERENCES submissions(id))''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_strategy BEFORE UPDATE OF
                    origin_submission,origin_goal,scope,guidance,body_hash,created ON strategies
                    BEGIN SELECT RAISE(ABORT,'frozen_strategy'); END''',
                '''CREATE TRIGGER IF NOT EXISTS frozen_learning_payload BEFORE UPDATE OF payload ON learning_jobs
                    BEGIN SELECT RAISE(ABORT,'frozen_learning_payload'); END''',
            ): c.execute(statement)

    def sync(self, now):
        with self.ledger._connection(True) as c:
            rows = c.execute('''SELECT s.* FROM submissions s WHERE s.settled=1 AND s.evidence IS NOT NULL
                AND NOT EXISTS(SELECT 1 FROM learning_jobs j WHERE j.submission_id=s.id)
                AND s.host_status IN ('completed','failed','cancelled') ORDER BY s.created,s.id LIMIT 50''').fetchall()
            for row in rows:
                sub = self.ledger._submission(row)
                goal = self.ledger._goal(c, c.execute('SELECT * FROM goals WHERE id=?', (sub['goal_id'],)).fetchone())
                checked = sub['evidence']
                # Nonfailures are recorded as ignored so old success rows cannot starve new work.
                eligible = (checked.get('verdict') is False and checked.get('contract_hash') == goal['contract_hash']
                            and not goal.get('cancel_requested') and goal['state'] != 'cancelled')
                payload = {'goal_id': goal['id'], 'objective': goal['objective'],
                           'scope': scope_for(goal, sub['execution_identity']),
                           'evidence': {'submission_id': sub['id'], 'receipt': digest([sub['id'], checked]),
                                        'contract_type': goal['contract']['type'],
                                        'reason': str(checked.get('reason', ''))[:240],
                                        'artifact_hash': checked.get('artifact_hash')}}
                c.execute('INSERT OR IGNORE INTO learning_jobs(submission_id,payload,state) VALUES(?,?,?)',
                          (sub['id'], canonical(payload), 'pending' if eligible else 'ignored'))

    def claim(self, now):
        with self.ledger._connection(True) as c:
            c.execute("UPDATE learning_jobs SET state='invalid',owner=NULL,lease_until=NULL WHERE attempts>=2 AND state IN ('claimed','generating') AND lease_until<=?", (now,))
            row = c.execute('''SELECT * FROM learning_jobs WHERE attempts<2 AND next_retry<=?
                AND (state='pending' OR (state IN ('claimed','generating') AND lease_until<=?))
                ORDER BY next_retry,submission_id LIMIT 1''', (now, now)).fetchone()
            if row is None: return None
            owner = uuid.uuid4().hex
            c.execute('UPDATE learning_jobs SET state=\'claimed\',owner=?,generation=generation+1,lease_until=? WHERE submission_id=?',
                      (owner, now+LEASE_SECONDS, row['submission_id']))
            return {**dict(row), 'owner': owner, 'generation': row['generation']+1,
                    'payload': json.loads(row['payload'])}

    @staticmethod
    def _owned(c, job, now):
        return c.execute('''SELECT * FROM learning_jobs WHERE submission_id=? AND owner=?
            AND generation=? AND lease_until>? AND state IN ('claimed','generating')''',
            (job['submission_id'], job['owner'], job['generation'], now)).fetchone()

    def begin(self, job, now):
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None or row['state'] != 'claimed' or row['attempts'] >= 2: return False
            c.execute("UPDATE learning_jobs SET state='generating',attempts=attempts+1 WHERE submission_id=?", (job['submission_id'],))
            return True

    def complete(self, job, guidance, now):
        if (not isinstance(guidance, str) or not guidance.strip() or len(guidance)>600
                or any(ord(ch)<32 and ch not in '\n\t' for ch in guidance)):
            raise ValueError('invalid_guidance')
        guidance = guidance.strip()
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None or row['state'] != 'generating': return False
            payload = json.loads(row['payload'])
            c.execute('''INSERT OR IGNORE INTO strategies(id,origin_submission,origin_goal,scope,guidance,body_hash,created)
                VALUES(?,?,?,?,?,?,?)''', (uuid.uuid4().hex, job['submission_id'], payload['goal_id'],
                canonical(payload['scope']), guidance, digest(guidance), now))
            c.execute("UPDATE learning_jobs SET state='done',owner=NULL,lease_until=NULL WHERE submission_id=?", (job['submission_id'],))
            return True

    def defer(self, job, now, reason='unavailable'):
        with self.ledger._connection(True) as c:
            if self._owned(c, job, now) is None: return False
            c.execute("UPDATE learning_jobs SET state='pending',owner=NULL,lease_until=NULL,next_retry=? WHERE submission_id=?",
                      (now+60, job['submission_id']))
            return True

    def reject(self, job, now):
        with self.ledger._connection(True) as c:
            row = self._owned(c, job, now)
            if row is None: return False
            c.execute('UPDATE learning_jobs SET state=?,owner=NULL,lease_until=NULL,next_retry=? WHERE submission_id=?',
                      ('invalid' if row['attempts']>=2 else 'pending', now+60, job['submission_id']))
            return True

    @staticmethod
    def _strategy(row):
        return {'id': row['id'], 'origin_submission': row['origin_submission'], 'scope': json.loads(row['scope']),
                'guidance': row['guidance'], 'body_hash': row['body_hash'], 'status': row['state'],
                'kind': 'strategy_hypothesis'}

    def retrieve(self, goal, identity):
        with self.ledger._connection() as c:
            rows = c.execute('''SELECT * FROM strategies WHERE scope=? AND state IN ('candidate','active')
                ORDER BY CASE state WHEN 'active' THEN 0 ELSE 1 END,created DESC,id LIMIT 2''',
                (canonical(scope_for(goal, identity)),)).fetchall()
            return [self._strategy(row) for row in rows]

    def evaluate(self, now):
        with self.ledger._connection(True) as c:
            rows = c.execute('''SELECT s.* FROM submissions s WHERE s.settled=1 AND s.evidence IS NOT NULL
                AND s.host_status IN ('completed','failed','cancelled')
                AND NOT EXISTS(SELECT 1 FROM experience_scans e WHERE e.submission_id=s.id)
                ORDER BY s.created,s.id LIMIT 50''').fetchall()
            for row in rows:
                sub = self.ledger._submission(row)
                goal = self.ledger._goal(c, c.execute('SELECT * FROM goals WHERE id=?', (sub['goal_id'],)).fetchone())
                checked = sub['evidence']
                try: selected = json.loads(sub['request']['input']).get('experience', [])
                except (ValueError, KeyError, TypeError, AttributeError): selected = []
                if not isinstance(selected, list): selected = []
                if (type(checked.get('verdict')) is bool and checked.get('contract_hash') == goal['contract_hash']
                        and not goal.get('cancel_requested') and goal['state'] != 'cancelled'):
                    for binding in selected[:2]:
                        if not isinstance(binding, dict): continue
                        strategy = c.execute('SELECT * FROM strategies WHERE id=?', (binding.get('id'),)).fetchone()
                        if (strategy is None or strategy['body_hash'] != binding.get('body_hash')
                                or strategy['guidance'] != binding.get('guidance')
                                or strategy['scope'] != canonical(scope_for(goal, sub['execution_identity']))): continue
                        verdict = checked['verdict']
                        heldout = (verdict and sub['attempt']==1 and goal['attempts']==1
                                   and goal['state']=='succeeded' and goal['id'] != strategy['origin_goal']
                                   and goal['created'] > strategy['created'])
                        c.execute('''INSERT OR IGNORE INTO strategy_evaluations VALUES(?,?,?,?,?,?,?)''',
                            (strategy['id'], sub['id'], goal['id'], int(verdict), int(heldout), digest(checked), now))
                        if not verdict:
                            c.execute("UPDATE strategies SET state='retired',reason='verified_reuse_failure' WHERE id=?", (strategy['id'],))
                        elif strategy['state'] != 'retired':
                            count = c.execute('SELECT COUNT(DISTINCT goal_id) FROM strategy_evaluations WHERE strategy_id=? AND heldout=1', (strategy['id'],)).fetchone()[0]
                            if count >= 2:
                                c.execute("UPDATE strategies SET state='active',reason='two_independent_first_pass_results' WHERE id=? AND state!='retired'", (strategy['id'],))
                c.execute('INSERT INTO experience_scans VALUES(?)', (sub['id'],))

    def planning_context(self, observations, identity, policy):
        source_ids = {o['id'] for o in observations}
        scopes = {canonical({'schema': SCHEMA, 'source_id': source['id'], 'domain': source['domain'],
                             'contract_hash': digest(contract), 'execution_identity': identity})
                  for source in policy['sources'] if source['id'] in source_ids
                  for contract in source['contracts'].values()}
        return [s for s in self.summary()['strategies'] if canonical(s['scope']) in scopes and s['status']!='retired'][:2]

    def summary(self):
        with self.ledger._connection() as c:
            strategies = []
            for row in c.execute('SELECT * FROM strategies ORDER BY created DESC,id LIMIT 20'):
                item = self._strategy(row)
                item['heldout_successes'] = c.execute('SELECT COUNT(DISTINCT goal_id) FROM strategy_evaluations WHERE strategy_id=? AND heldout=1', (row['id'],)).fetchone()[0]
                item['reason'] = row['reason']; strategies.append(item)
            jobs = {row['state']: row['n'] for row in c.execute('SELECT state,COUNT(*) n FROM learning_jobs GROUP BY state')}
            states = {row['state']: row['n'] for row in c.execute('SELECT state,COUNT(*) n FROM strategies GROUP BY state')}
        return {'schema': SCHEMA, 'strategies': strategies, 'jobs': jobs, 'states': states,
                'claim': 'Scoped prompt-strategy use associations, not causal improvement or executable skill certification'}
