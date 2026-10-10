"""Fresh-process stdlib fixtures, independent of native Hermes and model calls."""
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_channel import atomic_json,read_json


def gateway(mode):
    service=Path(os.environ['ZHULONG_SERVICE_DIR']);root=service.parent
    counts=read_json(root/'fixture-counts.json');counts['starts']=counts.get('starts',0)+1
    atomic_json(root/'fixture-counts.json',counts)
    if mode=='crash' or (mode=='fail-first' and counts['starts']<=2):os._exit(23)
    boot=os.environ['ZHULONG_BOOT_ID'];stop=threading.Event();key=os.environ['API_SERVER_KEY']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.headers.get('Authorization')!='Bearer '+key:self.send_error(401);return
            if self.path=='/health/detailed':data={'readiness':{'status':'ok'},'gateway_state':'running','pid':os.getpid()}
            elif self.path=='/v1/capabilities':data={'features':{'run_submission':True,'run_status':True,'run_stop':True,
                'runs_idempotency':{'supported':True,'durable':True,'retention_seconds':86400}}}
            else:self.send_error(404);return
            payload=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',int(os.environ['API_SERVER_PORT'])),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def terminate(*args):
        counts=read_json(root/'fixture-counts.json')
        health=read_json(service/'health.json');control=read_json(service/'control.json')
        counts['drain_after_gate']=control.get('state')=='stopping' and health.get('admission_closed') is True
        atomic_json(root/'fixture-counts.json',counts);stop.set()
    signal.signal(signal.SIGINT,terminate if mode!='stubborn' else signal.SIG_IGN)
    signal.signal(signal.SIGTERM,terminate if mode!='stubborn' else signal.SIG_IGN)
    seq=0
    try:
        while not stop.wait(0.025):
            control=read_json(service/'control.json');seq+=1
            atomic_json(service/'health.json',{'version':1,'pid':os.getpid(),
                'boot_id':'wrong-boot' if mode=='stale' else boot,'state':control.get('state'),
                'updated_monotonic':time.monotonic(),'sequence':seq,
                'admission_closed':control.get('state')=='stopping' and mode!='stubborn',
                'progress':{'thread_alive':True,'ticks':seq,'errors':0,'phase':'idle',
                    'updated_monotonic':time.monotonic()},'status':{'enabled':True,'active_executions':0}})
    finally:server.shutdown();server.server_close()


def runs_server(root,port):
    root=Path(root)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            key=self.headers['Idempotency-Key'];body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state=read_json(root/'effects.json');state['posts']=state.get('posts',0)+1
            if not state.get('key'):
                state.update(key=key,body=body,admissions=1,effects=1)
                (root/'result').write_text('done')
            elif state['key']!=key or state['body']!=body:self.send_error(409);return
            atomic_json(root/'effects.json',state)
            if state['posts']==1:self.connection.close();return
            payload=json.dumps({'run_id':'run_effect','status':'completed'}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',int(port)),Handler)
    atomic_json(root/'server.json',{'pid':os.getpid(),'ready':True})
    server.serve_forever()


if __name__=='__main__':
    if sys.argv[1]=='gateway':gateway(sys.argv[2])
    elif sys.argv[1]=='supervisor':
        from runtime_policy import load_manifest
        from runtime_supervisor import Supervisor
        m,p=load_manifest(sys.argv[2],verify=False)
        sys.exit(Supervisor(m,p,preflight=lambda:True,cleanup_workers=lambda:0).run())
    elif sys.argv[1]=='runs-server':runs_server(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=='source-crash':
        from autonomy_store import Ledger
        n=int(sys.argv[3]);ledger=Ledger(Path(sys.argv[2]))
        os._exit(0 if ledger.claim_source('s','r',str(n),1000+n*3,2,3) else 24)
    elif sys.argv[1]=='recover-client':
        from autonomy import Controller
        from autonomy_checks import validate_config,Verifier
        from autonomy_store import Ledger
        from self_model import SelfModel
        from hermes_runs import RunsClient
        root=Path(sys.argv[2]);policy=validate_config(json.loads((root/'policy.json').read_text()),root)
        ledger=Ledger(root/'ledger.db');model=SelfModel(ledger,root)
        runs=RunsClient(policy['api_url'],'API_SERVER_KEY',policy['api_identity_version'])
        controller=Controller(ledger,policy,None,runs,Verifier(policy),model,clock=lambda:float(sys.argv[3]))
        controller.admission_gate=lambda:False
        controller.tick()
        os._exit(0)
