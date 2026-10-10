"""Run untrusted JSON programs in isolated Docker; compare answers on the host."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

try:
    from .autonomy_store import canonical, digest
except ImportError:
    from autonomy_store import canonical, digest

CODE_LIMIT = 6000
OUTPUT_LIMIT = 16384
IMAGE_PATTERN = r'[a-zA-Z0-9./_:-]+@sha256:[0-9a-f]{64}'


def _shape(value, depth=0):
    if depth > 32: raise ValueError('json_depth_limit')
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value): raise ValueError('invalid_json_key')
        for item in value.values(): _shape(item, depth+1)
    elif isinstance(value, list):
        for item in value: _shape(item, depth+1)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    def invalid(value): raise ValueError('nonfinite_json')
    try: value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except RecursionError: raise ValueError('json_depth_limit') from None
    _shape(value)
    # Numeric exponent overflow (1e999) also produces non-finite floats.
    json.dumps(value, allow_nan=False)
    return value


def validate_skills(raw, sources):
    if not isinstance(raw, list) or len(raw) > 4: raise ValueError('invalid_executable_skills')
    result = []; ids = set()
    for item in raw:
        required = {'id', 'source_id', 'contract_id', 'description', 'image', 'examples', 'holdout'}
        if not isinstance(item, dict) or not required <= set(item) or set(item)-required-{'replay_origin'}: raise ValueError('invalid_skill_manifest')
        if 'replay_origin' in item and type(item['replay_origin']) is not bool: raise ValueError('invalid_replay_origin')
        sid = item['id']
        if not isinstance(sid, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', sid) or sid in ids: raise ValueError('invalid_skill_id')
        ids.add(sid)
        source = next((s for s in sources if s['id'] == item['source_id']), None)
        if source is None or item['contract_id'] not in source['contracts']: raise ValueError('invalid_skill_scope')
        if not isinstance(item['description'], str) or not 1 <= len(item['description']) <= 1000: raise ValueError('invalid_skill_description')
        if not isinstance(item['image'], str) or not re.fullmatch(IMAGE_PATTERN, item['image']): raise ValueError('skill_image_digest_required')
        if not isinstance(item['examples'], list) or not isinstance(item['holdout'], list): raise ValueError('invalid_skill_cases')
        if not item['examples'] or len(item['holdout']) < 2 or len(item['examples'])+len(item['holdout']) > 8: raise ValueError('invalid_skill_case_count')
        seen = set()
        for case in item['examples']+item['holdout']:
            if not isinstance(case, dict) or set(case) != {'input', 'output'}: raise ValueError('invalid_skill_case')
            for value in case.values():
                _shape(value)
                if len(json.dumps(value, allow_nan=False, ensure_ascii=False).encode()) > 4096: raise ValueError('skill_case_too_large')
            fingerprint = digest(case['input'])
            if fingerprint in seen: raise ValueError('duplicate_skill_input')
            seen.add(fingerprint)
        # Copy so caller mutation cannot change a trusted task after normalization.
        normalized = strict_json(canonical(item))
        normalized.update(domain=source['domain'], contract_hash=digest(source['contracts'][item['contract_id']]), task_digest=digest(item))
        if item.get('replay_origin'):
            try:
                from .task_inputs import rule_for
            except ImportError:
                from task_inputs import rule_for
            rule = rule_for(source)
            if rule is None or source['contracts'][item['contract_id']]['type'] != 'json_equals': raise ValueError('invalid_replay_scope')
            normalized['input_rule_hash'] = digest(rule)
            normalized['task_digest'] = digest([item, normalized['input_rule_hash']])
        result.append(normalized)
    return result


class DockerError(Exception): pass


class DockerEvaluator:
    def __init__(self, ledger_path):
        self.ledger_path = Path(ledger_path).resolve()
        self.namespace = hashlib.sha256(str(self.ledger_path).encode()).hexdigest()[:20]
        self.lock_path = self.ledger_path.with_suffix('.skill-eval.lock')
        self._lock_fd = None

    @contextmanager
    def locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        acquired = False
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); acquired = True
            except BlockingIOError: pass
            if acquired:
                if self._lock_fd is not None: raise DockerError('nested_evaluation_lock')
                self._lock_fd = fd
            yield acquired
        finally:
            if acquired: self._lock_fd = None
            # Do not explicitly unlock: any still-running Docker client inherits this
            # open-file description and must retain the lock after a parent crash.
            os.close(fd)

    def _command(self, args):
        if self._lock_fd is None: raise DockerError('evaluation_lock_required')
        env = os.environ.copy()
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'): env.pop(key, None)
        return ['docker', '--host=unix:///var/run/docker.sock', *args], env

    def _control(self, args):
        command, env = self._command(args)
        try:
            # Independent watchdog survives a killed caller and bounds inherited-lock lifetime.
            process = subprocess.run(['/usr/bin/timeout', '--signal=KILL', '10', *command], env=env,
                                     capture_output=True, timeout=12, pass_fds=(self._lock_fd,))
            if process.returncode: raise DockerError('docker_control_failed')
            return process.stdout
        except (OSError, subprocess.SubprocessError): raise DockerError('docker_control_unavailable') from None

    def cleanup(self):
        try:
            args = ['ps', '-aq', '--filter', 'label=zhulong.eval='+self.namespace]
            ids = self._control(args).decode().split()
            if any(not re.fullmatch('[0-9a-f]{12,64}', cid) for cid in ids): return False
            for cid in ids:
                info = strict_json(self._control(['inspect', cid]))[0]
                if info['Config'].get('Labels', {}).get('zhulong.eval') != self.namespace: return False
                self._control(['rm', '-f', cid])
            return not self._control(args).strip()
        except (DockerError, ValueError, KeyError, IndexError): return False

    def _verify_boundary(self, info, directory, image):
        config, host = info['Config'], info['HostConfig']
        required = {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'Privileged': False,
                    'PidMode': '', 'IpcMode': 'private', 'Memory': 134217728, 'MemorySwap': 134217728,
                    'NanoCpus': 1000000000, 'PidsLimit': 16}
        if any(host.get(key) != value for key, value in required.items()): raise DockerError('evaluator_isolation_drift')
        if config.get('Image') != image or config.get('User') != '1000:1000': raise DockerError('evaluator_identity_drift')
        if config.get('Labels', {}).get('zhulong.eval') != self.namespace: raise DockerError('evaluator_ownership_drift')
        if host.get('CapDrop') != ['ALL'] or host.get('CapAdd') or host.get('SecurityOpt') != ['no-new-privileges']: raise DockerError('evaluator_privilege_drift')
        if host.get('LogConfig', {}).get('Type') != 'none' or host.get('Tmpfs') != {'/tmp': 'rw,nosuid,nodev,noexec,size=8m'}: raise DockerError('evaluator_storage_drift')
        mounts = info.get('Mounts', [])
        if len(mounts) != 1 or any(m.get(key) != value for m in mounts for key, value in
                {'Type': 'bind', 'Source': str(directory), 'Destination': '/candidate', 'RW': False}.items()): raise DockerError('evaluator_mount_drift')
        for variable in config.get('Env', []):
            key, _, value = variable.partition('=')
            if value and key != 'GPG_KEY' and re.search('KEY|TOKEN|SECRET|PASSWORD|PROXY|DOCKER_HOST', key.upper()): raise DockerError('evaluator_secret_environment')

    def _case(self, code, case_input, image, name):
        # No writable host mount. Expected output and the manifest never enter here.
        with tempfile.TemporaryDirectory(prefix='zhulong-skill-code-', dir=self.ledger_path.parent) as temporary:
            directory = Path(temporary); directory.chmod(0o755)
            program = directory/'main.py'; program.write_bytes(code.encode()); program.chmod(0o444)
            args = ['create', '--pull', 'never', '--name', name, '--label', 'zhulong.eval='+self.namespace,
                    '--log-driver', 'none', '-i', '--network', 'none', '--user', '1000:1000',
                    '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--cpus', '1', '--memory', '128m', '--memory-swap', '128m', '--pids-limit', '16',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=8m', '--workdir', '/tmp',
                    '--mount', 'type=bind,src='+str(directory)+',dst=/candidate,readonly',
                    '--entrypoint', 'python3']
            for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
                args += ['--env', key+'=']
            args += [image, '-I', '/candidate/main.py']
            self._control(args)
            self._verify_boundary(strict_json(self._control(['inspect', name]))[0], directory, image)
            command, env = self._command(['start', '-ai', name])
            process = subprocess.Popen(['/usr/bin/timeout', '--signal=KILL', '3', *command], env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True, pass_fds=(self._lock_fd,))
            selector = selectors.DefaultSelector(); outputs = [bytearray(), bytearray()]
            try:
                process.stdin.write(canonical(case_input).encode()+b'\n'); process.stdin.close()
                for index, stream in enumerate((process.stdout, process.stderr)): selector.register(stream, selectors.EVENT_READ, index)
                deadline = time.monotonic()+2
                while selector.get_map():
                    if time.monotonic() >= deadline: return -1, b'', b'timeout'
                    for key, _ in selector.select(min(0.05, max(0, deadline-time.monotonic()))):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk: selector.unregister(key.fileobj); continue
                        outputs[key.data].extend(chunk)
                        if sum(map(len, outputs)) > OUTPUT_LIMIT: return -1, b'', b'output_limit'
                remaining = deadline-time.monotonic()
                if remaining <= 0: return -1, b'', b'timeout'
                return process.wait(timeout=remaining), bytes(outputs[0]), bytes(outputs[1])
            except subprocess.TimeoutExpired: return -1, b'', b'timeout'
            finally:
                selector.close()
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=5)
                process.stdout.close(); process.stderr.close()

    def evaluate(self, code, task, token, admissible):
        if self._lock_fd is None: raise DockerError('evaluation_lock_required')
        if not isinstance(code, str) or not code.strip() or len(code.encode()) > CODE_LIMIT or '\x00' in code: raise ValueError('invalid_skill_code')
        if not re.fullmatch('[0-9a-f]{32}', token): raise ValueError('invalid_evaluation_token')
        report = {'verdict': 'unknown', 'reason': 'cleanup_unknown', 'cleanup_confirmed': False,
                  'code_hash': hashlib.sha256(code.encode()).hexdigest(), 'task_digest': task['task_digest'],
                  'image': task['image'], 'passed': 0, 'cases': []}
        if task.get('replay_origin'):
            report.update(evaluation_digest=task['evaluation_digest'], origin_replay={**task['origin_replay'], 'passed':False})
        if not self.cleanup(): return report
        try:
            for index, case in enumerate(task.get('_evaluation_cases', task['examples']+task['holdout'])):
                if not admissible(): report['reason'] = 'admission_closed'; return report
                name = 'zhulong-eval-'+self.namespace+'-'+token+'-'+str(index)
                status, output, _ = self._case(code, case['input'], task['image'], name)
                valid = False
                try:
                    value = strict_json(output)
                    valid = status == 0 and ('output' not in case or canonical(value) == canonical(case['output']))
                    if 'predicate' in case:
                        try:
                            from .skill_replay import field
                        except ImportError:
                            from skill_replay import field
                        valid = valid and canonical(field(value, case['predicate']['field'])) == canonical(case['predicate']['value'])
                except (KeyError, ValueError, UnicodeError): pass
                report['cases'].append({'input_hash': digest(case['input']), 'output_hash': hashlib.sha256(output).hexdigest(), 'passed': valid})
                if task.get('replay_origin') and index == task['origin_replay']['case_index']:
                    report['origin_replay']['passed'] = valid
                # Cleanup before any further case or publication, including timeout.
                if not self.cleanup(): return report
                if not valid: report.update(verdict=False, reason='case_failed'); return report
                report['passed'] += 1
            if not admissible(): report['reason'] = 'admission_closed'; return report
            report.update(verdict=True, reason='trusted_cases_passed')
        except (DockerError, OSError, subprocess.SubprocessError): report.update(verdict='unknown', reason='evaluator_unavailable')
        finally:
            report['cleanup_confirmed'] = self.cleanup()
            if not report['cleanup_confirmed']: report.update(verdict='unknown', reason='cleanup_unknown')
        return report
