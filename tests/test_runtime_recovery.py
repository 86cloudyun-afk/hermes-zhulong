import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from autonomy_store import Ledger
from runtime_channel import read_json

FIXTURE=Path(__file__).with_name('runtime_fixture.py')


class ProcessRecoveryTests(unittest.TestCase):
    def test_seven_actual_source_owner_deaths_do_not_exhaust_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'ledger.db'
            for n in range(7):
                p=subprocess.run([sys.executable,str(FIXTURE),'source-crash',str(db),str(n)],capture_output=True,timeout=5)
                self.assertEqual(p.returncode,0,p.stderr.decode())
            ledger=Ledger(db)
            self.assertEqual(ledger.source_state('s')['outcome']['attempts'],0)
            self.assertTrue(ledger.claim_source('s','r','alive',1025,20,3))

    def test_lost_admission_reply_recovered_in_new_process_has_one_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'facts.json').write_text('{"missing":true}')
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}';identity={'api_url':url,'credential_env':'API_SERVER_KEY','identity_version':'fixture-v1','profile':'default'}
            policy={'enabled':True,'mission':'Create local evidence','workspace_roots':[str(root)],'api_url':url,
                'api_identity_version':'fixture-v1','sources':[{'id':'s','domain':'code','path':str(root/'facts.json'),
                    'contracts':{'result':{'type':'file_contains','path':str(root/'result'),'text':'done','require_change':True}}}]}
            (root/'policy.json').write_text(json.dumps(policy))
            ledger=Ledger(root/'ledger.db');contract=policy['sources'][0]['contracts']['result']
            goal=ledger.create_goal({'source_id':'s','domain':'code','contract_id':'result','objective':'Create result','reason':'Missing','confidence':None},
                'r',contract,{'verdict':False,'artifact_hash':None},1000,600)
            lease=ledger.claim('prepared',1000,2)
            prepared=ledger.prepare_submission(lease,{'input':'immutable original request'},'immutable-session',identity,1000,1,1,1,86400)
            server=subprocess.Popen([sys.executable,str(FIXTURE),'runs-server',str(root),str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while not read_json(root/'server.json').get('ready') and time.monotonic()<deadline:time.sleep(0.02)
                self.assertTrue(read_json(root/'server.json').get('ready'))
                env={**os.environ,'API_SERVER_KEY':'fixture-only-local-auth'}
                for now in (1003,1006):
                    p=subprocess.run([sys.executable,str(FIXTURE),'recover-client',str(root),str(now)],env=env,capture_output=True,timeout=5)
                    self.assertEqual(p.returncode,0,p.stderr.decode())
                result=ledger.get_goal(goal['id']);counter=read_json(root/'effects.json')
                self.assertEqual(counter['posts'],2);self.assertEqual(counter['admissions'],1);self.assertEqual(counter['effects'],1)
                self.assertEqual(counter['key'],prepared['submission']['id'])
                self.assertEqual(counter['body'],{'input':'immutable original request'})
                self.assertEqual(result['state'],'succeeded');self.assertTrue(result['submission']['settled'])
                self.assertEqual(result['attempts'],1)
                self.assertEqual(sum(e['outcome']=='succeeded' for e in ledger.model_records()['evidence']),1)
            finally:server.kill();server.communicate(timeout=5)
