"""Simulated lifecycle tests. These are not real elapsed follow-up evidence."""
import copy
from contextlib import closing,contextmanager
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
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
    def delayed_transaction_action(self,ledger,action,*,transaction_number=1):
        # Pause before the real lock, so another caller can legitimately commit
        # a newer clock. No transaction, stored value or clock is forged.
        entered=threading.Event();release=threading.Event();original=ledger.journal.transaction
        errors=[];results=[];calls=0
        @contextmanager
        def scheduled(**kwargs):
            nonlocal calls
            if threading.current_thread().name=='delayed-observer':
                calls+=1
                if calls==transaction_number:
                    entered.set()
                    if not release.wait(5):raise RuntimeError('test scheduling timeout')
            with original(**kwargs) as connection:yield connection
        ledger.journal.transaction=scheduled
        def run():
            try:results.append(action())
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=run,name='delayed-observer');thread.start()
        def cleanup():release.set();thread.join(5);ledger.journal.transaction=original
        self.addCleanup(cleanup)
        self.assertTrue(entered.wait(5),'delayed operation did not reach journal boundary')
        def complete():
            release.set();thread.join(5)
            self.assertFalse(thread.is_alive(),'delayed operation remained blocked')
            self.assertEqual(errors,[])
            return results[0]
        return complete

    def test_concurrent_reports_preserve_actual_clock_order(self):
        c=self.registered();c.observe();complete=self.delayed_transaction_action(c,c.report)
        self.clock.advance(1);newer=c.report();older=complete();final=c.report()
        self.assertTrue(newer['clock_valid']);self.assertTrue(older['clock_valid']);self.assertTrue(final['clock_valid'])
        self.assertEqual(final['actual_elapsed_seconds'],1);self.assertEqual(final['clock_reasons'],[])

    def test_concurrent_report_does_not_stop_bounded_watcher(self):
        c=self.registered();c.observe();complete=self.delayed_transaction_action(c,c.report)
        self.clock.advance(1);waits=[]
        def wait(seconds):
            if not waits:complete()
            waits.append(seconds);self.clock.advance(seconds)
        final=c.watch(wait=wait,poll_seconds=1)
        self.assertGreater(len(waits),1);self.assertTrue(final['clock_valid'])
        self.assertEqual(final['actual_elapsed_seconds'],74);self.assertEqual(final['states']['observed'],10)
        self.assertEqual(final['paid_allocations'],0);self.assertEqual(final['allocated_measurements'],10)

    def test_watch_start_and_tick_sample_after_concurrent_report_commits(self):
        # Watch's first two transactions reconcile/report; the next two write
        # start and first tick. Exercise both event capture boundaries.
        for transaction_number in (3,4):
            with self.subTest(transaction_number=transaction_number):
                self.root=Path(self.tmp.name)/str(transaction_number);self.clock=Clock()
                c=self.registered();c.observe()
                complete=self.delayed_transaction_action(c,lambda:c.watch(wait=self.clock.advance,poll_seconds=1),transaction_number=transaction_number)
                self.clock.advance(1);self.assertTrue(c.report()['clock_valid']);final=complete()
                self.assertTrue(final['clock_valid']);self.assertEqual(final['actual_elapsed_seconds'],74)
                self.assertEqual(final['states']['observed'],10);self.assertEqual(final['clock_reasons'],[])

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
    def test_missed_windows_never_reopen_after_same_boot_clock_rollback(self):
        c=self.registered();c.observe(owner='first');self.clock.advance(25);before=c.observe(owner='later')
        self.assertEqual(before['states']['missed'],2)
        self.clock.advance(-18);after=c.observe(owner='rollback')
        self.assertEqual(after['states']['missed'],2);self.assertEqual(after['states']['observed'],4)
        self.assertIsNone(after['actual_elapsed_seconds']);self.assertIn('monotonic_rollback',after['clock_reasons'])
        self.assertEqual(after['allocated_measurements'],10)
        resumed=self.m.CohortLedger(self.root,clock=self.clock).report()
        self.assertEqual(resumed['states']['missed'],2);self.assertIsNone(resumed['actual_elapsed_seconds'])

    def test_report_clock_highwater_survives_restart_without_measurement(self):
        c=self.registered();c.observe();self.clock.advance(25);before=c.report()
        self.assertEqual(before['states']['missed'],2)
        self.clock.advance(-18);c=self.m.CohortLedger(self.root,clock=self.clock)
        after=c.observe(owner='resume')
        self.assertEqual(after['states']['missed'],2);self.assertEqual(after['states']['observed'],2)
        self.assertIsNone(after['actual_elapsed_seconds'])

    def test_clock_invalid_finish_never_records_observed_or_elapsed(self):
        c=self.registered();cell=c.report()['measurements'][0]['id'];claim=c.claim(cell,'owner')
        self.clock.advance(1);c.report();self.clock.advance(-.5)
        result=c.finish(claim)
        self.assertEqual(result['state'],'unknown');self.assertIsNone(result['actual_elapsed_seconds'])
        self.assertIn('monotonic_rollback',result['clock_reasons'])

    def test_boot_change_remains_invalid_after_restart_and_clock_restoration(self):
        c=self.registered();c.observe();self.clock.advance(1);self.clock.boot='boot-b';c.report()
        self.clock.boot='boot-a';self.clock.advance(5)
        c=self.m.CohortLedger(self.root,clock=self.clock);r=c.observe(owner='resume')
        self.assertIsNone(r['actual_elapsed_seconds']);self.assertIn('boot_changed',r['clock_reasons'])
        self.assertEqual(r['states']['observed'],2);self.assertEqual(r['states']['unknown'],2)

    def test_gap_alone_preserves_actual_elapsed_without_continuity_claim(self):
        c=self.registered();c.observe();self.clock.advance(25);r=c.observe()
        self.assertEqual(r['actual_elapsed_seconds'],25)
        self.assertEqual(r['clock_reasons'],['observation_gap']);self.assertFalse(r['clock_continuity'])
        self.assertEqual(r['states']['observed'],4)

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
