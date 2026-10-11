import importlib.util
import tempfile
import unittest
from pathlib import Path


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('causal_trial'), 'causal trial ledger missing')
        import causal_trial
        self.m = causal_trial
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'trial.db'

    def protocol(self, arms=None):
        scope = {'goal': 'business-v1', 'identity': 'same-model-profile', 'input_scope': 'facts-v1', 'version': 1}
        return {'version': 1, 'seed': 42, 'mode': 'finite_usefulness_pilot',
                'versions': {'plugin': 'rev', 'host': 'host', 'reference': 1},
                'arms': arms or [{'id': 'baseline', 'scope': scope, 'mechanisms': {'learning': False}}],
                'inputs': [{'id': 'a', 'input_hash': 'a'*64}, {'id': 'b', 'input_hash': 'b'*64}],
                'max_attempts': 1, 'deadline_seconds': 180}

    def test_preregisters_all_allocations_and_replays_order(self):
        ledger = self.m.TrialLedger(self.path); protocol = self.protocol()
        rows = ledger.preregister(protocol)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows, ledger.preregister(protocol))
        second = self.m.TrialLedger(Path(self.temp.name)/'other.db')
        self.assertEqual([r['input_id'] for r in rows], [r['input_id'] for r in second.preregister(protocol)])
        self.assertEqual(ledger.summary()['unrun'], 2)
        changed = dict(protocol, seed=43)
        with self.assertRaisesRegex(ValueError, 'protocol_frozen'): ledger.preregister(changed)

    def test_denominator_includes_failure_unknown_and_unrun(self):
        ledger = self.m.TrialLedger(self.path); rows = ledger.preregister(self.protocol())
        ledger.record(rows[0]['id'], {'input_hash': rows[0]['input_hash'], 'scope_hash': rows[0]['scope_hash'], 'arm': 'baseline', 'outcome': 'failed',
             'business': False, 'native': False, 'settled': True, 'cleanup': True,
             'main_usage': None, 'auxiliary_calls': 1, 'billing': None})
        report = ledger.summary()
        self.assertEqual((report['allocated'], report['failed'], report['unrun']), (2, 1, 1))
        self.assertEqual(report['missing_main_usage'], 2)
        self.assertEqual(report['billing_unknown'], 2)
        self.assertEqual(report['auxiliary_calls'], 1)
        self.assertFalse(report['causal_gain_supported'])

    def test_success_requires_all_trusted_receipts_and_complete_cost_is_not_assumed(self):
        ledger = self.m.TrialLedger(self.path); row = ledger.preregister(self.protocol())[0]
        receipt = {'input_hash': row['input_hash'], 'scope_hash': row['scope_hash'], 'arm': 'baseline', 'outcome': 'succeeded',
                   'business': True, 'native': True, 'settled': True, 'cleanup': False,
                   'main_usage': {'input_tokens': 4}, 'auxiliary_calls': 0, 'billing': None}
        ledger.record(row['id'], receipt)
        report = ledger.summary()
        self.assertEqual(report['unknown'], 1); self.assertEqual(report['succeeded'], 0)
        self.assertEqual(report['missing_token_counts'], 2)
        with self.assertRaisesRegex(ValueError, 'receipt_frozen'): ledger.record(row['id'], receipt)

    def test_duplicate_input_hash_scope_and_unqualified_arms_rejected(self):
        protocol = self.protocol(); protocol['inputs'][1]['input_hash'] = 'a'*64
        with self.assertRaisesRegex(ValueError, 'duplicate_input'): self.m.TrialLedger(self.path).preregister(protocol)
        protocol = self.protocol(); scope = protocol['arms'][0]['scope']
        protocol['arms'].append({'id': 'treatment', 'scope': dict(scope, identity='different-profile'), 'mechanisms': {'learning': True}})
        with self.assertRaisesRegex(ValueError, 'scope'): self.m.TrialLedger(self.path).preregister(protocol)
        protocol['arms'][1]['scope'] = scope; protocol['arms'][1]['mechanisms'] = {'learning': True, 'other': True}
        with self.assertRaisesRegex(ValueError, 'single_mechanism'): self.m.TrialLedger(self.path).preregister(protocol)

    def test_unsettled_or_unknown_cleanup_does_not_become_failure(self):
        ledger = self.m.TrialLedger(self.path); row = ledger.preregister(self.protocol())[0]
        ledger.record(row['id'], {'input_hash': row['input_hash'], 'scope_hash': row['scope_hash'], 'arm': row['arm'],
                     'outcome': 'failed', 'business': False, 'native': False, 'settled': True, 'cleanup': None,
                     'main_usage': None, 'auxiliary_calls': 0, 'billing': None})
        self.assertEqual(ledger.summary()['unknown'], 1)
        self.assertEqual(ledger.summary()['failed'], 0)

    def test_broad_learning_switch_cannot_be_a_single_mechanism_trial(self):
        protocol = self.protocol()
        protocol['arms'][0]['mechanisms'] = {'learning_enabled': False}
        protocol['arms'].append(dict(protocol['arms'][0], id='treatment', mechanisms={'learning_enabled': True}))
        with self.assertRaisesRegex(ValueError, 'broad_mechanism'):
            self.m.TrialLedger(self.path).preregister(protocol)

    def test_paired_allocations_and_receipt_binding(self):
        protocol = self.protocol(); baseline = protocol['arms'][0]
        protocol['arms'].append(dict(baseline, id='treatment', mechanisms={'learning': True}))
        ledger = self.m.TrialLedger(self.path); rows = ledger.preregister(protocol)
        self.assertEqual(len(rows), 4)
        for item in protocol['inputs']:
            self.assertEqual({r['arm'] for r in rows if r['input_id'] == item['id']}, {'baseline', 'treatment'})
        row = rows[0]
        with self.assertRaisesRegex(ValueError, 'receipt_binding'):
            ledger.record(row['id'], {'input_hash': '0'*64, 'arm': row['arm'], 'outcome': 'failed'})
        with self.assertRaisesRegex(ValueError, 'receipt_binding'):
            ledger.record(row['id'], {'input_hash': row['input_hash'], 'scope_hash': '0'*64, 'arm': row['arm'], 'outcome': 'failed'})
        with self.assertRaisesRegex(ValueError, 'allocation_missing'): ledger.record('unknown', {})


