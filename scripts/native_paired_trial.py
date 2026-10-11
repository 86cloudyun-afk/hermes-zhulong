"""Freeze a provider-free paired protocol; execute only with explicit --paid."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_trial import FrozenTrial
from cohort import canonical,strict_read,durable_json


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    freeze=sub.add_parser('freeze');freeze.add_argument('--root',type=Path,required=True);freeze.add_argument('--host',type=Path,required=True)
    freeze.add_argument('--image',required=True);freeze.add_argument('--oracle',type=Path,required=True);freeze.add_argument('--fixtures',type=Path);freeze.add_argument('--seed',type=int,default=20261011);freeze.add_argument('--hermes-command',type=Path)
    for name in ('execute','summary','reconcile'):
        cmd=sub.add_parser(name);cmd.add_argument('--root',type=Path,required=True)
        if name=='execute':cmd.add_argument('--paid',action='store_true')
    audit=sub.add_parser('_audit',help=argparse.SUPPRESS);audit.add_argument('--root',type=Path,required=True);audit.add_argument('--allocation',required=True);audit.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='_audit':
        trial=FrozenTrial(args.root);durable_json(args.output,trial.qualify_artifacts(args.allocation),exclusive=True);return
    if args.command=='freeze':
        fixtures=None
        if args.fixtures:
            manifest=strict_read(args.fixtures)
            if not isinstance(manifest,dict) or set(manifest)!={'schema','fixtures'} or type(manifest['schema']) is not int or manifest['schema']!=1:raise ValueError('invalid_fixture_manifest')
            fixtures=manifest['fixtures']
        trial=FrozenTrial.freeze(args.root,host=args.host,image=args.image,oracle=args.oracle,fixtures=fixtures,seed=args.seed,hermes_command=args.hermes_command);result=trial.summary()
    else:
        trial=FrozenTrial(args.root)
        result=trial.execute(paid=args.paid) if args.command=='execute' else trial.reconcile() if args.command=='reconcile' else trial.summary()
    durable_json(args.root/'report.json',result)
    print(canonical(result))


if __name__=='__main__':main()
