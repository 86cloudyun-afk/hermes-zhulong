"""Local daemon-boundary fixtures; never real Docker or provider evidence."""
from contextlib import closing
import copy
import datetime
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import unittest
from unittest.mock import patch
import test_native_paired_trial as fixtures


class WorkerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('native_worker_capture'),'creation observer missing')
        import native_worker_capture
        self.m=native_worker_capture
        self.fixture=fixtures.PairedTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.trial,self.a,self.profile,self.sub=self.fixture.execution_artifacts()
        self.clock=self.fixture.clock;self.cid='a'*64;self.boot='test-service-boot'
        from runtime_channel import process_identity
        self.identity=process_identity(os.getpid())
        service=self.profile.parent/'service'
        self.fixture.m.durable_json(service/'status.json',dict(state='running',boot_id=self.boot,child_identity=self.identity,supervisor_identity=self.identity))
        self.fixture.m.durable_json(service/'health.json',dict(state='running',boot_id=self.boot,pid=os.getpid()))
        self.fixture.m.durable_json(self.trial.base(self.a)/'worker-endpoint.json',self.trial._event('endpoint_origin',self.a['id']))
        self.scope=self.profile.parent/'worker-observer-scope.json'
        self.manifest=json.loads((self.profile.parent/'deployment.json').read_text())
        # Reuse the explicit full boundary fixture, but no caller verdict enters
        # the observer: only the mocked external daemon returns this raw object.
        self.raw=self.fixture.worker_raw(self.trial,self.a)
        self.raw.update(Id=self.cid,Created=datetime.datetime.fromtimestamp(self.clock.utc,datetime.timezone.utc).isoformat())
        self.raw['Config']['Hostname']=self.cid[:12]
        self.raw['Config']['Labels'].update({'zhulong.boot':self.boot,'hermes-task-id':self.sub['session_key'],'hermes-agent':'1'})
        args=self.fixture.m.native_config(self.manifest,self.trial.inspect_controls(self.a['id'])['policy'],self.boot)['terminal']['docker_extra_args']
        self.env=patch.dict(os.environ,{'ZHULONG_BOOT_ID':self.boot,'TERMINAL_DOCKER_EXTRA_ARGS':json.dumps(args),'HERMES_BUNDLED_SKILLS':self.manifest['paired_bootstrap']['bundled_source']})
        self.env.start();self.addCleanup(self.env.stop)

    def daemon(self,argv,**kwargs):
        self.assertGreater(kwargs['timeout'],0)
        if argv[1]=='run':return subprocess.CompletedProcess(argv,0,(self.cid+'\n').encode(),b'')
        if argv[1]=='inspect':return subprocess.CompletedProcess(argv,0,json.dumps([self.raw]).encode(),b'')
        self.fail('unexpected daemon operation')

    def run_creation(self,transport=None):
        return self.m.invoke(self.scope,['run','-d','--label','hermes-task-id='+self.sub['session_key'],'explicit-test-image'],clock=self.clock,transport=transport or self.daemon)

    def test_paired_bootstrap_overrides_before_probe_and_main_and_rejects_population(self):
        from runtime_policy import child_environment
        for boot in ('probe',self.boot):
            env=child_environment(self.manifest,boot,{'HERMES_BUNDLED_SKILLS':'/foreign/source'},api_key='fixture')
            self.assertNotEqual(env['HERMES_BUNDLED_SKILLS'],'/foreign/source')
            self.assertFalse(Path(env['HERMES_BUNDLED_SKILLS']).exists())
        skills=self.profile/'skills';skills.mkdir(exist_ok=True);(skills/'unexpected').write_text('fixture')
        with self.assertRaisesRegex(ValueError,'paired_skills'):
            child_environment(self.manifest,self.boot,{},api_key='fixture')
        with self.assertRaises(ValueError):self.trial.inspect_controls(self.a['id'])

    def test_bootstrap_absence_canonical_parent_and_empty_skills_are_enforced(self):
        from runtime_policy import child_environment
        source=Path(self.manifest['paired_bootstrap']['bundled_source']);parent=source.parent
        for kind in ('directory','dangling_link'):
            parent.chmod(0o700)
            if kind=='directory':source.mkdir()
            else:source.symlink_to(parent/'missing-target')
            parent.chmod(0o500)
            try:
                with self.assertRaisesRegex(ValueError,'bundled_source_present'):child_environment(self.manifest,self.boot,{},api_key='fixture')
                with self.assertRaises(ValueError):self.run_creation()
            finally:
                parent.chmod(0o700)
                if kind=='directory':source.rmdir()
                else:source.unlink()
                parent.chmod(0o500)
        renamed=parent.with_name('old-parent');parent.rename(renamed);parent.symlink_to(renamed,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError,'parent_changed'):child_environment(self.manifest,self.boot,{},api_key='fixture')
        finally:parent.unlink();renamed.rename(parent)
        skills=self.profile/'skills';skills.rmdir();skills.symlink_to(self.fixture.root/'missing-skills')
        try:
            with self.assertRaisesRegex(ValueError,'skills_not_empty'):child_environment(self.manifest,self.boot,{},api_key='fixture')
        finally:skills.unlink();skills.mkdir()
        ordinary=dict(self.manifest);ordinary.pop('paired_bootstrap')
        self.assertEqual(child_environment(ordinary,self.boot,{'HERMES_BUNDLED_SKILLS':'ordinary-choice'},api_key='fixture')['HERMES_BUNDLED_SKILLS'],'ordinary-choice')

    def test_rejection_diagnostic_is_bounded_nonqualifying_and_sanitized(self):
        self.raw['Config']['Labels']['hermes-task-id']='foreign'
        with self.assertRaises(ValueError):self.run_creation()
        with self.trial.journal.transaction() as c:
            rejected=self.trial.journal.rows(c,'worker_rejection');self.assertEqual(self.trial.journal.rows(c,'worker'),[])
        self.assertEqual(len(rejected),1);value=rejected[0]['payload']
        self.assertEqual(value['code'],'observer_actual_container_changed');self.assertEqual(value['stage'],'boundary')
        self.assertEqual(set(value),{'allocation_id','clock','code','stage'})

    def test_auxiliary_prompt_capture_cannot_supply_foreground_identity(self):
        self.raw['Config']['Labels']['hermes-task-id']='prompt-backend-probe'
        self.m.invoke(self.scope,['run','-d','--label','hermes-task-id=prompt-backend-probe','explicit-test-image'],clock=self.clock,transport=self.daemon)
        with self.trial.journal.transaction() as c:records=self.trial.journal.rows(c,'worker')
        self.assertEqual(records[0]['payload']['purpose'],'prompt_probe')
        result=self.trial.qualify_artifacts(self.a['id']);self.assertIsNone(result['arm_qualified'])
        self.assertNotIn('worker_boundary',result)

    def test_duplicate_or_foreign_requested_labels_reject_before_daemon(self):
        for labels in (['--label','hermes-task-id='+self.sub['session_key']]*2,['--label=hermes-task-id=foreign'],['--label-file','untrusted']):
            with self.subTest(labels=labels),self.assertRaises(ValueError):
                self.m.invoke(self.scope,['run','-d',*labels,'explicit-test-image'],clock=self.clock,transport=lambda *a,**k:self.fail('ambiguous request reached daemon'))

    def test_probe_environment_never_installs_main_observer(self):
        from runtime_policy import child_environment
        env=child_environment(self.manifest,'probe',{},api_key='test-only')
        self.assertNotIn('HERMES_DOCKER_BINARY',env)

    def test_direct_probe_cannot_create_main_capture(self):
        with patch.dict(os.environ,{'ZHULONG_BOOT_ID':'probe'}):
            with self.assertRaises(ValueError):self.run_creation()

    def test_actual_inspect_is_durable_before_created_id_is_returned(self):
        result=self.run_creation();self.assertEqual(result.stdout,(self.cid+'\n').encode())
        with self.trial.journal.transaction() as c:records=self.trial.journal.rows(c,'worker')
        self.assertEqual(len(records),1);record=records[0]['payload']
        self.assertEqual(record['container_id'],self.cid);self.assertEqual(record['session_id'],self.sub['session_key'])
        self.assertTrue((self.trial.base(self.a)/'worker-captures'/f'{self.cid}.json').is_file())
        self.assertEqual(record['service_boot_id'],self.boot)

    def test_stale_boot_foreign_session_replaced_container_and_boundary_reject(self):
        original=copy.deepcopy(self.raw)
        for mutation in ('boot','session','id','image','network'):
            with self.subTest(mutation=mutation):
                self.raw=copy.deepcopy(original)
                if mutation=='boot':self.raw['Config']['Labels']['zhulong.boot']='preflight'
                elif mutation=='session':self.raw['Config']['Labels']['hermes-task-id']='foreign'
                elif mutation=='id':self.raw['Id']='b'*64
                elif mutation=='image':self.raw['Config']['Image']='wrong-image'
                else:self.raw['HostConfig']['NetworkMode']='host'
                with self.assertRaises(ValueError):self.run_creation()
        with self.trial.journal.transaction() as c:self.assertEqual(self.trial.journal.rows(c,'worker'),[])

    def test_late_inspection_retains_launch_without_qualifying_capture(self):
        def late(argv,**kwargs):
            result=self.daemon(argv,**kwargs)
            if argv[1]=='inspect':self.clock.advance(181)
            return result
        with self.assertRaises(TimeoutError):self.run_creation(late)
        with self.trial.journal.transaction() as c:
            self.assertEqual(len(self.trial.journal.rows(c,'worker_launch')),1)
            self.assertEqual(self.trial.journal.rows(c,'worker'),[])

    def test_two_workers_are_separate_and_duplicate_container_cannot_replace(self):
        self.run_creation();self.cid='b'*64;self.raw['Id']=self.cid;self.raw['Config']['Hostname']=self.cid[:12]
        self.run_creation()
        with self.assertRaises((ValueError,FileExistsError)):self.run_creation()
        with self.trial.journal.transaction() as c:self.assertEqual(len(self.trial.journal.rows(c,'worker')),2)

    def test_inspect_failure_and_partial_write_leave_unmatched_intent(self):
        def failed(argv,**kwargs):
            if argv[1]=='inspect':return subprocess.CompletedProcess(argv,1,b'',b'gone')
            return self.daemon(argv,**kwargs)
        with self.assertRaises(ValueError):self.run_creation(failed)
        with patch.object(self.m,'durable_json',side_effect=OSError('interrupted write')):
            with self.assertRaises(OSError):self.run_creation()
        with self.trial.journal.transaction() as c:
            self.assertEqual(len(self.trial.journal.rows(c,'worker_launch')),2)
            self.assertEqual(self.trial.journal.rows(c,'worker'),[])
        self.assertIsNone(self.trial.qualify_artifacts(self.a['id'])['arm_qualified'])

    def test_actual_two_worker_receipt_join_and_unknown_hostname(self):
        self.run_creation();self.cid='b'*64;self.raw['Id']=self.cid;self.raw['Config']['Hostname']=self.cid[:12]
        self.run_creation()
        for hostname,qualified in [('a'*12,True),('b'*12,True),('c'*12,None)]:
            with closing(sqlite3.connect(self.profile/'state.db')) as c,c:
                row=c.execute("SELECT content FROM messages WHERE role='tool'").fetchone()
                content=json.loads(row[0]);output=json.loads(content['output']);output['worker_hostname']=hostname
                content['output']=json.dumps(output);c.execute("UPDATE messages SET content=? WHERE role='tool'",(json.dumps(content),))
            result=self.trial.qualify_artifacts(self.a['id'])
            self.assertEqual(result['arm_qualified'],qualified)
            if qualified:self.assertEqual(result['worker_boundary']['container_id'],hostname[0]*64)

    def test_private_capture_tamper_and_unmatched_launch_never_qualify(self):
        self.run_creation();path=self.trial.base(self.a)/'worker-captures'/f'{self.cid}.json'
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777,0o700)
        original=path.read_bytes();path.write_bytes(b'{"partial":')
        self.assertIsNone(self.trial.qualify_artifacts(self.a['id'])['arm_qualified'])
        path.write_bytes(original)
        with self.assertRaises((ValueError,FileExistsError)):self.run_creation()
        value=self.trial.qualify_artifacts(self.a['id'])
        self.assertIsNone(value['arm_qualified']);self.assertIn('actual_worker_capture_incomplete',value['reasons'])

    def test_session_mapping_and_owner_reject_before_any_daemon_call(self):
        with closing(sqlite3.connect(self.profile/'runs_idempotency.db')) as c,c:
            row=c.execute('SELECT status_json FROM run_idempotency').fetchone();status=json.loads(row[0]);status['session_id']='different'
            c.execute('UPDATE run_idempotency SET status_json=?',(json.dumps(status),))
        with self.assertRaisesRegex(ValueError,'session_ambiguous'):
            self.run_creation(lambda *args,**kwargs:self.fail('daemon called before session binding'))
        with patch.object(self.m,'process_identity',return_value=None):
            with self.assertRaisesRegex(ValueError,'service_owner'):
                self.run_creation(lambda *args,**kwargs:self.fail('daemon called before owner binding'))

    def test_noncreation_uses_exec_with_original_arguments(self):
        class Replaced(Exception):pass
        args=['inspect','--format','{{.Id}}','literal-container']
        with patch.object(self.m.sys,'argv',['observer',*args]),patch.object(self.m.os,'execv',side_effect=Replaced) as call:
            with self.assertRaises(Replaced):self.m.main(str(self.scope))
        docker=json.loads(self.scope.read_text())['docker']['path']
        call.assert_called_once_with(docker,[docker,*args])

    def test_daemon_failure_preserves_exact_return_and_no_capture(self):
        result=self.run_creation(lambda argv,**kw:subprocess.CompletedProcess(argv,7,b'output',b'error'))
        self.assertEqual((result.returncode,result.stdout,result.stderr),(7,b'output',b'error'))
        with self.trial.journal.transaction() as c:self.assertEqual(self.trial.journal.rows(c,'worker'),[])


