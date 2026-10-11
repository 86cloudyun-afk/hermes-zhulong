"""Independent untrusted producer and exhaustive public-execution cross-check.

The trusted checker never imports this producer or uses row enumeration. This
supplementary probe is evidence about implementation, not its soundness proof.
No providers or optional dependencies. Run with --bundle-out /private/bundle.json
and --output /private/probe.json; --produce-only writes the fixed proposal only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from certified_ticket import canonical_bytes,verify_ticket_certificate,execute_ticket_program
from work_reference import reference_output


def proposed_bundle():
    score=['add',['mul',100,['severity']],['min',['age'],['int',168]],['if',['blocked'],['int',50],['int',0]]]
    priority=['if',['ge',['score'],['int',500]],['text','urgent'],['if',['ge',['score'],['int',300]],['text','high'],['text','normal']]]
    cells=[]
    for severity in range(1,6):
        for blocked in (False,True):
            base=100*severity+50*blocked
            splits=sorted({0,168,87601}|{threshold-base for threshold in (300,500) if 0<threshold-base<168})
            for lo,end in zip(splits,splits[1:]):
                value=base+min(lo,168)
                cells.append({'severity':severity,'blocked':blocked,'lo':lo,'hi':end-1,
                              'score_affine':[1,base] if lo<168 else [0,base+168],
                              'priority':'urgent' if value>=500 else 'high' if value>=300 else 'normal'})
    return {'schema':1,'program':{'schema':1,'kind':'ticket_priority_v1','score':score,'priority':priority},
            'certificate':{'schema':1,'kind':'ticket_priority_v1','cells':cells}}


def crosscheck(bundle):
    p=canonical_bytes(bundle['program']);c=canonical_bytes(bundle['certificate'])
    report=verify_ticket_certificate(p,c)
    if report['status']!='certified_within_scope':raise AssertionError(report)
    rows=0;batches=0;batch=[];max_bytes=0
    def check(records):
        nonlocal batches,max_bytes
        data={'tickets':records};size=len(canonical_bytes(data));max_bytes=max(max_bytes,size)
        assert len(records)<=64 and size<=4096
        actual=execute_ticket_program(p,c,data)
        expected=reference_output('ticket_priority_v1',data)
        assert canonical_bytes(actual)==canonical_bytes(expected)
        assert sorted(r['id'] for r in actual['tickets'])==sorted(r['id'] for r in records)
        batches+=1
    for severity in range(1,6):
        for blocked in (False,True):
            for age in range(87601):
                batch.append({'id':str(len(batch)),'severity':severity,'blocked':blocked,'age_hours':age})
                rows+=1
                if len(batch)==48:check(batch);batch=[]
    if batch:check(batch)
    check([])
    check([{'id':sid,'severity':3,'blocked':False,'age_hours':0} for sid in ('é','A','a','😀',' Z')])
    assert rows==876010
    return {'numeric_rows_crosschecked':rows,'public_execution_batches':batches,'max_input_bytes':max_bytes,
            'list_oracle':'independent_work_reference_plus_id_permutation','bundle_bytes':len(canonical_bytes(bundle)),
            'certificate':report,'claim':'Supplementary exhaustive execution cross-check; not a mechanically formalized soundness proof'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle-out',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--produce-only',action='store_true');args=parser.parse_args();bundle=proposed_bundle()
    if args.bundle_out:args.bundle_out.write_bytes(canonical_bytes(bundle))
    if args.produce_only:result={'bundle_bytes':len(canonical_bytes(bundle)),'checked':False}
    else:result=crosscheck(bundle)
    rendered=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.output:args.output.write_text(rendered)
    print(rendered,end='')


if __name__=='__main__':main()
