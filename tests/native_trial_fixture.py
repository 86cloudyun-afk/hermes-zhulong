"""Explicit local mock host versus opted-in actual pinned host test bindings.

No fixture substitutes a positive verifier result. Mock mode still uses real Git
clean/revision checks, file hashes, manifests, journal and artifact qualification.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


def configured_host():
    from runtime_policy import HOST_REVISION
    name=os.environ.get('HERMES_AGENT_ROOT')
    if not name:raise RuntimeError('actual host test requires HERMES_AGENT_ROOT and the pinned Hermes SDK')
    host=Path(name).resolve()
    for relative in ('hermes','gateway/run.py','gateway/platforms/api_server.py','gateway/platforms/api_server_runs.py','hermes_cli/config.py'):
        if not (host/relative).is_file():raise RuntimeError('actual host prerequisite missing: '+relative)
    revision=subprocess.check_output(['git','-C',str(host),'rev-parse','HEAD'],text=True).strip()
    if revision!=HOST_REVISION:raise RuntimeError('actual host prerequisite has wrong pinned revision')
    return host


def install_unit_host(case):
    """Install test-owned inert source/executable bindings, never an actual SDK."""
    import native_trial
    import native_worker_capture
    import runtime_policy
    host=case.root/'unit-host';host.mkdir()
    files={'hermes':'raise SystemExit("inert unit launcher must never execute")\n',
           'gateway/platforms/api_server.py':'# Synthetic unit source: runtime identity basis only.\n',
           'gateway/platforms/api_server_runs.py':'# Synthetic unit source: durable Runs basis only.\n'}
    for name,body in files.items():
        path=host/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
    for args in (['init','-q'],['add','.'],['-c','user.name=Unit Fixture','-c','user.email=fixture@example.invalid','commit','-qm','inert fixture']):
        subprocess.run(['git','-C',str(host),*args],check=True,capture_output=True)
    revision=subprocess.check_output(['git','-C',str(host),'rev-parse','HEAD'],text=True).strip()
    executable=case.root/'inert-docker';executable.write_text('#!'+sys.executable+'\nraise SystemExit("mock transport required")\n');executable.chmod(0o500)
    descriptor={'path':str(executable),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}
    for binding in (patch.object(native_trial,'HOST_REVISION',revision),patch.object(runtime_policy,'HOST_REVISION',revision),
                    patch.object(native_worker_capture,'real_docker_identity',return_value=descriptor)):
        binding.start();case.addCleanup(binding.stop)
    original_run=subprocess.run

    def audit_transport(args,*positional,**kwargs):
        # The production read-only child cannot inherit fixture revision bindings.
        # Intercept ONLY its exact private audit command. All validators remain real.
        if (isinstance(args,list) and len(args)==9 and args[:3]==[sys.executable,str(native_trial.ROOT/'scripts/native_paired_trial.py'),'_audit']
                and args[3]=='--root' and args[5]=='--allocation' and args[7]=='--output'
                and Path(args[4])==case.root/'trial' and Path(args[8]).parent.parent==case.root/'trial'):
            value=native_trial.FrozenTrial(args[4]).qualify_artifacts(args[6])
            native_trial.durable_json(args[8],value,exclusive=True)
            return subprocess.CompletedProcess(args,0,b'',b'')
        return original_run(args,*positional,**kwargs)

    binding=patch.object(subprocess,'run',side_effect=audit_transport);binding.start();case.addCleanup(binding.stop)
    return host
