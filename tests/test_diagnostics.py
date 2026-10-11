"""Runtime-bound factorial intervention receipts, never narrative causes."""
import copy
import hashlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy_store import Ledger, canonical, digest
from skill_evaluator import DockerEvaluator
import test_skill_replay as replay_fixture


def program(a=False, b=False):
    return ('import json,sys\nx=json.load(sys.stdin)\n'
            f'A={a!r}\nB={b!r}\n'
            'y=sum(x["observations"])\n'
            'if x["observations"]==[2,4]: y+=int(not A)+int(not B)\n'
            'print(json.dumps({"result":{"sum":y}}))\n')


def manifest():
    return {'id':'joint-repair','skill_id':'sum','factors':['a','b'],
            'variants':[{'enabled':['a'],'code':program(True,False)},
                        {'enabled':['b'],'code':program(False,True)},
                        {'enabled':['a','b'],'code':program(True,True)}],
            'negative_controls':[{'input':{'observations':[0]},'output':{'result':{'sum':0}}}]}


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('diagnostics'), 'runtime diagnosis missing')
        from diagnostics import DiagnosticStore, DiagnosticRunner, validate_diagnostics
        self.fixture = replay_fixture.ReplayTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.ledger=f.ledger; self.evaluator=f.evaluator
        self.policy=dict(f.policy,executable_skills=f.tasks)
        self.catalogue=validate_diagnostics([manifest()],self.policy)
        self.store=DiagnosticStore(self.ledger,self.catalogue)
        self.now=[1005]
        self.runner=DiagnosticRunner(self.store,self.evaluator,clock=lambda:self.now[0],daily_budget=16)

    def backend(self, code, data, *args):
        value=sum(data['observations'])
        if data['observations']==[2,4]: value += int('A=True' not in code)+int('B=True' not in code)
        return 0,canonical({'result':{'sum':value}}).encode(),b''

    def origin(self):
        f=self.fixture; f.attempt(); job=f.claim()
        f.store.begin(job,1002); f.store.freeze(job,program(),1003)
        with self.evaluator.locked(),patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'_case',side_effect=self.backend):
            report=self.evaluator.evaluate(program(),job['task'],job['token'],lambda:True)
        self.assertIs(report['verdict'],False)
        self.assertTrue(f.store.finish(job,report,1004))
        self.store.sync(1005)
        return job,report

    def tick(self, gate=lambda:True):
        with patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'_case',side_effect=self.backend):
            self.runner.tick(self.now[0],gate)
        self.now[0]+=1

    def diagnostic(self): return self.store.summary()['diagnoses'][0]

    def test_validation_rejects_incomplete_factorial_or_extra_permissions(self):
        from diagnostics import validate_diagnostics
        for update in ({'variants':manifest()['variants'][:2]}, {'factors':['a']}, {'shell':'danger'}, {'skill_id':'missing'}):
            with self.subTest(update=update),self.assertRaises(ValueError):validate_diagnostics([dict(manifest(),**update)],self.policy)
        self.assertEqual(validate_diagnostics([],self.policy),[])

    def test_runtime_failure_joint_repair_and_frozen_provenance(self):
        job,report=self.origin()
        self.fixture.fact.write_text('{"observations":[999]}')
        for i in range(4):
            self.tick(); self.assertEqual(self.diagnostic()['completed_cells'],i+1)
        result=self.diagnostic()
        self.assertEqual(result['grade'],'intervention_supported')
        self.assertEqual(result['minimal_repair_sets'],[['a','b']])
        self.assertEqual(result['interactions'],[['a','b']])
        self.assertEqual(result['origin']['report_hash'],digest(report))
        self.assertEqual(result['origin']['code_hash'],hashlib.sha256(program().encode()).hexdigest())
        self.assertEqual(result['origin']['input_hash'],digest({'observations':[2,4]}))
        self.assertEqual(len(result['cell_receipts']),4)
        self.assertNotIn('observations',canonical(result))
        with self.ledger._connection(True) as c:
            for table,column in [('diagnostic_plans','payload'),('diagnostic_cells','task'),('diagnostic_cells','report')]:
                with self.assertRaisesRegex(Exception,'frozen_diagnostic'):c.execute('UPDATE '+table+' SET '+column+"='{}'")

    def test_pause_and_atomic_daily_budget_preserve_pending_cells(self):
        self.origin();self.ledger.set_pause(True);self.tick()
        self.assertEqual(self.diagnostic()['completed_cells'],0)
        self.ledger.set_pause(False);self.runner.daily_budget=0;self.tick()
        self.assertEqual(self.diagnostic()['completed_cells'],0)
        self.runner.daily_budget=1;self.tick();self.tick()
        self.assertEqual(self.diagnostic()['completed_cells'],1)
        from diagnostics import DiagnosticRunner
        other=DiagnosticRunner(self.store,self.evaluator,clock=lambda:self.now[0],daily_budget=1)
        with patch.object(self.evaluator,'cleanup',return_value=True):other.tick(self.now[0],lambda:True)
        self.assertEqual(self.diagnostic()['completed_cells'],1)
        self.now[0]+=86400;self.tick();self.assertEqual(self.diagnostic()['completed_cells'],2)

    def test_unknown_cleanup_preserves_frozen_cell_and_no_false_failure(self):
        self.origin()
        with patch.object(self.evaluator,'cleanup',return_value=False):self.runner.tick(1005,lambda:True)
        result=self.diagnostic();self.assertEqual(result['grade'],'inconclusive')
        self.assertEqual(result['completed_cells'],0);self.assertEqual(result['pending_reconciliation'],1)
        from diagnostics import DiagnosticStore,DiagnosticRunner
        other=DiagnosticStore(Ledger(self.ledger.path),self.catalogue)
        self.runner=DiagnosticRunner(other,self.evaluator,clock=lambda:self.now[0],daily_budget=16)
        self.tick();self.assertEqual(other.summary()['diagnoses'][0]['completed_cells'],1)

    def test_missing_report_binding_and_changed_manifest_are_unavailable(self):
        self.origin()
        with self.ledger._connection(True) as c:c.execute("UPDATE settings SET value='{}' WHERE key='skill_manifests'")
        self.tick();self.assertEqual(self.diagnostic()['grade'],'unavailable')
        self.assertEqual(self.diagnostic()['completed_cells'],0)

    def test_negative_control_failure_cannot_support_intervention(self):
        self.origin()
        def bad(code,data,*args):
            if data['observations']==[0]:return 0,b'{"result":{"sum":99}}',b''
            return self.backend(code,data,*args)
        with patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'_case',side_effect=bad):
            for i in range(4):self.runner.tick(1005+i,lambda:True)
        self.assertEqual(self.diagnostic()['grade'],'inconclusive')
        self.assertEqual(self.diagnostic()['minimal_repair_sets'],[])

    def test_forged_report_is_unknown_and_preserves_task_for_reconciliation(self):
        self.origin()
        with patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'evaluate',return_value={'verdict':True,'cleanup_confirmed':True,'cases':[]}):
            self.runner.tick(1005,lambda:True)
        self.assertEqual(self.diagnostic()['grade'],'inconclusive')
        self.assertEqual(self.diagnostic()['pending_reconciliation'],1)

    def test_unknown_reconciliation_precedes_budget_or_any_other_cell(self):
        self.origin()
        with patch.object(self.evaluator,'cleanup',return_value=False):self.runner.tick(1005,lambda:True)
        used=sum(self.store.summary()['daily_evaluations'].values())
        with patch.object(self.evaluator,'cleanup',return_value=False),patch.object(self.evaluator,'evaluate') as launch:
            self.runner.tick(1006,lambda:True)
            launch.assert_not_called()
        self.assertEqual(sum(self.store.summary()['daily_evaluations'].values()),used)
        self.runner.daily_budget=0
        with patch.object(self.evaluator,'cleanup',return_value=True) as cleanup:
            self.runner.tick(1007,lambda:True)
            cleanup.assert_called_once()
        self.assertEqual(self.diagnostic()['pending_reconciliation'],1)
        self.assertFalse(self.store.needs_cleanup(), 'known quiescence must not block unrelated business work')

    def test_repeated_unknown_has_finite_attempts_and_retains_all_cost_receipts(self):
        self.origin()
        with patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'evaluate',return_value={'verdict':'unknown','reason':'evaluator_unavailable','cleanup_confirmed':True}) as evaluate:
            for i in range(10):self.runner.tick(1005+i,lambda:True)
            self.assertEqual(evaluate.call_count,3)
        result=self.diagnostic()
        self.assertEqual(result['grade'],'inconclusive')
        self.assertEqual(result['completed_cells'],0)
        self.assertFalse(self.store.requires_quiescence())
        totals=self.store.summary()['evaluation_receipts']
        self.assertEqual(totals['reserved'],3);self.assertEqual(totals['unknown'],3)
        self.assertEqual(totals['missing_execution_seconds'],0)
        with self.ledger._connection(True) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM diagnostic_reservations WHERE report IS NOT NULL').fetchone()[0],3)
            with self.assertRaisesRegex(Exception,'frozen_diagnostic'):
                c.execute("UPDATE diagnostic_reservations SET report='{}'")
        self.tick();self.assertEqual(self.diagnostic()['completed_cells'],0)

    def test_stale_reservation_cannot_settle_a_reconciled_cell(self):
        self.origin()
        first=self.store.reserve(1005,16);second=self.store.reserve(1006,16)
        with self.evaluator.locked(),patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'_case',side_effect=self.backend):
            report=self.evaluator.evaluate(first['code'],first['task'],first['token'],lambda:True)
        self.assertFalse(self.store.finish(first,report,1007))
        self.assertTrue(self.store.finish(second,report,1007))

    def test_reports_and_plans_cannot_be_deleted(self):
        self.origin();self.tick()
        with self.ledger._connection(True) as c:
            for table in ('diagnostic_plans','diagnostic_cells'):
                with self.subTest(table=table),self.assertRaisesRegex(Exception,'frozen_diagnostic'):
                    c.execute('DELETE FROM '+table)

    def test_unknown_stop_during_cell_reuses_exact_frozen_task(self):
        self.origin();before=[];gate=[True]
        def interrupted(code,data,*args):
            before.append(data);gate[0]=False;return self.backend(code,data,*args)
        with patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'_case',side_effect=interrupted):
            self.runner.tick(1005,lambda:gate[0])
        self.assertEqual(self.diagnostic()['completed_cells'],0)
        self.assertEqual(self.diagnostic()['pending_reconciliation'],1)
        self.assertFalse(self.store.needs_cleanup())
        with self.ledger._connection() as c:
            original=dict(c.execute("SELECT * FROM diagnostic_cells WHERE state='running'").fetchone())
        self.fixture.fact.write_text('{"observations":[999]}')
        self.tick()
        with self.ledger._connection() as c:
            final=dict(c.execute('SELECT * FROM diagnostic_cells WHERE id=?',(original['id'],)).fetchone())
        self.assertEqual(final['task'],original['task']);self.assertEqual(final['token'],original['token'])
        self.assertEqual(self.diagnostic()['completed_cells'],1)

    def test_scan_progresses_past_old_failures_after_many_diagnoses(self):
        self.origin()
        with self.ledger._connection(True) as c:
            original=dict(c.execute('SELECT * FROM skill_versions LIMIT 1').fetchone())
            for i in range(200):
                c.execute('INSERT INTO skill_versions(id,job_id,attempt,scope,code,code_hash,token,created,report,state,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          ('old-'+str(i),original['job_id'],i+10,original['scope'],original['code'],original['code_hash'],
                           original['token'],1003,original['report'],'rejected','trusted_case_failure'))
        for i in range(5):self.store.sync(1005+i)
        with self.ledger._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM diagnostic_plans').fetchone()[0],201)

    def test_removed_configuration_recovers_cleanup_without_new_experiments(self):
        self.origin()
        with patch.object(self.evaluator,'cleanup',return_value=False):self.runner.tick(1005,lambda:True)
        self.assertTrue(self.store.requires_quiescence())
        from diagnostics import DiagnosticStore,DiagnosticRunner
        removed=DiagnosticStore(Ledger(self.ledger.path),[])
        runner=DiagnosticRunner(removed,self.evaluator,daily_budget=16)
        frozen=self.store.summary()['evaluation_receipts']['reserved']
        with patch.object(self.evaluator,'cleanup',return_value=False),patch.object(self.evaluator,'evaluate') as launch:
            runner.tick(1006,lambda:True);launch.assert_not_called()
        self.assertTrue(removed.requires_quiescence())
        with patch.object(self.evaluator,'cleanup',return_value=True),patch.object(self.evaluator,'evaluate') as launch:
            runner.tick(1007,lambda:True);launch.assert_not_called()
        self.assertFalse(removed.requires_quiescence())
        self.assertEqual(removed.summary()['evaluation_receipts']['reserved'],frozen)
        with self.ledger._connection() as c:
            plan=c.execute('SELECT * FROM diagnostic_plans').fetchone()
            self.assertEqual(plan['state'],'unavailable')
            self.assertEqual(plan['reason'],'trusted_configuration_changed')
            self.assertIsNotNone(c.execute("SELECT report FROM diagnostic_reservations LIMIT 1").fetchone()[0])
        restarted=DiagnosticStore(Ledger(self.ledger.path),[])
        self.assertFalse(restarted.requires_quiescence())
        with patch.object(self.evaluator,'locked',side_effect=AssertionError('disabled diagnostics touched Docker')):
            DiagnosticRunner(restarted,self.evaluator).tick(1008,lambda:False)

    def test_sync_marks_removed_quiescent_plans_unavailable(self):
        self.origin();self.tick()
        from diagnostics import DiagnosticStore
        removed=DiagnosticStore(self.ledger,[]);removed.sync(1006)
        with self.ledger._connection() as c:
            plan=c.execute('SELECT * FROM diagnostic_plans').fetchone()
            self.assertEqual(plan['state'],'unavailable')
            self.assertEqual(plan['reason'],'trusted_configuration_changed')
        self.assertFalse(removed.requires_quiescence())

    def test_empty_catalogue_before_skill_tables_is_inert(self):
        from diagnostics import DiagnosticStore,DiagnosticRunner
        ledger=Ledger(self.fixture.root/'empty.db')
        store=DiagnosticStore(ledger,[]);store.sync(1005)
        with ledger._connection() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='skill_versions'").fetchone())
        with patch.object(self.evaluator,'locked',side_effect=AssertionError('disabled diagnostics touched Docker')):
            DiagnosticRunner(store,self.evaluator).tick(1005,lambda:False)
        self.assertEqual(store.summary()['diagnoses'],[])
        self.assertFalse(store.requires_quiescence())

    def test_missing_legacy_input_provenance_is_unavailable(self):
        # Legacy jobs can have old evaluations but cannot create a trusted original replay.
        self.origin()
        from diagnostics import DiagnosticStore,validate_diagnostics
        legacy=copy.deepcopy(self.policy);legacy['executable_skills'][0].pop('replay_origin')
        store=DiagnosticStore(self.ledger,validate_diagnostics([dict(manifest(),id='legacy')],legacy))
        store.sync(1005)
        self.assertEqual(store.summary()['diagnoses'][0]['grade'],'unavailable')


