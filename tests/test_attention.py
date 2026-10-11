"""Prospective attention at real Workspace and Controller boundaries (no provider)."""
import copy
import importlib
import json
import math
import sqlite3
import unittest
from pathlib import Path

import test_cognition as fixtures
from autonomy_checks import observe_sources
from autonomy_store import Ledger, canonical, digest


class AttentionTests(unittest.TestCase):
    setUp = fixtures.CognitionTests.setUp
    controller = fixtures.CognitionTests.controller

    def policy(self, **changes):
        return fixtures.CognitionTests.policy(self, attention_mode='adaptive', **changes)

    def workspace(self, policy):
        import cognition
        return cognition.Workspace(self.ledger, policy, {'identity': 'test'})

    def rows(self, table):
        with self.ledger._connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY seq')]

    def forecasts(self):
        return [json.loads(r['forecast']) for r in self.rows('cognition_forecasts')]

    def outcomes(self):
        return [json.loads(r['outcome']) for r in self.rows('cognition_forecast_outcomes')]

    def test_module_and_strict_settings(self):
        self.assertIsNotNone(importlib.util.find_spec('attention'), 'attention kernel missing')
        import cognition
        self.assertEqual(cognition.validate_cognition(None)['attention_mode'], 'off')
        for key, values in {'attention_mode': ['bad', {}, True],
                            'attention_constant_probability': [True, -1, 2, math.nan, math.inf],
                            'attention_max_wait': [True, 0, 1025, 1.5],
                            'attention_switch_penalty': [True, -1, 2, math.nan]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    cognition.validate_cognition({key: value})

    def test_legacy_full_controller_policy_without_cognition_is_off(self):
        from autonomy_checks import validate_config
        policy=validate_config(self.raw,self.root); policy.pop('cognition')
        c=self.controller(policy)
        self.assertFalse(c.workspace.policy['enabled'])
        self.assertEqual(c.workspace.policy['attention_mode'],'off')
        c._synthesize(observe_sources(policy))
        self.assertEqual(len(self.calls[0][0]),1)
        self.assertEqual(self.forecasts(),[])

    def test_forecast_all_configured_sources_and_no_future_leakage(self):
        policy=self.policy(capacity=1); w=self.workspace(policy); obs=observe_sources(policy)
        first=w.select(obs,self.now); f=self.forecasts()[0]
        self.assertEqual(len(f['source_predictions']),5)
        self.assertEqual(f['prior_outcome_ids'],[])
        self.assertEqual(f['prior_outcome_cutoff'],0)
        self.assertEqual(f['focus_state']['focus_ids'],[])
        self.assertNotIn('PRIVATE_FACT',canonical(f))
        self.assertTrue(all(p['probability_fresh']==0.5 for p in f['source_predictions']))
        changed=copy.deepcopy(obs); changed[-1]['facts']='later-disturbance'
        w.select(changed,self.now+1)
        self.assertEqual(f,self.forecasts()[0])
        o=self.outcomes()[0]
        self.assertEqual(o['status'],'observed_on_time')
        self.assertEqual(o['sources'][-1]['content'],'facts_drift')
        next_f=self.forecasts()[1]
        self.assertEqual(next_f['prior_outcome_ids'],[o['outcome_id']])
        self.assertEqual(next_f['prior_outcome_cutoff'],self.rows('cognition_forecast_outcomes')[0]['seq'])
        self.assertEqual(next_f['focus_state']['focus_ids'],[first['entries'][0]['source_id']])
        report=w.summary(now=self.now+1)['attention']
        self.assertEqual(report['per_source']['source-4']['n_scored'],1)
        self.assertEqual(report['per_source']['source-4']['n_excluded'],1)
        self.assertEqual(report['per_source']['source-4']['brier'],0.25)
        self.assertEqual(report['per_source']['source-4']['content']['facts_drift'],1)

    def test_actual_controller_sees_unavailable_and_processed_exclusion_separately(self):
        policy=self.policy(capacity=1); c=self.controller(policy); obs=observe_sources(policy)
        c._synthesize(obs)
        Path(policy['sources'][-1]['path']).unlink()
        self.now+=1; c._synthesize(observe_sources(policy))
        o=self.outcomes()[0]
        cells={p['source_id']:p for p in o['sources']}
        self.assertEqual(cells['source-4']['content'],'unavailable')
        self.assertEqual(cells['source-4']['fresh'],0)
        self.assertEqual(cells['source-0']['content'],'fresh')
        self.assertNotEqual(cells['source-0']['eligibility'],'eligible')
        receipts=[]
        with self.ledger._connection() as db:
            receipts=[json.loads(r[0]) for r in db.execute('SELECT receipt FROM cognition_receipts')]
        self.assertEqual(sum(r['channel']=='planner_method' for r in receipts),2)

    def test_empty_eligibility_still_settles_allocates_and_missing_evidence_unknown(self):
        policy=self.policy(); w=self.workspace(policy); obs=observe_sources(policy)
        w.select(obs,self.now)
        for o in obs:self.ledger.mark_source(o['id'],o['revision'],{'status':'processed'},self.now)
        self.assertIsNone(w.select(obs,self.now+1,source_owner='planner'))
        self.assertEqual(len(self.forecasts()),2)
        self.assertEqual(len(self.outcomes()),1)
        self.assertTrue(all(p['content']=='fresh' for p in self.outcomes()[0]['sources']))
        self.assertIsNone(w.select([],self.now+2))
        self.assertEqual(self.outcomes()[-1]['status'],'unobserved')
        self.assertTrue(all(p['fresh'] is None for p in self.outcomes()[-1]['sources']))
        self.assertEqual(len(self.forecasts()[-1]['source_predictions']),5)

    def test_rank_state_is_before_actual_counter_reset_and_restart_no_duplicate_training(self):
        policy=self.policy(capacity=1); w=self.workspace(policy); obs=observe_sources(policy)
        frame=w.select(obs,self.now)
        forecast=self.forecasts()[0]; sid=frame['entries'][0]['source_id']
        self.assertEqual(forecast['rank_state']['wait_ticks'][sid],1)
        self.assertEqual(forecast['state_after']['wait_ticks'][sid],0)
        w=self.workspace(policy); w.select(obs,self.now+1)
        self.assertEqual(len(self.outcomes()),1)
        w=self.workspace(policy); w.select(obs,self.now+2)
        self.assertEqual(len(self.outcomes()),2)
        self.assertEqual(self.forecasts()[-1]['model']['counts'][sid],{'fresh':2,'not_fresh':0})

    def test_backward_clock_is_rejected_without_settlement_or_new_prediction(self):
        policy=self.policy(); w=self.workspace(policy); obs=observe_sources(policy)
        w.select(obs,self.now)
        with self.assertRaisesRegex(ValueError,'attention_clock_reversed'):w.select(obs,self.now-1)
        self.assertEqual(len(self.outcomes()),0)
        self.assertEqual(len(self.forecasts()),1)

    def test_revision_input_and_facts_drift_are_independent_categories(self):
        policy=self.policy(); w=self.workspace(policy); obs=observe_sources(policy)
        w.select(obs,self.now)
        changed=copy.deepcopy(obs); changed[0]['revision']='revision-drift'
        changed[1]['facts']='facts-drift'
        # Input hash may be absent on ordinary source observations; use a real validated projection.
        from task_inputs import project
        source={**policy['sources'][2],'input_fields':['report'],'persist_input_fields':['report']}
        for observations,data in ((obs,{'report':'a'}),(changed,{'report':'b'})):
            observations[2]['task_input']={**project(source,data),'source_revision':observations[2]['revision']}
        self.ledger=Ledger(self.root/'input.db'); w=self.workspace(policy); w.select(obs,self.now)
        w.select(changed,self.now+1)
        self.assertEqual([p['content'] for p in self.outcomes()[0]['sources']],
                         ['revision_drift','facts_drift','input_drift','fresh','fresh'])

    def test_overdue_summary_partition_restart_and_scope_transition(self):
        policy=self.policy(ttl_seconds=2); w=self.workspace(policy); obs=observe_sources(policy)
        w.select(obs,self.now)
        with self.ledger._connection() as db:before=tuple(db.iterdump())
        summary=w.summary(now=self.now+3)['attention']
        self.assertEqual(summary['events']['overdue'],1)
        self.assertEqual(summary['n_scored'],0)
        with self.ledger._connection() as db:self.assertEqual(tuple(db.iterdump()),before)
        w=self.workspace(policy); w.select(obs,self.now+3)
        self.assertEqual(self.outcomes()[0]['status'],'overdue')
        w=self.workspace(self.policy(ttl_seconds=2,attention_switch_penalty=0.25))
        w.select(obs,self.now+4)
        self.assertEqual(self.outcomes()[1]['status'],'scope_mismatch')
        summary=w.summary(now=self.now+4)['attention']
        self.assertEqual(sum(summary['events'].values()),summary['n_allocated'])
        self.assertEqual(sum(summary['source_content'].values()),summary['n_source_cells'])
        self.assertEqual(summary['n_scored']+summary['n_excluded'],summary['n_source_cells'])
        self.assertEqual(len(self.outcomes()),2)

    def test_disappearing_observation_does_not_change_configured_scope(self):
        policy=self.policy(); w=self.workspace(policy); obs=observe_sources(policy)
        w.select(obs,self.now); w.select(obs[:-1],self.now+1)
        self.assertEqual(self.forecasts()[0]['scope_hash'],self.forecasts()[1]['scope_hash'])
        self.assertEqual(self.outcomes()[0]['sources'][-1]['content'],'unobserved')
        self.assertIsNone(self.outcomes()[0]['sources'][-1]['fresh'])
        changed=copy.deepcopy(policy); changed['sources']=changed['sources'][:-1]
        self.workspace(changed).select(obs[:-1],self.now+2)
        self.assertEqual(self.outcomes()[-1]['status'],'scope_mismatch')

    def test_immutable_collision_update_delete_and_missing_journal(self):
        policy=self.policy(); w=self.workspace(policy); obs=observe_sources(policy)
        w.select(obs,self.now); w.select(obs,self.now+1)
        with self.ledger._connection(True) as db:
            for table in ('cognition_forecasts','cognition_forecast_outcomes'):
                row=db.execute('SELECT * FROM '+table+' LIMIT 1').fetchone()
                for statement,args in ((f'INSERT OR REPLACE INTO {table} VALUES('+','.join('?' for _ in row)+')',tuple(row)),
                                       (f'UPDATE {table} SET seq=seq',()),(f'DELETE FROM {table}',())):
                    with self.assertRaises(sqlite3.IntegrityError):db.execute(statement,args)
            db.execute('DROP TABLE cognition_forecast_outcomes')
        self.assertEqual(w.summary(now=self.now+1)['attention']['visibility'],'unavailable')

    def test_discriminating_modes_switch_penalty_and_capacity_fairness(self):
        selections={}
        for mode in ('adaptive','constant','permuted'):
            self.ledger=Ledger(self.root/(mode+'.db'))
            policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode=mode,attention_max_wait=100)
            w=self.workspace(policy); obs=observe_sources(policy)
            for tick in range(6):
                for i in range(1,5):obs[i]['revision']=str(tick)+'-'+str(i)
                w.select(obs,self.now+tick)
            selections[mode]=w.select(obs,self.now+7)['entries'][0]['source_id']
        self.assertEqual(selections['adaptive'],'source-0')
        self.assertNotEqual(selections['constant'],selections['adaptive'])
        self.assertNotEqual(selections['permuted'],selections['adaptive'])
        for capacity in (1,2,3,5):
            for mode in ('adaptive','constant','permuted'):
                self.ledger=Ledger(self.root/f'fair-{capacity}-{mode}.db')
                policy=fixtures.CognitionTests.policy(self,capacity=capacity,attention_mode=mode,
                                            attention_max_wait=2,attention_switch_penalty=1)
                w=self.workspace(policy); obs=observe_sources(policy); last={o['id']:0 for o in obs}
                bound=2+math.ceil(5/capacity)-1
                for tick in range(1,35):
                    if tick==10:w=self.workspace(policy)
                    frame=w.select(obs,self.now+tick)
                    for e in frame['entries']:last[e['source_id']]=tick
                    self.assertTrue(all(tick-t<=bound for t in last.values()),(capacity,mode,tick,last))

    def test_switch_penalty_changes_actual_focus_with_matched_constant_probability(self):
        choices=[]
        for penalty in (0,1):
            self.ledger=Ledger(self.root/f'switch-{penalty}.db')
            policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                                 attention_max_wait=100,attention_switch_penalty=penalty)
            w=self.workspace(policy); obs=observe_sources(policy)
            w.select(obs,self.now)
            choices.append(w.select(obs,self.now+1)['entries'][0]['source_id'])
        self.assertEqual(choices,['source-1','source-0'])

    def test_model_window_is_bounded_but_summary_keeps_all_allocations(self):
        policy=self.policy(capacity=1); w=self.workspace(policy); obs=observe_sources(policy)
        for tick in range(133):w.select(obs,self.now+tick)
        f=self.forecasts()[-1]
        self.assertEqual(len(f['prior_outcome_ids']),128)
        self.assertEqual(f['model']['counts']['source-0'],{'fresh':128,'not_fresh':0})
        s=w.summary(now=self.now+133)['attention']
        self.assertEqual(s['n_allocated'],133)
        self.assertEqual(s['n_scored'],132*5)

    def test_frozen_protocol_and_actual_controller_study_smoke(self):
        folder=Path(__file__).resolve().parents[1]/'docs/research/experiments/core_kernel'
        path=folder/'attention_protocol.json'
        self.assertTrue(path.exists(),'frozen provider-free attention protocol missing')
        protocol=json.loads(path.read_text())
        self.assertEqual(protocol['evaluation_learning'],'continues_identically_in_all_arms')
        spec=importlib.util.spec_from_file_location('attention_study',folder/'attention_study.py')
        study=importlib.util.module_from_spec(spec); spec.loader.exec_module(study)
        result=study.run_arm(self.root/'study','adaptive',protocol['sequences'][0],protocol)
        self.assertEqual(result['provider_calls'],0)
        self.assertGreater(result['planner_method_receipts'],0)
        self.assertEqual(sum(result['attention']['events'].values()),result['attention']['n_allocated'])
        self.assertEqual(result['actual_deliveries'],result['planner_method_receipts'])
        self.assertEqual(result['attention']['events']['scope_mismatch'],1)
        self.assertGreaterEqual(result['attention']['events']['overdue'],1)


if __name__=='__main__':unittest.main()
