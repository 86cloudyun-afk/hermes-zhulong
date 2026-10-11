"""Production correspondence: real operations, independent SQL faults and gates."""
import importlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_store import Ledger, canonical, digest
from helpers import make_goal, evidence


class RefinementTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('refinement'), 'production refinement checker missing')
        self.r = importlib.import_module('refinement')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'ledger.db'
        self.ledger = Ledger(self.path)

    def audit(self, **kwargs):
        with self.ledger._connection() as c: return self.r.audit(c, **kwargs)

    def valid(self):
        result = self.audit()
        self.assertEqual(result['status'], 'valid_within_scope', result)
        return result

    def prepare(self, lease, ledger=None, **changes):
        args = dict(request={'input':'intent'}, session_key='session', execution_identity={'identity_version':'v1'},
                    now=1001, daily_cap=10, max_active=2, max_attempts=3, retention_seconds=3600)
        args.update(changes)
        return (ledger or self.ledger).prepare_submission(lease, **args)

    def started(self):
        goal = make_goal(self.ledger); lease = self.ledger.claim('owner',1000,100)
        result = self.prepare(lease); self.assertTrue(result['admitted'],result)
        return goal, lease, result['submission']

    def test_real_lifecycle_corresponds_after_every_operation(self):
        self.valid(); goal = make_goal(self.ledger); self.valid()
        lease = self.ledger.claim('owner',1000,100); self.valid()
        self.ledger.renew(lease,1000,120); self.valid()
        sub = self.prepare(lease)['submission']; self.valid()
        self.ledger.record_admission(lease,sub['id'],'run','completed',1002); self.valid()
        self.ledger.record_runtime(lease,sub['id'],{'usage':{'tokens':7}},1002); self.valid()
        self.ledger.record_attempt_result(lease,sub['id'],evidence(goal),1003); self.valid()
        self.ledger.transition(lease,'verifying','check',1003,True,expected_submission_id=sub['id']); self.valid()
        self.ledger.finish(lease,evidence(goal),'succeeded',True,1004,expected_submission_id=sub['id']); self.valid()
        self.ledger.request_cancel(goal['id']); self.valid()
        self.ledger.set_pause(True); self.valid(); self.ledger.set_pause(False); self.valid()
        other=make_goal(self.ledger,source_revision='other'); lease=self.ledger.claim('new',1005,20,(other['id'],))
        self.ledger.release(lease,1005); self.valid()

    def test_sql_faults_name_changed_fields_and_fence_before_allocation(self):
        for sql, field in [("INSERT INTO run_budget VALUES('1970-01-01',9)",'run_budget'),
                           ("UPDATE goals SET state='blocked'",'state'),
                           ("UPDATE goals SET owner='forged'",'owner'),
                           ("UPDATE goals SET submission_id='fake'",'submission_id')]:
            with self.subTest(field=field):
                temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
                ledger=Ledger(Path(temp.name)/'db'); goal=make_goal(ledger); lease=ledger.claim('owner',1000,100)
                with ledger._connection(True) as c:c.execute(sql)
                with ledger._connection() as c:
                    before=[tuple(x) for x in c.execute('SELECT * FROM run_budget')]
                    result=self.r.audit(c)
                self.assertEqual(result['status'],'counterexample',result)
                self.assertIn(field,result['difference']['field'])
                denied=self.prepare(lease,ledger)
                self.assertEqual(denied['reason'],'refinement_blocked',denied)
                with ledger._connection() as c:
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM submissions').fetchone()[0],0)
                    self.assertEqual([tuple(x) for x in c.execute('SELECT * FROM run_budget')],before)

    def test_submission_and_fixed_evidence_faults(self):
        goal,lease,sub=self.started()
        self.ledger.record_attempt_result(lease,sub['id'],evidence(goal),1002)
        for field,value in [('run_id','fake'),('evidence',canonical(evidence(goal,False)))]:
            with self.subTest(field=field):
                with self.ledger._connection(True) as c:
                    c.execute('SAVEPOINT fault'); c.execute('UPDATE submissions SET '+field+'=?',(value,))
                    result=self.r.audit(c)
                    self.assertEqual(result['status'],'counterexample',result)
                    self.assertIn(field,result['difference']['field'])
                    c.execute('ROLLBACK TO fault'); c.execute('RELEASE fault')
        self.valid()

    def test_actual_identity_uses_contract_content_and_request_content(self):
        goal,lease,sub=self.started()
        fields=[('goals','frozen_goal',column,value) for column,value in
                [('candidate','{}'),('source_revision','changed'),('contract','{}'),('baseline','{}'),('created',999),('deadline',999)]]
        fields += [('submissions','frozen_submission',column,value) for column,value in
                   [('request','{}'),('execution_identity','{}'),('session_key','changed'),('created',999),('retention_seconds',999)]]
        for table,trigger,column,value in fields:
            with self.subTest(table=table,column=column), self.ledger._connection(True) as c:
                c.execute('SAVEPOINT fault');c.execute('DROP TRIGGER '+trigger)
                c.execute('UPDATE '+table+' SET '+column+'=?',(value,))
                self.assertEqual(self.r.audit(c)['status'],'counterexample')
                c.execute('ROLLBACK TO fault');c.execute('RELEASE fault')

    def test_restart_does_not_replace_divergence(self):
        make_goal(self.ledger)
        with self.ledger._connection(True) as c:c.execute('UPDATE goals SET attempts=6')
        self.ledger=Ledger(self.path)
        self.assertEqual(self.audit()['status'],'counterexample')

    def test_missing_or_cleared_journal_never_rebootstraps_and_cancel_survives(self):
        for lost in ('drop','clear'):
            with self.subTest(lost=lost):
                temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
                ledger=Ledger(Path(temp.name)/'db');goal=make_goal(ledger)
                with ledger._connection(True) as c:
                    if lost=='drop':c.execute('DROP TABLE refinement_journal')
                    else:
                        for row in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='refinement_journal'").fetchall():c.execute('DROP TRIGGER '+row[0])
                        c.execute('DELETE FROM refinement_journal')
                ledger=Ledger(ledger.path)
                self.assertTrue(ledger.request_cancel(goal['id']))
                lease=ledger.claim('recovery',1000,100)
                self.assertTrue(ledger.finish(lease,evidence(goal,None),'cancelled',True,1001))
                ledger.set_pause(True)
                with ledger._connection() as c:self.assertEqual(self.r.audit(c)['status'],'unavailable')

    def test_cancel_and_recovery_keep_original_divergence(self):
        goal,lease,sub=self.started()
        with self.ledger._connection(True) as c:c.execute('UPDATE run_budget SET runs=99')
        self.ledger.request_cancel(goal['id'])
        self.ledger.finish(lease,evidence(goal,None),'cancelled',True,1002,expected_submission_id=sub['id'])
        self.assertEqual(self.audit()['status'],'counterexample')
        self.assertEqual(self.ledger.get_goal(goal['id'])['state'],'cancelled')

    def test_event_and_sql_commit_and_rollback_together(self):
        before=self.valid()['through_seq']
        with self.assertRaisesRegex(RuntimeError,'crash'),self.ledger._connection(True) as c:
            c.execute("INSERT INTO settings VALUES('paused','true')")
            self.r.record(c,'pause',{'paused':True},1000)
            raise RuntimeError('crash')
        self.assertEqual(self.valid()['through_seq'],before)

    def test_post_admission_failure_rolls_back_all_reservation(self):
        make_goal(self.ledger);lease=self.ledger.claim('owner',1000,100)
        real=self.r.audit; calls=[]
        def fault(c,**kw):
            calls.append(1)
            return real(c,**kw) if len(calls)==1 else {'status':'counterexample','difference':{'field':'injected'}}
        with patch.object(self.r,'audit',side_effect=fault): result=self.prepare(lease)
        self.assertEqual(result['reason'],'refinement_blocked',result)
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM submissions').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM run_budget').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM attempt_predictions').fetchone()[0],0)
        self.valid()

    def test_audit_limits_are_unavailable_not_partial_success(self):
        make_goal(self.ledger)
        for args in ({'max_events':0},{'max_bytes':1}):
            self.assertEqual(self.audit(**args)['status'],'unavailable')
        with self.ledger._connection(True) as c:
            c.execute('DROP TRIGGER frozen_refinement_marker_update')
            c.execute('UPDATE refinement_marker SET schema=999')
        self.assertEqual(self.audit()['status'],'unavailable')

    def test_two_ledgers_fence_admission(self):
        goals=[make_goal(self.ledger,source_revision=str(i)) for i in range(2)]
        other=Ledger(self.path); leases=[self.ledger.claim('one',1000,100,(goals[0]['id'],)),other.claim('two',1000,100,(goals[1]['id'],))]
        barrier=threading.Barrier(2);results=[]
        def reserve(ledger,lease):barrier.wait();results.append(self.prepare(lease,ledger,daily_cap=1))
        workers=[threading.Thread(target=reserve,args=(l,x)) for l,x in zip((self.ledger,other),leases)]
        for w in workers:w.start()
        for w in workers:w.join(10);self.assertFalse(w.is_alive())
        self.assertEqual(sum(r['admitted'] for r in results),1,results);self.valid()

    def test_journal_is_immutable(self):
        with self.ledger._connection(True) as c:
            for sql in ('DELETE FROM refinement_journal','UPDATE refinement_journal SET action=\'pause\''):
                with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)


    def test_workflow_child_cancel_and_block_correspond(self):
        import test_workflow
        fixture=test_workflow.WorkflowTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        child=fixture.create_child()
        with fixture.ledger._connection() as c:self.assertEqual(self.r.audit(c)['status'],'valid_within_scope')
        fixture.ledger.request_cancel(fixture.parent['id']);fixture.store.sync_cancellations(1002)
        with fixture.ledger._connection() as c:self.assertEqual(self.r.audit(c)['status'],'valid_within_scope')
        self.assertTrue(fixture.ledger.get_goal(child)['cancel_requested'])
        self.assertEqual(fixture.ledger.get_goal(fixture.parent['id'])['state'],'cancelled')
        other=test_workflow.WorkflowTests();other.setUp();self.addCleanup(other.doCleanups)
        other.store.sync(1000);other.store.advance(2000,lambda:True)
        self.assertEqual(other.ledger.get_goal(other.parent['id'])['state'],'blocked')
        with other.ledger._connection() as c:self.assertEqual(self.r.audit(c)['status'],'valid_within_scope')

    def skill_fixture(self):
        import test_skill_store
        fixture=test_skill_store.SkillStoreTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        return fixture

    def test_positive_publication_fenced_but_rejection_available(self):
        import test_skill_store
        f=self.skill_fixture();f.attempt('failure');f.store.sync(1002);job=f.store.claim(1002)
        f.store.begin(job,1002);f.store.freeze(job,test_skill_store.CODE,1003)
        with f.ledger._connection(True) as c:c.execute('UPDATE run_budget SET runs=99')
        self.assertFalse(f.store.finish(job,f.report(),1004))
        self.assertEqual(f.store.summary()['states'],{'candidate':1})
        with f.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT reason FROM skill_versions').fetchone()[0],'refinement_blocked')
        self.assertTrue(f.store.finish(job,f.report(verdict=False),1004))
        self.assertEqual(f.store.summary()['states'],{'rejected':1})

    def test_immediate_and_pause_deferred_fallback_preserve_retirement(self):
        for paused in (False,True):
            with self.subTest(paused=paused):
                f=self.skill_fixture();_,_,first=f.publish('first');_,_,second=f.publish('second',now=1020)
                f.attempt('bound-failure',bindings=[second],now=1040)
                if paused:f.ledger.set_pause(True)
                with f.ledger._connection(True) as c:c.execute('UPDATE run_budget SET runs=99')
                f.store.sync(1042)
                if paused:f.ledger.set_pause(False);f.store.sync(1043)
                with f.ledger._connection() as c:
                    old=c.execute('SELECT state,reason FROM skill_versions WHERE id=?',(first['id'],)).fetchone()
                    retired=c.execute('SELECT state FROM skill_versions WHERE id=?',(second['id'],)).fetchone()[0]
                self.assertEqual(retired,'retired')
                self.assertEqual(tuple(old),('standby','refinement_blocked'))

    def test_assurance_status_is_fresh_and_separate_from_model_check(self):
        from autonomy import Controller
        class StatusOnly:
            ledger=self.ledger
        valid=Controller.assurance_status(StatusOnly())
        self.assertEqual(valid['refinement']['status'],'valid_within_scope')
        make_goal(self.ledger)
        with self.ledger._connection(True) as c:c.execute('UPDATE goals SET generation=99')
        self.assertEqual(Controller.assurance_status(StatusOnly())['refinement']['status'],'counterexample')

    def test_install_and_native_protected_copy_include_checker(self):
        import runtime_policy
        self.assertIn('refinement.py',runtime_policy.PLUGIN_FILES)
        self.assertIn('refinement.py',(Path(__file__).resolve().parents[1]/'scripts/install.sh').read_text())

    def test_legacy_checkpoint_is_complete_and_all_pages_verified(self):
        # Remove the entire marker only to simulate a pre-migration legacy DB.
        with self.ledger._connection(True) as c:
            c.execute('DROP TABLE refinement_journal');c.execute('DROP TABLE refinement_marker')
            candidate={'source_id':'legacy','contract_id':'c'};contract={'type':'legacy'}
            rows=[(str(i),str(i),canonical(candidate),'r',canonical(contract),digest(contract),'{}',1000,1600) for i in range(6500)]
            c.executemany('INSERT INTO goals(id,dedupe,candidate,source_revision,contract,contract_hash,baseline,created,deadline) VALUES(?,?,?,?,?,?,?,?,?)',rows)
        self.ledger=Ledger(self.path);report=self.valid()
        self.assertEqual(report['checkpoint_boundary'],51)
        with self.ledger._connection(True) as c:
            c.execute('DROP TRIGGER frozen_refinement_journal_delete')
            c.execute('DELETE FROM refinement_journal WHERE seq=2')
        self.assertEqual(self.audit()['status'],'unavailable')
        self.ledger=Ledger(self.path);self.assertEqual(self.audit()['status'],'unavailable')

    def test_checkpoint_content_count_and_schema_fail_closed(self):
        for damage in ('count','page','schema','duplicate'):
            with self.subTest(damage=damage),self.ledger._connection(True) as c:
                c.execute('SAVEPOINT damage')
                c.execute('DROP TRIGGER frozen_refinement_journal_update')
                c.execute('DROP TRIGGER frozen_refinement_marker_update')
                if damage=='count':c.execute('UPDATE refinement_marker SET item_count=2')
                elif damage=='page':c.execute("UPDATE refinement_journal SET payload=? WHERE seq=1",('{"page":2,"items":[]}',))
                elif damage=='schema':c.execute('UPDATE refinement_journal SET schema=99')
                else:c.execute("UPDATE refinement_journal SET payload=?",('{"page":0,"page":0,"items":[]}',))
                self.assertEqual(self.r.audit(c)['status'],'unavailable')
                c.execute('ROLLBACK TO damage');c.execute('RELEASE damage')

    def test_matching_sql_and_event_invalid_final_transition_is_rejected(self):
        goal=make_goal(self.ledger);lease=self.ledger.claim('owner',1000,100)
        with self.ledger._connection(True) as c:
            c.execute("UPDATE goals SET state='succeeded'")
            self.r.record(c,'transition',{'goal_id':goal['id'],'owner':'owner','generation':lease.generation,
                          'submission_id':None,'state':'succeeded','settled':True},1001)
        result=self.audit();self.assertEqual(result['status'],'counterexample',result)
        self.assertIn('final_truth',result['difference']['field'])

    def test_matching_sql_and_event_invalid_pause_admission_is_rejected(self):
        goal=make_goal(self.ledger);lease=self.ledger.claim('owner',1000,100);self.ledger.set_pause(True)
        payload=dict(goal_id=goal['id'],owner='owner',generation=lease.generation,submission_id='invalid',
            expected_submission_id=None,request_hash=digest({}),session_hash=digest('s'),identity_hash=digest({}),retention_seconds=3600,
            daily_cap=10,max_active=2,max_attempts=3)
        with self.ledger._connection(True) as c:
            c.execute("INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds) VALUES('invalid',?,1,'{}','s','{}',1001,3600)",(goal['id'],))
            c.execute("INSERT INTO run_budget VALUES('1970-01-01',1)")
            c.execute("UPDATE goals SET attempts=1,submission_id='invalid',state='submitting'")
            self.r.record(c,'prepare',payload,1001)
        self.assertEqual(self.audit()['difference']['field'],'paused')

    def test_unknown_extra_counter_and_nonfinite_events_are_unavailable(self):
        for raw in ('{"paused":true,"runs":0}','{"paused":NaN}','{"paused":1e999}','{"paused":true,"paused":false}'):
            with self.subTest(raw=raw),self.ledger._connection(True) as c:
                c.execute('SAVEPOINT fault')
                c.execute("INSERT INTO refinement_journal(schema,action,payload,now) VALUES(1,'pause',?,1000)",(raw,))
                self.assertEqual(self.r.audit(c)['status'],'unavailable')
                c.execute('ROLLBACK TO fault');c.execute('RELEASE fault')

    def test_audit_holds_one_snapshot_while_legal_writer_commits(self):
        goal=make_goal(self.ledger);other=Ledger(self.path)
        c=sqlite3.connect(self.path)
        try:c.execute('PRAGMA journal_mode=WAL')
        finally:c.close()
        original=self.r._actual_items;commits=[]
        def concurrent(c):
            other.request_cancel(goal['id']);commits.append(True)
            yield from original(c)
        with patch.object(self.r,'_actual_items',side_effect=concurrent):self.valid()
        self.assertEqual(commits,[True]);self.valid()


    def test_large_request_is_frozen_as_operand_hash_without_journal_duplication(self):
        goal=make_goal(self.ledger);lease=self.ledger.claim('owner',1000,100)
        request={'input':'PRIVATE_OPERAND_'+'x'*9000000}
        result=self.prepare(lease,request=request)
        self.assertTrue(result['admitted'],result)
        self.assertEqual(self.audit(max_bytes=1048576)['status'],'unavailable')
        report=self.audit()
        self.assertEqual(report['status'],'valid_within_scope',report)
        with self.ledger._connection() as c:
            raw=c.execute("SELECT payload FROM refinement_journal WHERE action='prepare'").fetchone()[0]
        self.assertNotIn('PRIVATE_OPERAND_',raw)
        self.assertLess(len(raw),2000)

    def test_lost_marker_alone_is_unavailable_without_constructor_failure(self):
        make_goal(self.ledger)
        with self.ledger._connection(True) as c:c.execute('DROP TABLE refinement_marker')
        self.ledger=Ledger(self.path)
        self.assertEqual(self.audit()['status'],'unavailable')


    def test_matching_sql_and_event_invalid_admission_guards_are_rejected(self):
        for guard in ('lease_fencing','cancel_requested','state','daily_cap','max_active','attempts'):
            with self.subTest(guard=guard):
                temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
                ledger=Ledger(Path(temp.name)/'db');goal=make_goal(ledger);lease=ledger.claim('owner',1000,10)
                if guard=='cancel_requested':ledger.request_cancel(goal['id'])
                if guard=='state':ledger.transition(lease,'blocked','block',1001)
                payload=dict(goal_id=goal['id'],owner='owner',generation=lease.generation,submission_id='invalid',
                    expected_submission_id=None,request_hash=digest({}),session_hash=digest('s'),identity_hash=digest({}),
                    retention_seconds=3600,daily_cap=10,max_active=2,max_attempts=3)
                if guard=='daily_cap':payload['daily_cap']=0
                if guard=='max_active':payload['max_active']=0
                if guard=='attempts':payload['max_attempts']=True
                now=1011 if guard=='lease_fencing' else 1002
                with ledger._connection(True) as c:
                    c.execute("INSERT INTO submissions(id,goal_id,attempt,request,session_key,execution_identity,created,retention_seconds) VALUES('invalid',?,1,'{}','s','{}',?,3600)",(goal['id'],now))
                    c.execute("INSERT INTO run_budget VALUES('1970-01-01',1)")
                    c.execute("UPDATE goals SET attempts=1,submission_id='invalid',state='submitting'")
                    self.r.record(c,'prepare',payload,now)
                    result=self.r.audit(c)
                self.assertEqual(result['status'],'counterexample',result)
                self.assertIn(guard.replace('attempts','max_attempts'),result['difference']['field'])

    def test_matching_final_evidence_invalid_verdict_is_rejected(self):
        goal,lease,sub=self.started();wrong=evidence(goal,False)
        with self.ledger._connection(True) as c:
            c.execute("INSERT INTO evidence(goal_id,receipt,outcome,data,created) VALUES(?,?,'succeeded',?,1002)",(goal['id'],digest([goal['id'],'succeeded',wrong]),canonical(wrong)))
            c.execute("UPDATE goals SET state='succeeded',owner=NULL,lease_until=NULL")
            c.execute('UPDATE submissions SET settled=1')
            self.r.record(c,'finish',dict(goal_id=goal['id'],owner=lease.owner,generation=lease.generation,
                submission_id=sub['id'],evidence=wrong,outcome='succeeded',settled=True),1002)
        result=self.audit();self.assertEqual(result['status'],'counterexample',result)
        self.assertIn('final_truth.verdict',result['difference']['field'])

    def test_malformed_authoritative_evidence_is_unavailable(self):
        goal,lease,sub=self.started()
        with self.ledger._connection(True) as c:
            c.execute("INSERT INTO evidence(goal_id,receipt,outcome,data,created) VALUES(?,'broken','cancelled','[]',1002)",(goal['id'],))
        self.assertEqual(self.audit()['status'],'unavailable')


    def test_same_column_names_with_unsupported_schema_is_unavailable(self):
        with self.ledger._connection(True) as c:
            c.execute('ALTER TABLE refinement_journal RENAME TO damaged_journal')
            c.execute('CREATE TABLE refinement_journal(seq INTEGER PRIMARY KEY,schema INTEGER NOT NULL,action BLOB NOT NULL,payload TEXT NOT NULL,now REAL NOT NULL)')
            c.execute('INSERT INTO refinement_journal SELECT * FROM damaged_journal')
        self.assertEqual(self.audit()['status'],'unavailable')


    def test_large_corrupt_field_reports_bounded_difference(self):
        make_goal(self.ledger)
        with self.ledger._connection(True) as c:c.execute('UPDATE goals SET owner=?',('X'*100000,))
        report=self.audit();self.assertEqual(report['status'],'counterexample')
        self.assertIn('owner',report['difference']['field'])
        self.assertLess(len(canonical(report)),10000)


    def test_cancel_survives_journal_loss_and_unwritable_fault_diagnostic(self):
        goal=make_goal(self.ledger)
        with self.ledger._connection(True) as c:
            c.execute('DROP TABLE refinement_journal')
            c.execute("CREATE TRIGGER no_diagnostics BEFORE INSERT ON settings WHEN NEW.key='refinement_journal_fault' BEGIN SELECT RAISE(ABORT,'fault_diagnostic_unavailable'); END")
        self.assertTrue(self.ledger.request_cancel(goal['id']))
        self.assertEqual(self.audit()['status'],'unavailable')


    def test_insert_or_replace_cannot_rewrite_journal_checkpoint_or_marker(self):
        self.ledger.set_pause(True)
        with self.ledger._connection(True) as c:
            self.assertEqual(c.execute('PRAGMA recursive_triggers').fetchone()[0],0)
            event=c.execute("SELECT * FROM refinement_journal WHERE action='pause'").fetchone()
            checkpoint=c.execute('SELECT * FROM refinement_journal WHERE seq=1').fetchone()
            marker=c.execute('SELECT * FROM refinement_marker').fetchone()
            attempts=[('event','INSERT OR REPLACE INTO refinement_journal VALUES(?,?,?,?,?)',
                       (event['seq'],event['schema'],event['action'],canonical({'paused':False}),event['now'])),
                      ('checkpoint','INSERT OR REPLACE INTO refinement_journal VALUES(?,?,?,?,?)',
                       (checkpoint['seq'],checkpoint['schema'],checkpoint['action'],canonical({'page':0,'items':[['paused','value',True]]}),checkpoint['now'])),
                      ('marker','INSERT OR REPLACE INTO refinement_marker VALUES(?,?,?,?,?)',
                       (marker['id'],marker['schema'],marker['page_count'],marker['item_count'],'rewritten'))]
            for name,sql,args in attempts:
                with self.subTest(table=name):
                    c.execute('SAVEPOINT replace_fault')
                    try:
                        with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable_refinement'):c.execute(sql,args)
                    finally:
                        c.execute('ROLLBACK TO replace_fault');c.execute('RELEASE replace_fault')
            # A separately corrupted actual row remains divergent: a failed
            # replacement cannot rewrite expected history to bless it.
            c.execute("UPDATE settings SET value='false' WHERE key='paused'")
            divergent=self.r.audit(c)
            self.assertEqual(divergent['status'],'counterexample')
            self.assertEqual(divergent['difference']['field'],'paused.value')
            c.execute("UPDATE settings SET value='true' WHERE key='paused'")
        self.assertTrue(self.ledger.paused());before=self.valid()['through_seq']
        self.ledger.set_pause(False)
        self.assertEqual(self.valid()['through_seq'],before+1)

    def test_existing_marker_gains_insert_guards_without_recheckpoint(self):
        make_goal(self.ledger)
        with self.ledger._connection(True) as c:
            checkpoint=tuple(c.execute('SELECT * FROM refinement_journal WHERE seq=1').fetchone())
            marker=tuple(c.execute('SELECT * FROM refinement_marker').fetchone())
            for table in ('refinement_journal','refinement_marker'):
                c.execute('DROP TRIGGER IF EXISTS frozen_'+table+'_insert')
        self.ledger=Ledger(self.path)
        with self.ledger._connection(True) as c:
            self.assertEqual(tuple(c.execute('SELECT * FROM refinement_journal WHERE seq=1').fetchone()),checkpoint)
            self.assertEqual(tuple(c.execute('SELECT * FROM refinement_marker').fetchone()),marker)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable_refinement'):
                c.execute('INSERT OR REPLACE INTO refinement_marker VALUES(?,?,?,?,?)',marker)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable_refinement'):
                c.execute('INSERT OR REPLACE INTO refinement_journal VALUES(?,?,?,?,?)',checkpoint)
        self.valid()

    def test_unwritable_publication_diagnostic_preserves_negative_retirement(self):
        f=self.skill_fixture();_,_,first=f.publish('first');_,_,second=f.publish('second',now=1020)
        f.attempt('bound-failure',bindings=[second],now=1040)
        with f.ledger._connection(True) as c:
            c.execute('DROP TABLE refinement_journal')
            c.execute("CREATE TRIGGER no_blocked_status BEFORE INSERT ON settings WHEN NEW.key='refinement_last_blocked' BEGIN SELECT RAISE(ABORT,'status_unavailable'); END")
        f.store.sync(1042)
        with f.ledger._connection() as c:
            retired=c.execute('SELECT state,reason FROM skill_versions WHERE id=?',(second['id'],)).fetchone()
            fallback=c.execute('SELECT state,reason FROM skill_versions WHERE id=?',(first['id'],)).fetchone()
            self.assertEqual(tuple(retired),('retired','verified_bound_goal_failure'))
            self.assertEqual(tuple(fallback),('standby','refinement_blocked'))
            self.assertEqual(self.r.audit(c)['status'],'unavailable')


    def test_large_private_mapping_key_is_hashed_in_public_difference(self):
        key='PRIVATE_'+'X'*100000
        with self.ledger._connection(True) as c:c.execute('INSERT INTO run_budget VALUES(?,1)',(key,))
        report=self.audit();self.assertEqual(report['status'],'counterexample')
        self.assertIn('run_budget',report['difference']['field'])
        self.assertIn('sha256',report['difference']['field'])
        self.assertIn('100008',report['difference']['field'])
        self.assertNotIn('PRIVATE_',canonical(report))
        self.assertLess(len(canonical(report)),10000)


if __name__=='__main__':unittest.main()