@unittest.skipUnless(os.environ.get('ZHULONG_DIAGNOSTIC_DOCKER_TESTS')=='1','explicit cached local Docker fixture')
class RealDiagnosticTests(DiagnosticTests):
    def origin(self):
        f=self.fixture;f.attempt();job=f.claim();f.store.begin(job,1002);f.store.freeze(job,program(),1003)
        with self.evaluator.locked():report=self.evaluator.evaluate(program(),job['task'],job['token'],lambda:True)
        self.assertIs(report['verdict'],False);self.assertTrue(f.store.finish(job,report,1004))
        self.store.sync(1005);return job,report

    def tick(self, gate=lambda:True):
        self.runner.tick(self.now[0],gate);self.now[0]+=1

    # Keep the real fixture finite; remaining unit edge cases use injected container IO.
    test_pause_and_atomic_daily_budget_preserve_pending_cells=None
    test_unknown_cleanup_preserves_frozen_cell_and_no_false_failure=None
    test_missing_report_binding_and_changed_manifest_are_unavailable=None
    test_negative_control_failure_cannot_support_intervention=None
    test_forged_report_is_unknown_and_preserves_task_for_reconciliation=None
    test_missing_legacy_input_provenance_is_unavailable=None
    test_removed_configuration_recovers_cleanup_without_new_experiments=None
    test_empty_catalogue_before_skill_tables_is_inert=None
    test_sync_marks_removed_quiescent_plans_unavailable=None
    test_scan_progresses_past_old_failures_after_many_diagnoses=None
    test_unknown_reconciliation_precedes_budget_or_any_other_cell=None
    test_reports_and_plans_cannot_be_deleted=None
    test_stale_reservation_cannot_settle_a_reconciled_cell=None
    test_repeated_unknown_has_finite_attempts_and_retains_all_cost_receipts=None
    test_unknown_stop_during_cell_reuses_exact_frozen_task=None
