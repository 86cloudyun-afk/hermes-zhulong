"""Initialize, inspect and supervise a protected native Zhulong deployment."""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime_channel import atomic_json,read_json,status_view
from runtime_policy import create_deployment,load_manifest,load_control_manifest
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
    if args.action in {'status','stop'}:m=load_control_manifest(args.deployment);policy=None
    else:m,policy=load_manifest(args.deployment)
    service=Path(m['root'])/'service'
    if args.action=='status':
        print(json.dumps(status_view(m['root']),sort_keys=True));return 0
    if args.action=='stop':
        request={'deployment_id':m['deployment_id'],'request_id':uuid.uuid4().hex}
        atomic_json(service/'operator-stop.json',request)
        print(json.dumps({'stop_requested':True,'request_id':request['request_id']}));return 0
    supervisor=Supervisor(m,policy)
    if args.action=='check':
        result=supervisor.run(check_only=True)
        if result:return result
        if supervisor.current.get('state')!='checked':
            print(json.dumps({'check_cancelled':True}));return 1
        print(json.dumps(read_json(service/'boundary.json'),sort_keys=True));return 0
    return supervisor.run()


if __name__=='__main__':sys.exit(main())
