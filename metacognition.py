"""Receipt-based attempt forecasts and bounded admission-time monitoring.

All connection-taking functions are pure SQLite/JSON work. The caller performs
any verifier I/O before its BEGIN IMMEDIATE admission transaction.
"""
from __future__ import annotations

import json
import math

try:
    from .autonomy_store import canonical, digest
except ImportError:
    from autonomy_store import canonical, digest


def validate_monitoring(raw, policy=None):
    if raw is None: raw = {}
    if not isinstance(raw, dict): raise ValueError('invalid_monitoring')
    allowed = {'enabled','mode','threshold','max_rechecks','constant_probability'}
    if set(raw) - allowed: raise ValueError('invalid_monitoring_fields')
    result = {'enabled':False,'mode':'normal','threshold':.6,'max_rechecks':1,'constant_probability':.5,**raw}
    if type(result['enabled']) is not bool or result['mode'] not in ('normal','masked','constant'):
        raise ValueError('invalid_monitoring_mode')
    for key in ('threshold','constant_probability'):
        value = result[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('invalid_monitoring_probability')
    if type(result['max_rechecks']) is not int or not 0 <= result['max_rechecks'] <= 1:
        raise ValueError('invalid_monitoring_rechecks')
    return result


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS attempt_predictions(
        submission_id TEXT PRIMARY KEY REFERENCES submissions(id),
        prediction TEXT NOT NULL, prediction_hash TEXT NOT NULL)''')
    for action in ('UPDATE','DELETE'):
        c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_attempt_prediction_{action.lower()}
            BEFORE {action} ON attempt_predictions
            BEGIN SELECT RAISE(ABORT,'frozen_attempt_prediction'); END''')


def _base_request(request):
    value = json.loads(canonical(request))
    try: intent = json.loads(value['input'])
    except (KeyError,TypeError,ValueError): return value
    if isinstance(intent,dict) and 'functional_monitoring' in intent:
        del intent['functional_monitoring']; value['input'] = canonical(intent)
    return value


def _policy(policy):
    # Accept either the monitoring section or the complete Controller policy.
    return validate_monitoring(policy.get('monitoring') if 'monitoring' in policy else policy)


def capture(c, goal, identity, request, now, policy):
    policy = _policy(policy)
    now = float(now)
    stratum = 'first' if goal['attempts'] == 0 else 'retry'
    scope = {'source_id':goal['source_id'],'domain':goal['domain'],
             'contract_id':goal['contract_id'],'contract_hash':goal['contract_hash'],
             'execution_identity':identity,'stratum':stratum}
    samples = []
    columns = {r[1] for r in c.execute('PRAGMA table_info(submissions)')}
    # Legacy dispatch times do not establish when evidence or quiescence became known.
    if {'evidence_created','settled_at'} <= columns:
        rows = c.execute('''SELECT s.*,g.candidate,g.contract_hash FROM submissions s
            JOIN goals g ON g.id=s.goal_id WHERE s.settled=1 AND s.created<?
            AND s.evidence_created<? AND s.settled_at<? AND s.evidence IS NOT NULL
            ORDER BY s.id''',(now,now,now)).fetchall()
        for row in rows:
            candidate = json.loads(row['candidate']); evidence = json.loads(row['evidence'])
            if (any(candidate.get(key) != scope[key] for key in ('source_id','domain','contract_id'))
                or row['contract_hash'] != scope['contract_hash']
                or json.loads(row['execution_identity']) != identity
                or ('first' if row['attempt']==1 else 'retry') != stratum
                or not isinstance(evidence,dict) or type(evidence.get('verdict')) is not bool
                or evidence.get('contract_hash') != scope['contract_hash']): continue
            samples.append({'submission_id':row['id'],'verdict':evidence['verdict'],
                            'evidence_hash':digest(evidence),'evidence_created':row['evidence_created'],
                            'settled_at':row['settled_at']})
    successes = sum(item['verdict'] for item in samples)
    probability = (successes+1)/(len(samples)+2)
    origin = 'scoped_attempt_laplace' if samples else 'prior_only'
    if not policy['enabled']:
        probability = goal.get('confidence')
        origin = 'goal_prior_reused_before_submission'
    elif policy['mode'] == 'constant':
        probability = policy['constant_probability']; origin = 'trusted_constant'
    action = ('recheck' if policy['enabled'] and policy['mode'] != 'masked'
              and probability < policy['threshold'] and policy['max_rechecks'] else 'continue')
    provenance = {'origin':origin,'samples':len(samples),'positive_samples':successes,
                  'negative_samples':len(samples)-successes,'sample_ids':[s['submission_id'] for s in samples],
                  'stratum':stratum,'scope':scope,'monitor_masked':policy['mode']=='masked',
                  'method':('Candidate goal prior reused; not an attempt estimator' if not policy['enabled'] else
                            'Trusted configured probability; not an adaptive estimate' if policy['mode']=='constant' else
                            'Laplace (successes+1)/(samples+2); no model self-report')}
    result = {'schema':1,'goal_id':goal['id'],'attempt':goal['attempts']+1,'captured_at':now,
              'probability':probability,'provenance':provenance,'action':action,'policy':policy,
              'estimator_hash':digest({'scope':scope,'samples':samples,'policy':policy}),
              'base_request_hash':digest(_base_request(request)),
              'input_hash':(goal.get('task_input') or {}).get('input_hash')}
    result['capture_hash'] = digest(result)
    return result


