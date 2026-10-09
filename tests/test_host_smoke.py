"""Optional integration checks against the pinned real host, never claimed as model runs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


@unittest.skipUnless(os.environ.get('HERMES_AGENT_ROOT'),'HERMES_AGENT_ROOT not set; host integration unrun')
class HostStorageTests(unittest.TestCase):
    def test_real_durable_reservation_and_dead_owner_replay(self):
        sys.path.insert(0,os.environ['HERMES_AGENT_ROOT'])
        from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
        from gateway.platforms import api_server_runs
        with tempfile.TemporaryDirectory() as td:
            path=str(Path(td)/'runs.db')
            store=RunIdempotencyStore(path)
            try:
                outcome,record=store.reserve('test-scope','test-key','frozen-fingerprint','run_test',
                    {'run_id':'run_test','status':'queued'},owner_pid=2147483647,owner_started=0)
                self.assertEqual(outcome,'created')
            finally:store.close()
            store=RunIdempotencyStore(path)
            try:
                self.assertEqual(store.lookup('test-scope','test-key','changed')[0],'conflict')
                outcome,record=store.lookup('test-scope','test-key','frozen-fingerprint')
                self.assertEqual(outcome,'reused');self.assertEqual(record['run_id'],'run_test')
                adapter=SimpleNamespace(_run_statuses={},_run_idempotency_store=store,
                                        _run_idempotency_ids=set(),_run_owners={},
                                        _run_idempotency_scope=lambda request:'test-scope')
                status=api_server_runs._durable_run_status(adapter,None,'run_test')
                self.assertEqual(status['status'],'interrupted')
                self.assertEqual(store.lookup('test-scope','test-key','frozen-fingerprint')[1]['status']['status'],'interrupted')
            finally:store.close()
