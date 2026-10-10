"""Read-only transcript evidence for the finite native executable-skill smoke."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def runner_command(code_hash, source, output):
    return "python3 - <<'ZHULONG_SKILL_SMOKE'\n" + (
        "import hashlib,json,subprocess\nfrom pathlib import Path\n"
        f"expected={code_hash!r}\nprogram=Path('.zhulong-skill-'+expected+'.py')\n"
        "assert hashlib.sha256(program.read_bytes()).hexdigest()==expected\n"
        f"result=subprocess.run(['python3','-I',str(program)],input=Path({str(source)!r}).read_bytes(),capture_output=True,check=True,timeout=10)\n"
        "value=json.loads(result.stdout)\n"
        f"Path({str(output)!r}).write_text(json.dumps(value,sort_keys=True)+'\\n')\n"
        "print(json.dumps({'code_hash':expected,'value':value},sort_keys=True))\n"
        "ZHULONG_SKILL_SMOKE")


@contextmanager
def read_db(path):
    path = Path(path).resolve()
    if not path.is_file(): raise RuntimeError('native_transcript_store_missing')
    c = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=5); c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=1')
    try: yield c
    finally: c.close()


def audit_native_skill(profile, submission, binding, command, program, expected_value):
    profile = Path(profile)
    with read_db(profile/'runs_idempotency.db') as c:
        records = c.execute('SELECT fingerprint,status_json FROM run_idempotency WHERE idempotency_key=? AND run_id=?',
                            (submission['id'], submission['run_id'])).fetchall()
    fingerprint = hashlib.sha256(json.dumps({'body': submission['request'], 'gateway_session_key': submission['session_key']},
                                            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if len(records) != 1 or records[0]['fingerprint'] != fingerprint: raise RuntimeError('native_run_request_mapping_mismatch')
    status = json.loads(records[0]['status_json'])
    if status.get('run_id') != submission['run_id'] or status.get('status') != 'completed' or not status.get('session_id'): raise RuntimeError('native_completed_session_mapping_missing')
    with read_db(profile/'state.db') as c:
        rows = c.execute('SELECT id,role,content,tool_calls,tool_call_id FROM messages WHERE session_id=? ORDER BY id',
                         (status['session_id'],)).fetchall()
    successful = []
    for row in rows:
        if row['role'] != 'assistant' or not row['tool_calls']: continue
        for call in json.loads(row['tool_calls']):
            function = call.get('function', {})
            if function.get('name') != 'terminal': continue
            arguments = function.get('arguments', {})
            if isinstance(arguments, str): arguments = json.loads(arguments)
            if arguments.get('background', False) is not False or arguments.get('command', '').strip() != command.strip(): continue
            results = [r for r in rows if r['role'] == 'tool' and r['tool_call_id'] == call.get('id') and r['id'] > row['id']]
            if len(results) != 1: raise RuntimeError('native_tool_result_mapping_mismatch')
            result = json.loads(results[0]['content'])
            if type(result.get('exit_code')) is not int or result['exit_code'] != 0 or result.get('error') is not None or 'session_id' in result: continue
            try: output = json.loads(result['output'])
            except (ValueError, KeyError): continue
            if output != {'code_hash': binding['code_hash'], 'value': expected_value}: continue
            successful.append(call['id'])
    if len(successful) != 1: raise RuntimeError('native_skill_execution_unverified')
    if hashlib.sha256(binding['code'].encode()).hexdigest() != binding['code_hash'] or hashlib.sha256(Path(program).read_bytes()).hexdigest() != binding['code_hash']:
        raise RuntimeError('native_skill_code_hash_mismatch')
    return {'execution_command_observed': True, 'execution_result_successful': True,
            'worker_copy_matches_published_code': True, 'execution_command_sha256': hashlib.sha256(command.encode()).hexdigest(),
            'claim': 'Observed execution in this finite smoke; no general execution enforcement or causal improvement claim'}