class PairedTrialTests(unittest.TestCase):
    setUp = TrialTests.setUp
    protocol = TrialTests.protocol
    def paired_protocol(self, n=30):
        p = self.protocol()
        control = dict(p['arms'][0], mechanism_version='guidance-v1')
        control['scope'] = dict(control['scope'], identity={'provider':'deepseek', 'model':'deepseek-flash', 'profile':'fixed', 'identity_version':'fixed-v1'})
        treatment = dict(control, id='treatment', mechanisms={'learning': True})
        p['versions']['reference_checker_sha256'] = self.m.digest('trusted-checker-v1')
        p['mechanism'] = {'id': 'learning', 'version': 'guidance-v1', 'control_artifact_sha256': self.m.digest('control-code'), 'treatment_artifact_sha256': self.m.digest('treatment-code')}
        control['artifact_sha256'] = p['mechanism']['control_artifact_sha256']
        treatment['artifact_sha256'] = p['mechanism']['treatment_artifact_sha256']
        p.update(mode='paired_fixed_n', fixed_n=n, alpha=.05,
                 endpoint='qualified_success_by_deadline_v1', stop_rule='fixed_n_only',
                 control_arm='baseline', treatment_arm='treatment', arms=[control, treatment],
                 inputs=[{'id': str(i), 'input_hash': self.m.digest({'case': i}), 'reference_id':'fixture-reference', 'reference_version':1} for i in range(n)])
        return p

    def receipt(self, p, row, success):
        arm = next(a for a in p['arms'] if a['id'] == row['arm'])
        bind = {'allocation_id': row['id'], 'arm': row['arm'], 'input_hash': row['input_hash'], 'scope_hash': row['scope_hash']}
        proofs = {'business': dict(bind, verdict=success, reference_id=next(i['reference_id'] for i in p['inputs'] if i['id']==row['input_id']), reference_version=1, reference_checker_sha256=p['versions']['reference_checker_sha256']), 'native': dict(bind, verdict=success),
                  'quiet': dict(bind, settled=True, started_at=100, completed_at=110, deadline_at=280), 'cleanup': dict(bind, confirmed=True),
                  'arm': dict(bind, arm_hash=self.m.digest(arm), identity_hash=self.m.digest(arm['scope']['identity']),
                              mechanism_version=arm['mechanism_version'], artifact_sha256=arm['artifact_sha256'])}
        return dict(bind, outcome='succeeded' if success else 'failed', business=success, native=success,
                    settled=True, cleanup=True, main_usage=None, auxiliary_calls=0, billing=None,
                    **{k+'_receipt': v for k,v in proofs.items()},
                    proof_hashes={k: self.m.digest(v) for k,v in proofs.items()})

    def filled(self, n=30, control=False, treatment=True):
        p = self.paired_protocol(n); ledger = self.m.TrialLedger(self.path); rows = ledger.preregister(p)
        for row in rows: ledger.record(row['id'], self.receipt(p, row, control if row['arm']=='baseline' else treatment))
        return ledger, p, rows

    def test_fixed_n_validates_and_all_pairs_zero_difference_are_not_gain(self):
        ledger, p, rows = self.filled(control=True)
        a = ledger.summary()['paired_analysis']
        self.assertEqual((a['pairs'], a['ties'], a['discordant_pairs']), (30,30,0))
        self.assertEqual(a['exact_mcnemar_p'], 1)
        self.assertEqual(a['paired_effect'], 0)
        self.assertFalse(ledger.summary()['causal_gain_supported'])
        p['fixed_n'] = 31
        with self.assertRaisesRegex(ValueError, 'fixed_n'): self.m.validate_protocol(p)

    def test_complete_qualified_discordants_support_only_the_frozen_endpoint(self):
        ledger, p, rows = self.filled()
        report = ledger.summary(); a = report['paired_analysis']
        self.assertEqual((a['treatment_only'], a['control_only'], a['qualified_pairs']), (30,0,30))
        self.assertAlmostEqual(a['exact_mcnemar_p'], 2/(2**30))
        self.assertEqual(a['paired_effect'], 1)
        self.assertGreater(a['hoeffding_interval'][0], 0)
        self.assertTrue(report['causal_gain_supported'])
        self.assertEqual(report['billing_unknown'], 60)
        self.assertEqual(report['missing_auxiliary_usage'], 0)
        self.assertEqual(report['missing_training_usage'], 60)

    def test_unknown_unrun_and_missing_proof_remain_in_denominator_without_gain(self):
        p=self.paired_protocol(); ledger=self.m.TrialLedger(self.path); rows=ledger.preregister(p)
        unknown=self.receipt(p,rows[0],False);unknown.update(outcome='unknown',business=None,native=None)
        unknown.pop('proof_hashes'); ledger.record(rows[0]['id'],unknown)
        unqualified=self.receipt(p,rows[1],True);unqualified.pop('arm_receipt');ledger.record(rows[1]['id'],unqualified)
        report=ledger.summary();a=report['paired_analysis']
        self.assertEqual(report['allocated'],60);self.assertEqual(report['unrun'],58)
        self.assertEqual(a['pairs'],30);self.assertEqual(a['qualified_pairs'],0)
        self.assertEqual(a['complete_pairs'],1 if rows[0]['input_id']==rows[1]['input_id'] else 0)
        self.assertFalse(report['causal_gain_supported'])
        self.assertIn('incomplete',a['disqualifications'])

    def test_changed_arm_or_proof_hash_rejected_without_consuming_receipt(self):
        p=self.paired_protocol();ledger=self.m.TrialLedger(self.path);row=ledger.preregister(p)[0]
        receipt=self.receipt(p,row,True);receipt['arm_receipt']['identity_hash']='0'*64
        receipt['proof_hashes']['arm']=self.m.digest(receipt['arm_receipt'])
        with self.assertRaisesRegex(ValueError,'arm_proof'):ledger.record(row['id'],receipt)
        receipt=self.receipt(p,row,True);receipt['proof_hashes']['native']='0'*64
        with self.assertRaisesRegex(ValueError,'proof_hash'):ledger.record(row['id'],receipt)
        ledger.record(row['id'],self.receipt(p,row,True))
        with self.assertRaisesRegex(ValueError,'receipt_frozen'):ledger.record(row['id'],self.receipt(p,row,True))

    def test_reference_and_actual_deadline_binding_are_required(self):
        p=self.paired_protocol();ledger=self.m.TrialLedger(self.path);row=ledger.preregister(p)[0]
        for kind, key, bad in [('business','reference_id','wrong-contract'), ('quiet','deadline_at',300)]:
            r=self.receipt(p,row,True);r[kind+'_receipt'][key]=bad
            r['proof_hashes'][kind]=self.m.digest(r[kind+'_receipt'])
            with self.assertRaises(ValueError):ledger.record(row['id'],r)
        r=self.receipt(p,row,True);r['quiet_receipt'].pop('started_at');r['proof_hashes']['quiet']=self.m.digest(r['quiet_receipt'])
        ledger.record(row['id'],r)
        self.assertFalse(ledger.summary()['allocations'][0]['receipt']['paired_qualified'])

    def test_mixed_discordants_use_two_sided_exact_test_and_conservative_interval(self):
        import math
        p=self.paired_protocol();ledger=self.m.TrialLedger(self.path);rows=ledger.preregister(p)
        for row in rows:
            i=int(row['input_id'])
            success=(i<15 and row['arm']=='treatment') or (15<=i<20 and row['arm']=='baseline')
            ledger.record(row['id'],self.receipt(p,row,success))
        a=ledger.summary()['paired_analysis']
        self.assertEqual((a['treatment_only'],a['control_only'],a['ties']),(15,5,10))
        self.assertAlmostEqual(a['exact_mcnemar_p'],2*sum(math.comb(20,k) for k in range(6))/(2**20))
        self.assertAlmostEqual(a['paired_effect'],1/3)
        self.assertLess(a['hoeffding_interval'][0],0)
        self.assertFalse(ledger.summary()['causal_gain_supported'])

    def test_empty_auxiliary_or_training_usage_remains_unknown(self):
        p=self.paired_protocol();ledger=self.m.TrialLedger(self.path);row=ledger.preregister(p)[0]
        r=self.receipt(p,row,True);r.update(auxiliary_calls=1, auxiliary_usage={}, training_usage={})
        ledger.record(row['id'],r)
        report=ledger.summary()
        self.assertEqual(report['missing_auxiliary_usage'],60)
        self.assertEqual(report['missing_training_usage'],60)

    def test_analysis_without_a_frozen_ledger_never_supports_gain(self):
        ledger,p,rows=self.filled()
        allocations=ledger.summary()['allocations']
        a=self.m.paired_analysis(p,allocations)
        self.assertFalse(a['causal_gain_supported'])
        self.assertIn('protocol_not_frozen',a['disqualifications'])

    def test_small_n_and_operator_stop_prevent_gain(self):
        ledger,p,rows=self.filled(n=3)
        self.assertFalse(ledger.summary()['causal_gain_supported'])
        self.assertIn('small_n',ledger.summary()['paired_analysis']['disqualifications'])
        ledger=self.m.TrialLedger(Path(self.temp.name)/'stopped.db');p=self.paired_protocol();rows=ledger.preregister(p)
        ledger.stop('operator_interrupt')
        for row in rows:ledger.record(row['id'],self.receipt(p,row,row['arm']=='treatment'))
        self.assertFalse(ledger.summary()['causal_gain_supported'])
        self.assertIn('protocol_stopped',ledger.summary()['paired_analysis']['disqualifications'])

    def test_late_business_success_is_zero_under_preregistered_deadline(self):
        p=self.paired_protocol();ledger=self.m.TrialLedger(self.path);rows=ledger.preregister(p)
        for row in rows:
            r=self.receipt(p,row,row['arm']=='treatment')
            if row['arm']=='treatment':
                r['quiet_receipt']['completed_at']=281;r['proof_hashes']['quiet']=self.m.digest(r['quiet_receipt'])
            ledger.record(row['id'],r)
        a=ledger.summary()['paired_analysis']
        self.assertEqual(a['paired_effect'],0);self.assertEqual(a['qualified_pairs'],0)
        self.assertFalse(ledger.summary()['causal_gain_supported'])


if __name__ == '__main__': unittest.main()
