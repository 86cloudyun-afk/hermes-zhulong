"""Private, boot-scoped service control. Contains no planner or execution loop."""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path


def atomic_json(path, value):
    path=Path(path)
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def read_json(path):
    try:
        with open(path,encoding='utf-8') as stream:
            value=json.load(stream)
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def process_identity(pid):
    """Linux PID plus kernel start ticks, excluding exited/zombie processes."""
    if type(pid) is not int or pid<=0:return None
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()
        if fields[0] in {'Z','X'}:return None
        return {'pid':pid,'start_ticks':int(fields[19])}
    except (OSError,ValueError,IndexError):return None


def current_health(value,boot,pid):
    if (not isinstance(value,dict) or not boot or value.get('boot_id')!=boot
        or type(value.get('pid')) is not int or value['pid']!=pid
        or value.get('state') not in {'starting','running','stopping','blocked'}):return False
    progress,status=value.get('progress'),value.get('status')
    if not isinstance(progress,dict) or not isinstance(status,dict):return False
    now=time.monotonic();updated=value.get('updated_monotonic');phase_updated=progress.get('updated_monotonic')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (updated,phase_updated)):return False
    return 0<=now-updated<=5 and 0<=phase_updated<=now


def status_view(root):
    service=read_json(Path(root)/'service/status.json');plugin=read_json(Path(root)/'service/health.json')
    parent=service.get('supervisor_identity');child=service.get('child_identity')
    parent_live=isinstance(parent,dict) and process_identity(service.get('supervisor_pid'))==parent
    child_live=isinstance(child,dict) and process_identity(service.get('child_pid'))==child
    healthy=child_live and current_health(plugin,service.get('boot_id'),service.get('child_pid'))
    reported=service.get('state','unknown');state=reported;reason=None
    if reported in {'checking','starting','running','stopping','restarting'}:
        if not parent_live:state='orphaned' if child_live else 'stale';reason='supervisor_not_current'
        elif reported=='running':
            if not child_live:state='stale';reason='child_not_current'
            elif (not healthy or plugin.get('state')!='running'
                or plugin['progress'].get('thread_alive') is not True
                or plugin['status'].get('enabled') is not True):state='unhealthy';reason='health_not_current'
    return {'service':{**service,'state':state,'reported_state':reported,'observation_reason':reason,
        'observation':{'supervisor_live':parent_live,'child_live':child_live,'health_current':healthy}},
        'plugin':{**plugin,'current':healthy}}


class ServiceChannel:
    def __init__(self,root,boot_id,controller,stop_event,interval=0.5):
        self.root,self.boot_id,self.controller=Path(root),boot_id,controller
        self.stop_event,self.interval=stop_event,interval
        self._stop=threading.Event();self._thread=None;self.sequence=0
        if controller is not None:controller.admission_gate=self.admissible

    def control(self):
        value=read_json(self.root/'control.json')
        if value.get('boot_id')!=self.boot_id or value.get('state') not in {'starting','running','stopping'}:return {'state':'blocked'}
        return value

    def admissible(self):return self.control()['state']=='running'

    def publish(self):
        state=self.control()['state'];progress={};status={}
        if state in {'stopping','blocked'}:
            self.stop_event.set()
            if self.controller is not None:self.controller.request_stop()
        if self.controller is not None:
            progress=self.controller.progress();status=self.controller.status()
        else:state='blocked'
        self.sequence+=1
        atomic_json(self.root/'health.json',{'version':1,'boot_id':self.boot_id,'pid':os.getpid(),
            'state':state,'sequence':self.sequence,'updated_monotonic':time.monotonic(),
            'admission_closed':state!='running' and progress.get('phase')=='idle',
            'progress':progress,'status':status})

    def start(self):
        self.publish()
        def monitor():
            while not self._stop.wait(self.interval):
                try:self.publish()
                except Exception:
                    self.stop_event.set()
                    if self.controller is not None:self.controller.request_stop()
                    break
        self._thread=threading.Thread(target=monitor,daemon=True,name='zhulong-service-health');self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():self._thread.join(timeout=2)
