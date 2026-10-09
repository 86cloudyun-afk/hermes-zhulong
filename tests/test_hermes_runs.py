import importlib
import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class RunHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,value,status=200):
        body=json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.headers.get('Authorization')!='Bearer test-only':self.reply({'error':'secret-body'},401);return
        if getattr(self.server,'large',False):self.reply({'blob':'x'*65536});return
        if self.path=='/v1/capabilities':
            self.reply({'features':{'run_submission':True,'run_status':True,'run_stop':True,
                'runs_idempotency':{'supported':True,'durable':self.server.durable,'retention_seconds':86400}}})
        elif self.path=='/v1/runs/run_1':self.reply({'run_id':'run_1','status':'interrupted'})
        else:self.reply({'error':'missing'},404)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path.endswith('/stop'):self.reply({'run_id':'run_1','status':'stopping'});return
        key=self.headers.get('Idempotency-Key');fingerprint=json.dumps([body,self.headers.get('X-Hermes-Session-Key')],sort_keys=True)
        with self.server.lock:
            if key in self.server.keys and self.server.keys[key]!=fingerprint:self.reply({'error':'conflict-secret'},409);return
            if key not in self.server.keys:self.server.keys[key]=fingerprint;self.server.admissions+=1
            if self.server.drop:
                self.server.drop=False
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
        self.reply({'run_id':'run_1','status':getattr(self.server,'admission_status','queued')},202)


class RunsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('hermes_runs'),'public Runs client is missing')
        self.m=importlib.import_module('hermes_runs')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),RunHandler)
        self.server.keys={};self.server.admissions=0;self.server.drop=True;self.server.durable=True;self.server.lock=threading.Lock()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.env=patch.dict(os.environ,{'ZHULONG_TEST_API_KEY':'test-only'});self.env.start();self.addCleanup(self.env.stop)
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.client=self.m.RunsClient(self.url,'ZHULONG_TEST_API_KEY','v1',1)
        self.submission={'id':'stable-key','request':{'input':'Create result'},'session_key':'stable-session',
                         'execution_identity':{'api_url':self.url,'credential_env':'ZHULONG_TEST_API_KEY','identity_version':'v1'}}

    def test_lost_admission_replays_once(self):
        with self.assertRaises(self.m.RunsError) as error:self.client.submit(self.submission)
        self.assertTrue(error.exception.admission_unknown)
        response=self.client.submit(self.submission)
        self.assertEqual(response['run_id'],'run_1');self.assertEqual(self.server.admissions,1)
        self.assertEqual(self.client.submit(self.submission)['run_id'],'run_1')
        self.assertEqual(self.server.admissions,1)

    def test_payload_or_session_conflict(self):
        self.server.drop=False;self.client.submit(self.submission)
        for changed in [{'request':{'input':'Changed'}},{'session_key':'different'}]:
            with self.assertRaises(self.m.RunsError) as error:self.client.submit({**self.submission,**changed})
            self.assertEqual(error.exception.code,'idempotency_conflict')
        self.assertEqual(self.server.admissions,1)

    def test_identity_rotation_prevents_network_admission(self):
        rotated=self.m.RunsClient(self.url,'ZHULONG_TEST_API_KEY','v2',1)
        with self.assertRaises(self.m.RunsError) as error:rotated.submit(self.submission)
        self.assertEqual(error.exception.code,'execution_identity_changed')
        self.assertEqual(self.server.admissions,0)

    def test_capabilities_durable_and_missing_credential(self):
        self.assertEqual(self.client.capabilities()['retention_seconds'],86400)
        self.server.durable=False
        with self.assertRaises(self.m.RunsError):self.client.capabilities()
        with patch.dict(os.environ,{'ZHULONG_TEST_API_KEY':''}):
            with self.assertRaises(self.m.RunsError) as error:self.client.capabilities()
            self.assertEqual(error.exception.code,'missing_credential')
        with patch.dict(os.environ,{'ZHULONG_TEST_API_KEY':'incorrect'}):
            with self.assertRaises(self.m.RunsError) as error:self.client.capabilities()
            self.assertEqual(error.exception.code,'http_401');self.assertNotIn('secret-body',str(error.exception))

    def test_interrupted_and_stop_are_facts(self):
        self.submission['run_id']='run_1'
        self.assertEqual(self.client.status(self.submission)['status'],'interrupted')
        self.assertEqual(self.client.stop(self.submission)['status'],'stopping')
        self.assertEqual(self.server.admissions,0)

    def test_oversized_response_is_unknown(self):
        self.server.large=True
        with self.assertRaises(self.m.RunsError) as error:self.client.capabilities()
        self.assertEqual(error.exception.code,'response_too_large')

    def test_native_started_admission_is_accepted(self):
        self.server.drop=False;self.server.admission_status='started'
        response=self.client.submit(self.submission)
        self.assertEqual(response['run_id'],'run_1');self.assertEqual(response['status'],'queued')


if __name__=='__main__':unittest.main()
