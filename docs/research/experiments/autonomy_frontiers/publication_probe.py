"""Read-only-to-product enumeration of actual SQLite publication gates.

Uses the repository's existing test fixture. The fixture replaces only the
Docker case runner/cleanup; no model or network calls occur. This is bounded
exhaustive testing of selected input partitions, not a deductive proof.
"""
import copy
import itertools
import json
from pathlib import Path
import shutil
import sys
import tempfile
import subprocess
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[4]
OUT=Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT))
from test_skill_replay import ReplayTests, CODE
from autonomy_store import Ledger, canonical
from skill_learning import SkillLearner
from skill_store import SkillStore

AXES=('lease_current','manifest_current','input_rule_current','cleanup_confirmed',
      'verdict_true','code_hash_correct','task_digest_correct','evaluation_digest_correct',
      'origin_submission_correct','origin_passed','all_case_receipts_pass','case_input_hash_correct')

fixture=ReplayTests(methodName='test_new_origin_case_is_private_and_report_is_bound_to_exact_plan')
fixture.setUp()
try:
    goal=fixture.attempt(); job=fixture.claim(); fixture.frozen(job)
    good=fixture.evaluate(job)
    base=fixture.ledger.path
    with tempfile.TemporaryDirectory(prefix='zhulong-finite-publication-') as temp:
        probe_path=Path(temp)/'probe.sqlite'
        counts={'enumerated':0,'published':0,'blocked_without_mutation':0}
        violations=[]
        def restore():
            shutil.copyfile(base,probe_path)
            ledger=Ledger(probe_path)
            store=copy.copy(fixture.store);store.ledger=ledger
            return ledger,store
        for bits in itertools.product((False,True),repeat=len(AXES)):
            flags=dict(zip(AXES,bits));ledger,store=restore();report=copy.deepcopy(good)
            with ledger._connection(True) as connection:
                if not flags['manifest_current']:
                    connection.execute("UPDATE settings SET value='{}' WHERE key='skill_manifests'")
                if not flags['input_rule_current']:
                    connection.execute("UPDATE settings SET value='{}' WHERE key='input_rules'")
            if not flags['cleanup_confirmed']:report['cleanup_confirmed']=False
            if not flags['verdict_true']:report['verdict']='unknown'
            for flag,key in [('code_hash_correct','code_hash'),('task_digest_correct','task_digest'),
                             ('evaluation_digest_correct','evaluation_digest')]:
                if not flags[flag]:report[key]='wrong'
            if not flags['origin_submission_correct']:report['origin_replay']['submission_id']='other'
            if not flags['origin_passed']:report['origin_replay']['passed']=False
            if not flags['all_case_receipts_pass']:report['cases'][0]['passed']=False
            if not flags['case_input_hash_correct']:report['cases'][0]['input_hash']='wrong'
            result=store.finish(copy.deepcopy(job),report,1004 if flags['lease_current'] else 1203)
            states=store.summary()['states'];published=states.get('active',0)==1
            expected=all(bits)
            if bool(result)!=expected or published!=expected or (not expected and states!={'candidate':1}):
                violations.append({'flags':flags,'result':result,'states':states})
            counts['enumerated']+=1
            counts['published']+=int(published)
            counts['blocked_without_mutation']+=int(not result and states=={'candidate':1})
        extra=[]
        for name,alter in [
            ('image_mismatch',lambda r:r.update(image='wrong')),
            ('missing_case',lambda r:r.update(cases=r['cases'][:-1])),
            ('passed_count_mismatch',lambda r:r.update(passed=3)),
            ('numeric_verdict',lambda r:r.update(verdict=1)),
            ('numeric_cleanup',lambda r:r.update(cleanup_confirmed=1)),
            ('numeric_origin_pass',lambda r:r['origin_replay'].update(passed=1)),
        ]:
            ledger,store=restore();report=copy.deepcopy(good);alter(report)
            accepted=store.finish(copy.deepcopy(job),report,1004)
            extra.append({'case':name,'accepted':accepted,'states':store.summary()['states']})
        # Deliberately record layer ownership: direct store.finish has no pause
        # predicate; the supported SkillLearner.tick path owns admission gating.
        ledger,store=restore();ledger.set_pause(True)
        direct_paused=store.finish(copy.deepcopy(job),copy.deepcopy(good),1004)
        ledger,store=restore();ledger.set_pause(True)
        calls=[]
        evaluator=SimpleNamespace(locked=fixture.evaluator.locked,cleanup=lambda:True,
            evaluate=lambda *args:calls.append('evaluate') or copy.deepcopy(good))
        learner=SkillLearner(store,SimpleNamespace(complete_structured=lambda **kw:calls.append('model')),
                             SimpleNamespace(take=lambda:calls.append('budget') or True),evaluator,clock=lambda:1004)
        paused_result=learner.tick(1004,lambda:not ledger.paused())
        paused_candidate_retained=store.summary()['states']=={'candidate':1}
        # Unknown evaluation must preserve bytes, and recovery must not regenerate.
        ledger,store=restore()
        unknown=copy.deepcopy(good);unknown.update(verdict='unknown',cleanup_confirmed=False)
        unknown_accepted=store.finish(copy.deepcopy(job),unknown,1004)
        store.defer(copy.deepcopy(job),1004,'unknown')
        recovered=store.claim(1065)
        result={
            'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'axes':list(AXES),'counts':counts,'violations':violations,
            'extra_negative_cases':extra,
            'pause_layer_observation':{'direct_finish_while_paused_accepted':direct_paused,
                'supported_learner_while_paused':paused_result,'calls':calls,
                'candidate_retained':paused_candidate_retained},
            'unknown_recovery':{'unknown_report_accepted':unknown_accepted,
                'same_code':recovered['code']==CODE,'same_token':recovered['token']==job['token'],
                'same_evaluation_digest':recovered['task']['evaluation_digest']==job['task']['evaluation_digest'],
                'job_generation_advanced':recovered['generation']==job['generation']+1},
            'limitations':['Boolean guard partitions, one scope, one version, one original goal, four trusted cases.',
                'No arbitrary program inputs, process concurrency, real Docker cleanup, SQLite fault injection or formal refinement proof.',
                'Pause gate is external to direct publication transaction; this probe does not establish atomic pause/publication ordering.']}
        (OUT/'publication-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if (violations or counts!={'enumerated':4096,'published':1,'blocked_without_mutation':4095}
                or any(x['accepted'] or x['states']!={'candidate':1} for x in extra)):
            raise SystemExit(1)
finally:
    fixture.doCleanups()