@unittest.skipUnless(os.environ.get('ZHULONG_WORKER_DOCKER_TESTS')=='1','explicit cached actual Docker creation validation')
class ActualWorkerCaptureTests(unittest.TestCase):
    def test_pinned_entry_two_actual_workers_and_foreground_join(self):
        """Real Docker/backend/runner; ledger/session setup is an explicit local fixture."""
        import sys,time
        from cohort import host_clock
        from runtime_channel import process_identity
        from runtime_policy import child_environment
        from native_worker_capture import real_docker_identity
        fixture=fixtures.PairedTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        class ActualClock:
            @property
            def utc(self):return time.time()
            def __call__(self):return host_clock()
            def advance(self,seconds):time.sleep(seconds)
        fixture.clock=ActualClock()
        image=os.environ.get('ZHULONG_WORKER_TEST_IMAGE','python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1')
        with patch.object(fixtures,'IMAGE',image):trial,a,profile,sub=fixture.execution_artifacts()
        manifest=json.loads((profile.parent/'deployment.json').read_text());boot='provider-free-real-worker-test'
        identity=process_identity(os.getpid());service=profile.parent/'service'
        fixture.m.durable_json(service/'status.json',dict(state='running',boot_id=boot,child_identity=identity,supervisor_identity=identity))
        fixture.m.durable_json(service/'health.json',dict(state='running',boot_id=boot,pid=os.getpid()))
        fixture.m.durable_json(trial.base(a)/'worker-endpoint.json',trial._event('endpoint_origin',a['id']))
        work=Path(manifest['work']);(work/'.zhulong-work.py').write_text('import json\nprint(json.dumps('+repr(fixture.expected)+'))\n')
        env=child_environment(manifest,boot,api_key='provider-free-fixture')
        env.pop('DEEPSEEK_API_KEY',None);env['ZHULONG_NO_AUTOSWEEP']='1'
        script=r'''import ast,json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from hermes_cli.config import apply_terminal_config_to_env,_is_ssh_remote_tilde_cwd
from hermes_cli.config_effective import load_user_config_effective
expected=os.environ['TERMINAL_DOCKER_EXTRA_ARGS']
apply_terminal_config_to_env()
assert os.environ['TERMINAL_DOCKER_EXTRA_ARGS']==expected
config=load_user_config_effective(Path(os.environ['HERMES_HOME'])/'config.yaml')
assert 'docker_extra_args' not in config['terminal']
tree=ast.parse((Path(sys.argv[1])/'gateway/run.py').read_text())
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_bridge_terminal_config_to_env')
scope={'os':os,'json':json,'_is_ssh_remote_tilde_cwd':_is_ssh_remote_tilde_cwd}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-pinned-gateway-bridge','exec'),scope)
scope['_bridge_terminal_config_to_env'](config['terminal'])
assert os.environ['TERMINAL_DOCKER_EXTRA_ARGS']==expected
from gateway.run import _start_gateway_configure_logging
_start_gateway_configure_logging(None)
assert not any((Path(os.environ['HERMES_HOME'])/'skills').iterdir())
from tools import terminal_tool as terminal
from agent.prompt_builder import _run_backend_probe
assert _run_backend_probe('docker',terminal)
workers=[];receipts=[]
try:
    for index in range(2):
        worker=terminal.ensure_task_env(sys.argv[2]);assert worker is not None
        workers.append(worker._container_id)
        result=worker.execute(sys.argv[3],timeout=30)
        assert result.get('returncode')==0,result
        receipt=json.loads(result['output']);assert receipt['worker_hostname']==worker._container_id[:12]
        receipts.append(receipt)
        terminal._evict_environment_for_task(sys.argv[2])
    assert len(set(workers))==2
    print(json.dumps({'workers':workers,'receipts':receipts}))
finally:
    terminal.cleanup_all_environments()
'''
        docker=real_docker_identity()['path'];ids=[]
        try:
            result=subprocess.run([sys.executable,'-c',script,str(fixtures.HOST),sub['session_key'],fixture.m.native.TRUSTED_RUNNER_COMMAND],env=env,capture_output=True,text=True,timeout=150)
            self.assertEqual(result.returncode,0,result.stderr[-3000:]);actual=json.loads(result.stdout.strip().splitlines()[-1]);ids=actual['workers']
            with trial.journal.transaction() as c:records=trial.journal.rows(c,'worker')
            self.assertEqual(len(records),3)
            self.assertEqual(sum(r['payload']['purpose']=='prompt_probe' for r in records),1)
            self.assertEqual({r['payload']['container_id'] for r in records if r['payload']['purpose']=='session'},set(ids))
            with closing(sqlite3.connect(profile/'state.db')) as c,c:
                c.execute("UPDATE messages SET content=? WHERE role='tool'",(json.dumps({'exit_code':0,'error':None,'output':json.dumps(actual['receipts'][-1])}),))
            proof=trial.qualify_artifacts(a['id']);self.assertTrue(proof['arm_qualified'],proof['reasons'])
            self.assertEqual(proof['worker_boundary']['container_id'],ids[-1])
        finally:
            # Scope every removal to this explicit test deployment, even if a
            # wrapper fails after create but before returning its ID.
            listed=subprocess.run([docker,'--host=unix:///var/run/docker.sock','ps','-aq','--filter','label=zhulong.runtime='+manifest['deployment_id']],capture_output=True,text=True,check=True,timeout=10)
            owned=listed.stdout.split()
            if owned:subprocess.run([docker,'--host=unix:///var/run/docker.sock','rm','-f',*owned],capture_output=True,check=True,timeout=20)
            final=subprocess.run([docker,'--host=unix:///var/run/docker.sock','ps','-aq','--filter','label=zhulong.runtime='+manifest['deployment_id']],capture_output=True,text=True,check=True,timeout=10)
            self.assertEqual(final.stdout.strip(),'')


if __name__=='__main__':unittest.main()
