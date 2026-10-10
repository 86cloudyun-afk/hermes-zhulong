"""Foreground native gateway supervision, with no cognitive scheduler."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from runtime_channel import atomic_json,read_json,current_health,process_identity
from runtime_policy import child_environment,file_hash,DOCKER_ENV_KEYS,validate_manifest,validate_worker_policy


def docker(m,args):
    env=os.environ.copy()
    for name in DOCKER_ENV_KEYS:env.pop(name,None)
    env['DOCKER_HOST']='unix:///var/run/docker.sock'
    return subprocess.run(['docker','--host=unix:///var/run/docker.sock',*args],
        env=env,capture_output=True,text=True,timeout=15,check=True)


def remove_owned_workers(m):
    result=docker(m,['ps','-aq','--filter','label=zhulong.runtime='+m['deployment_id']])
    ids=result.stdout.split()
    if len(ids)>256:raise ValueError('too_many_owned_workers')
    if ids:
        workers=json.loads(docker(m,['inspect',*ids]).stdout)
        if any(w['Config']['Labels'].get('zhulong.runtime')!=m['deployment_id'] for w in workers):raise ValueError('worker_ownership_changed')
        docker(m,['rm','-f',*ids])
    return len(ids)


def ready_body(health,capabilities,pid):
    readiness=health.get('readiness',{})
    if not isinstance(readiness,dict):return False
    features=capabilities.get('features',{})
    if not isinstance(features,dict):return False
    idem=features.get('runs_idempotency',{})
    if not isinstance(idem,dict):return False
    return (health.get('pid')==pid and health.get('gateway_state')=='running'
        and readiness.get('status')=='ok'
        and all(features.get(k) is True for k in ('run_submission','run_status','run_stop'))
        and idem.get('supported') is True and idem.get('durable') is True
        and type(idem.get('retention_seconds')) is int and idem['retention_seconds']>0)


def group_running(group):
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():continue
        try:
            fields=(entry/'stat').read_text().rsplit(') ',1)[1].split()
            if fields[0] not in {'Z','X'} and int(fields[2])==group:return True
        except (OSError,ValueError,IndexError):continue
    return False


def terminate_group(process,deadline,*,interrupt=True):
    """Own start_new_session groups even after their direct leader exits."""
    def send(sig):
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:pass
    forced=False
    if interrupt:send(signal.SIGINT)
    if process.poll() is None and interrupt:
        try:process.wait(timeout=max(0.01,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:pass
    if process.poll() is None or group_running(process.pid):
        forced=True;send(signal.SIGKILL)
    process.wait(timeout=5)
    while group_running(process.pid) and time.monotonic()<deadline:time.sleep(0.01)
    if group_running(process.pid):raise ValueError('owned_group_not_quiet')
    return forced


class Supervisor:
    def __init__(self,manifest,policy,*,preflight=None,cleanup_workers=None):
        self.m,self.policy=manifest,policy
        self.root=Path(manifest['root']);self.service=self.root/'service'
        self.preflight=preflight or self.native_preflight
        self.cleanup_workers=cleanup_workers or (lambda:remove_owned_workers(self.m))
        self.stop_event=threading.Event();self.child=None;self.boot=None;self.current={}
        self.parent_identity=process_identity(os.getpid());self.child_identity=None
        self.stop_baseline=None;self.internal_stopping=False
        self.key=(self.root/'api.key').read_text()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def record(self,state,reason=None,**fields):
        self.current.update(state=state,reason=reason,boot_id=self.boot,supervisor_pid=os.getpid(),
            supervisor_identity=self.parent_identity,child_identity=self.child_identity,
            child_pid=self.child.pid if self.child else None,updated=time.time(),**fields)
        atomic_json(self.service/'status.json',self.current)

    def control(self,state):atomic_json(self.service/'control.json',{'version':1,'boot_id':self.boot,'state':state})

    def verify_controls(self):
        validate_manifest(self.m);validate_worker_policy(self.m,self.policy)
        for name,expected in self.m['hashes'].items():
            if file_hash(name)!=expected:raise ValueError('protected_file_changed')

    def reserve_launch(self):
        path=self.service/'launches.json';state=read_json(path)
        used=state.get('used',0)
        if path.exists() and (type(state.get('used')) is not int or used<0):raise ValueError('launch_budget_corrupt')
        if used>=self.m['max_launches']:return False
        atomic_json(path,{'version':1,'used':used+1})
        self.current['launches']=used+1
        return True

    def native_preflight(self):
        command=[sys.executable,str(Path(self.m['plugin_root'])/'scripts/runtime_probe.py'),
            '--deployment',str(self.root/'deployment.json')]
        process=subprocess.Popen(command,cwd=self.root/'profile',
            env=child_environment(self.m,'probe',api_key=self.key),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,
            pass_fds=(self.lock,) if hasattr(self,'lock') else ())
        deadline=time.monotonic()+self.m['startup_seconds']
        try:
            while True:
                if self.requested_stop():raise InterruptedError('operator_stop_requested')
                remaining=deadline-time.monotonic()
                if remaining<=0:raise subprocess.TimeoutExpired(command,self.m['startup_seconds'])
                try:output,error=process.communicate(timeout=min(0.1,remaining));break
                except subprocess.TimeoutExpired:continue
            if process.returncode:raise subprocess.CalledProcessError(process.returncode,command)
            report=json.loads(output.strip().splitlines()[-1])
            if report.get('ok') is not True:raise ValueError('worker_preflight_failed')
            atomic_json(self.service/'boundary.json',report)
            return True
        finally:
            try:terminate_group(process,max(deadline,time.monotonic()+1),interrupt=False)
            finally:process.communicate(timeout=5)

    def get(self,path):
        request=urllib.request.Request(f"http://127.0.0.1:{self.m['port']}"+path,
            headers={'Authorization':'Bearer '+self.key})
        with self.opener.open(request,timeout=1) as response:
            body=response.read(65537)
            if len(body)>65536:raise ValueError('health_response_too_large')
            value=json.loads(body)
            if not isinstance(value,dict):raise ValueError('invalid_health_body')
            return value

    def health(self):
        h=read_json(self.service/'health.json')
        if not self.child or not current_health(h,self.boot,self.child.pid):return None
        return h

    def ready(self):
        h=self.health()
        if not h or h['state'] not in {'starting','running'} or h['progress'].get('thread_alive') is not True or h['status'].get('enabled') is not True:return False
        try:return ready_body(self.get('/health/detailed'),self.get('/v1/capabilities'),self.child.pid)
        except Exception:return False

    def requested_stop(self):
        if self.stop_event.is_set():return True
        path=self.service/'operator-stop.json';request=read_json(path)
        if path.exists():
            if request.get('deployment_id')!=self.m['deployment_id'] or not isinstance(request.get('request_id'),str):return True
            if request['request_id']!=self.stop_baseline:return True
        c=read_json(self.service/'control.json')
        return not self.internal_stopping and c.get('boot_id')==self.boot and c.get('state')=='stopping'

    def cleanup_owned(self):
        try:removed=self.cleanup_workers()
        except Exception as exc:
            self.current['cleanup_error']=type(exc).__name__;raise
        self.current['removed_workers']=self.current.get('removed_workers',0)+removed
        return removed

    def shutdown_child(self):
        if not self.child:return
        self.internal_stopping=True
        self.control('stopping');self.record('stopping')
        deadline=time.monotonic()+self.m['shutdown_seconds']
        ack_deadline=time.monotonic()+self.m['shutdown_seconds']*0.6
        acknowledged=False
        while self.child.poll() is None and time.monotonic()<ack_deadline:
            h=self.health()
            if h and h.get('admission_closed') is True:acknowledged=True;break
            time.sleep(0.025)
        forced=terminate_group(self.child,deadline)
        self.current.update(admission_acknowledged=acknowledged,forced_shutdown=forced)
        self.cleanup_owned()

    def run_owned(self,*,check_only=False):
        try:
            self.verify_controls();self.record('checking')
            if self.requested_stop():self.record('stopped');return 0
            if self.preflight() is not True:raise ValueError('worker_preflight_failed')
            if self.requested_stop():self.record('stopped');return 0
            self.cleanup_owned()
            if check_only:self.record('checked');return 0
            while not self.requested_stop():
                self.verify_controls()
                reserved=self.reserve_launch()
                if self.requested_stop():self.record('stopped');return 0
                if not reserved:self.record('blocked','launch_budget_exhausted');return 1
                self.boot=uuid.uuid4().hex;self.control('starting');self.internal_stopping=False
                if self.requested_stop():self.record('stopped');return 0
                descriptor=os.open(self.root/'gateway.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
                with os.fdopen(descriptor,'ab') as logfile:
                    self.child=subprocess.Popen(self.m['command'],env=child_environment(self.m,self.boot,api_key=self.key),
                        cwd=self.root/'profile',stdout=logfile,stderr=subprocess.STDOUT,
                        start_new_session=True,pass_fds=(self.lock,))
                self.child_identity=process_identity(self.child.pid)
                self.record('starting')
                deadline=time.monotonic()+self.m['startup_seconds']
                while self.child.poll() is None and time.monotonic()<deadline and not self.requested_stop():
                    self.verify_controls()
                    if self.ready():break
                    time.sleep(0.1)
                if self.requested_stop():self.shutdown_child();self.record('stopped');return 0
                if self.child.poll() is None and self.ready():
                    self.control('running');self.record('running')
                    while self.child.poll() is None and not self.requested_stop():
                        self.verify_controls();h=self.health()
                        if not h or h['state']=='blocked':break
                        if time.monotonic()-h['progress']['updated_monotonic']>self.m['progress_seconds']:break
                        time.sleep(0.1)
                if self.requested_stop():self.shutdown_child();self.record('stopped');return 0
                reason='child_exited' if self.child.poll() is not None else 'health_or_startup_timeout'
                self.shutdown_child();self.record('restarting',reason,last_failure=reason)
                if self.stop_event.wait(0.1):break
            self.record('stopped');return 0
        except Exception as exc:
            code=str(exc) if isinstance(exc,ValueError) else 'supervisor_error:'+type(exc).__name__
            try:self.shutdown_child()
            except Exception as cleanup_exc:
                self.record('blocked',code,cleanup_error=type(cleanup_exc).__name__);return 1
            if self.requested_stop():self.record('stopped',last_failure=code);return 0
            self.record('blocked',code);print(code,file=sys.stderr);return 1

    def run(self,*,check_only=False):
        lock=os.open(self.service/'runtime.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                print('deployment_already_locked',file=sys.stderr);return 1
            self.lock=lock
            # A later explicit run starts a new invocation; new requests after
            # this ownership point cannot be overwritten by boot transitions.
            self.stop_baseline=read_json(self.service/'operator-stop.json').get('request_id')
            previous={}
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGINT,signal.SIGTERM):
                    previous[sig]=signal.signal(sig,lambda *_:self.stop_event.set())
            result=1
            try:result=self.run_owned(check_only=check_only)
            finally:
                try:self.cleanup_owned()
                except Exception as exc:
                    self.record('blocked','worker_cleanup_failed',last_failure=self.current.get('reason'),cleanup_error=type(exc).__name__)
                    result=1
                else:
                    if self.current:self.record(self.current['state'],self.current.get('reason'))
                for sig,handler in previous.items():signal.signal(sig,handler)
            return result
        finally:os.close(lock)