def _directive(captured):
    return {'schema':1,'action':'recheck','forecast_origin':captured['provenance']['origin'],
            'probability':captured['probability'],'estimator_hash':captured['estimator_hash'],
            'instruction':'A trusted independent prerequisite recheck was required before admission. Reconsider task prerequisites; the original acceptance contract remains binding.'}


def apply_directive(request, captured):
    result = _base_request(request)
    if captured['action'] == 'recheck':
        try: intent = json.loads(result['input'])
        except (KeyError,TypeError,ValueError): raise ValueError('monitoring_intent_required') from None
        if not isinstance(intent,dict): raise ValueError('monitoring_intent_required')
        intent['functional_monitoring'] = _directive(captured); result['input'] = canonical(intent)
        if len(result['input'].encode()) > 16384: raise ValueError('execution_intent_too_large')
    return result


def prepare(c, goal, identity, request, now, policy, *, capture=None, recheck=None):
    # capture() is also exposed for the read-only preflight before external checking.
    now = float(now)
    current = globals()['capture'](c,goal,identity,request,now,policy)
    if capture is not None:
        original = dict(capture); capture_hash = original.pop('capture_hash',None)
        if (digest(original) != capture_hash or capture.get('captured_at',now+1)>now
            or any(capture.get(k)!=current.get(k) for k in
                   ('schema','goal_id','attempt','probability','provenance','action','policy',
                    'estimator_hash','base_request_hash','input_hash'))):
            raise ValueError('monitoring_capture_stale')
    else:
        if current['action'] == 'recheck': raise ValueError('monitoring_capture_required')
        capture = current
    if canonical(request) != canonical(apply_directive(request,capture)):
        raise ValueError('monitoring_directive_mismatch')
    checks = 0; seconds = 0
    if current['action'] == 'recheck':
        if not isinstance(recheck,dict): raise ValueError('monitoring_recheck_required')
        evidence = recheck.get('evidence'); start = recheck.get('started_at'); end = recheck.get('finished_at')
        if (type(recheck.get('checks')) is not int or recheck['checks'] != 1
            or type(start) not in (int,float) or type(end) not in (int,float)
            or not math.isfinite(start) or not math.isfinite(end)
            or not capture['captured_at'] <= start <= end <= now
            or not isinstance(evidence,dict) or evidence.get('contract_hash') != goal['contract_hash']
            or 'verdict' not in evidence or 'artifact_hash' not in evidence
            or type(evidence.get('check_version')) is not int or evidence['check_version'] not in (1,2)
            or not isinstance(evidence.get('reason'),str)
            or not (type(evidence['verdict']) is bool or evidence['verdict'] is None or evidence['verdict']=='unknown')):
            raise ValueError('monitoring_recheck_invalid')
        checks = 1; seconds = end-start
    elif recheck is not None: raise ValueError('monitoring_unexpected_recheck')
    result = {**current,'capture':capture,'prepared_at':now,'request_hash':digest(request),
              'execution_identity_hash':digest(identity),'extra_checks':checks,
              'extra_check_seconds':seconds,'recheck_receipt':recheck}
    result['prediction_hash'] = digest(result)
    return result


def record(c, submission_id, prediction):
    payload = dict(prediction); supplied = payload.pop('prediction_hash',None)
    if digest(payload) != supplied: raise ValueError('monitoring_prediction_invalid')
    row = c.execute('SELECT * FROM submissions WHERE id=?',(submission_id,)).fetchone()
    if row is None: raise ValueError('monitoring_submission_missing')
    if row['settled'] or row['evidence'] is not None:
        raise ValueError('monitoring_prediction_after_outcome')
    if any(key in row.keys() and row[key] is not None for key in ('run_id','host_status')):
        raise ValueError('monitoring_prediction_after_dispatch')
    request = json.loads(row['request']); identity = json.loads(row['execution_identity'])
    if (row['goal_id'] != prediction['goal_id'] or row['attempt'] != prediction['attempt']
        or row['created'] != prediction['prepared_at'] or digest(request) != prediction['request_hash']
        or digest(identity) != prediction['execution_identity_hash'] or row['forecast'] != prediction['probability']):
        raise ValueError('monitoring_prediction_binding')
    goalrow = c.execute('SELECT * FROM goals WHERE id=?',(row['goal_id'],)).fetchone()
    candidate = json.loads(goalrow['candidate'])
    inputrow = c.execute('SELECT input_hash FROM task_inputs WHERE goal_id=?',(row['goal_id'],)).fetchone()
    goal = {**candidate,'id':row['goal_id'],'attempts':row['attempt']-1,
            'contract_hash':goalrow['contract_hash'],'task_input':dict(inputrow) if inputrow else None}
    expected = prepare(c,goal,identity,request,row['created'],prediction['policy'],
                       capture=prediction['capture'],recheck=prediction['recheck_receipt'])
    if canonical(expected) != canonical(prediction): raise ValueError('monitoring_prediction_invalid')
    existing = c.execute('SELECT prediction_hash FROM attempt_predictions WHERE submission_id=?',(submission_id,)).fetchone()
    if existing:
        if existing[0] != supplied: raise ValueError('monitoring_prediction_conflict')
        return
    c.execute('INSERT INTO attempt_predictions VALUES(?,?,?)',(submission_id,canonical(prediction),supplied))


def predictions(c):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempt_predictions'").fetchone() is None:
        return {}
    return {row['submission_id']:json.loads(row['prediction']) for row in c.execute('SELECT * FROM attempt_predictions')}
