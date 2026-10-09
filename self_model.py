"""Scoped capability estimates from independent receipts; narratives never become truth."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

try:
    from .autonomy_store import canonical,digest
except ImportError:
    from autonomy_store import canonical,digest


def _metrics(samples):
    pairs=[(p,int(y)) for p,y in samples if p is not None]
    good=[p for p,y in pairs if y];bad=[p for p,y in pairs if not y]
    ece=None
    if pairs:
        ece=0
        for i in range(5):
            bucket=[(p,y) for p,y in pairs if i/5<=p<(i+1)/5 or (i==4 and p==1)]
            if bucket:ece+=len(bucket)/len(pairs)*abs(sum(p for p,_ in bucket)/len(bucket)-sum(y for _,y in bucket)/len(bucket))
    return {'forecast_samples':len(pairs),'brier':sum((p-y)**2 for p,y in pairs)/len(pairs) if pairs else None,
            'ece':ece,'mean_confidence':sum(p for p,_ in pairs)/len(pairs) if pairs else None,
            'confidence_on_correct':sum(good)/len(good) if good else None,
            'confidence_on_error':sum(bad)/len(bad) if bad else None,
            'error_discrimination':'available' if good and bad else 'unavailable'}


def _stats(goals,truth,submissions,scope=None):
    verified=[g for g in goals if g['id'] in truth]
    successes=sum(truth[g['id']]['outcome']=='succeeded' for g in verified)
    forecasts=[(g.get('confidence'),truth[g['id']]['outcome']=='succeeded') for g in verified]
    first=[];attempts=[]
    ids={g['id'] for g in goals}
    for s in submissions:
        if s['goal_id'] not in ids or (scope is not None and s['execution_identity']!=scope):continue
        ev=s.get('evidence')
        if ev and type(ev.get('verdict')) is bool:
            attempts.append((s.get('forecast'),ev['verdict']))
            if s['attempt']==1:first.append(ev['verdict'])
        elif s['attempt']==1 and s['goal_id'] in truth:
            # A single final verified attempt also supplies first-pass truth.
            goal=next(g for g in verified if g['id']==s['goal_id'])
            if goal['attempts']==1:first.append(truth[goal['id']]['outcome']=='succeeded')
    attempt_success=sum(y for _,y in attempts)
    n=len(verified)
    return {'verified_samples':n,'success':successes,'failure':n-successes,
            'accuracy':successes/n if n else None,'capability_status':'limited_verified_evidence' if n else 'unknown',
            'unknown':sum(g['state']=='unknown_result' for g in goals),'blocked':sum(g['state']=='blocked' for g in goals),
            'already_satisfied':sum(g['state']=='already_satisfied' for g in goals),
            'first_attempt_verified':len(first),'first_attempt_success':sum(first),
            'eventual_success':successes,'eventual_verified':n,
            'expected_success_estimate':(successes+1)/(n+2),'estimate_method':'Laplace; scope and sample size apply',
            **_metrics(forecasts),'attempts':{'verified_samples':len(attempts),'success':attempt_success,
                'failure':len(attempts)-attempt_success,'forecast_origin':'goal_prior_reused_before_submission',**_metrics(attempts)}}


class SelfModel:
    def __init__(self,ledger,base:Path):
        self.ledger,self.base=ledger,Path(base)
        self.base.mkdir(parents=True,exist_ok=True)

    def _export(self,snapshot):
        fd,name=tempfile.mkstemp(prefix='.self-model-',dir=self.base)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(canonical(snapshot)+'\n');stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.base/'self_model.json')
            if os.name=='posix':
                directory=os.open(self.base,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                try:os.fsync(directory)
                finally:os.close(directory)
        finally:
            try:os.unlink(name)
            except FileNotFoundError:pass

    def refresh(self):
        records=self.ledger.model_records();goals=records['goals'];submissions=records['submissions']
        revision=digest({'goals':sorted((g['id'],g['state'],g['attempts']) for g in goals),
                         'receipts':sorted(e['receipt'] for e in records['evidence']),
                         'attempt_evidence':[(s['id'],s.get('evidence')) for s in submissions]})
        versions=self.ledger.model_versions(1)
        if versions and versions[0]['evidence_revision']==revision:
            self._export(versions[0]);return versions[0]
        truth={e['goal_id']:e for e in records['evidence'] if e['outcome'] in ('succeeded','failed')}
        domains={domain:_stats([g for g in goals if g['domain']==domain],truth,submissions) for domain in ('code','research','personal')}
        contexts={}
        for goal in goals:
            identity=goal['submission']['execution_identity'] if goal['submission'] else {}
            key=digest([goal['domain'],identity])
            if key not in contexts:
                group=[g for g in goals if g['domain']==goal['domain'] and (g['submission']['execution_identity'] if g['submission'] else {})==identity]
                contexts[key]={'domain':goal['domain'],'execution_context':identity,**_stats(group,truth,submissions,identity)}
        snapshot={'schema':1,'evidence_revision':revision,'domains':domains,'contexts':contexts,
                  'scope':'Configured local contracts; no subjective consciousness or general capability claim',
                  'active_commitments':[{'goal_id':g['id'],'domain':g['domain'],'state':g['state'],'objective':g['objective'],
                      'deadline':g['deadline'],'attempts':g['attempts']} for g in goals
                      if g['state'] in ('ready','submitting','running','verifying','unknown_result','blocked')],
                  'policy_hypotheses':[{'domain':g['domain'],'kind':'failed_contract','status':'hypothesis',
                      'scope':g['contract_id'],'evidence_receipt':truth[g['id']]['receipt'],
                      'statement':'Previous execution did not satisfy this configured contract; reconsider prerequisites before related work.'}
                      for g in goals if g['id'] in truth and truth[g['id']]['outcome']=='failed'][-20:]}
        snapshot=self.ledger.save_model(snapshot)
        self._export(snapshot);return snapshot

    def snapshot(self):
        versions=self.ledger.model_versions(1)
        return versions[0] if versions else self.refresh()

    def restore(self,version:int):
        with self.ledger._connection() as c:
            row=c.execute('SELECT snapshot FROM model_versions WHERE version=?',(version,)).fetchone()
        if not row:raise ValueError('unknown_model_version')
        snapshot=json.loads(row[0]);self._export(snapshot);return snapshot

    def expected_success(self,domain:str,context=None):
        snapshot=self.snapshot()
        if context is not None:
            for entry in snapshot['contexts'].values():
                if entry['domain']==domain and entry['execution_context']==context:return entry['expected_success_estimate']
            return 0.5
        return snapshot['domains'].get(domain,{}).get('expected_success_estimate',0.5)
