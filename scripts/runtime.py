"""Initialize, inspect and supervise a protected native Zhulong deployment."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime_channel import atomic_json,read_json
from runtime_policy import create_deployment,load_manifest
from runtime_supervisor import Supervisor


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    init=sub.add_parser('init')
    for name in ('root','work','hermes-root','autonomy-config'):init.add_argument('--'+name,required=True,type=Path)
    init.add_argument('--hermes-command',required=True)
    init.add_argument('--image',required=True);init.add_argument('--port',type=int,default=8642)
    init.add_argument('--max-launches',type=int,default=6)
    for action in ('check','run','status','stop'):
        sub.add_parser(action).add_argument('--deployment',required=True,type=Path)
    args=parser.parse_args()
    if args.action=='init':
        raw=json.loads(args.autonomy_config.read_text());raw=raw.get('autonomy',raw)
        path=create_deployment(args.root,args.work,args.hermes_root,args.image,
            [args.hermes_command,'gateway','run','--no-supervise'],raw,port=args.port,max_launches=args.max_launches)
        print(json.dumps({'deployment':str(path),'state':'initialized'}));return 0
    m,policy=load_manifest(args.deployment,verify=args.action in {'check','run'})
    service=Path(m['root'])/'service'
    if args.action=='status':
        print(json.dumps({'service':read_json(service/'status.json'),'plugin':read_json(service/'health.json')},sort_keys=True));return 0
    if args.action=='stop':
        control=read_json(service/'control.json')
        if not control.get('boot_id'):raise ValueError('no_live_boot')
        control['state']='stopping';atomic_json(service/'control.json',control)
        print(json.dumps({'stop_requested':True,'boot_id':control['boot_id']}));return 0
    supervisor=Supervisor(m,policy)
    if args.action=='check':
        supervisor.native_preflight();print(json.dumps(read_json(service/'boundary.json'),sort_keys=True));return 0
    return supervisor.run()


if __name__=='__main__':sys.exit(main())
