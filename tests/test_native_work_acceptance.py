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
            self.assertIn('python3 /root/.hermes/cache/generated/zhulong-work-runner.py',request['mission'])
            self.assertNotIn('<<',request['mission'])
            self.assertEqual(request['run_deadline_seconds'], 180)
            self.assertEqual(request['max_attempts'], 1)
            self.assertEqual(request['daily_runs'], 1)
            self.assertEqual(request['sources'][0]['contracts']['result']['type'], 'json_reference')

    def runner_deployment(self):
        profile=self.root/'deployment/profile';profile.mkdir(parents=True)
        (self.root/'deployment/service').mkdir()
        config=profile/'config.yaml'
        self.m.atomic_json(config,{'approvals':{'mode':'smart','deny':['rm *']},'terminal':{'backend':'docker'}})
        manifest=self.root/'deployment/deployment.json'
        self.m.atomic_json(manifest,{'root':str(manifest.parent),'hashes':{str(config):self.m.digest_bytes(config.read_bytes())}})
        return manifest,profile,config

    def test_trusted_runner_is_protected_and_only_one_literal_is_allowlisted(self):
        manifest,profile,config=self.runner_deployment()
        self.assertTrue(callable(getattr(self.m,'prepare_trusted_runner',None)),'protected runner setup missing')
        result=self.m.prepare_trusted_runner(manifest,'a'*64)
        runner=profile/'cache/generated/zhulong-work-runner.py'
        self.assertTrue(runner.is_file())
        self.assertEqual(runner.stat().st_mode&0o222,0)
        updated=self.m.read_json(config)
        self.assertEqual(updated['command_allowlist'],['python3 /root/.hermes/cache/generated/zhulong-work-runner.py'])
        self.assertEqual(updated['approvals'],{'mode':'smart','deny':['rm *']})
        hashes=self.m.read_json(manifest)['hashes']
        self.assertEqual(hashes[str(runner)],self.m.digest_bytes(runner.read_bytes()))
        self.assertEqual(hashes[str(config)],self.m.digest_bytes(config.read_bytes()))
        self.assertEqual(result['runner_sha256'],hashes[str(runner)])
        from runtime_policy import CACHE_PATHS
        self.assertIn('cache/generated',CACHE_PATHS)

    def test_trusted_runner_reads_code_and_input_once_and_preserves_strict_receipt(self):
        self.assertTrue(callable(getattr(self.m,'trusted_runner_body',None)),'trusted runner body missing')
        code=b'import json,sys\nprint(json.dumps({"total":sum(json.load(sys.stdin)["hours"])}))\n'
        payload=b'{"hours":[3,7]}'
        body=self.m.trusted_runner_body(hashlib.sha256(payload).hexdigest())
        reads=[];launches=[]
        def read(path):
            reads.append(path.name);return code if path.name=='.zhulong-work.py' else payload
        def launch(args,**kwargs):
            launches.append((args,kwargs));return SimpleNamespace(stdout=b'{"total":10}')
        with patch.object(Path,'read_bytes',read),patch.object(Path,'write_text'), \
             patch.object(subprocess,'run',side_effect=launch),patch('builtins.print') as printer:
            exec(body,{})
        self.assertEqual(reads,['.zhulong-work.py','facts.json'])
        self.assertEqual(launches[0][0],['python3','-I','-c',code.decode()])
        self.assertEqual(launches[0][1]['input'],payload)
        self.assertEqual(launches[0][1]['timeout'],10)
        value=json.loads(printer.call_args.args[0])
        self.assertEqual(set(value),{'code_hash','input_hash','value'})
        self.assertEqual(value['value'],{'total':10})

    def test_trusted_runner_rejects_changed_input_and_duplicate_output(self):
        self.assertTrue(callable(getattr(self.m,'trusted_runner_body',None)),'trusted runner body missing')
        source=self.root/'facts.json';source.write_text('{"hours":[3,7]}')
        runner=self.root/'runner.py';runner.write_text(self.m.trusted_runner_body(hashlib.sha256(source.read_bytes()).hexdigest()))
        program=self.root/'.zhulong-work.py';program.write_text('print('+repr('{"total":10,"total":99}')+')')
        result=subprocess.run(['python3',str(runner)],cwd=self.root,capture_output=True,timeout=15)
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.root/'result.json').exists())
        program.write_text('print('+repr('{"total":10}')+')');source.write_text('{}')
        result=subprocess.run(['python3',str(runner)],cwd=self.root,capture_output=True,timeout=15)
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.root/'result.json').exists())

    def test_runner_and_config_tamper_are_rejected_by_existing_supervisor(self):
        manifest,profile,config=self.runner_deployment()
        self.m.prepare_trusted_runner(manifest,'a'*64)
        work=self.root/'work';work.mkdir();(work/'facts.json').write_text('{}')
        m=self.m.read_json(manifest)
        m.update(version=1,deployment_id='unit-runtime',work=str(work),host=str(self.root/'host'),
                 plugin_root=str(self.root/'plugin'),image='python@sha256:'+'a'*64,command=['/bin/true'],
                 port=8642,max_launches=1,startup_seconds=120,shutdown_seconds=60,progress_seconds=120)
        policy={'workspace_roots':[str(work)],'sources':[{'path':str(work/'facts.json'),
                'contracts':{'result':{'type':'file_contains','path':str(work/'result'),'text':'done'}}}]}
        (manifest.parent/'api.key').write_text('unit-only-not-a-credential')
        from runtime_supervisor import Supervisor
        supervisor=Supervisor(m,policy,preflight=lambda:True,cleanup_workers=lambda:0)
        supervisor.verify_controls()
        runner=profile/'cache/generated/zhulong-work-runner.py'
        original=runner.read_bytes();runner.chmod(0o644);runner.write_text('changed runner')
        with self.assertRaisesRegex(ValueError,'protected_file_changed'):supervisor.verify_controls()
        runner.write_bytes(original)
        config.write_text('{}')
        with self.assertRaisesRegex(ValueError,'protected_file_changed'):supervisor.verify_controls()

    def test_new_literal_native_audit_requires_actual_code_and_input_binding(self):
        fixture_path=Path(__file__).with_name('test_skill_smoke_evidence.py')
        fixture_spec=importlib.util.spec_from_file_location('zhulong_native_audit_fixture',fixture_path)
        fixture_module=importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture_module)
        from autonomy_store import canonical
        fixture=fixture_module.NativeSkillEvidenceTests(methodName='test_full_successful_command_and_code_hash_are_required')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        snapshot=fixture.frozen_input()
        fixture.program=fixture.root/'.zhulong-work.py'
        code='import json,sys\nprint(json.dumps({"sum":sum(json.load(sys.stdin)["observations"])}))\n'
        fixture.program.write_text(code)
        fixture.binding={'code':code,'code_hash':hashlib.sha256(code.encode()).hexdigest()}
        (fixture.root/'facts.json').write_text(canonical(snapshot['data']))
        runner=fixture.root/'runner.py';runner.write_text(self.m.trusted_runner_body(snapshot['input_hash']))
        executed=subprocess.run(['python3',str(runner)],cwd=fixture.root,capture_output=True,timeout=15)
        self.assertEqual(executed.returncode,0,executed.stderr)
        literal='python3 /root/.hermes/cache/generated/zhulong-work-runner.py'
        fixture.calls(literal,{'exit_code':0,'error':None,'output':executed.stdout.decode()})
        audit=self.m.audit_native_skill(fixture.root,fixture.sub,fixture.binding,literal,fixture.program,{'sum':6},task_input=snapshot)
        self.assertTrue(audit['execution_command_observed']);self.assertTrue(audit['frozen_input_execution_verified'])
        fixture.program.write_text(code+'# changed after receipt\n')
        with self.assertRaisesRegex(RuntimeError,'code_hash_mismatch'):
            self.m.audit_native_skill(fixture.root,fixture.sub,fixture.binding,literal,fixture.program,{'sum':6},task_input=snapshot)
        fixture.program.write_text(code)
        bad=dict(snapshot,input_hash='0'*64)
        with self.assertRaisesRegex(RuntimeError,'input_binding_mismatch'):
            self.m.audit_native_skill(fixture.root,fixture.sub,fixture.binding,literal,fixture.program,{'sum':6},task_input=bad)

    def test_pinned_native_allowlist_mount_and_guard_floors_offline(self):
        wrapper=Path('/workspace/.cloud-onboarding/bin/zhulong-python')
        host=Path('/workspace/.cloud-onboarding/dependencies/hermes-agent')
        if not wrapper.is_file() or not host.is_dir():self.skipTest('pinned native host unavailable')
        manifest,profile,config=self.runner_deployment();self.m.prepare_trusted_runner(manifest,'a'*64)
        script="""import json,os,sys
from pathlib import Path
os.environ['HERMES_HOME']=sys.argv[1]
sys.path.insert(0,sys.argv[2])
from tools import approval
from tools.approval_floors import _command_matches_permanent_allowlist
from tools.environments.docker import _readonly_skill_mount_args
literal='python3 /root/.hermes/cache/generated/zhulong-work-runner.py'
assert approval.load_permanent_allowlist()=={literal}
assert _command_matches_permanent_allowlist(literal)
for other in (literal+'; echo extra',literal+' --extra','python3 /root/.hermes/cache/generated/other.py'):
    assert not _command_matches_permanent_allowlist(other)
assert approval.check_dangerous_command(literal,'docker',has_host_access=True)['approved'] is True
blocked=approval.check_dangerous_command('rm -rf /','docker',has_host_access=True)
assert blocked['approved'] is False and blocked['hardline'] is True
mount=str(Path(sys.argv[1])/'cache/generated')+':/root/.hermes/cache/generated:ro'
assert mount in _readonly_skill_mount_args()
config=Path(sys.argv[1])/'config.yaml'
data=json.loads(config.read_text());data['approvals']['deny']=[literal];config.write_text(json.dumps(data))
blocked=approval.check_dangerous_command(literal,'docker',has_host_access=True)
assert blocked['approved'] is False and blocked['user_deny'] is True
print(json.dumps({'exact_literal':True,'readonly_generated_cache':True,'hardline':True,'user_deny':True,'provider_calls':0}))
"""
        result=subprocess.run([str(wrapper),'-c',script,str(profile),str(host)],cwd=host,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        evidence=json.loads(result.stdout)
        self.assertEqual(evidence['provider_calls'],0)
        self.assertTrue(all(evidence[k] for k in ('exact_literal','readonly_generated_cache','hardline','user_deny')))

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
            config=profile/'config.yaml';self.m.atomic_json(config,{'approvals':{'mode':'smart','deny':['rm *']}})
            self.m.atomic_json(root/'deployment.json',{'deployment_id':'fixture','root':str(root),'hashes':{str(config):self.m.digest_bytes(config.read_bytes())}})
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


class CertifiedNativeWorkTests(unittest.TestCase):
    def setUp(self):
        from scripts import native_work_acceptance
        self.m=native_work_acceptance
        self.assertTrue(callable(getattr(self.m,'prepare_certified_runner',None)),'protected certified runner missing')
        from test_certified_ticket import bundle
        from autonomy_store import canonical,digest,Ledger
        from autonomy_checks import validate_config,observe_sources,Verifier
        from autonomy import Controller
        from self_model import SelfModel
        from test_autonomy import Planner,Runs
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.work=self.root/'work';self.work.mkdir();self.bundle=bundle()
        self.fixture=self.m.business_inputs(2)[1]
        (self.work/'facts.json').write_text(canonical(self.fixture['data']))
        self.input_hash=digest(self.fixture['data'])
        self.profile=self.root/'deployment/profile';(self.profile/'zhulong').mkdir(parents=True)
        (self.root/'deployment/service').mkdir()
        self.manifest=self.root/'deployment/deployment.json'
        raw=self.m.work_policy(self.work,self.fixture,program_bundle=self.bundle)
        raw.update(enabled=True,workspace_roots=[str(self.work)],api_url='http://127.0.0.1:8642',api_identity_version='test-v1')
        config=self.profile/'config.yaml';self.m.atomic_json(config,{'terminal':{'backend':'docker'},'approvals':{'mode':'smart'}})
        plugin_config=self.profile/'zhulong/config.json';self.m.atomic_json(plugin_config,{'autonomy':raw})
        self.m.atomic_json(self.manifest,{'root':str(self.manifest.parent),'work':str(self.work),
              'hashes':{str(p):self.m.digest_bytes(p.read_bytes()) for p in (config,plugin_config)}})
        self.prepared=self.m.prepare_certified_runner(self.manifest,self.input_hash,self.bundle)
        self.policy=validate_config(raw,self.profile/'zhulong');self.ledger=Ledger(self.profile/'zhulong/autonomy.db')
        self.controller=Controller(self.ledger,self.policy,Planner(),Runs(),Verifier(self.policy),SelfModel(self.ledger,self.profile/'zhulong'),clock=lambda:1000)
        obs=observe_sources(self.policy)[0];self.snapshot=obs['task_input']
        g=self.ledger.create_goal({'source_id':obs['id'],'contract_id':'result','domain':'code','objective':'tickets','reason':'missing','confidence':.5},
              obs['revision'],self.policy['sources'][0]['contracts']['result'],{'verdict':False},1000,600,task_input=self.snapshot)
        lease=self.ledger.claim('test',1000,50,(g['id'],))
        admitted=self.ledger.prepare_submission(lease,self.controller._request(g),'session',self.controller.execution_identity,1000,1,1,1,86400)
        self.assertTrue(admitted['admitted'],admitted)
        self.ledger.record_admission(lease,admitted['submission']['id'],'run','completed',1001)
        self.sub=self.ledger.get_goal(g['id'])['submission']

    def execute(self):
        return subprocess.run(['python3','-I',str(self.profile/self.m.CERTIFIED_RUNNER_RELATIVE)],cwd=self.work,capture_output=True,timeout=15)

    def transcript(self,command=None,receipt=None,background=False):
        import sqlite3
        from contextlib import closing
        from autonomy_store import canonical,digest
        if receipt is None:
            result=self.execute();self.assertEqual(result.returncode,0,result.stderr);receipt=result.stdout.decode()
        with closing(sqlite3.connect(self.profile/'runs_idempotency.db')) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS run_idempotency(idempotency_key TEXT,run_id TEXT,fingerprint TEXT,status_json TEXT)')
            c.execute('DELETE FROM run_idempotency')
            c.execute('INSERT INTO run_idempotency VALUES(?,?,?,?)',(self.sub['id'],'run',digest({'body':self.sub['request'],'gateway_session_key':'session'}),canonical({'session_id':'session','run_id':'run','status':'completed'})))
        with closing(sqlite3.connect(self.profile/'state.db')) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT,tool_call_id TEXT)')
            c.execute('DELETE FROM messages')
            call=[{'id':'call','function':{'name':'terminal','arguments':{'command':command or self.m.CERTIFIED_RUNNER_COMMAND,'background':background}}}]
            c.execute('INSERT INTO messages VALUES(1,?,?,?,?,?)',('session','assistant',None,canonical(call),None))
            c.execute('INSERT INTO messages VALUES(2,?,?,?,?,?)',('session','tool',canonical({'exit_code':0,'error':None,'output':receipt}),None,'call'))

    def test_fixed_interpreter_executes_without_workspace_python_and_manifest_hashes_all_files(self):
        from work_reference import reference_output
        (self.work/'.zhulong-work.py').write_text("raise RuntimeError('MUST NOT RUN')")
        result=self.execute();self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads(result.stdout);expected=reference_output('ticket_priority_v1',self.fixture['data'])
        self.assertEqual(receipt['value'],expected);self.assertEqual(json.loads((self.work/'result.json').read_text()),expected)
        self.assertEqual(receipt['output_hash'],self.m.digest_bytes((self.work/'result.json').read_bytes()))
        self.assertEqual(receipt['input_hash'],self.input_hash)
        manifest=self.m.read_json(self.manifest)
        for name in ('zhulong-certified-runner.py','certified_ticket.py','zhulong-ticket-bundle.json','zhulong-ticket-scope.json'):
            path=self.profile/'cache/generated'/name
            self.assertEqual(path.stat().st_mode&0o222,0);self.assertEqual(manifest['hashes'][str(path)],self.m.digest_bytes(path.read_bytes()))
        self.assertEqual(self.m.read_json(self.profile/'config.yaml')['command_allowlist'],[self.m.CERTIFIED_RUNNER_COMMAND])
        self.assertNotIn('.zhulong-work.py',self.policy['mission'])

    def test_changed_input_or_kernel_fails_before_artifact(self):
        (self.work/'facts.json').write_text('{}');result=self.execute()
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.work/'result.json').exists())
        from autonomy_store import canonical
        (self.work/'facts.json').write_text(canonical(self.fixture['data']))
        kernel=self.profile/'cache/generated/certified_ticket.py';kernel.chmod(0o644);kernel.write_text('raise RuntimeError("changed")')
        result=self.execute();self.assertNotEqual(result.returncode,0);self.assertFalse((self.work/'result.json').exists())

    def test_actual_admitted_request_foreground_and_artifact_audit(self):
        self.transcript()
        audit=self.m.audit_native_certified(self.manifest,self.sub)
        self.assertTrue(audit['execution_command_observed']);self.assertTrue(audit['admitted_request_binding_verified'])
        self.assertEqual(audit['submission_id'],self.sub['id']);self.assertEqual(audit['input_hash'],self.input_hash)
        (self.work/'result.json').write_text('{}')
        with self.assertRaises(RuntimeError):self.m.audit_native_certified(self.manifest,self.sub)

    def test_arbitrary_python_fake_receipt_and_background_cannot_prove_execution(self):
        for command,receipt,bg in (('python3 .zhulong-work.py',None,False),(None,'{}',False),(None,None,True)):
            self.transcript(command,receipt,bg)
            with self.assertRaises(RuntimeError):self.m.audit_native_certified(self.manifest,self.sub)

    def test_audit_rejects_forged_admitted_bundle_and_identity(self):
        import copy
        from autonomy_store import canonical
        from test_certified_ticket import program
        self.transcript()
        forged=copy.deepcopy(self.sub);intent=json.loads(forged['request']['input'])
        intent['acceptance_contract']['program_bundle']['program']=program(True);forged['request']['input']=canonical(intent)
        with self.assertRaises(RuntimeError):self.m.audit_native_certified(self.manifest,forged)
        forged=copy.deepcopy(self.sub);forged['execution_identity']['profile']='other'
        with self.assertRaises(RuntimeError):self.m.audit_native_certified(self.manifest,forged)

    def test_installer_rejects_other_bundle_and_non_ticket_fixture(self):
        from test_certified_ticket import program
        import copy
        other=copy.deepcopy(self.bundle);other['program']=program(True)
        with self.assertRaises(ValueError):self.m.prepare_certified_runner(self.manifest,self.input_hash,other)
        with self.assertRaises(ValueError):self.m.work_policy(self.work,self.m.business_inputs(1)[0],program_bundle=self.bundle)

    def test_real_later_admission_of_different_bundle_cannot_match_installed_runner(self):
        import certified_bindings
        from autonomy_store import GoalLease,canonical
        from autonomy_checks import observe_sources
        from test_certified_ticket import program
        old=self.ledger.get_goal(self.sub['goal_id'])
        lease=GoalLease(old['id'],old['owner'],old['generation'],old['lease_until'])
        self.ledger.finish(lease,{'contract_hash':old['contract_hash'],'verdict':False},'failed',True,1002,expected_submission_id=self.sub['id'])
        self.policy['sources'][0]['contracts']['result']['program_bundle']['program']=program(True)
        certified_bindings.configure(self.ledger,self.policy['sources'],self.controller.execution_identity)
        obs=observe_sources(self.policy)[0]
        g=self.ledger.create_goal(old['candidate'],obs['revision'],self.policy['sources'][0]['contracts']['result'],{'verdict':False},1003,600,task_input=obs['task_input'])
        lease=self.ledger.claim('later',1003,50,(g['id'],))
        result=self.ledger.prepare_submission(lease,self.controller._request(g),'session',self.controller.execution_identity,1003,2,1,1,86400)
        self.assertTrue(result['admitted'],result)
        self.ledger.record_admission(lease,result['submission']['id'],'run','completed',1004)
        self.sub=self.ledger.get_goal(g['id'])['submission']
        self.assertEqual(json.loads(self.sub['request']['input'])['acceptance_contract']['program_bundle']['program'],program(True))
        self.transcript()
        with self.assertRaises(RuntimeError):self.m.audit_native_certified(self.manifest,self.sub)

    def test_certified_literal_is_accepted_by_pinned_native_guard_without_relaxing_floors(self):
        wrapper=Path('/workspace/.cloud-onboarding/bin/zhulong-python')
        host=Path('/workspace/.cloud-onboarding/dependencies/hermes-agent')
        if not wrapper.is_file() or not host.is_dir():self.skipTest('pinned native host unavailable')
        script="""import os,sys
os.environ['HERMES_HOME']=sys.argv[1]
sys.path.insert(0,sys.argv[2])
from tools import approval
from tools.approval_floors import _command_matches_permanent_allowlist
literal=sys.argv[3]
assert approval.load_permanent_allowlist()=={literal}
assert _command_matches_permanent_allowlist(literal)
assert approval.check_dangerous_command(literal,'docker',has_host_access=True)['approved'] is True
assert not _command_matches_permanent_allowlist(literal+'; echo forged')
assert not _command_matches_permanent_allowlist('python3 .zhulong-work.py')
assert approval.check_dangerous_command('rm -rf /','docker',has_host_access=True)['approved'] is False
"""
        result=subprocess.run([str(wrapper),'-c',script,str(self.profile),str(host),self.m.CERTIFIED_RUNNER_COMMAND],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
