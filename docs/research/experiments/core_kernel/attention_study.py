"""Frozen provider-free Controller panel. Run with --output outside the checkout.

The training population/focus checkpoint is matched, while mode-specific hashes
and forecast UUIDs retain honest provenance. Evaluation learning continues in
every arm. This harness tests context routing, not business task performance.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from autonomy import Controller
from autonomy_checks import Verifier, observe_sources, validate_config
from autonomy_store import Ledger, canonical, digest
from helpers import policy_config
from self_model import SelfModel


class NoProvider:
    def __init__(self):
        self.calls = 0

    def submit(self, submission):
        self.calls += 1
        raise AssertionError('provider calls forbidden by frozen attention protocol')


def run_arm(root, mode, seed, protocol):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    ledger_path = root/(mode+'.db')
    if ledger_path.exists():
        raise ValueError('study arm requires a fresh ledger')
    raw = policy_config(root); template = raw['sources'][0]; raw['sources'] = []
    for i in range(5):
        source = copy.deepcopy(template)
        source.update(id=f'source-{i}', path=str(root/f'facts-{i}.json'))
        source['contracts']['result']['path'] = str(root/f'result-{i}.txt')
        raw['sources'].append(source)
    raw['max_candidates'] = 1
    raw['cognition'] = {k: protocol[k] for k in ('capacity', 'ttl_seconds', 'attention_max_wait',
                                               'attention_switch_penalty', 'attention_constant_probability')}
    raw['cognition'].update(enabled=True, attention_mode=mode)
    ledger = Ledger(ledger_path); boundary = NoProvider(); clock = [1000.0]
    delivered = []; waits = []; accepted = 0; checkpoint = None; drift_failures = 0
    policy = validate_config(raw, root)
    def plan(observations, context, policy):
        delivered.append({'time': clock[0], 'source_ids': [o['id'] for o in observations],
                          'frame_id': context['workspace']['frame_id']})
        return []
    def controller():
        return Controller(ledger, policy, SimpleNamespace(plan=plan), boundary,
                          Verifier(policy), SelfModel(ledger, root), clock=lambda: clock[0])
    c = controller(); versions = dict.fromkeys(range(6), 0)
    warmup = protocol['warmup_ticks']; total = warmup+protocol['evaluation_ticks']
    heldout_deliveries = []; learned_checkpoint = None
    for tick in range(total):
        offset = tick-warmup
        if offset == 10:
            source = copy.deepcopy(template)
            source.update(id='source-5', path=str(root/'facts-5.json'))
            source['contracts']['result']['path'] = str(root/'result-5.txt')
            raw['sources'].append(source); policy = validate_config(raw, root); c = controller()
        if offset == 7:
            ledger = Ledger(ledger_path); c = controller()
        clock[0] += protocol['ttl_seconds']+1 if offset == 8 else 1
        for i, source in enumerate(policy['sources']):
            if i and (tick+seed+i) % 3:
                versions[i] += 1
            path = Path(source['path'])
            if i == 4 and offset in (2, 3):
                path.unlink(missing_ok=True)
            else:
                path.write_text(canonical({'report': f'independent-{seed}-{i}-{versions[i]}'}))
        observations = observe_sources(policy)
        for o in observations:
            if o['available']:
                ledger.mark_source(o['id'], o['revision'], {}, clock[0])
                excluded = tick < warmup and o['id'] != 'source-0' or offset == 3 and o['id'] == 'source-0' or offset == 5
                if excluded:
                    ledger.claim_source(o['id'], o['revision'], 'protocol-exclusion', clock[0], 100, 3)
        before = len(delivered)
        if offset == 6:
            def disturbed_refresh(current_policy):
                Path(current_policy['sources'][0]['path']).write_text(canonical({'report': 'fixed-refresh-disturbance'}))
                return observe_sources(current_policy)
            # Filesystem perturbation at the declared observation boundary;
            # the production refresh, frame validation and failure path run.
            with patch('autonomy.observe_sources', side_effect=disturbed_refresh):
                accepted += c._synthesize(observations)
        else:
            accepted += c._synthesize(observations)
        with ledger._connection() as db:
            row = db.execute('SELECT seq,forecast FROM cognition_forecasts ORDER BY seq DESC LIMIT 1').fetchone()
        f = json.loads(row['forecast']); waits.append(max(f['rank_state']['wait_ticks'].values(), default=0))
        if offset == 6 and len(delivered) == before and 'source-0' in f['expected_next_source_ids']:
            drift_failures += 1
        if tick == warmup-1:
            checkpoint = row['seq']
            learned_checkpoint = {'counts': f['model']['counts'], 'state': f['state_after']}
        if tick >= warmup:
            heldout_deliveries.extend(delivered[before:])
    with ledger._connection() as db:
        receipts = [json.loads(r[0]) for r in db.execute('SELECT receipt FROM cognition_receipts')]
        rows = db.execute('''SELECT f.seq,f.forecast,o.outcome FROM cognition_forecasts f
                            LEFT JOIN cognition_forecast_outcomes o USING(forecast_id) ORDER BY f.seq''').fetchall()
    held_scored = 0; held_excluded = 0; held_error = 0.0; selected_fresh = 0; selected_scored = 0
    for row in rows:
        f = json.loads(row['forecast']); o = json.loads(row['outcome']) if row['outcome'] else None
        if row['seq'] <= checkpoint:
            continue
        actual = {p['source_id']: p for p in o['sources']} if o else {}
        for prediction in f['source_predictions']:
            cell = actual.get(prediction['source_id'])
            if o and o['status'] == 'observed_on_time' and cell['fresh'] is not None:
                held_scored += 1; held_error += (prediction['probability_fresh']-cell['fresh'])**2
                if cell['source_id'] in f['expected_next_source_ids']:
                    selected_scored += 1; selected_fresh += cell['fresh']
            else:
                held_excluded += 1
    return {'mode': mode, 'sequence': seed, 'checkpoint_signature': digest(learned_checkpoint),
            'checkpoint': learned_checkpoint, 'evaluation_learning': protocol['evaluation_learning'],
            'attention': c.workspace.summary(now=clock[0])['attention'],
            'held_out': {'n_scored': held_scored, 'n_excluded': held_excluded,
                         'brier': held_error/held_scored if held_scored else None,
                         'selected_fresh': selected_fresh, 'selected_scored': selected_scored},
            'planner_method_receipts': sum(r['channel'] == 'planner_method' for r in receipts),
            'actual_deliveries': len(delivered), 'held_out_deliveries': heldout_deliveries,
            'coverage': sorted({sid for d in heldout_deliveries for sid in d['source_ids']}),
            'maximum_eligible_wait_ticks': max(waits), 'accepted_goals': accepted,
            'selected_frame_delivery_failures': sum(json.loads(r['forecast'])['origin_frame_id'] is not None for r in rows)-len(delivered),
            'drift_delivery_failures': drift_failures,
            'provider_calls': boundary.calls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(Path(__file__).with_name('attention_protocol.json').read_text())
    results = []
    with tempfile.TemporaryDirectory(prefix='attention-study-') as temporary:
        for seed in protocol['sequences']:
            paired = [run_arm(Path(temporary)/str(seed), mode, seed, protocol) for mode in protocol['arms']]
            assert len({r['checkpoint_signature'] for r in paired}) == 1, 'unmatched training checkpoint'
            assert all(r['provider_calls'] == 0 for r in paired)
            results.extend(paired)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'protocol': protocol, 'protocol_hash': digest(protocol), 'arms': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
