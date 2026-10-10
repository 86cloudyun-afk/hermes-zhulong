import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
import subprocess
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT))
from autonomy_store import canonical, digest
import task_inputs


class NativeSkillEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('skill_smoke_evidence'), 'native executable evidence audit missing')
        import skill_smoke_evidence
        self.m = skill_smoke_evidence
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.program = self.root/'program.py'; self.program.write_text('print(6)\n')
        self.binding = {'code': self.program.read_text(), 'code_hash': hashlib.sha256(self.program.read_bytes()).hexdigest()}
        self.sub = {'id': 'submission', 'run_id': 'run', 'request': {'input': '{}'}, 'session_key': 'session'}
        with closing(sqlite3.connect(self.root/'runs_idempotency.db')) as c, c:
            c.execute('CREATE TABLE run_idempotency(idempotency_key TEXT,run_id TEXT,fingerprint TEXT,status_json TEXT)')
            fingerprint = hashlib.sha256(json.dumps({'body': self.sub['request'], 'gateway_session_key': 'session'}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            c.execute('INSERT INTO run_idempotency VALUES(?,?,?,?)', ('submission', 'run', fingerprint, json.dumps({'session_id': 'session', 'run_id': 'run', 'status': 'completed'})))
        with closing(sqlite3.connect(self.root/'state.db')) as c, c:
            c.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT,tool_call_id TEXT)')

    def calls(self, command, result, background=False):
        with closing(sqlite3.connect(self.root/'state.db')) as c, c:
            call = [{'id': 'call', 'function': {'name': 'terminal', 'arguments': json.dumps({'command': command, 'background': background})}}]
            c.execute('INSERT INTO messages VALUES(1,?,?,?,?,?)', ('session', 'assistant', None, json.dumps(call), None))
            c.execute('INSERT INTO messages VALUES(2,?,?,?,?,?)', ('session', 'tool', json.dumps(result), None, 'call'))

    def test_full_successful_command_and_code_hash_are_required(self):
        command = self.m.runner_command(self.binding['code_hash'], '/facts', '/out')
        self.calls(command, {'exit_code': 0, 'error': None, 'output': json.dumps({'code_hash': self.binding['code_hash'], 'value': {'sum': 6}})})
        result = self.m.audit_native_skill(self.root, self.sub, self.binding, command, self.program, {'sum': 6})
        self.assertTrue(result['execution_command_observed']); self.assertTrue(result['worker_copy_matches_published_code'])

    def test_echo_marker_does_not_count_as_execution(self):
        self.calls('echo claimed-executed', {'exit_code': 0, 'error': None, 'output': 'claimed-executed'})
        with self.assertRaisesRegex(RuntimeError, 'native_skill_execution_unverified'):
            self.m.audit_native_skill(self.root, self.sub, self.binding, 'actual runner', self.program, 6)

    def test_background_or_nonzero_exit_cannot_prove_execution(self):
        self.calls('runner', {'exit_code': 0, 'error': None, 'session_id': 'background', 'output': '{}'}, background=True)
        with self.assertRaises(RuntimeError): self.m.audit_native_skill(self.root, self.sub, self.binding, 'runner', self.program, 6)

    def test_numeric_type_confusion_and_duplicate_result_keys_are_rejected(self):
        for raw, expected in [(json.dumps({'code_hash':self.binding['code_hash'],'value':{'sum':True}}), {'sum':1}),
                              (json.dumps({'code_hash':self.binding['code_hash'],'value':{'sum':6.0}}), {'sum':6}),
                              ('{"code_hash":"'+self.binding['code_hash']+'","value":0,"value":6}',6)]:
            with self.subTest(raw=raw):
                with closing(sqlite3.connect(self.root/'state.db')) as c,c:c.execute('DELETE FROM messages')
                self.calls('runner',{'exit_code':0,'error':None,'output':raw})
                with self.assertRaises(RuntimeError):self.m.audit_native_skill(self.root,self.sub,self.binding,'runner',self.program,expected)

    def frozen_input(self):
        snapshot=task_inputs.project({'id':'facts','input_fields':['observations'],'persist_input_fields':['observations']},
                                     {'observations':[2,4]})
        snapshot['source_revision']='observed-revision'
        self.sub['request']={'input':canonical({'task_input':snapshot})}
        with closing(sqlite3.connect(self.root/'runs_idempotency.db')) as c,c:
            fingerprint=digest({'body':self.sub['request'],'gateway_session_key':self.sub['session_key']})
            c.execute('UPDATE run_idempotency SET fingerprint=?',(fingerprint,))
        return snapshot

    def test_frozen_input_receipt_must_bind_canonical_hash_and_native_request(self):
        snapshot=self.frozen_input()
        self.calls('runner',{'exit_code':0,'error':None,'output':canonical({'code_hash':self.binding['code_hash'],
            'input_hash':snapshot['input_hash'],'value':{'sum':6}})})
        result=self.m.audit_native_skill(self.root,self.sub,self.binding,'runner',self.program,{'sum':6},task_input=snapshot)
        self.assertTrue(result['frozen_input_execution_verified']);self.assertEqual(result['input_hash'],snapshot['input_hash'])
        for bad in (dict(snapshot,input_hash='0'*64),dict(snapshot,data={'observations':[99]})):
            with self.assertRaises(RuntimeError):self.m.audit_native_skill(self.root,self.sub,self.binding,'runner',self.program,{'sum':6},task_input=bad)

    def test_wrong_input_hash_in_terminal_result_does_not_prove_frozen_execution(self):
        snapshot=self.frozen_input()
        self.calls('runner',{'exit_code':0,'error':None,'output':canonical({'code_hash':self.binding['code_hash'],
            'input_hash':'0'*64,'value':{'sum':6}})})
        with self.assertRaisesRegex(RuntimeError,'native_skill_execution_unverified'):
            self.m.audit_native_skill(self.root,self.sub,self.binding,'runner',self.program,{'sum':6},task_input=snapshot)

    def test_runner_executes_the_same_verified_bytes_and_reads_files_once(self):
        code=b'import json,sys\nprint(json.dumps({"sum":sum(json.load(sys.stdin)["observations"])}))\n'
        payload=canonical({'observations':[2,4]}).encode(); reads=[]; launches=[]
        code_hash=hashlib.sha256(code).hexdigest(); input_hash=hashlib.sha256(payload).hexdigest()
        command=self.m.runner_command(code_hash,self.root/'input.json',self.root/'out.json',input_hash=input_hash)
        def read(path):
            reads.append(path.name);return code if path.name.startswith('.zhulong-skill-') else payload
        def run(args,**kw):
            launches.append((args,kw));return SimpleNamespace(stdout=b'{"sum":6}')
        body=command.split("\n",1)[1].rsplit('\nZHULONG_SKILL_SMOKE',1)[0]
        with patch.object(Path,'read_bytes',read),patch.object(subprocess,'run',side_effect=run),patch('builtins.print'):
            exec(body,{})
        self.assertEqual(reads,['.zhulong-skill-'+code_hash+'.py','input.json'])
        self.assertEqual(launches[0][0],['python3','-I','-c',code.decode()]);self.assertEqual(launches[0][1]['input'],payload)

    def test_actual_runner_rejects_input_drift_before_program_execution(self):
        code=b'import json,sys\nprint(json.dumps({"sum":sum(json.load(sys.stdin)["observations"])}))\n'
        code_hash=hashlib.sha256(code).hexdigest(); (self.root/('.zhulong-skill-'+code_hash+'.py')).write_bytes(code)
        source=self.root/'input.json';source.write_text(canonical({'observations':[2,4]}))
        output=self.root/'out.json';command=self.m.runner_command(code_hash,source,output,input_hash=digest({'observations':[2,4]}))
        good=subprocess.run(command,shell=True,cwd=self.root,capture_output=True,timeout=15)
        self.assertEqual(good.returncode,0,good.stderr);self.assertEqual(json.loads(output.read_text()),{'sum':6})
        output.unlink();source.write_text(canonical({'observations':[9]}))
        bad=subprocess.run(command,shell=True,cwd=self.root,capture_output=True,timeout=15)
        self.assertNotEqual(bad.returncode,0);self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
