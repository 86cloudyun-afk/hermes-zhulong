import importlib
import multiprocessing
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import evidence, make_goal


def prepare_in_process(path, start, output, goal_id=None, crash=False):
    from autonomy_store import Ledger
    ledger = Ledger(Path(path))
    start.wait()
    lease = ledger.claim(str(os.getpid()), 1000, 2)
    result = None
    if lease:
        result = ledger.prepare_submission(lease, {'input': 'intent'}, 'session',
            {'api_url': 'http://127.0.0.1:8642', 'credential_env': 'API_SERVER_KEY', 'identity_version': 'v1'},
            1000, 1, 1, 1, 86400)
        if crash: os._exit(0)
    output.put(result)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('autonomy_store'), 'durable ledger module is missing')
        self.module = importlib.import_module('autonomy_store')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'autonomy.db'
        self.ledger = self.module.Ledger(self.path)

    def prepare(self, lease, **overrides):
        args = dict(request={'input':'intent'}, session_key='session',
            execution_identity={'api_url':'http://127.0.0.1:8642','credential_env':'API_SERVER_KEY','identity_version':'v1'},
            now=1000, daily_cap=1, max_active=1, max_attempts=1, retention_seconds=86400)
        args.update(overrides)
        return self.ledger.prepare_submission(lease, **args)

    def test_goal_dedup_and_frozen_contract(self):
        goal = make_goal(self.ledger)
        self.assertEqual(make_goal(self.ledger)['id'], goal['id'])
        self.assertNotEqual(make_goal(self.ledger, source_revision='r2')['id'], goal['id'])
        lease = self.ledger.claim('owner', 1000, 2)
        wrong = evidence(goal); wrong['contract_hash']='modified'
        with self.assertRaises(ValueError): self.ledger.finish(lease, wrong, 'succeeded', True, 1001)
        self.assertEqual(self.ledger.get_goal(goal['id'])['state'], 'ready')

    def test_final_attempt_recovery_does_not_spend_budget(self):
        goal = make_goal(self.ledger)
        old = self.ledger.claim('old',1000,2)
        submission = self.prepare(old)['submission']
        reopened = self.module.Ledger(self.path)
        new = reopened.claim('new',1003,2)
        self.assertEqual(new.goal_id, goal['id'])
        self.assertFalse(reopened.record_admission(old,submission['id'],'old-run','running',1003))
        self.assertTrue(reopened.record_admission(new,submission['id'],'real-run','running',1003))
        self.assertEqual(reopened.get_goal(goal['id'])['attempts'],1)
        self.assertEqual(reopened.get_goal(goal['id'])['submission']['request'],{'input':'intent'})

    def test_unknown_execution_keeps_capacity(self):
        goal = make_goal(self.ledger)
        lease = self.ledger.claim('a',1000,20)
        self.prepare(lease)
        self.ledger.finish(lease,evidence(goal,None),'unknown_result',False,1001)
        other = make_goal(self.ledger,domain='research')
        other_lease = self.ledger.claim('b',1002,20,ranked_goal_ids=(other['id'],))
        blocked = self.prepare(other_lease,now=1002,daily_cap=8)
        self.assertFalse(blocked['admitted'])
        self.assertEqual(blocked['reason'],'max_active')

    def test_outcome_receipt_is_once_and_old_owner_is_fenced(self):
        goal = make_goal(self.ledger)
        old = self.ledger.claim('a',1000,2)
        self.prepare(old)
        new = self.ledger.claim('b',1003,20)
        self.assertFalse(self.ledger.finish(old,evidence(goal),'succeeded',True,1003))
        self.assertTrue(self.ledger.finish(new,evidence(goal),'succeeded',True,1003))
        self.ledger.finish(new,evidence(goal),'succeeded',True,1003)
        self.assertEqual(len(self.ledger.model_records()['evidence']),1)

    def test_atomic_admission_between_processes(self):
        make_goal(self.ledger)
        make_goal(self.ledger,domain='research')
        ctx=multiprocessing.get_context('spawn')
        start, output = ctx.Event(),ctx.Queue()
        workers=[ctx.Process(target=prepare_in_process,args=(str(self.path),start,output)) for _ in range(4)]
        for p in workers:p.start()
        start.set()
        results=[output.get(timeout=15) for p in workers]
        for p in workers:
            p.join(15); self.assertEqual(p.exitcode,0)
        self.assertEqual(sum(bool(r and r['admitted']) for r in results),1)

    def test_prepare_survives_process_death(self):
        goal=make_goal(self.ledger)
        ctx=multiprocessing.get_context('spawn'); start=ctx.Event();start.set()
        output=ctx.Queue()  # Keep spawn synchronization resources alive until the child exits.
        child=ctx.Process(target=prepare_in_process,args=(str(self.path),start,output,None,True))
        child.start();child.join(15);self.assertEqual(child.exitcode,0)
        ledger=self.module.Ledger(self.path)
        self.assertEqual(ledger.get_goal(goal['id'])['attempts'],1)
        self.assertIsNotNone(ledger.get_goal(goal['id'])['submission'])
        ledger.set_pause(True)
        self.assertIsNotNone(ledger.claim('recovery',1003,2))


if __name__=='__main__':unittest.main()
