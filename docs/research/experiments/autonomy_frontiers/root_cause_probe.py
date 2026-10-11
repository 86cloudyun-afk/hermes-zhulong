"""Finite injected-fault diagnosis demonstration; no Hermes/provider calls."""
import hashlib, itertools, json, pathlib, random, subprocess, sys
ROOT=pathlib.Path(sys.argv[1]).resolve()
ROOT.mkdir(parents=True,exist_ok=True)
def canonical(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
def hashvalue(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def program(a,b):
    return "import sys,json\nv=json.load(sys.stdin)['observations']\n"+('v=[x for x in v if x>=0]\n' if a else '')+('v=v[:-1]\n' if b else '')+"print(json.dumps({'sum':sum(v)}))\n"
def run(values,a,b):
    data={'observations':values}; code=program(a,b)
    result=subprocess.run([sys.executable,'-I','-c',code],input=canonical(data).encode(),capture_output=True,timeout=2,check=True)
    observed=json.loads(result.stdout); expected={'sum':sum(values)}
    return {'input_hash':hashvalue(data),'code_hash':hashlib.sha256(code.encode()).hexdigest(),
            'output_hash':hashlib.sha256(result.stdout).hexdigest(),'observed':observed,'expected':expected,
            'failure':canonical(observed)!=canonical(expected),'faults':{'drop_negative':bool(a),'drop_last':bool(b)}}
contexts={'both_faults_visible':[3,-2,4],'negative_fault_masked':[3,0,4],'last_fault_masked':[3,-2,0]}
trials=[(name,values,a,b,repeat) for name,values in contexts.items() for a,b in itertools.product((0,1),repeat=2) for repeat in range(3)]
random.Random(20261011).shuffle(trials)
results=[{'context':name,'repeat':repeat,**run(values,a,b)} for name,values,a,b,repeat in trials]
# ddmin-like complement deletion, then exhaustive single-element deletions certify 1-minimality only.
def minimize(initial,a,b):
    value=list(initial); n=2; trace=[]
    assert run(value,a,b)['failure']
    while len(value)>=2:
        chunks=[value[i*len(value)//n:(i+1)*len(value)//n] for i in range(n)]
        changed=False
        offset=0
        for chunk in chunks:
            candidate=value[:offset]+value[offset+len(chunk):]; offset+=len(chunk)
            verdict=run(candidate,a,b)['failure']; trace.append({'candidate':candidate,'failure':verdict})
            if verdict: value=candidate; n=max(2,n-1); changed=True; break
        if changed: continue
        if n==len(value): break
        n=min(len(value),2*n)
    checks=[{'removed':i,'remaining':value[:i]+value[i+1:],'failure':run(value[:i]+value[i+1:],a,b)['failure']} for i in range(len(value))]
    return {'original':initial,'reduced':value,'trace':trace,'single_deletion_checks':checks,
            'one_minimal':not any(check['failure'] for check in checks),'claim':'1-minimal for this deterministic predicate; not a globally smallest or unique root cause'}
minimized={'both_faults':minimize([3,-2,4],1,1),'negative_only':minimize([3,-2,4],1,0),'last_only':minimize([3,-2,4],0,1)}
summary={'schema':1,'seed':20261011,'trial_count':len(results),'repeats_per_cell':3,'api_calls':0,
         'execution':'fresh offline Python -I processes, 2 second timeout, trusted deterministic fixture; no container/sandbox certification',
         'observations':results,'minimization':minimized,
         'scope':'Known injected program mutations and these contexts only; not live Hermes root-cause diagnosis'}
(ROOT/'experiment-results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
for name in contexts:
    print(name,[(a,b,sum(r['failure'] for r in results if r['context']==name and r['faults']=={'drop_negative':bool(a),'drop_last':bool(b)})) for a,b in itertools.product((0,1),repeat=2)])
for name,r in minimized.items(): print(name,r['reduced'],'1-minimal=',r['one_minimal'])
