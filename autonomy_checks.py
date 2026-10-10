"""Configured facts and mechanical contracts. Path checks are not an OS sandbox."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .autonomy_store import digest, canonical
except ImportError:
    from autonomy_store import digest, canonical

LIMIT=65536
DEFAULTS={'daily_runs':8,'skill_daily_evaluations':16,'input_snapshot_bytes':8388608,'max_active':1,'max_candidates':3,'lease_seconds':120,
          'run_deadline_seconds':600,'max_attempts':3,'request_timeout_seconds':15,'tick_interval_seconds':15}


def bounded_text(value,name,limit=500):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('invalid_'+name)
    return value.strip()


def api_endpoint(value):
    value=bounded_text(value,'api_url',2048).rstrip('/')
    parts=urlsplit(value)
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:raise ValueError('invalid_api_url')
    try: loopback=ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:loopback=parts.hostname.lower()=='localhost'
    if parts.scheme!='https' and not (parts.scheme=='http' and loopback):raise ValueError('insecure_api_url')
    try:parts.port
    except ValueError:raise ValueError('invalid_api_port') from None
    return value[:-3] if value.endswith('/v1') else value


def scoped_path(value,policy):
    if not isinstance(value,str) or not value or '\x00' in value:raise ValueError('invalid_path')
    path=Path(value)
    if '..' in path.parts:raise ValueError('parent_path_rejected')
    path=(path if path.is_absolute() else Path(policy['base'])/path).resolve()
    if not any(path==Path(r) or path.is_relative_to(Path(r)) for r in policy['workspace_roots']):raise ValueError('outside_workspace')
    return path


def contract_policy(raw,policy):
    if not isinstance(raw,dict):raise ValueError('invalid_contract')
    kind=raw.get('type')
    fields={'file_contains':{'path','text'},'json_equals':{'path','field','value'},'argv':{'argv','cwd','timeout_seconds'}}
    if kind not in fields or set(raw)-fields[kind]-{'type','require_change','safe_retry'}:raise ValueError('invalid_contract_fields')
    out=dict(raw)
    for flag in ('require_change','safe_retry'):
        if type(out.get(flag,False)) is not bool:raise ValueError('invalid_'+flag)
        out[flag]=out.get(flag,False)
    if kind in ('file_contains','json_equals'):
        out['path']=str(scoped_path(out.get('path'),policy))
        if kind=='file_contains':out['text']=bounded_text(out.get('text'),'contract_text',4096)
        else:
            out['field']=bounded_text(out.get('field'),'json_field',200)
            if 'value' not in out or len(canonical(out['value']))>4096:raise ValueError('invalid_json_value')
    else:
        argv=out.get('argv')
        if not isinstance(argv,list) or not 1<=len(argv)<=32 or any(not isinstance(a,str) or not a or len(a)>4096 or '\x00' in a for a in argv):raise ValueError('invalid_argv')
        out['cwd']=str(scoped_path(out.get('cwd'),policy))
        timeout=out.get('timeout_seconds',15)
        if type(timeout) is not int or timeout<=0:raise ValueError('invalid_verifier_timeout')
        out['timeout_seconds']=timeout
    return out


def validate_config(raw,base):
    if not isinstance(raw,dict):raise ValueError('invalid_autonomy_config')
    if type(raw.get('enabled',False)) is not bool:raise ValueError('invalid_enabled')
    if not raw.get('enabled',False):return {'enabled':False,'base':str(base)}
    allowed={'enabled','mission','workspace_roots','sources','api_url','api_key_env','api_identity_version','api_profile','learning_enabled','executable_skills',*DEFAULTS}
    if set(raw)-allowed:raise ValueError('unknown_autonomy_setting')
    policy={**DEFAULTS,**raw,'base':str(Path(base).resolve())}
    if type(policy.get('learning_enabled',True)) is not bool:raise ValueError('invalid_learning_enabled')
    policy['learning_enabled']=policy.get('learning_enabled',True)
    for key in DEFAULTS:
        if type(policy[key]) is not int or policy[key]<(0 if key in {'daily_runs','skill_daily_evaluations','input_snapshot_bytes'} else 1):raise ValueError('invalid_'+key)
    policy['mission']=bounded_text(policy.get('mission'),'mission',2000)
    roots=policy.get('workspace_roots')
    if not isinstance(roots,list) or not roots or any(not isinstance(r,str) or not r for r in roots):raise ValueError('missing_workspace_roots')
    policy['workspace_roots']=[str((Path(r) if Path(r).is_absolute() else Path(base)/r).resolve()) for r in roots]
    if any(not Path(r).is_dir() for r in policy['workspace_roots']):raise ValueError('workspace_unavailable')
    policy['api_url']=api_endpoint(policy.get('api_url'))
    policy['api_identity_version']=bounded_text(policy.get('api_identity_version'),'api_identity_version',128)
    policy['api_key_env']=policy.get('api_key_env','API_SERVER_KEY')
    if not isinstance(policy['api_key_env'],str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',policy['api_key_env']):raise ValueError('invalid_credential_env')
    policy['api_profile']=bounded_text(policy.get('api_profile','default'),'api_profile',128)
    sources=policy.get('sources')
    if not isinstance(sources,list) or not sources or len(sources)>32:raise ValueError('missing_sources')
    normalized=[];ids=set()
    for raw_source in sources:
        if not isinstance(raw_source,dict) or set(raw_source)-{'id','domain','path','direction','input_fields','persist_input_fields','contracts'}:raise ValueError('invalid_source')
        source=dict(raw_source);sid=bounded_text(source.get('id'),'source_id',100)
        if sid in ids or source.get('domain') not in {'code','research','personal'}:raise ValueError('invalid_source_identity')
        ids.add(sid);source['id']=sid
        source['path']=str(scoped_path(source.get('path'),policy))
        source['direction']=bounded_text(source.get('direction',policy['mission']),'direction',1000)
        if 'input_fields' in source:
            fields=source['input_fields']
            if not isinstance(fields,list) or not fields or len(fields)>32 or any(not isinstance(f,str) or not f or len(f)>200 for f in fields):raise ValueError('invalid_input_fields')
        try:
            from .task_inputs import rule_for
        except ImportError:
            from task_inputs import rule_for
        rule=rule_for(source)
        if rule is not None:source['persist_input_fields']=rule['fields']
        contracts=source.get('contracts')
        if not isinstance(contracts,dict) or not contracts or len(contracts)>16:raise ValueError('missing_contracts')
        source['contracts']={bounded_text(k,'contract_id',100):contract_policy(v,policy) for k,v in contracts.items()}
        for contract in source['contracts'].values():
            if contract.get('path')==source['path'] and not source.get('input_fields'):raise ValueError('source_output_feedback')
        normalized.append(source)
    policy['sources']=normalized
    try:
        from .skill_evaluator import validate_skills
    except ImportError:
        from skill_evaluator import validate_skills
    policy['executable_skills']=validate_skills(raw.get('executable_skills',[]),normalized)
    return policy


def _read(value,policy):
    path=scoped_path(value,policy)
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        metadata=os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):raise ValueError('not_regular_file')
        # Recheck the resolved name against the opened inode before consuming data.
        current=scoped_path(str(path),policy).stat()
        if (metadata.st_dev,metadata.st_ino)!=(current.st_dev,current.st_ino):raise ValueError('path_changed')
        with os.fdopen(fd,'rb',closefd=False) as stream:content=stream.read(LIMIT+1)
        if len(content)>LIMIT:raise ValueError('file_too_large')
        return content
    finally:os.close(fd)


def _field(value,field):
    for key in field.split('.'):
        if not isinstance(value,dict) or key not in value:raise KeyError('missing_field')
        value=value[key]
    return value


def observe_sources(policy):
    observations=[]
    for source in policy.get('sources',[]):
        item={'id':source['id'],'domain':source['domain'],'direction':source['direction'],
              'contract_ids':list(source['contracts']),'available':False,'reason':'source_unavailable'}
        try:
            content=_read(source['path'],policy).decode('utf-8')
            snapshot=None
            if source.get('persist_input_fields'):
                try:
                    from .task_inputs import project
                    from .skill_evaluator import strict_json
                except ImportError:
                    from task_inputs import project
                    from skill_evaluator import strict_json
                parsed=strict_json(content);snapshot=project(source,parsed)
            if source.get('input_fields'):
                if snapshot is None:parsed=json.loads(content)
                content=canonical({f:_field(parsed,f) for f in source['input_fields']})
            basis={'facts':content,'direction':source['direction'],'contracts':source['contracts'],'mission':policy['mission']}
            if snapshot is not None:basis['input_snapshot']={k:snapshot[k] for k in ('rule_hash','input_hash')}
            revision=digest(basis)
            item.update(available=True,revision=revision,facts=content,reason='observed')
            if snapshot is not None:item['task_input']={**snapshot,'source_revision':revision}
        except (OSError,ValueError,KeyError,UnicodeError):pass
        observations.append(item)
    return observations


def validate_candidates(raw,observations,policy):
    if not isinstance(raw,list) or len(raw)>policy['max_candidates']:raise ValueError('invalid_candidates')
    known={o['id']:o for o in observations if o['available']}
    result=[]
    for candidate in raw:
        if not isinstance(candidate,dict) or set(candidate)-{'source_id','contract_id','objective','reason','expected_benefit','confidence'}:raise ValueError('invalid_candidate_fields')
        source=known.get(candidate.get('source_id'))
        if not source or candidate.get('contract_id') not in source['contract_ids']:raise ValueError('unknown_candidate_contract')
        out=dict(candidate)
        for key in ('objective','reason'):out[key]=bounded_text(out.get(key),key)
        for key,default in [('expected_benefit',0.5),('confidence',None)]:
            value=out.get(key,default)
            if value is None and key=='confidence':out[key]=None;continue
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('invalid_'+key)
            out[key]=float(value)
        out.update(domain=source['domain'],source_revision=source['revision'])
        result.append(out)
    return result


class Verifier:
    def __init__(self,policy):self.policy=policy

    def capture(self,contract):
        result={'verdict':'unknown','contract_hash':digest(contract),'artifact_hash':None,'reason':'verification_unavailable','check_version':1}
        try:
            normalized=contract_policy(contract,self.policy)
            kind=normalized['type']
            if kind=='argv':
                code,content=self._argv(normalized)
                result.update(verdict=code==0,artifact_hash=digest([code,hashlib.sha256(content).hexdigest()]),reason='argv_exit_'+str(code))
            else:
                try:content=_read(normalized['path'],self.policy)
                except FileNotFoundError:
                    result.update(verdict=False,reason='artifact_absent');return result
                result['artifact_hash']=hashlib.sha256(content).hexdigest()
                if kind=='file_contains':valid=normalized['text'] in content.decode('utf-8')
                else:
                    try:valid=canonical(_field(json.loads(content),normalized['field']))==canonical(normalized['value'])
                    except KeyError:valid=False
                result.update(verdict=valid,reason='contract_satisfied' if valid else 'contract_not_satisfied')
        except (OSError,ValueError,UnicodeError,subprocess.SubprocessError):pass
        return result

    def check(self,contract,baseline):
        result=self.capture(contract)
        if baseline.get('verdict') is True:
            result.update(verdict='already_satisfied',reason='satisfied_before_action')
        elif result['verdict'] is True and contract.get('require_change',False) and result['artifact_hash']==baseline.get('artifact_hash'):
            result.update(verdict=False,reason='artifact_unchanged')
        return result

    def _argv(self,contract):
        cwd=scoped_path(contract['cwd'],self.policy)
        process=subprocess.Popen(contract['argv'],cwd=cwd,shell=False,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=(os.name=='posix'))
        selector=selectors.DefaultSelector();output=bytearray()
        try:
            selector.register(process.stdout,selectors.EVENT_READ)
            deadline=time.monotonic()+contract.get('timeout_seconds',15)
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ValueError('verifier_timeout')
                for key,_ in selector.select(min(remaining,0.1)):
                    chunk=os.read(key.fileobj.fileno(),8192)
                    if not chunk:selector.unregister(key.fileobj);continue
                    output.extend(chunk)
                    if len(output)>LIMIT:raise ValueError('verifier_output_limit')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('verifier_timeout')
            return process.wait(timeout=remaining),bytes(output)
        finally:
            selector.close()
            # Clean the entire group, including children retaining a pipe after parent exit.
            if os.name=='posix':
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            elif process.poll() is None:process.kill()
            process.wait(timeout=5)
            process.stdout.close()
