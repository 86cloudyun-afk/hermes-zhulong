import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace


class NativeWorkTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.native_work_acceptance'), 'native useful work harness missing')
        from scripts import native_work_acceptance
        self.m = native_work_acceptance
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_runner_hashes_actual_work_program_and_frozen_input(self):
        from autonomy_store import canonical, digest
        code = 'import sys,json\nx=json.load(sys.stdin)\nprint(json.dumps({"total":sum(x["hours"])}))\n'
        (self.root/'.zhulong-work.py').write_text(code)
        source = self.root/'facts.json'; source.write_text(canonical({'hours': [3, 7]}))
        output = self.root/'out.json'
        command = self.m.work_command(source, output, digest({'hours': [3, 7]}))
        result = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['code_hash'], hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(receipt['input_hash'], digest({'hours': [3, 7]}))
        self.assertEqual(json.loads(output.read_text()), {'total': 10})
        source.write_text('{}'); output.unlink()
        result = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0); self.assertFalse(output.exists())

    def test_business_fixtures_vary_and_keep_expected_answers_private(self):
        fixtures = self.m.business_inputs(3)
        self.assertEqual(len(fixtures), 3)
        self.assertEqual(len({json.dumps(f['data'], sort_keys=True) for f in fixtures}), 3)
        for fixture in fixtures:
            request = self.m.work_policy(self.root, fixture)
            self.assertNotIn('expected_output', json.dumps(request))
            self.assertLessEqual(len(request['mission']), 2000)
            self.assertIn('.zhulong-work.py', request['mission'])
            self.assertIn('ZHULONG_SKILL_SMOKE', request['mission'])
            self.assertEqual(request['run_deadline_seconds'], 180)
            self.assertEqual(request['max_attempts'], 1)
            self.assertEqual(request['daily_runs'], 1)
            self.assertEqual(request['sources'][0]['contracts']['result']['type'], 'json_reference')

    def test_completed_polls_the_actual_ledger_api(self):
        from autonomy_store import Ledger
        ledger = Ledger(self.root/'autonomy.db')
        goal = ledger.create_goal({'source_id': 's', 'contract_id': 'c', 'domain': 'code', 'objective': 'work', 'reason': 'pilot', 'confidence': .5},
                                 'revision', {'type': 'file_contains', 'path': str(self.root/'out'), 'text': 'x'},
                                 {'verdict': False}, 100, 180)
        self.assertTrue(callable(getattr(self.m, 'completed_goal', None)), 'actual Ledger polling helper missing')
        self.assertIsNone(self.m.completed_goal(ledger, goal['id']))

    def test_unpaid_preregistration_makes_no_deployment_or_calls(self):
        with patch.object(self.m, 'create_deployment', side_effect=AssertionError('no paid launch')):
            result = self.m.run(self.root/'retained', Path('/host'), 'worker@sha256:'+'a'*64, count=2, paid=False)
        self.assertEqual(result['allocated'], 2); self.assertEqual(result['unrun'], 2)
        self.assertTrue((self.root/'retained'/'trial.db').exists())
        self.assertFalse(result['causal_gain_supported'])
        for entry in result['allocations']:
            a = entry['allocation']
            frozen = self.root/'retained'/'inputs'/(a['input_id']+'.json')
            self.assertEqual(hashlib.sha256(frozen.read_bytes()).hexdigest(), a['input_hash'])

    def test_failed_allocations_persist_receipts_and_other_allocations_stay_in_denominator(self):
        with patch.object(self.m, 'execute_allocation', side_effect=RuntimeError('fixture_launch_failure')):
            report = self.m.run(self.root/'retained', Path('/host'), 'worker@sha256:'+'a'*64, count=2, paid=True)
        self.assertEqual(report['allocated'], 2); self.assertEqual(report['unknown'], 1)
        self.assertTrue((self.root/'retained'/'report.json').exists())
        self.assertEqual(report['billing_unknown'], 2)
        self.assertEqual(report['allocations'][0]['receipt'].get('error_code'), 'fixture_launch_failure')
        self.assertEqual(report['unrun'], 1)
        self.assertEqual(report['stop_reason'], 'unconfirmed_execution_quiescence')
        self.assertTrue((self.root/'retained'/'allocation-0'/'receipt.json').exists())
        self.assertFalse((self.root/'retained'/'allocation-1').exists())

    def test_unconfirmed_quiescence_stops_new_calls_and_preserves_all_allocations(self):
        for i, (settled, cleanup) in enumerate([(False,True),(True,False),(True,None),(None,True)]):
            with self.subTest(settled=settled,cleanup=cleanup):
                def unknown(base, host, image, fixture, allocation, command):
                    receipt=self.m._blank_receipt(allocation)
                    receipt.update(settled=settled,cleanup=cleanup)
                    return receipt
                retained=self.root/('retained-'+str(i))
                with patch.object(self.m,'execute_allocation',side_effect=unknown) as executor:
                    report=self.m.run(retained,Path('/host'),'worker@sha256:'+'a'*64,count=3,paid=True)
                self.assertEqual(executor.call_count,1)
                self.assertEqual((report['allocated'],report['unknown'],report['unrun']),(3,1,2))
                self.assertEqual(report['stop_reason'],'unconfirmed_execution_quiescence')
                disk=json.loads((retained/'report.json').read_text())
                self.assertEqual(disk['unrun'],2)
                self.assertFalse((retained/'allocation-1').exists())

    def test_actual_unknown_verifier_receipt_is_durable_before_quiescence_stop(self):
        # Only process boundaries are replaced: source binding, Verifier, goal
        # storage, execute_allocation, TrialLedger and report persistence are real.
        def deployment(root,work,host,image,command,raw,**kwargs):
            root.mkdir();profile=root/'profile';(profile/'zhulong').mkdir(parents=True)
            (root/'service').mkdir()
            raw=dict(raw,enabled=True,api_identity_version='fixture-v1',workspace_roots=[str(work)],api_url='http://127.0.0.1:8642')
            self.m.atomic_json(profile/'zhulong/config.json',{'autonomy':raw})
            self.m.atomic_json(root/'service/health.json',{'boot_id':'fixture','progress':{'thread_alive':True}})
            self.m.atomic_json(root/'service/status.json',{'state':'stopped'})
            self.m.atomic_json(root/'deployment.json',{'deployment_id':'fixture'})
            return root/'deployment.json'
        active={}
        def wait(predicate,timeout,process):
            if timeout==150:return {'state':'running','boot_id':'fixture'}
            base=self.root/'retained'/'allocation-0'
            raw=self.m.read_json(base/'deployment/profile/zhulong/config.json')['autonomy']
            policy=self.m.validate_config(raw,base/'deployment/profile/zhulong')
            if timeout==75:
                observation=self.m.observe_sources(policy)[0];snapshot=observation['task_input']
                contract=policy['sources'][0]['contracts']['result']
                ledger=self.m.Ledger(base/'deployment/profile/zhulong/autonomy.db')
                active['goal']=ledger.create_goal({'source_id':observation['id'],'contract_id':'result','domain':'code',
                    'objective':'bounded fixture','reason':'unit test','confidence':.5},observation['revision'],contract,
                    self.m.Verifier(policy).capture(contract,task_input=snapshot),100,180,task_input=snapshot)
                return predicate()
            # Duplicate JSON is a real unknown checker verdict, never false.
            (base/'work/result.json').write_text('{"duplicate":1,"duplicate":2}')
            return dict(active['goal'],state='unknown_result',attempts=1,submission={'settled':True,'usage':None})
        process=SimpleNamespace(returncode=0,wait=lambda **kwargs:0)
        with patch.object(self.m,'create_deployment',side_effect=deployment), \
             patch.object(self.m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='fixture')), \
             patch.object(self.m.subprocess,'Popen',return_value=process), \
             patch.object(self.m,'_wait',side_effect=wait), \
             patch.object(self.m,'docker',side_effect=RuntimeError('fixture_cleanup_unconfirmed')):
            try:
                report=self.m.run(self.root/'retained',Path('/host'),'worker@sha256:'+'a'*64,count=3,paid=True)
            except ValueError as exc:
                self.fail('unknown checker verdict must persist instead of crashing: '+str(exc))
        self.assertEqual((report['unknown'],report['unrun'],report['allocated']),(1,2,3))
        self.assertTrue(report['protocol_stopped'])
        receipt=report['allocations'][0]['receipt']
        self.assertIsNone(receipt['business'])
        self.assertIn('business_receipt',receipt)
        self.assertEqual(receipt['business_receipt']['verdict'],'unknown')
        self.assertEqual(receipt['business_receipt']['reason'],'verification_unavailable')
        from causal_trial import TrialLedger
        durable=TrialLedger(self.root/'retained/trial.db').summary()
        self.assertEqual((durable['unknown'],durable['unrun']),(1,2))
        self.assertFalse((self.root/'retained/allocation-1').exists())

    def test_settled_unknown_business_with_cleanup_is_recorded_and_can_continue(self):
        def unknown(base,host,image,fixture,allocation,command):
            receipt=self.m._blank_receipt(allocation)
            receipt.update(business=None,native=None,settled=True,cleanup=True,
                           business_receipt={'verdict':'unknown','reason':'verification_unavailable'})
            return receipt
        with patch.object(self.m,'execute_allocation',side_effect=unknown) as executor:
            report=self.m.run(self.root/'retained',Path('/host'),'worker@sha256:'+'a'*64,count=3,paid=True)
        self.assertEqual(executor.call_count,3)
        self.assertEqual((report['allocated'],report['unknown'],report['unrun']),(3,3,0))
        self.assertFalse(report['protocol_stopped'])
        self.assertTrue(all(a['receipt']['business'] is None for a in report['allocations']))

    def test_settled_business_failure_with_cleanup_can_continue(self):
        def failed(base,host,image,fixture,allocation,command):
            receipt=self.m._blank_receipt(allocation)
            receipt.update(outcome='failed',business=False,native=False,settled=True,cleanup=True)
            return receipt
        with patch.object(self.m,'execute_allocation',side_effect=failed) as executor:
            report=self.m.run(self.root/'retained',Path('/host'),'worker@sha256:'+'a'*64,count=3,paid=True)
        self.assertEqual(executor.call_count,3)
        self.assertEqual((report['allocated'],report['failed'],report['unrun']),(3,3,0))
        self.assertFalse(report['protocol_stopped'])


if __name__ == '__main__': unittest.main()
