import importlib
import json
import sqlite3
import unittest

from autonomy_store import canonical, digest


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('metacognition'), 'attempt-time monitoring module missing')
        self.m = importlib.import_module('metacognition')
        self.c = sqlite3.connect(':memory:'); self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        self.c.executescript('''CREATE TABLE goals(id TEXT PRIMARY KEY,candidate TEXT,contract_hash TEXT,attempts INTEGER);
            CREATE TABLE submissions(id TEXT PRIMARY KEY,goal_id TEXT,attempt INTEGER,execution_identity TEXT,
              created REAL,settled INTEGER,evidence TEXT,evidence_created REAL,settled_at REAL,request TEXT,forecast REAL);
            CREATE TABLE task_inputs(goal_id TEXT PRIMARY KEY,input_hash TEXT);''')
        self.m.initialize(self.c)
        self.identity = {'api_url': 'local', 'identity_version': 'v1'}
        self.goal = {'id': 'current', 'source_id': 'facts', 'domain': 'code', 'contract_id': 'work',
                     'contract_hash': digest({'type': 'test'}), 'attempts': 0, 'task_input': None}
        self.request = {'input': canonical({'objective': 'Work'})}
        self.policy = self.m.validate_monitoring({'enabled': True})

    def add_attempt(self, sid, verdict, *, source='facts', domain='code', contract=None,
                    identity=None, attempt=1, created=1, evidence_created=2, settled_at=3, settled=1):
        candidate = {'source_id': source, 'domain': domain, 'contract_id': 'work'}
        self.c.execute('INSERT INTO goals VALUES(?,?,?,?)',
                       (sid,canonical(candidate),contract or self.goal['contract_hash'],attempt))
        self.c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (sid,sid,attempt,canonical(identity or self.identity),created,settled,
                        canonical({'verdict':verdict,'contract_hash':contract or self.goal['contract_hash']}),
                        evidence_created,settled_at,canonical(self.request),.7))

    def test_zero_sample_prior_and_trusted_constant_are_honest(self):
        prior = self.m.capture(self.c,self.goal,self.identity,self.request,10,self.policy)
        self.assertEqual(prior['probability'],.5)
        self.assertEqual(prior['provenance']['origin'],'prior_only')
        constant = self.m.capture(self.c,self.goal,self.identity,self.request,10,
                                 self.m.validate_monitoring({'enabled':True,'mode':'constant','constant_probability':.9}))
        self.assertEqual(constant['probability'],.9)
        self.assertEqual(constant['provenance']['origin'],'trusted_constant')
        self.assertEqual(constant['provenance']['samples'],0)

    def test_estimate_excludes_future_unknown_unsettled_and_other_scope(self):
        self.add_attempt('valid',True)
        self.add_attempt('future',False,evidence_created=11)
        self.add_attempt('future_settle',False,settled_at=11)
        self.add_attempt('unknown',None)
        self.add_attempt('unsettled',False,settled=0)
        self.add_attempt('source',False,source='other')
        self.add_attempt('domain',False,domain='research')
        self.add_attempt('contract',False,contract='different')
        self.add_attempt('identity',False,identity={'identity_version':'other'})
        self.add_attempt('retry',False,attempt=2)
        prediction=self.m.capture(self.c,self.goal,self.identity,self.request,10,self.policy)
        self.assertEqual(prediction['provenance']['samples'],1)
        self.assertAlmostEqual(prediction['probability'],2/3)
        self.assertEqual(prediction['provenance']['sample_ids'],['valid'])
        retry=self.m.capture(self.c,{**self.goal,'attempts':1},self.identity,self.request,10,self.policy)
        self.assertAlmostEqual(retry['probability'],1/3)
        self.assertEqual(retry['provenance']['stratum'],'retry')

    def test_capture_revalidates_last_estimator_before_admission(self):
        captured=self.m.capture(self.c,self.goal,self.identity,self.request,10,self.policy)
        self.add_attempt('new',True)
        with self.assertRaisesRegex(ValueError,'monitoring_capture_stale'):
            self.m.prepare(self.c,self.goal,self.identity,self.request,12,self.policy,capture=captured,recheck=None)

    def test_recheck_requires_real_bound_receipt_and_freezes_final_request(self):
        captured=self.m.capture(self.c,self.goal,self.identity,self.request,10,self.policy)
        request=self.m.apply_directive(self.request,captured)
        self.assertIn('functional_monitoring',json.loads(request['input']))
        with self.assertRaisesRegex(ValueError,'monitoring_recheck_required'):
            self.m.prepare(self.c,self.goal,self.identity,request,11,self.policy,capture=captured)
        receipt={'checks':1,'started_at':10,'finished_at':10.5,
                 'evidence':{'contract_hash':self.goal['contract_hash'],'verdict':False,'reason':'precondition check','check_version':2,'artifact_hash':None}}
        prediction=self.m.prepare(self.c,self.goal,self.identity,request,11,self.policy,capture=captured,recheck=receipt)
        self.assertEqual(prediction['request_hash'],digest(request))
        self.assertEqual(prediction['action'],'recheck')
        self.assertEqual(prediction['extra_checks'],1)
        self.assertEqual(prediction['extra_check_seconds'],.5)
        candidate={k:self.goal[k] for k in ('source_id','domain','contract_id')}
        self.c.execute('INSERT INTO goals VALUES(?,?,?,?)',('current',canonical(candidate),self.goal['contract_hash'],1))
        self.c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       ('submission','current',1,canonical(self.identity),11,0,None,None,None,canonical(request),.5))
        self.m.record(self.c,'submission',prediction)
        frozen=self.m.predictions(self.c)['submission']
        self.assertEqual(frozen['recheck_receipt'],receipt)
        with self.assertRaisesRegex(sqlite3.IntegrityError,'frozen_attempt_prediction'):
            self.c.execute("UPDATE attempt_predictions SET prediction='{}'")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'frozen_attempt_prediction'):
            self.c.execute('DELETE FROM attempt_predictions')
        forged={**prediction,'probability':.99}
        with self.assertRaisesRegex(ValueError,'monitoring_prediction_invalid'):
            self.m.record(self.c,'submission',forged)

    def test_historical_settled_submission_cannot_acquire_a_backdated_forecast(self):
        policy=self.m.validate_monitoring({'enabled':True,'mode':'masked'})
        prediction=self.m.prepare(self.c,self.goal,self.identity,self.request,10,policy)
        candidate={k:self.goal[k] for k in ('source_id','domain','contract_id')}
        self.c.execute('INSERT INTO goals VALUES(?,?,?,?)',('current',canonical(candidate),self.goal['contract_hash'],1))
        self.c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       ('historical','current',1,canonical(self.identity),10,1,
                        canonical({'verdict':True,'contract_hash':self.goal['contract_hash']}),11,11,
                        canonical(self.request),.5))
        with self.assertRaisesRegex(ValueError,'monitoring_prediction_after_outcome'):
            self.m.record(self.c,'historical',prediction)
        self.c.execute('ALTER TABLE submissions ADD COLUMN run_id TEXT')
        self.c.execute("UPDATE submissions SET settled=0,evidence=NULL,run_id='already-dispatched'")
        with self.assertRaisesRegex(ValueError,'monitoring_prediction_after_dispatch'):
            self.m.record(self.c,'historical',prediction)

    def test_masked_policy_changes_action_without_claiming_probability(self):
        policy=self.m.validate_monitoring({'enabled':True,'mode':'masked'})
        captured=self.m.capture(self.c,self.goal,self.identity,self.request,10,policy)
        self.assertEqual(captured['action'],'continue')
        self.assertEqual(captured['probability'],.5)
        self.assertTrue(captured['provenance']['monitor_masked'])
        prediction=self.m.prepare(self.c,self.goal,self.identity,self.request,10,policy,capture=captured)
        self.assertEqual(prediction['extra_checks'],0)

    def test_recheck_receipt_rejects_missing_verdict_and_accepts_mechanical_unknown(self):
        captured=self.m.capture(self.c,self.goal,self.identity,self.request,10,self.policy)
        request=self.m.apply_directive(self.request,captured)
        valid={'contract_hash':self.goal['contract_hash'],'verdict':'unknown',
               'check_version':2,'reason':'verification_unavailable','artifact_hash':None}
        receipt={'checks':1,'started_at':10,'finished_at':10.5,'evidence':valid}
        for patch in ({'verdict':'succeeded'},{'contract_hash':'wrong'},{'check_version':True}):
            with self.subTest(patch=patch),self.assertRaisesRegex(ValueError,'monitoring_recheck_invalid'):
                self.m.prepare(self.c,self.goal,self.identity,request,11,self.policy,capture=captured,
                               recheck={**receipt,'evidence':{**valid,**patch}})
        no_verdict={k:v for k,v in valid.items() if k!='verdict'}
        with self.assertRaisesRegex(ValueError,'monitoring_recheck_invalid'):
            self.m.prepare(self.c,self.goal,self.identity,request,11,self.policy,capture=captured,
                           recheck={**receipt,'evidence':no_verdict})
        prediction=self.m.prepare(self.c,self.goal,self.identity,request,11,self.policy,capture=captured,recheck=receipt)
        self.assertEqual(prediction['recheck_receipt']['evidence']['verdict'],'unknown')

    def test_disabled_preserves_legacy_abstention(self):
        captured=self.m.capture(self.c,{**self.goal,'confidence':None},self.identity,self.request,10,
                                self.m.validate_monitoring(None))
        self.assertIsNone(captured['probability'])
        self.assertEqual(captured['action'],'continue')
        self.assertEqual(captured['provenance']['origin'],'goal_prior_reused_before_submission')

    def test_recheck_without_preflight_capture_is_rejected(self):
        captured=self.m.capture(self.c,self.goal,self.identity,self.request,10,self.policy)
        request=self.m.apply_directive(self.request,captured)
        receipt={'checks':1,'started_at':11,'finished_at':11,
                 'evidence':{'contract_hash':self.goal['contract_hash'],'verdict':False}}
        with self.assertRaisesRegex(ValueError,'monitoring_capture_required'):
            self.m.prepare(self.c,self.goal,self.identity,request,11,self.policy,recheck=receipt)

    def test_policy_rejects_nonfinite_and_unbounded_checks(self):
        self.assertFalse(self.m.validate_monitoring(None)['enabled'])
        for raw in ({'threshold':float('nan')},{'max_rechecks':2},{'max_rechecks':True},
                    {'mode':'postresult'},{'enabled':'yes'},{'constant_probability':-1}):
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.m.validate_monitoring(raw)


if __name__=='__main__':unittest.main()
