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

    def launch(self,manifest):
        p=subprocess.Popen([sys.executable,str(FIXTURE),'supervisor',str(manifest)],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        self.processes.append(p);return p

    def status(self):return read_json(self.root/'service/status.json')

    def stop(self):
        control=read_json(self.root/'service/control.json');control['state']='stopping'
        atomic_json(self.root/'service/control.json',control)

    def cleanup(self):
        if hasattr(self,'root'):
            self.stop()
            pid=self.status().get('child_pid')
            if pid:
                try:os.killpg(pid,signal.SIGKILL)
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
        duplicate=self.launch(manifest);_,err=duplicate.communicate(timeout=4)
        self.assertEqual(duplicate.returncode,1)
        self.assertIn('deployment_already_locked',err)
        p.kill();p.communicate(timeout=4)
        orphan_duplicate=self.launch(manifest);_,err=orphan_duplicate.communicate(timeout=4)
        self.assertEqual(orphan_duplicate.returncode,1)
        self.assertIn('deployment_already_locked',err)

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
