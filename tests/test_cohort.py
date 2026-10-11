"""Simulated lifecycle tests. These are not real elapsed follow-up evidence."""
import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest


class Clock:
    def __init__(self): self.utc=1000.; self.mono=100.; self.boot='boot-a'
    def __call__(self): return dict(utc=self.utc,monotonic=self.mono,boot_id=self.boot)
    def advance(self,n): self.utc+=n; self.mono+=n


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('cohort'),'CohortLedger is missing')
        import cohort
        self.m=cohort; self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'cohort';self.clock=Clock()
    def registered(self,**changes):
        p=self.m.observation_protocol(['control','treatment'],checkpoints=[0,6,24,48,72],late_tolerance=2,max_gap=10)
        p.update(changes)
        return self.m.CohortLedger.register(self.root,p,clock=self.clock)
    def test_original_denominator_pending_and_no_paid_allocations(self):
        c=self.registered();r=c.report()
        self.assertEqual(r['units'],2);self.assertEqual(r['allocated_measurements'],10)
        self.assertEqual(r['paid_allocations'],0);self.assertEqual(r['states']['not_due'],8)
        self.assertFalse(r['continuous_liveness_supported']);self.assertFalse(r['causal_gain_supported'])
    def test_real_window_receipt_is_immutable_and_later_time_cannot_backfill(self):
        c=self.registered(); c.observe(owner='first'); self.clock.advance(25);r=c.observe(owner='later')
        self.assertEqual(r['states']['missed'],2);self.assertEqual(r['states']['observed'],4)
        saved=copy.deepcopy(r['measurements']);self.clock.advance(60);r=c.report()
        self.assertEqual([x for x in r['measurements'] if x['receipt']],[x for x in saved if x['receipt']])
    def test_claim_collision_expiry_requires_reconciliation_not_replay(self):
        c=self.registered();cell=c.report()['measurements'][0]['id']
        claim=c.claim(cell,'one',lease=1)
        with self.assertRaisesRegex(ValueError,'claimed'):c.claim(cell,'two',lease=1)
        self.clock.advance(2)
        with self.assertRaisesRegex(ValueError,'reconciliation'):c.claim(cell,'two',lease=1)
        c.reconcile();r=c.report();row=next(x for x in r['measurements'] if x['id']==cell)
        self.assertEqual(row['state'],'unknown')
        with self.assertRaises(ValueError):c.finish(claim,{'observed':True})
    def test_clock_rollback_boot_change_and_gap_never_claim_continuity(self):
        for mode in ('rollback','boot','gap'):
            with self.subTest(mode=mode):
                self.root=Path(self.tmp.name)/mode;self.clock=Clock();c=self.registered();c.observe(owner='first')
                self.clock.advance(24)
                if mode=='rollback':self.clock.utc=900
                if mode=='boot':self.clock.boot='boot-b';self.clock.mono=1
                r=c.observe(owner='second')
                self.assertFalse(r['clock_continuity']);self.assertFalse(r['continuous_liveness_supported'])
    def test_replaced_journal_and_hashchain_tampering_reject(self):
        c=self.registered();db=self.root/'journal.db';other=self.root/'copy.db'
        shutil.copyfile(db,other);other.replace(db)
        with self.assertRaisesRegex(ValueError,'identity'):c.report()
    def test_sql_replace_and_delete_cannot_replace_measurement(self):
        c=self.registered();c.observe(owner='first')
        with closing(sqlite3.connect(self.root/'journal.db')) as db,db:
            row=db.execute('SELECT seq,kind,key,payload,previous,hash FROM events LIMIT 1').fetchone()
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?)',row)
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM events')
    def test_strict_protocol_rejects_paid_extra_duplicate_and_nonfinite(self):
        for change in ({'max_paid_calls':1},{'unknown':1},{'units':['a','a']},{'late_tolerance':float('nan')},{'checkpoints':[0,6,6]},{'horizon_seconds':999}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):self.registered(**change)
    def test_watch_stops_at_original_last_window_and_never_allocates_calls(self):
        c=self.registered();start=self.clock.utc
        r=c.watch(owner='watch',wait=self.clock.advance,poll_seconds=1)
        self.assertLessEqual(self.clock.utc,start+74);self.assertEqual(r['states']['observed'],10)
        self.assertEqual(r['paid_allocations'],0);self.assertTrue(r['clock_continuity'])
        self.clock.advance(100);r=c.watch(owner='resume',wait=lambda n:self.fail('horizon reset'))
        self.assertEqual(r['states']['observed'],10)
    def test_watch_oversleep_preserves_missed_windows_and_final_window(self):
        c=self.registered();r=c.watch(owner='watch',wait=lambda n:self.clock.advance(75),poll_seconds=1)
        self.assertEqual(r['states']['observed'],2);self.assertEqual(r['states']['missed'],8)
    def test_duplicate_observe_keeps_receipts_and_report_snapshots_durable(self):
        c=self.registered();a=c.observe(owner='one');b=c.observe(owner='two')
        self.assertEqual(a['measurements'],b['measurements'])
        reopened=self.m.CohortLedger(self.root,clock=self.clock)
        self.assertEqual(reopened.report()['measurements'],a['measurements'])
        self.assertGreaterEqual(len(list((self.root/'reports').glob('*.json'))),1)
    def test_corrupt_anchor_never_reinitializes_existing_cohort(self):
        c=self.registered();(self.root/'anchor.json').unlink()
        with self.assertRaises(ValueError):self.m.CohortLedger(self.root,clock=self.clock)
        with self.assertRaises(FileExistsError):self.registered()

    def test_journal_lock_wait_is_bounded_for_shared_native_deadline(self):
        import fcntl,inspect
        c=self.registered()
        self.assertIn('timeout',inspect.signature(c.journal.transaction).parameters,'journal wait has no deadline bound')
        with (self.root/'journal.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(TimeoutError,'journal_lock'):
                with c.journal.transaction(timeout=.02):self.fail('competing lock acquired')

    def test_duplicate_live_watcher_does_not_observe_or_replace_owner(self):
        import fcntl
        c=self.registered()
        with (self.root/'watch.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'already_owned'):c.watch(wait=self.clock.advance)
        self.assertEqual(c.report()['states']['unrun'],2)

if __name__=='__main__':unittest.main()

