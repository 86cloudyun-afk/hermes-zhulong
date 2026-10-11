"""Opt-in prospective metadata prediction and bounded focus routing.

Waiting update order: on each real select observation, increment continuously
eligible counters once before ranking, clear counters for excluded sources, then
reset only actually selected counters to zero. Oldest overdue counters precede
all scores. For a fixed N continuously eligible sources, capacity K, threshold W,
the gap between selections is at most W + ceil(N/K) - 1 observation ticks.
At W, at most N sources can precede a waiting source; each tick services K of
that queue, and newly overdue/reset sources cannot overtake its older counter.
This bound includes simultaneous overdue queue service; it assumes no churn,
failed transaction, capacity reduction or eligibility interruption.

Freshness is an external next-observation endpoint, independent of admission and
the conditional schedule endpoint. Counts learn only on-time binary outcomes
under exactly the frozen identity/configuration/policy/horizon scope. This is a
small stationary-regime estimator, not evidence of subjective experience.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid

try:
    from .autonomy_store import canonical, digest
except ImportError:
    from autonomy_store import canonical, digest


MODEL_OUTCOME_LIMIT = 128
MECHANISM = {'schema': 1, 'target': 'next_observation_source_freshness',
             'model_outcome_limit': MODEL_OUTCOME_LIMIT,
             'model': 'scoped_on_time_laplace', 'permutation': 'sorted_id_cycle_one',
             'wait_update': 'increment_eligible_before_rank_reset_selected_after',
             'rank': 'oldest_overdue_then_freshness_minus_switch_then_oldest_selection_id',
             'fairness': 'fixed_N_K_gap_le_W_plus_ceil_N_over_K_minus_1',
             'hidden_activations': 'unavailable', 'subjective_experience': 'not_established'}
EVENTS = ('observed_on_time', 'overdue', 'unobserved', 'scope_mismatch', 'pending')
CONTENT = ('fresh', 'revision_drift', 'input_drift', 'facts_drift', 'unavailable',
           'newly_available', 'unobserved', 'pending')


def initialize(c):
    definitions = {
        'cognition_forecasts': (
            'seq INTEGER PRIMARY KEY AUTOINCREMENT, forecast_id TEXT UNIQUE NOT NULL, '
            'origin_frame_id TEXT, scope_hash TEXT NOT NULL, forecast TEXT NOT NULL, forecast_hash TEXT NOT NULL',
            'seq=NEW.seq OR forecast_id=NEW.forecast_id'),
        'cognition_forecast_outcomes': (
            'seq INTEGER PRIMARY KEY AUTOINCREMENT, forecast_id TEXT UNIQUE NOT NULL '
            'REFERENCES cognition_forecasts(forecast_id), observed_at REAL NOT NULL, '
            'outcome TEXT NOT NULL, outcome_hash TEXT NOT NULL',
            'seq=NEW.seq OR forecast_id=NEW.forecast_id'),
        'cognition_attention_off_observations': (
            'seq INTEGER PRIMARY KEY AUTOINCREMENT, observation_id TEXT UNIQUE NOT NULL, '
            'observation TEXT NOT NULL, observation_hash TEXT NOT NULL',
            'seq=NEW.seq OR observation_id=NEW.observation_id')}
    for table, (columns, collision) in definitions.items():
        c.execute(f'CREATE TABLE IF NOT EXISTS {table}({columns})')
        for action in ('UPDATE', 'DELETE'):
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_{table}_{action.lower()}
                BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'frozen_attention'); END''')
        c.execute(f'''CREATE TRIGGER IF NOT EXISTS frozen_{table}_collision BEFORE INSERT ON {table}
            WHEN EXISTS(SELECT 1 FROM {table} WHERE {collision})
            BEGIN SELECT RAISE(ABORT,'frozen_attention_collision'); END''')
    c.execute('CREATE INDEX IF NOT EXISTS attention_scope_seq ON cognition_forecasts(scope_hash,seq)')


def observe_off(c, selected_ids, frame_id, now, policy, identity_hash, configuration,
                *, reason='attention_off_observation'):
    """Best-effort inactive marker, only after attention has ever been active.

    An off observation is still the next real observation for pending forecasts.
    Its changed policy makes those targets unobserved rather than training them
    on a later resumed sample. No forecast is allocated and no waits are invented.
    """
    c.execute('SAVEPOINT attention_off_observation')
    try:
        if c.execute('SELECT 1 FROM cognition_forecasts LIMIT 1').fetchone() is None:
            c.execute('RELEASE attention_off_observation')
            return True
        observation = {'schema': 1, 'observation_id': uuid.uuid4().hex, 'observed_at': now,
                       'frame_id': frame_id, 'focus_ids': selected_ids, 'wait_state_available': False,
                       'frame_seq_cutoff': c.execute('SELECT COALESCE(MAX(seq),0) FROM cognition_frames').fetchone()[0]+int(frame_id is not None),
                       'scope_hash': digest({'identity_hash': identity_hash, 'configuration': configuration,
                                             'policy': policy, 'mechanism': MECHANISM})}
        if reason != 'attention_off_observation':
            observation['reason'] = reason
        for row in c.execute('''SELECT f.forecast FROM cognition_forecasts f
                              LEFT JOIN cognition_forecast_outcomes o USING(forecast_id)
                              WHERE o.forecast_id IS NULL ORDER BY f.seq'''):
            f = json.loads(row[0])
            if now < f['captured_at']:
                raise ValueError('attention_clock_reversed')
            outcome = {'schema': 1, 'outcome_id': uuid.uuid4().hex, 'forecast_id': f['forecast_id'],
                       'scope_hash': f['scope_hash'], 'observation_scope_hash': observation['scope_hash'],
                       'observed_at': now, 'elapsed_seconds': now-f['captured_at'], 'status': 'scope_mismatch',
                       'scope_mismatch_reason': reason,
                       'off_observation_id': observation['observation_id'],
                       'sources': [{'source_id': p['source_id'], 'content': 'unobserved', 'fresh': None,
                                    'observed_entry': None, 'eligibility': 'cognition_disabled_scope' if
                                    reason == 'cognition_disabled_observation' else 'attention_off_scope'}
                                   for p in f['source_predictions']],
                       'new_source_ids': [], 'expected_next_source_ids': f['expected_next_source_ids']}
            c.execute('INSERT INTO cognition_forecast_outcomes(forecast_id,observed_at,outcome,outcome_hash) VALUES(?,?,?,?)',
                      (f['forecast_id'], now, canonical(outcome), digest(outcome)))
        c.execute('INSERT INTO cognition_attention_off_observations(observation_id,observation,observation_hash) VALUES(?,?,?)',
                  (observation['observation_id'], canonical(observation), digest(observation)))
        c.execute('RELEASE attention_off_observation')
        return True
    except (sqlite3.DatabaseError, ValueError):
        c.execute('ROLLBACK TO attention_off_observation')
        c.execute('RELEASE attention_off_observation')
        return False


def _prior_control(c, now):
    """Physical selection history is global; freshness evidence remains scoped."""
    row = c.execute('SELECT forecast FROM cognition_forecasts ORDER BY seq DESC LIMIT 1').fetchone()
    previous = json.loads(row[0]) if row else None
    empty = {'focus_ids': [], 'wait_ticks': {}, 'last_selected_seq': {}}
    frame = c.execute('SELECT seq,frame FROM cognition_frames ORDER BY seq DESC LIMIT 1').fetchone()
    latest_frame = json.loads(frame['frame']) if frame else None
    historical = {'historical_frame_id': latest_frame['frame_id']} if frame else {}
    frame_cutoff = previous.get('frame_seq_cutoff', 0) if previous else 0
    marker = c.execute('SELECT seq,observation FROM cognition_attention_off_observations ORDER BY seq DESC LIMIT 1').fetchone()
    observation = json.loads(marker['observation']) if marker else None
    marker_is_new = marker and (previous is None or marker['seq'] > previous.get('off_observation_cutoff', 0))
    marker_frame_cutoff = observation.get('frame_seq_cutoff') if observation else None
    if marker_is_new and type(marker_frame_cutoff) is not int:
        # A legacy marker's associated frame gives a cursor; an empty legacy
        # marker cannot establish order beyond the previous forecast's cursor.
        associated = c.execute('SELECT seq FROM cognition_frames WHERE frame_id=?',
                               (observation['frame_id'],)).fetchone()
        marker_frame_cutoff = associated['seq'] if associated else frame_cutoff
    interruption = None
    for row in c.execute('SELECT seq,frame FROM cognition_frames WHERE seq>? ORDER BY seq DESC', (frame_cutoff,)):
        candidate = json.loads(row['frame'])
        if candidate.get('inactive_observation_reason'):
            interruption = (row['seq'], candidate)
            break
    if interruption:
        interruption_seq, interrupted_frame = interruption
        if now < interrupted_frame['captured_at']:
            raise ValueError('attention_clock_reversed')
        if not marker_is_new or marker_frame_cutoff < interruption_seq:
            # Later unmarked frames cannot hide an unacknowledged interruption.
            # Only a marker that captured it, or a new forecast cursor, consumes it.
            return empty, {**historical, 'origin': 'cognition_disabled_observation_journal_unavailable_reset',
                'interruption_frame_id': interrupted_frame['frame_id'], 'interruption_frame_seq': interruption_seq,
                'interruption_reason': interrupted_frame['inactive_observation_reason'],
                'wait_state_available': False, 'focus_state_available': False, 'interrupted_since_forecast': True}
    if marker_is_new:
        if now < observation['observed_at']:
            raise ValueError('attention_clock_reversed')
        if frame and frame['seq'] > marker_frame_cutoff:
            return empty, {**historical, 'origin': 'inactive_observation_order_unavailable_reset',
                'interruption_reason': 'inactive_observation_order_unavailable', 'wait_state_available': False,
                'focus_state_available': False, 'interrupted_since_forecast': True}
        return {**empty, 'focus_ids': observation['focus_ids']}, {
            'origin': 'cognition_disabled_observation_wait_reset' if
                observation.get('reason') == 'cognition_disabled_observation' else 'off_observation_wait_reset',
            'observation_id': observation['observation_id'],
            'observed_at': observation['observed_at'], 'frame_id': observation['frame_id'],
            'wait_state_available': False, 'focus_state_available': True, 'interrupted_since_forecast': True}
    if previous is not None:
        if 'frame_seq_cutoff' not in previous or 'off_observation_cutoff' not in previous:
            # Legacy empty off calls left neither frame nor marker. A stored
            # selection/capture timestamp cannot establish the latest state.
            return empty, {**historical, 'origin': 'legacy_unrecorded_observation_reset',
                'historical_forecast_id': previous['forecast_id'], 'wait_state_available': False,
                'focus_state_available': False, 'interrupted_since_forecast': True}
        if frame and frame['seq'] > previous['frame_seq_cutoff']:
            return empty, {**historical, 'origin': 'legacy_off_frame_unknown_focus_reset',
                'wait_state_available': False, 'focus_state_available': False, 'interrupted_since_forecast': True}
        return previous['state_after'], {'origin': 'immediately_preceding_forecast',
            'forecast_id': previous['forecast_id'], 'scope_hash': previous['scope_hash'],
            'wait_state_available': True, 'focus_state_available': True, 'interrupted_since_forecast': False}
    # Default-off history is intentionally inert; even a latest nonempty legacy
    # frame may have been followed by unrecorded empty observations.
    return empty, {**historical, 'origin': 'initial_unrecorded_focus_reset', 'wait_state_available': False,
                   'focus_state_available': False, 'interrupted_since_forecast': False}


def _content(expected, actual):
    if actual is None:
        return 'unobserved', None
    if not actual['available']:
        return 'unavailable', 0
    if expected is None:
        return 'newly_available', 0
    for key, category in (('revision', 'revision_drift'), ('input_hash', 'input_drift'),
                          ('facts_hash', 'facts_drift')):
        if expected[key] != actual['entry'][key]:
            return category, 0
    return 'fresh', 1


def prepare(c, observations, eligible, now, policy, identity_hash, configuration, entry):
    """Settle old scopes before ranking; capture only real, hash-only evidence."""
    known = {}
    for o in observations:
        if not isinstance(o.get('id'), str) or not o['id'] or o['id'] in known:
            raise ValueError('invalid_attention_source')
        known[o['id']] = {'available': bool(o.get('available')),
                          'entry': entry(o) if o.get('available') else None}
    if len(known) > 32:
        raise ValueError('attention_source_limit')
    base_scope = {'identity_hash': identity_hash, 'policy': policy,
                  'mechanism': MECHANISM, 'source_configuration': configuration}
    base_hash = digest(base_scope)
    # In observations-only usage, disappearance means missing evidence, never a
    # configuration transition. Remember earlier IDs; explicit configured usage
    # supplies the authoritative population and supports removals/reconfiguration.
    population = set(known) if configuration is None else {s['id'] for s in configuration}
    if configuration is None:
        row = c.execute('SELECT forecast FROM cognition_forecasts ORDER BY seq DESC LIMIT 1').fetchone()
        if row:
            old = json.loads(row[0])
            if old['base_scope_hash'] == base_hash:
                population.update(p['source_id'] for p in old['source_predictions'])
    if len(population) > 32:
        raise ValueError('attention_source_limit')
    scope_hash = digest({'base': base_scope, 'population': sorted(population)})
    eligible_ids = {o['id'] for o in eligible}
    eligibility = {sid: ('eligible' if sid in eligible_ids else
                        'observation_unavailable' if sid in known and not known[sid]['available'] else
                        'observation_missing' if sid not in known else 'admission_excluded')
                   for sid in population}
    prior_state, provenance = _prior_control(c, now)
    settled = []
    for row in c.execute('''SELECT f.forecast FROM cognition_forecasts f
                          LEFT JOIN cognition_forecast_outcomes o USING(forecast_id)
                          WHERE o.forecast_id IS NULL ORDER BY f.seq'''):
        f = json.loads(row[0]); matches = f['scope_hash'] == scope_hash and not provenance['interrupted_since_forecast']
        if now < f['captured_at']:
            raise ValueError('attention_clock_reversed')
        cells = []
        for prediction in f['source_predictions']:
            sid = prediction['source_id']
            content, fresh = _content(prediction['expected_entry'], known.get(sid)) if matches else ('unobserved', None)
            cells.append({'source_id': sid, 'content': content, 'fresh': fresh,
                          'observed_entry': known.get(sid, {}).get('entry') if matches else None,
                          'eligibility': eligibility.get(sid, 'outside_current_scope')})
        status = ('scope_mismatch' if not matches else 'overdue' if now >= f['expires_at'] else
                  'unobserved' if not any(p['fresh'] is not None for p in cells) else 'observed_on_time')
        settled.append({'schema': 1, 'outcome_id': uuid.uuid4().hex, 'forecast_id': f['forecast_id'],
                        'scope_hash': f['scope_hash'], 'observation_scope_hash': scope_hash,
                        'observed_at': now, 'elapsed_seconds': now-f['captured_at'], 'status': status,
                        'sources': cells, 'new_source_ids': sorted(set(known)-{p['source_id'] for p in f['source_predictions']}),
                        'expected_next_source_ids': f['expected_next_source_ids'],
                        'scope_mismatch_reason': provenance.get('interruption_reason','legacy_observation_order_unavailable') if provenance['interrupted_since_forecast'] else
                            'configuration_transition' if not matches else None})
    # Persist labels now, before training or ranking. Schedule evidence lives in
    # the next forecast, linked to these immutable outcomes, and is scored there.
    for outcome in settled:
        c.execute('INSERT INTO cognition_forecast_outcomes(forecast_id,observed_at,outcome,outcome_hash) VALUES(?,?,?,?)',
                  (outcome['forecast_id'], now, canonical(outcome), digest(outcome)))
    counts = {sid: {'fresh': 0, 'not_fresh': 0} for sid in population}
    outcome_ids = []; cutoff = 0
    rows = c.execute('''SELECT o.seq,o.outcome FROM cognition_forecast_outcomes o
                       JOIN cognition_forecasts f USING(forecast_id) WHERE f.scope_hash=?
                       ORDER BY o.seq DESC LIMIT ?''', (scope_hash, MODEL_OUTCOME_LIMIT)).fetchall()
    for row in reversed(rows):
        outcome = json.loads(row['outcome'])
        if outcome['scope_hash'] != scope_hash:
            continue
        cutoff = row['seq']; outcome_ids.append(outcome['outcome_id'])
        if outcome['status'] == 'observed_on_time':
            for cell in outcome['sources']:
                if cell['source_id'] in counts and cell['fresh'] is not None:
                    counts[cell['source_id']]['fresh' if cell['fresh'] else 'not_fresh'] += 1
    prior_state = json.loads(canonical(prior_state))
    state = json.loads(canonical(prior_state))
    state['wait_ticks'] = {sid: value for sid, value in state['wait_ticks'].items() if sid in population}
    state['last_selected_seq'] = {sid: value for sid, value in state['last_selected_seq'].items() if sid in population}
    for sid in population:
        state['wait_ticks'][sid] = state['wait_ticks'].get(sid, 0)+1 if sid in eligible_ids else 0
    probabilities = {sid: (counts[sid]['fresh']+1)/(sum(counts[sid].values())+2) for sid in population}
    if policy['attention_mode'] == 'constant':
        probabilities = {sid: policy['attention_constant_probability'] for sid in population}
    elif policy['attention_mode'] == 'permuted':
        ids = sorted(population)
        probabilities = {sid: probabilities[ids[(i-1) % len(ids)]] for i, sid in enumerate(ids)}
    capture_seq = c.execute('SELECT COALESCE(MAX(seq),0)+1 FROM cognition_forecasts').fetchone()[0]
    return {'scope_hash': scope_hash, 'base_scope_hash': base_hash, 'population': sorted(population),
            'known': known, 'eligibility': eligibility, 'counts': counts, 'probabilities': probabilities,
            'prior_state': prior_state, 'rank_state': json.loads(canonical(state)), 'state': state,
            'focus_state_provenance': provenance,
            'prior_outcome_ids': outcome_ids,
            'prior_outcome_cutoff': cutoff, 'capture_seq': capture_seq, 'settled': settled}


def rank(eligible, capture, policy):
    state = capture['state']; threshold = policy['attention_max_wait']
    def key(o):
        sid = o['id']; wait = state['wait_ticks'][sid]
        score = capture['probabilities'][sid]-policy['attention_switch_penalty']*(sid not in state['focus_ids'])
        return (0, -wait, state['last_selected_seq'].get(sid, 0), sid) if wait >= threshold else (
            1, -score, state['last_selected_seq'].get(sid, 0), sid)
    return sorted(eligible, key=key)


def finish(c, capture, selected_ids, frame_id, now, policy):
    state = capture['state']
    for sid in selected_ids:
        state['wait_ticks'][sid] = 0; state['last_selected_seq'][sid] = capture['capture_seq']
    state['focus_ids'] = selected_ids
    schedule = [{'outcome_id': o['outcome_id'], 'actual_selected_ids': selected_ids,
                 'exact_set_hit': set(o['expected_next_source_ids']) == set(selected_ids)}
                for o in capture['settled'] if o['scope_hash'] == capture['scope_hash']]
    model = {'counts': capture['counts'], 'probabilities': capture['probabilities'],
             'prior_outcome_cutoff': capture['prior_outcome_cutoff'], 'mechanism': MECHANISM}
    f = {'schema': 1, 'forecast_id': uuid.uuid4().hex, 'origin_frame_id': frame_id,
         'capture_seq': capture['capture_seq'], 'captured_at': now, 'expires_at': now+policy['ttl_seconds'],
         'scope_hash': capture['scope_hash'], 'base_scope_hash': capture['base_scope_hash'],
         'policy_hash': digest(policy), 'mechanism_hash': digest(MECHANISM), 'model_hash': digest(model),
         'model': model, 'target': MECHANISM['target'], 'origin': 'prior_settled_observations',
         'prior_outcome_ids': capture['prior_outcome_ids'], 'prior_outcome_cutoff': capture['prior_outcome_cutoff'],
         'focus_state': capture['prior_state'], 'focus_state_hash': digest(capture['prior_state']),
         'focus_state_provenance': capture['focus_state_provenance'],
         'frame_seq_cutoff': c.execute('SELECT COALESCE(MAX(seq),0) FROM cognition_frames').fetchone()[0]+int(frame_id is not None),
         'off_observation_cutoff': c.execute('SELECT COALESCE(MAX(seq),0) FROM cognition_attention_off_observations').fetchone()[0],
         'rank_state': capture['rank_state'],
         'state_after': state, 'expected_next_source_ids': selected_ids,
         'prior_schedule_outcomes': schedule,
         'source_predictions': [{'source_id': sid, 'expected_entry': capture['known'].get(sid, {}).get('entry'),
                                 'observed_available': capture['known'].get(sid, {}).get('available'),
                                 'probability_fresh': capture['probabilities'][sid],
                                 'eligibility': capture['eligibility'][sid]} for sid in capture['population']],
         'limitations': dict(MECHANISM)}
    c.execute('INSERT INTO cognition_forecasts(forecast_id,origin_frame_id,scope_hash,forecast,forecast_hash) VALUES(?,?,?,?,?)',
              (f['forecast_id'], frame_id, f['scope_hash'], canonical(f), digest(f)))
    return f


def summary(c, now=None):
    """Read-only partitions: forecast events and forecast source cells differ."""
    if now is None:
        now = time.time()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('invalid_attention_time')
    for table in ('cognition_forecasts', 'cognition_forecast_outcomes'):
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
            return {'visibility': 'unavailable', 'reason': 'journal_unavailable'}
    events = dict.fromkeys(EVENTS, 0); content = dict.fromkeys(CONTENT, 0)
    excluded = dict.fromkeys(('pending', 'overdue', 'unobserved', 'scope_mismatch'), 0)
    scored = 0; error = 0.0; allocated = 0; cells = 0; schedule_hits = 0; schedules = 0
    per_source = {}
    for row in c.execute('''SELECT f.forecast,o.outcome FROM cognition_forecasts f
                          LEFT JOIN cognition_forecast_outcomes o USING(forecast_id) ORDER BY f.seq'''):
        f = json.loads(row['forecast']); o = json.loads(row['outcome']) if row['outcome'] else None
        status = o['status'] if o else 'overdue' if now >= f['expires_at'] else 'pending'
        allocated += 1; events[status] += 1
        actual = {p['source_id']: p for p in o['sources']} if o else {}
        for prediction in f['source_predictions']:
            cells += 1; cell = actual.get(prediction['source_id'])
            category = cell['content'] if cell else 'pending'
            content[category] += 1
            source = per_source.setdefault(prediction['source_id'], {'n_allocated': 0, 'n_scored': 0,
                'n_excluded': 0, 'squared_error_sum': 0.0, 'content': dict.fromkeys(CONTENT, 0)})
            source['n_allocated'] += 1; source['content'][category] += 1
            if status == 'observed_on_time' and cell['fresh'] is not None:
                squared_error = (prediction['probability_fresh']-cell['fresh'])**2
                scored += 1; error += squared_error
                source['n_scored'] += 1; source['squared_error_sum'] += squared_error
            else:
                excluded[status if status != 'observed_on_time' else 'unobserved'] += 1
                source['n_excluded'] += 1
        for schedule in f['prior_schedule_outcomes']:
            schedules += 1; schedule_hits += int(schedule['exact_set_hit'])
    for source in per_source.values():
        source['brier'] = source['squared_error_sum']/source['n_scored'] if source['n_scored'] else None
    return {'schema': 1, 'visibility': 'available', 'n_allocated': allocated, 'events': events,
            'n_source_cells': cells, 'source_content': content, 'n_scored': scored,
            'per_source': per_source,
            'n_excluded': cells-scored, 'excluded': excluded, 'brier': error/scored if scored else None,
            'schedule': {'n_observed': schedules, 'n_exact_set_hits': schedule_hits,
                         'exact_set_hit_rate': schedule_hits/schedules if schedules else None},
            'limitations': dict(MECHANISM)}
