"""Two-connection failpoint check of the actual research adapter's apply body.

Extracting just the nested function avoids executing the other research probes.
This validates one explicit transaction ordering, not a production connector.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('execution_probe.py')
    tree = ast.parse(source.read_text())
    adapter = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == 'idempotent_adapter_illustration')
    apply = next(node for node in adapter.body[0].body
                 if isinstance(node, ast.FunctionDef) and node.name == 'apply')
    module = ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(apply)], type_ignores=[]))
    with tempfile.TemporaryDirectory(prefix='zhulong-adapter-atomicity-') as temp:
        db = Path(temp) / 'effect.sqlite'
        actual = sqlite3.connect(db)
        actual.executescript("CREATE TABLE fence(resource TEXT PRIMARY KEY, token INTEGER);"
                            "INSERT INTO fence VALUES('counter',2);"
                            "CREATE TABLE operations(key TEXT PRIMARY KEY,payload_hash TEXT,result TEXT);"
                            "CREATE TABLE effect(value INTEGER); INSERT INTO effect VALUES(0);")
        peer = sqlite3.connect(db, timeout=0)
        observations = []
        trace = []
        actual.set_trace_callback(trace.append)

        class FenceCursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def fetchone(self):
                value = self.cursor.fetchone()
                observation = {'fence_read': value[0], 'read_in_transaction': actual.in_transaction}
                try:
                    with peer:
                        peer.execute("UPDATE fence SET token=3 WHERE resource='counter'")
                    observation.update(peer_commit_before_effect=True, peer_blocked=False)
                except sqlite3.OperationalError as error:
                    if 'locked' not in str(error):
                        raise
                    observation.update(peer_commit_before_effect=False, peer_blocked=True)
                observations.append(observation)
                return value

        class Connection:
            def __enter__(self):
                actual.__enter__()
                return self

            def __exit__(self, *args):
                return actual.__exit__(*args)

            def execute(self, sql, parameters=()):
                cursor = actual.execute(sql, parameters)
                if sql.startswith('SELECT token FROM fence'):
                    return FenceCursor(cursor)
                return cursor

        namespace = {'connection': Connection(), 'hashlib': hashlib, 'canonical': canonical}
        exec(compile(module, str(source), 'exec'), namespace)
        first = namespace['apply']('step-atomic', {'delta': 1}, 2)
        effects = actual.execute('SELECT value FROM effect').fetchone()[0]
        first_trace = list(trace)
        with peer:
            peer.execute("UPDATE fence SET token=3 WHERE resource='counter'")
        stale = namespace['apply']('late-step', {'delta': 1}, 2)
        final_effects = actual.execute('SELECT value FROM effect').fetchone()[0]
        peer.close()
        actual.close()
    checked = observations[0]
    passed = (checked['read_in_transaction'] and checked['peer_blocked']
              and not checked['peer_commit_before_effect'] and first == '1'
              and effects == 1 and stale == 'stale' and final_effects == 1)
    result = {'schema': 1, 'source_bytes_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'extracted_function': 'idempotent_adapter_illustration.apply',
              'first_read_observation': checked, 'first_call_sql_trace': first_trace,
              'first_result': first, 'effects_after_first': effects,
              'peer_commit_after_first': True, 'late_old_token_result': stale,
              'final_effects': final_effects, 'passed': bool(passed),
              'scope': 'One controlled second-connection update after the real function reads its fence; no model, product connector, arbitrary concurrency or remote service proof.'}
    (out / 'adapter-atomicity-check.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
