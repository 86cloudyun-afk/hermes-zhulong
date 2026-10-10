import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))


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


if __name__ == '__main__': unittest.main()
