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

    def test_disabled_controller_observation_excludes_changed_then_restored_future(self):
        policy=self.policy(capacity=1); self.controller(policy)._synthesize(observe_sources(policy))
        original_forecast=copy.deepcopy(self.forecasts()[0])
        path=Path(policy['sources'][0]['path']); original=path.read_bytes()
        disabled=copy.deepcopy(policy); disabled['cognition']['enabled']=False
        self.now+=1; path.write_text(canonical({'report':'INTERVENING_PRIVATE_FACT'}))
        self.controller(disabled)._synthesize(observe_sources(disabled))
        self.assertEqual(len(self.outcomes()),1)
        outcome=self.outcomes()[0]
        self.assertEqual(outcome['observed_at'],self.now)
        self.assertEqual(outcome['status'],'scope_mismatch')
        self.assertEqual(outcome['scope_mismatch_reason'],'cognition_disabled_observation')
        self.assertEqual(len(outcome['sources']),5)
        self.assertTrue(all(cell['fresh'] is None and cell['observed_entry'] is None for cell in outcome['sources']))
        path.write_bytes(original); self.now+=1
        self.ledger=Ledger(self.ledger.path)
        self.controller(policy)._synthesize(observe_sources(policy))
        self.assertEqual(self.forecasts()[0],original_forecast)
        self.assertEqual(len(self.outcomes()),1)
        self.assertTrue(all(count=={'fresh':0,'not_fresh':0} for count in self.forecasts()[-1]['model']['counts'].values()))
        self.assertEqual(self.workspace(policy).summary(now=self.now)['attention']['n_scored'],0)
        self.assertNotIn('INTERVENING_PRIVATE_FACT',canonical(self.rows('cognition_attention_off_observations')))

    def test_disabled_controller_resumption_uses_actual_legacy_focus_beyond_workspace_capacity(self):
        self.raw['max_candidates']=2
        policy=self.policy(capacity=1,attention_switch_penalty=1)
        self.controller(policy)._synthesize(observe_sources(policy))
        disabled=copy.deepcopy(policy); disabled['cognition']['enabled']=False
        self.now+=1; self.controller(disabled)._synthesize(observe_sources(disabled))
        actual_ids=[o['id'] for o in self.calls[-1][0]]
        self.assertEqual(actual_ids,['source-1','source-2'])
        self.ledger=Ledger(self.ledger.path); self.now+=1
        self.controller(policy)._synthesize(observe_sources(policy))
        resumed=self.forecasts()[-1]
        self.assertEqual(resumed['focus_state']['focus_ids'],actual_ids)
        self.assertEqual(resumed['focus_state']['wait_ticks'],{})
        self.assertEqual(resumed['focus_state']['last_selected_seq'],{})
        self.assertEqual(resumed['focus_state_provenance']['origin'],'cognition_disabled_observation_wait_reset')
        self.assertTrue(resumed['focus_state_provenance']['focus_state_available'])
        self.assertFalse(resumed['focus_state_provenance']['wait_state_available'])
        self.assertTrue(resumed['focus_state_provenance']['interrupted_since_forecast'])

    def test_removed_cognition_configuration_records_empty_actual_selection_across_restart(self):
        policy=self.policy(capacity=1); observations=observe_sources(policy)
        self.controller(policy)._synthesize(observations)
        for o in observations:self.ledger.mark_source(o['id'],o['revision'],{'status':'processed'},self.now)
        disabled=copy.deepcopy(policy); disabled.pop('cognition')
        calls_before=len(self.calls); self.now+=1
        self.controller(disabled)._synthesize(observe_sources(disabled))
        self.assertEqual(len(self.calls),calls_before)
        self.assertEqual(len(self.outcomes()),1)
        self.assertEqual(self.outcomes()[0]['scope_mismatch_reason'],'cognition_disabled_observation')
        marker=json.loads(self.rows('cognition_attention_off_observations')[-1]['observation'])
        self.assertEqual(marker['focus_ids'],[])
        self.ledger=Ledger(self.ledger.path)
        self.controller(policy)._synthesize(observe_sources(policy))
        resumed=self.forecasts()[-1]
        self.assertEqual(resumed['focus_state'],{'focus_ids':[],'wait_ticks':{},'last_selected_seq':{}})
        self.assertEqual(resumed['focus_state_provenance']['observed_at'],self.now)
        self.assertEqual(resumed['focus_state_provenance']['origin'],'cognition_disabled_observation_wait_reset')

    def test_disabled_without_attention_history_keeps_forecast_and_inactive_journals_inert(self):
        from autonomy_checks import validate_config
        disabled=validate_config(self.raw,self.root)
        self.controller(disabled)._synthesize(observe_sources(disabled))
        self.assertEqual([o['id'] for o in self.calls[-1][0]],['source-0'])
        self.assertIsNone(self.workspace(disabled).select(observe_sources(disabled),self.now))
        for table in ('cognition_forecasts','cognition_forecast_outcomes','cognition_attention_off_observations','cognition_frames'):
            self.assertEqual(self.rows(table),[])

    def test_direct_disabled_workspace_observation_records_no_invented_selection(self):
        policy=self.policy(capacity=1); observations=observe_sources(policy)
        self.workspace(policy).select(observations,self.now)
        disabled=copy.deepcopy(policy); disabled['cognition']['enabled']=False
        self.assertIsNone(self.workspace(disabled).select(observations,self.now))
        self.assertEqual(len(self.forecasts()),1)
        self.assertEqual(len(self.outcomes()),1)
        self.assertEqual(self.outcomes()[0]['scope_mismatch_reason'],'cognition_disabled_observation')
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(observations,self.now)['attention']
        self.assertEqual(resumed['focus_state']['focus_ids'],[])
        self.assertEqual(resumed['focus_state']['wait_ticks'],{})
        self.assertEqual(resumed['focus_state_provenance']['origin'],'cognition_disabled_observation_wait_reset')

    def test_missing_disabled_observation_journal_preserves_planning_but_excludes_resumed_training(self):
        policy=self.policy(capacity=1); self.controller(policy)._synthesize(observe_sources(policy))
        disabled=copy.deepcopy(policy); disabled['cognition']['enabled']=False
        with self.ledger._connection(True) as db:db.execute('DROP TABLE cognition_attention_off_observations')
        self.now+=1; self.controller(disabled)._synthesize(observe_sources(disabled))
        self.assertEqual([o['id'] for o in self.calls[-1][0]],['source-1'])
        self.ledger=Ledger(self.ledger.path); self.now+=1
        self.controller(policy)._synthesize(observe_sources(policy))
        resumed=self.forecasts()[-1]
        self.assertFalse(resumed['focus_state_provenance']['focus_state_available'])
        self.assertFalse(resumed['focus_state_provenance']['wait_state_available'])
        self.assertTrue(resumed['focus_state_provenance']['interrupted_since_forecast'])
        self.assertEqual(resumed['focus_state'],{'focus_ids':[],'wait_ticks':{},'last_selected_seq':{}})
        self.assertEqual(self.outcomes()[0]['status'],'scope_mismatch')
        self.assertEqual(self.outcomes()[0]['scope_mismatch_reason'],'cognition_disabled_observation_journal_unavailable')
        self.assertEqual(self.workspace(policy).summary(now=self.now)['attention']['n_scored'],0)
        self.assertNotIn('PRIVATE_FACT',canonical(self.rows('cognition_frames')))

    def test_failed_empty_disabled_marker_does_not_restore_an_older_inactive_focus(self):
        policy=self.policy(capacity=1); self.controller(policy)._synthesize(observe_sources(policy))
        disabled=copy.deepcopy(policy); disabled['cognition']['enabled']=False
        self.now+=1; self.controller(disabled)._synthesize(observe_sources(disabled))
        self.assertEqual([o['id'] for o in self.calls[-1][0]],['source-1'])
        with self.ledger._connection(True) as db:
            db.execute("CREATE TRIGGER reject_inactive_marker BEFORE INSERT ON cognition_attention_off_observations BEGIN SELECT RAISE(ABORT,'journal_unavailable'); END")
        self.now+=1; self.controller(disabled)._synthesize([])
        self.ledger=Ledger(self.ledger.path)
        with self.ledger._connection(True) as db:db.execute('DROP TRIGGER reject_inactive_marker')
        self.now+=1; self.controller(policy)._synthesize(observe_sources(policy))
        resumed=self.forecasts()[-1]
        self.assertEqual(resumed['focus_state']['focus_ids'],[])
        self.assertEqual(resumed['focus_state']['wait_ticks'],{})
        self.assertFalse(resumed['focus_state_provenance']['focus_state_available'])
        self.assertTrue(resumed['focus_state_provenance']['interrupted_since_forecast'])
        self.assertEqual(self.workspace(policy).summary(now=self.now)['attention']['n_scored'],0)

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

    def test_returned_scope_uses_immediately_preceding_focus_wait_and_prior_scoped_counts(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                             attention_max_wait=100,attention_switch_penalty=1)
        obs=observe_sources(policy); a=self.workspace(policy)
        first=a.select(obs,self.now); a.select(obs,self.now+1)
        bpolicy=copy.deepcopy(policy); bpolicy['cognition']['attention_switch_penalty']=0
        b=self.workspace(bpolicy); excluded=copy.deepcopy(obs); excluded[0]['available']=False
        b.select(excluded,self.now+2); previous=b.select(excluded,self.now+3)
        self.assertEqual(previous['attention']['state_after']['focus_ids'],['source-2'])
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+4)
        f=resumed['attention']
        self.assertEqual(f['scope_hash'],first['attention']['scope_hash'])
        self.assertEqual(f['focus_state'],previous['attention']['state_after'])
        self.assertEqual([e['source_id'] for e in resumed['entries']],['source-2'])
        self.assertEqual(f['focus_state_provenance']['forecast_id'],previous['attention']['forecast_id'])
        self.assertEqual(f['model']['counts']['source-0'],{'fresh':1,'not_fresh':0})
        self.assertEqual(len(f['prior_outcome_ids']),2)  # A's fresh and intervening scope-mismatch settlements.

    def test_return_after_off_uses_real_off_frame_focus_and_resets_unknown_wait_history(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                             attention_max_wait=100,attention_switch_penalty=1)
        obs=observe_sources(policy); a=self.workspace(policy)
        a.select(obs,self.now); a.select(obs,self.now+1)
        offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        off=self.workspace(offpolicy).select(obs,self.now+2)
        self.assertEqual([e['source_id'] for e in off['entries']],['source-1'])
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+3); f=resumed['attention']
        self.assertEqual(f['focus_state']['focus_ids'],['source-1'])
        self.assertEqual(f['focus_state']['wait_ticks'],{})
        self.assertEqual(f['focus_state_provenance']['origin'],'off_observation_wait_reset')
        self.assertEqual(f['focus_state_provenance']['frame_id'],off['frame_id'])
        self.assertEqual([e['source_id'] for e in resumed['entries']],['source-1'])
        self.assertEqual(f['model']['counts']['source-0'],{'fresh':1,'not_fresh':0})
        self.assertEqual(self.outcomes()[-1]['status'],'scope_mismatch')
        self.assertEqual(self.outcomes()[-1]['scope_mismatch_reason'],'attention_off_observation')

    def test_off_frame_after_empty_forecast_at_same_clock_has_ordered_provenance(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                             attention_max_wait=100,attention_switch_penalty=1)
        obs=observe_sources(policy); a=self.workspace(policy)
        self.assertIsNone(a.select([],self.now))
        offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        off=self.workspace(offpolicy).select(obs,self.now)
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now)
        self.assertEqual(resumed['attention']['focus_state']['focus_ids'],['source-0'])
        self.assertEqual(resumed['attention']['focus_state_provenance']['frame_id'],off['frame_id'])
        self.assertEqual(self.outcomes()[-1]['status'],'scope_mismatch')

    def test_empty_off_observation_settles_pending_and_records_actual_empty_focus(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                             attention_max_wait=100,attention_switch_penalty=1)
        obs=observe_sources(policy); a=self.workspace(policy)
        a.select(obs,self.now); a.select(obs,self.now+1)
        offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        off=self.workspace(offpolicy)
        self.assertIsNone(off.select([],self.now+2))
        self.assertEqual(len(self.forecasts()),2)
        outcome=self.outcomes()[-1]
        self.assertEqual(outcome['status'],'scope_mismatch')
        self.assertEqual(outcome['observed_at'],self.now+2)
        self.assertTrue(all(p['fresh'] is None for p in outcome['sources']))
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+3)
        self.assertEqual(resumed['attention']['focus_state']['focus_ids'],[])
        self.assertEqual(resumed['attention']['focus_state_provenance']['origin'],'off_observation_wait_reset')
        self.assertEqual(resumed['attention']['model']['counts']['source-0'],{'fresh':1,'not_fresh':0})
        self.assertEqual(len(self.outcomes()),2)

    def test_first_activation_after_unrecorded_empty_off_resets_unknown_focus_without_stale_penalty(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                             attention_max_wait=100,attention_switch_penalty=1)
        obs=observe_sources(policy); offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        off=self.workspace(offpolicy)
        off.select(obs,self.now); previous=off.select(obs,self.now+1)
        self.assertEqual(previous['entries'][0]['source_id'],'source-1')
        self.assertIsNone(off.select([],self.now+2))
        with self.ledger._connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cognition_attention_off_observations').fetchone()[0],0)
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+3); f=resumed['attention']
        self.assertEqual(f['focus_state']['focus_ids'],[])
        self.assertFalse(f['focus_state_provenance']['focus_state_available'])
        self.assertEqual(f['focus_state_provenance']['origin'],'initial_unrecorded_focus_reset')
        self.assertEqual(f['focus_state_provenance']['historical_frame_id'],previous['frame_id'])
        self.assertEqual(resumed['entries'][0]['source_id'],'source-0')

    def test_legacy_unrecorded_off_frame_is_historical_not_actual_focus(self):
        from unittest.mock import patch
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',
                                             attention_max_wait=100,attention_switch_penalty=1)
        obs=observe_sources(policy); self.workspace(policy).select(obs,self.now)
        offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        # Represent the pre-marker writer's successful calls: nonempty frames
        # persisted, empty off calls left no observation record. No journal is rewritten.
        with patch('attention.observe_off',return_value=True):
            off=self.workspace(offpolicy); previous=off.select(obs,self.now+1)
            self.assertIsNone(off.select([],self.now+2))
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+3); f=resumed['attention']
        self.assertEqual(f['focus_state']['focus_ids'],[])
        self.assertFalse(f['focus_state_provenance']['focus_state_available'])
        self.assertEqual(f['focus_state_provenance']['historical_frame_id'],previous['frame_id'])
        self.assertEqual(resumed['entries'][0]['source_id'],'source-0')
        self.assertEqual(self.outcomes()[-1]['status'],'scope_mismatch')

    def test_legacy_forecast_without_off_cursor_cannot_establish_unrecorded_empty_observation_order(self):
        from unittest.mock import patch
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',attention_switch_penalty=1)
        obs=observe_sources(policy); frame=self.workspace(policy).select(obs,self.now)
        legacy=copy.deepcopy(frame['attention']); legacy.pop('off_observation_cutoff'); legacy.pop('frame_seq_cutoff')
        frame['attention']=legacy
        self.ledger=Ledger(self.root/'pre-marker.db')
        # Seed an intact pre-marker format journal in a fresh ledger, rather
        # than mutating any immutable current record.
        with self.ledger._connection(True) as db:
            db.execute('INSERT INTO cognition_forecasts(forecast_id,origin_frame_id,scope_hash,forecast,forecast_hash) VALUES(?,?,?,?,?)',
                       (legacy['forecast_id'],frame['frame_id'],legacy['scope_hash'],canonical(legacy),digest(legacy)))
            db.execute('INSERT INTO cognition_frames(frame_id,frame,frame_hash) VALUES(?,?,?)',
                       (frame['frame_id'],canonical(frame),digest(frame)))
        offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        with patch('attention.observe_off',return_value=True):
            self.assertIsNone(self.workspace(offpolicy).select([],self.now+1))
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+2)
        self.assertFalse(resumed['attention']['focus_state_provenance']['focus_state_available'])
        self.assertEqual(resumed['attention']['focus_state_provenance']['origin'],'legacy_unrecorded_observation_reset')
        self.assertEqual(resumed['attention']['focus_state']['focus_ids'],[])
        self.assertEqual(self.outcomes()[-1]['status'],'scope_mismatch')

    def test_repeated_off_observations_track_last_empty_selection_and_are_inert_without_attention_history(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant',attention_switch_penalty=1)
        obs=observe_sources(policy); offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        off=self.workspace(offpolicy)
        off.select(obs,self.now)
        with self.ledger._connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cognition_attention_off_observations').fetchone()[0],0)
        self.workspace(policy).select(obs,self.now+1)
        off.select(obs,self.now+2); off.select([],self.now+3)
        self.ledger=Ledger(self.ledger.path)
        resumed=self.workspace(policy).select(obs,self.now+4)
        self.assertEqual(resumed['attention']['focus_state']['focus_ids'],[])
        self.assertEqual(resumed['attention']['focus_state_provenance']['observed_at'],self.now+3)
        with self.ledger._connection(True) as db:
            row=db.execute('SELECT * FROM cognition_attention_off_observations LIMIT 1').fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT OR REPLACE INTO cognition_attention_off_observations VALUES('+','.join('?' for _ in row)+')',tuple(row))

    def test_off_state_instrumentation_missing_table_does_not_disable_legacy_selection(self):
        policy=fixtures.CognitionTests.policy(self,capacity=1,attention_mode='constant')
        obs=observe_sources(policy); self.workspace(policy).select(obs,self.now)
        offpolicy=copy.deepcopy(policy); offpolicy['cognition']['attention_mode']='off'
        with self.ledger._connection(True) as db:db.execute('DROP TABLE cognition_attention_off_observations')
        frame=self.workspace(offpolicy).select(obs,self.now+1)
        self.assertIsNotNone(frame)
        self.assertNotIn('attention',frame)

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
                    for e in frame['entries']:
                        sid=e['source_id']
                        self.assertLessEqual(tick-last[sid],bound,(capacity,mode,tick,sid,last[sid]))
                        last[sid]=tick
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
