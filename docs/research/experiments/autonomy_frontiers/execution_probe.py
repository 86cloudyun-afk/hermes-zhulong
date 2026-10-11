"""Read-only product imports; every probe artifact is isolated in this directory."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import subprocess

REPO=Path(__file__).resolve().parents[4]
ROOT=Path(sys.argv[1]).resolve()
ROOT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(REPO))
from autonomy_store import Ledger, canonical
from autonomy_checks import Verifier,contract_policy

def ledger_and_effect_fencing():
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='fencing-') as temp:
        directory=Path(temp);ledger=Ledger(directory/'ledger.sqlite')
        goal=ledger.create_goal({'source_id':'s','domain':'code','contract_id':'done','objective':'Fixture','reason':'Fixture'},
            'revision',{'type':'file_contains','path':str(directory/'result'),'text':'done'},
            {'verdict':False,'artifact_hash':None},1000,600)
        old=ledger.claim('old',1000,2)
        admission=ledger.prepare_submission(old,{'input':'immutable fixture'},'fixture-session',
            {'api_url':'http://127.0.0.1:9999','credential_env':'FIXTURE','identity_version':'fixture-v1'},1000,2,2,2,86400)
        fresh=ledger.claim('fresh',1003,20,(goal['id'],))
        # The effect sink is deliberately not integrated with lease checks. This is
        # a protocol illustration, not an observed duplicate in the native gateway.
        effects=0
        for worker in (old,fresh): effects+=1
        old_write=ledger.record_admission(old,admission['submission']['id'],'same-run','running',1003)
        fresh_write=ledger.record_admission(fresh,admission['submission']['id'],'same-run','running',1003)
        return {'old_generation':old.generation,'new_generation':fresh.generation,
                'old_ledger_write_accepted':old_write,'new_ledger_write_accepted':fresh_write,
                'unfenced_simulated_effects':effects,
                'scope':'stale ledger writes are fenced; an uninformed external sink is not'}

def verifier_cases():
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='verifier-') as temp:
        directory=Path(temp);artifact=directory/'result.json'
        verifier=Verifier({'workspace_roots':[str(directory)],'base':str(directory)})
        rows=[]
        for name,raw,expected in (
            ('duplicate-last-correct','{"sum":0,"sum":6}',6),
            ('duplicate-last-wrong','{"sum":6,"sum":0}',6),
            ('nan-in-unchecked-field','{"sum":6,"unused":NaN}',6),
            ('infinity-in-unchecked-field','{"sum":6,"unused":Infinity}',6),
            ('exponent-overflow-in-unchecked-field','{"sum":6,"unused":1e999}',6),
            ('nan-in-checked-field','{"sum":NaN}',6),
            ('infinity-in-checked-field','{"sum":Infinity}',6),
            ('boolean-vs-integer','{"sum":true}',1),
            ('integer-vs-boolean','{"sum":1}',True),
            ('float-vs-integer','{"sum":6.0}',6),
            ('integer-vs-float','{"sum":6}',6.0),
            ('exact-integer','{"sum":6}',6),
        ):
            artifact.write_text(raw)
            contract={'type':'json_equals','path':str(artifact),'field':'sum','value':expected}
            normalized=contract_policy(contract,verifier.policy)
            result=verifier.capture(normalized)
            rows.append({'case':name,'raw':raw,'expected':expected,'verdict':result['verdict'],'reason':result['reason']})
        invalid_contracts=[]
        for value in (float('nan'),float('inf')):
            try:contract_policy({'type':'json_equals','path':str(artifact),'field':'sum','value':value},verifier.policy)
            except ValueError:invalid_contracts.append(True)
            else:invalid_contracts.append(False)
        return {'cases':rows,'nonfinite_contract_values_rejected':invalid_contracts}

def idempotent_adapter_illustration():
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='adapter-') as temp:
        connection=sqlite3.connect(str(Path(temp)/'external.sqlite'))
        connection.executescript('CREATE TABLE fence(resource TEXT PRIMARY KEY, token INTEGER);'
            'CREATE TABLE operations(key TEXT PRIMARY KEY,payload_hash TEXT,result TEXT);'
            'CREATE TABLE effect(value INTEGER); INSERT INTO effect VALUES(0);'
            "INSERT INTO fence VALUES('counter',2);")
        def apply(key,payload,token):
            fingerprint=hashlib.sha256(canonical(payload).encode()).hexdigest()
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                if token<connection.execute("SELECT token FROM fence WHERE resource='counter'").fetchone()[0]:return 'stale'
                prior=connection.execute('SELECT payload_hash,result FROM operations WHERE key=?',(key,)).fetchone()
                if prior:return 'conflict' if prior[0]!=fingerprint else prior[1]
                connection.execute('UPDATE effect SET value=value+1')
                result=str(connection.execute('SELECT value FROM effect').fetchone()[0])
                connection.execute('INSERT INTO operations VALUES(?,?,?)',(key,fingerprint,result))
                return result
        stale=apply('step-1',{'delta':1},1)
        original=apply('step-1',{'delta':1},2)
        # Model lost reply after remote commit, then recovery sends same immutable intent.
        replay=apply('step-1',{'delta':1},2)
        conflict=apply('step-1',{'delta':2},2)
        effects=connection.execute('SELECT value FROM effect').fetchone()[0]
        connection.close()
        return {'stale_request':stale,'first_result':original,'lost_reply_replay_result':replay,
                'same_key_changed_intent':conflict,'effects':effects,
                'scope':'standalone SQLite protocol illustration; not a product connector'}

results={'git_base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
         'ledger_fencing':ledger_and_effect_fencing(),'verifier':verifier_cases(),
         'adapter_illustration':idempotent_adapter_illustration()}
(ROOT/'probe-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False,indent=2))
