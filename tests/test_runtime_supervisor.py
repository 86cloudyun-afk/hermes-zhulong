import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import copy
import types
from pathlib import Path

from runtime_channel import read_json,atomic_json
from runtime_policy import create_deployment,load_manifest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/runtime_fixture.py'


def until(predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(0.025)
    raise AssertionError('bounded condition did not occur')


def process_live(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[0]!='Z'
    except FileNotFoundError:return False


@unittest.skipUnless(os.name=='posix','Linux process supervision requires POSIX')
class SupervisorTests(unittest.TestCase):
    def test_readiness_checks_body_pid_and_durable_capabilities(self):
        m=importlib.import_module('runtime_supervisor')
        health={'readiness':{'status':'ok'},'gateway_state':'running','pid':42}
        caps={'features':{'run_submission':True,'run_status':True,'run_stop':True,
            'runs_idempotency':{'supported':True,'durable':True,'retention_seconds':86400}}}
        self.assertTrue(m.ready_body(health,caps,42))
        for wrong in ({**health,'gateway_state':'draining'},{**health,'readiness':{'status':'degraded'}},{**health,'pid':41}):
            self.assertFalse(m.ready_body(wrong,caps,42))
        for malformed in ({'features':[]},{'features':{'runs_idempotency':None}},{}):
            self.assertFalse(m.ready_body(health,malformed,42))

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime_supervisor'),'process supervisor missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.work=self.base/'work';self.work.mkdir()
        (self.work/'facts.json').write_text('{"missing":true}')
        self.processes=[];self.addCleanup(self.cleanup)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]

    def deployment(self,mode='normal',launches=3):
        raw={'mission':'Create a local report','daily_runs':0,'sources':[{'id':'facts','domain':'code',
            'path':str(self.work/'facts.json'),'contracts':{'result':{'type':'file_contains','path':str(self.work/'result'),'text':'done'}}}]}
        manifest=create_deployment(self.base/'service',self.work,self.base/'host',
            'python@sha256:'+'a'*64,[sys.executable,str(FIXTURE),'gateway',mode],raw,
            port=self.port,max_launches=launches)
        self.root=manifest.parent
        m=json.loads(manifest.read_text());m.update(startup_seconds=1,shutdown_seconds=1,progress_seconds=2)
        atomic_json(manifest,m);return manifest

    def launch(self,manifest,stage=None):
        command=[sys.executable,str(FIXTURE),'supervisor',str(manifest)]
        if stage:command.append(stage)
        p=subprocess.Popen(command,
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        self.processes.append(p);return p

    def status(self):return read_json(self.root/'service/status.json')

    def stop(self):
        control=read_json(self.root/'service/control.json');control['state']='stopping'
        atomic_json(self.root/'service/control.json',control)

    def cli(self,action,manifest):
        return subprocess.run([sys.executable,str(ROOT/'scripts/runtime.py'),action,'--deployment',str(manifest)],
            capture_output=True,text=True,timeout=5)

    def cleanup(self):
        if hasattr(self,'root'):
            self.stop()
            pid=self.status().get('child_pid')
            if pid:
                try:os.killpg(pid,signal.SIGKILL)
                except ProcessLookupError:pass
            for name in ('descendant.json','probe-descendant.json'):
                descendant=read_json(self.root/name).get('pid')
                if descendant:
                    try:os.kill(descendant,signal.SIGKILL)
                    except ProcessLookupError:pass
        for p in self.processes:
            if p.poll() is None:p.kill()
            p.communicate(timeout=5)

    def test_ready_stop_gate_before_native_drain_and_child_exit(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        self.stop();p.communicate(timeout=6)
        self.assertEqual(p.returncode,0)
        self.assertTrue(read_json(self.root/'fixture-counts.json')['drain_after_gate'])
        self.assertEqual(self.status()['state'],'stopped')

    def test_crash_restarts_and_persistent_launch_budget_exhaustion(self):
        manifest=self.deployment('crash',2);p=self.launch(manifest);p.communicate(timeout=8)
        self.assertEqual(p.returncode,1)
        self.assertEqual(self.status()['reason'],'launch_budget_exhausted')
        self.assertEqual(read_json(self.root/'fixture-counts.json')['starts'],2)
        again=self.launch(manifest);again.communicate(timeout=4)
        self.assertEqual(read_json(self.root/'fixture-counts.json')['starts'],2)
        self.assertEqual(read_json(self.root/'service/launches.json')['used'],2)

    def test_failed_children_then_healthy_boot_have_fresh_health(self):
        manifest=self.deployment('fail-first',3);p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        health=read_json(self.root/'service/health.json')
        self.assertEqual(health['boot_id'],self.status()['boot_id'])
        self.assertEqual(read_json(self.root/'fixture-counts.json')['starts'],3)
        self.stop();p.communicate(timeout=6);self.assertEqual(p.returncode,0)

    def test_wrong_boot_never_becomes_ready(self):
        manifest=self.deployment('stale',1);p=self.launch(manifest);p.communicate(timeout=7)
        self.assertEqual(p.returncode,1)
        self.assertNotEqual(self.status()['state'],'running')
        self.assertEqual(self.status()['reason'],'launch_budget_exhausted')

    def test_duplicate_and_orphan_gateway_keep_inherited_lock(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        cleanups=read_json(self.root/'cleanup-counts.json')['calls']
        duplicate=self.launch(manifest);_,err=duplicate.communicate(timeout=4)
        self.assertEqual(duplicate.returncode,1)
        self.assertIn('deployment_already_locked',err)
        self.assertEqual(read_json(self.root/'cleanup-counts.json')['calls'],cleanups)
        p.kill();p.communicate(timeout=4)
        orphan_duplicate=self.launch(manifest);_,err=orphan_duplicate.communicate(timeout=4)
        self.assertEqual(orphan_duplicate.returncode,1)
        self.assertIn('deployment_already_locked',err)
        self.assertEqual(read_json(self.root/'cleanup-counts.json')['calls'],cleanups)

    def test_noncooperative_child_is_killed_within_shutdown_bound(self):
        manifest=self.deployment('stubborn',1);p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        started=time.monotonic();self.stop();p.communicate(timeout=6)
        self.assertLess(time.monotonic()-started,4)
        self.assertEqual(self.status()['state'],'stopped')
        self.assertTrue(self.status()['forced_shutdown'])

    def test_protected_config_change_blocks_service_without_relaunch(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        (self.root/'profile/config.yaml').write_text('{}')
        p.communicate(timeout=6)
        self.assertEqual(p.returncode,1)
        self.assertEqual(self.status()['reason'],'protected_file_changed')
        self.assertEqual(read_json(self.root/'fixture-counts.json')['starts'],1)

    def test_source_inode_replacement_blocks_service_without_relaunch(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        replacement=self.work/'replacement';replacement.write_text('{}')
        replacement.replace(self.work/'facts.json')
        p.communicate(timeout=6)
        self.assertEqual(p.returncode,1)
        self.assertEqual(self.status()['reason'],'source_topology_changed')
        self.assertEqual(read_json(self.root/'fixture-counts.json')['starts'],1)

    def test_replaced_work_topology_fails_execution_validation(self):
        from runtime_supervisor import Supervisor
        manifest=self.deployment();m,policy=load_manifest(manifest,verify=False)
        supervisor=Supervisor(m,policy,preflight=lambda:True,cleanup_workers=lambda:0)
        self.work.rename(self.base/'old-work');self.work.mkdir()
        (self.work/'facts.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'source_topology_changed'):supervisor.verify_controls()

    def test_descendant_cleanup_after_leader_crash_preserves_unrelated_group(self):
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
        self.processes.append(unrelated)
        manifest=self.deployment('descendant-crash',1);p=self.launch(manifest);p.communicate(timeout=7)
        pid=read_json(self.root/'descendant.json')['pid']
        self.assertFalse(process_live(pid))
        self.assertIsNone(unrelated.poll())
        again=self.launch(manifest);_,err=again.communicate(timeout=4)
        self.assertNotIn('deployment_already_locked',err)

    def test_descendant_cleanup_after_leader_accepts_stop(self):
        manifest=self.deployment('descendant-normal',1);p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        pid=read_json(self.root/'descendant.json')['pid']
        self.stop();p.communicate(timeout=6)
        self.assertEqual(p.returncode,0);self.assertFalse(process_live(pid))

    def operator_stop_at_barrier(self,stage,mode,expected_starts):
        manifest=self.deployment(mode);p=self.launch(manifest,stage)
        until(lambda:read_json(self.root/'fixture-barrier.json').get('stage'))
        result=self.cli('stop',manifest)
        (self.root/'fixture-release').touch()
        p.communicate(timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(p.returncode,0)
        self.assertEqual(self.status()['state'],'stopped')
        self.assertEqual(read_json(self.root/'fixture-counts.json').get('starts',0),expected_starts)
        return manifest

    def test_operator_stop_during_checking_prevents_launch_and_later_run_is_explicit(self):
        manifest=self.operator_stop_at_barrier('preflight-barrier','normal',0)
        again=self.launch(manifest);until(lambda:self.status().get('state')=='running')
        self.assertEqual(self.cli('stop',manifest).returncode,0)
        again.communicate(timeout=6);self.assertEqual(again.returncode,0)

    def test_operator_stop_during_failure_cleanup_prevents_restart(self):
        self.operator_stop_at_barrier('cleanup-barrier','crash',1)

    def test_operator_stop_before_boot_publication_prevents_launch(self):
        self.operator_stop_at_barrier('before-start-barrier','normal',0)

    def test_operational_commands_survive_mutable_work_and_policy_failure(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        outside=self.base/'outside';outside.write_text('outside')
        (self.work/'result').symlink_to(outside)
        self.assertEqual(self.cli('status',manifest).returncode,0)
        self.assertEqual(self.cli('stop',manifest).returncode,0)
        p.communicate(timeout=6);self.assertEqual(p.returncode,0)
        self.work.rename(self.base/'moved-work')
        self.assertEqual(self.cli('status',manifest).returncode,0)
        self.assertEqual(self.cli('stop',manifest).returncode,0)
        (self.root/'profile/zhulong/config.json').write_text('{')
        self.assertEqual(self.cli('status',manifest).returncode,0)
        self.assertEqual(self.cli('stop',manifest).returncode,0)

    def test_status_distinguishes_live_orphan_stale_and_wrong_identity(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        def view():
            result=self.cli('status',manifest);self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(view()['service']['state'],'running')
        h=read_json(self.root/'service/health.json')
        p.kill();p.communicate(timeout=4)
        self.assertEqual(view()['service']['state'],'orphaned')
        os.killpg(h['pid'],signal.SIGKILL);until(lambda:not process_live(h['pid']))
        self.assertEqual(view()['service']['state'],'stale')

    def test_status_rejects_stale_wrong_boot_and_reused_pid_observations(self):
        manifest=self.deployment();p=self.launch(manifest)
        until(lambda:self.status().get('state')=='running')
        pid=self.status()['child_pid']
        os.kill(pid,signal.SIGSTOP);self.addCleanup(lambda:os.kill(pid,signal.SIGCONT) if process_live(pid) else None)
        original=read_json(self.root/'service/health.json')
        for change in ({'boot_id':'other'},{'updated_monotonic':time.monotonic()-10}):
            atomic_json(self.root/'service/health.json',{**original,**change})
            view=json.loads(self.cli('status',manifest).stdout)
            self.assertNotEqual(view['service']['state'],'running')
        saved=self.status();saved['supervisor_identity']={'pid':p.pid,'start_ticks':-1}
        atomic_json(self.root/'service/status.json',saved)
        self.assertNotEqual(json.loads(self.cli('status',manifest).stdout)['service']['state'],'running')

    def test_health_and_readiness_reject_malformed_or_nonfinite_records(self):
        from runtime_supervisor import Supervisor,ready_body
        manifest=self.deployment();m,policy=load_manifest(manifest,verify=False)
        supervisor=Supervisor(m,policy,preflight=lambda:True,cleanup_workers=lambda:0)
        supervisor.boot='boot';supervisor.child=types.SimpleNamespace(pid=os.getpid())
        good={'boot_id':'boot','pid':os.getpid(),'state':'running','updated_monotonic':time.monotonic(),
            'progress':{'thread_alive':True,'updated_monotonic':time.monotonic()},'status':{'enabled':True}}
        for field,value in (('progress',None),('status',[]),('updated_monotonic',True),
                ('updated_monotonic',float('nan')),('updated_monotonic',float('inf'))):
            (self.root/'service/health.json').write_text(json.dumps({**good,field:value}))
            self.assertIsNone(supervisor.health())
        for value in (float('nan'),float('inf'),time.monotonic()+100,True):
            wrong=copy.deepcopy(good);wrong['progress']['updated_monotonic']=value
            (self.root/'service/health.json').write_text(json.dumps(wrong))
            self.assertIsNone(supervisor.health())
        for readiness in (None,[],42):
            self.assertFalse(ready_body({'pid':42,'gateway_state':'running','readiness':readiness},{},42))

    def test_preflight_failure_always_cleans_owned_workers_and_reports_cleanup_failure(self):
        from runtime_supervisor import Supervisor
        manifest=self.deployment();m,policy=load_manifest(manifest,verify=False)
        calls=[]
        def failed():raise ValueError('probe_failed')
        supervisor=Supervisor(m,policy,preflight=failed,cleanup_workers=lambda:calls.append('cleanup') or 1)
        self.assertEqual(supervisor.run(),1);self.assertTrue(calls)
        self.assertEqual(self.status()['removed_workers'],1)
        def bad_cleanup():raise RuntimeError('cleanup_fixture')
        supervisor=Supervisor(m,policy,preflight=failed,cleanup_workers=bad_cleanup)
        self.assertEqual(supervisor.run(),1)
        self.assertEqual(self.status()['cleanup_error'],'RuntimeError')

    def test_native_probe_timeout_cleans_descendants_and_calls_worker_cleanup(self):
        manifest=self.deployment();m=json.loads(manifest.read_text())
        stub=self.base/'stub/scripts';stub.mkdir(parents=True)
        marker=self.root/'probe-descendant.json'
        child="import os,signal,time,json; from pathlib import Path; signal.signal(signal.SIGINT,signal.SIG_IGN); Path(%r).write_text(json.dumps({'pid':os.getpid()})); time.sleep(30)"%str(marker)
        probe="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); time.sleep(30)"%child
        (stub/'runtime_probe.py').write_text(probe)
        m['plugin_root']=str(stub.parent);atomic_json(manifest,m)
        p=self.launch(manifest,'native-preflight');p.communicate(timeout=7)
        self.assertEqual(p.returncode,1)
        self.assertFalse(process_live(read_json(marker)['pid']))
        self.assertGreaterEqual(read_json(self.root/'cleanup-counts.json').get('calls',0),1)

    def test_operator_stop_interrupts_native_preflight_before_gateway(self):
        manifest=self.deployment();m=json.loads(manifest.read_text())
        stub=self.base/'stub/scripts';stub.mkdir(parents=True)
        marker=self.root/'probe-descendant.json'
        (stub/'runtime_probe.py').write_text("import os,json,time; from pathlib import Path; Path(%r).write_text(json.dumps({'pid':os.getpid()})); time.sleep(30)"%str(marker))
        m.update(plugin_root=str(stub.parent),startup_seconds=30);atomic_json(manifest,m)
        p=self.launch(manifest,'native-preflight')
        until(lambda:read_json(marker).get('pid'))
        self.assertEqual(self.cli('stop',manifest).returncode,0)
        p.communicate(timeout=5)
        self.assertEqual(p.returncode,0);self.assertFalse(process_live(read_json(marker)['pid']))
        self.assertEqual(read_json(self.root/'fixture-counts.json').get('starts',0),0)
        self.assertGreaterEqual(read_json(self.root/'cleanup-counts.json').get('calls',0),1)
