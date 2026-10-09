"""Public, bounded Hermes Runs transport; secrets and assistant output are never returned."""
from __future__ import annotations

import http.client
import json
import math
import os
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote

try:
    from .autonomy_checks import api_endpoint
    from .autonomy_store import canonical
except ImportError:
    from autonomy_checks import api_endpoint
    from autonomy_store import canonical


class RunsError(Exception):
    def __init__(self,code:str,retryable:bool=False,admission_unknown:bool=False):
        self.code,self.retryable,self.admission_unknown=code,retryable,admission_unknown
        super().__init__(code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class RunsClient:
    def __init__(self,api_url:str,credential_env:str,identity_version:str,timeout_seconds:int=15,*,profile='default'):
        self.api_url=api_endpoint(api_url)
        self.credential_env,self.identity_version,self.profile=credential_env,identity_version,profile
        self.timeout=timeout_seconds
        self.opener=urllib.request.build_opener(_NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def _request(self,method,path,body=None,headers=None):
        secret=os.environ.get(self.credential_env,'')
        if not secret:raise RunsError('missing_credential')
        if any(ch in secret for ch in '\r\n'):raise RunsError('invalid_credential')
        data=canonical(body).encode() if body is not None else None
        request=urllib.request.Request(self.api_url+path,data=data,method=method,
            headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json',**(headers or {})})
        is_admission=method=='POST' and path=='/v1/runs'
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                data=response.read(65537)
                if len(data)>65536:raise RunsError('response_too_large',admission_unknown=is_admission)
                try:result=json.loads(data)
                except (ValueError,UnicodeError):raise RunsError('invalid_response',admission_unknown=is_admission) from None
                if not isinstance(result,dict):raise RunsError('invalid_response',admission_unknown=is_admission)
                return result
        except urllib.error.HTTPError as exc:
            code='idempotency_conflict' if exc.code==409 else 'http_'+str(exc.code)
            exc.close()
            raise RunsError(code,retryable=exc.code in (408,429) or exc.code>=500,admission_unknown=is_admission and exc.code>=500) from None
        except (urllib.error.URLError,TimeoutError,OSError,http.client.HTTPException):
            raise RunsError('transport_unavailable',retryable=True,admission_unknown=is_admission) from None

    def capabilities(self):
        result=self._request('GET','/v1/capabilities')
        features=result.get('features',{})
        idem=features.get('runs_idempotency',{}) if isinstance(features,dict) else {}
        if not isinstance(idem,dict) or any(features.get(k) is not True for k in ('run_submission','run_status','run_stop')) or idem.get('supported') is not True or idem.get('durable') is not True:
            raise RunsError('blocked_runtime')
        ttl=idem.get('retention_seconds')
        if type(ttl) is not int or ttl<=0:raise RunsError('blocked_runtime')
        return {'retention_seconds':ttl,'durable':True}

    def _identity(self,submission):
        identity=submission.get('execution_identity',{})
        expected={'api_url':self.api_url,'credential_env':self.credential_env,'identity_version':self.identity_version}
        if any(identity.get(k)!=v for k,v in expected.items()) or identity.get('profile','default')!=self.profile:
            raise RunsError('execution_identity_changed')

    @staticmethod
    def _result(raw,admission=False):
        run_id=raw.get('run_id');status=raw.get('status','queued' if admission else None)
        if admission and status=='started':status='queued'
        states={'queued','running','waiting_for_approval','stopping','completed','failed','cancelled','interrupted'}
        if not isinstance(run_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',run_id) or status not in states:
            raise RunsError('invalid_run_response',admission_unknown=admission)
        result={'run_id':run_id,'status':status}
        usage=raw.get('usage')
        if isinstance(usage,dict):
            result['usage']={k:v for k,v in usage.items() if k in {'input_tokens','output_tokens','prompt_tokens','completion_tokens','total_tokens','cached_tokens','cost'} and type(v) in (int,float) and math.isfinite(v) and v>=0} or None
        else:result['usage']=None
        runtime=raw.get('runtime')
        result['runtime']={k:v[:128] for k,v in runtime.items() if k in {'provider','model','api_mode'} and isinstance(v,str)} if isinstance(runtime,dict) else {}
        return result

    def submit(self,submission):
        self._identity(submission)
        key=submission['id']
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',key):raise RunsError('invalid_submission_key')
        session=submission['session_key']
        if not isinstance(session,str) or not re.fullmatch('[A-Za-z0-9_-]{1,200}',session):raise RunsError('invalid_session_key')
        raw=self._request('POST','/v1/runs',submission['request'],{'Idempotency-Key':key,'X-Hermes-Session-Key':session})
        return self._result(raw,True)

    def status(self,submission):
        self._identity(submission)
        run_id=submission.get('run_id')
        if not isinstance(run_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',run_id):raise RunsError('missing_run_id')
        result=self._result(self._request('GET','/v1/runs/'+quote(run_id,safe='')))
        if result['run_id']!=run_id:raise RunsError('run_identity_changed')
        return result

    def stop(self,submission):
        self._identity(submission)
        run_id=submission.get('run_id')
        if not isinstance(run_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',run_id):raise RunsError('missing_run_id')
        return self._result(self._request('POST','/v1/runs/'+quote(run_id,safe='')+'/stop',{}))
