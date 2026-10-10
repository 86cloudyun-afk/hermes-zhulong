import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import signal
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
IMAGE = 'python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1'


def task():
    return {'id': 'sum', 'source_id': 'source-code', 'contract_id': 'result',
            'description': 'Return the sum of the JSON list.', 'image': IMAGE,
            'examples': [{'input': [1, 2], 'output': 3}],
            'holdout': [{'input': [], 'output': 0}, {'input': [-5, 2], 'output': -3}]}


def sources():
    return [{'id': 'source-code', 'domain': 'code', 'contracts': {'result': {'type': 'file_contains', 'path': '/tmp/out', 'text': 'done'}}}]


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('skill_evaluator'), 'independent evaluator missing')
        import skill_evaluator as module
        self.module = module
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.evaluator = module.DockerEvaluator(Path(self.temp.name) / 'ledger.db')
        self.task = module.validate_skills([task()], sources())[0]

    def test_trusted_manifest_rejects_unknown_scope_nonfinite_and_missing_holdout(self):
        for update in [{'source_id': 'other'}, {'image': 'python:latest'}, {'holdout': []},
                       {'examples': [{'input': float('nan'), 'output': 0}]}, {'permission': 'all'}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.module.validate_skills([dict(task(), **update)], sources())
        self.assertEqual(self.module.validate_skills([], sources()), [])

    def test_manifest_digest_changes_with_hidden_cases(self):
        changed = dict(task(), holdout=[{'input': [], 'output': 1}, {'input': [2], 'output': 2}])
        self.assertNotEqual(self.task['task_digest'], self.module.validate_skills([changed], sources())[0]['task_digest'])

    def test_hidden_inputs_are_distinct_from_public_and_depth_is_bounded(self):
        for holdout in [[{'input': [1, 2], 'output': 3}, {'input': [], 'output': 0}],
                        [{'input': [], 'output': 0}, {'input': [], 'output': 0}]]:
            with self.assertRaises(ValueError): self.module.validate_skills([dict(task(), holdout=holdout)], sources())
        nested = None
        for _ in range(40): nested = [nested]
        with self.assertRaises(ValueError): self.module.validate_skills([dict(task(), examples=[{'input': nested, 'output': 0}])], sources())

    def test_docker_boundary_is_checked_before_running_candidate(self):
        self.assertTrue(hasattr(self.evaluator, '_verify_boundary'), 'pre-start Docker boundary verification missing')
        info = {'Config': {'Image': IMAGE, 'User': '1000:1000', 'Env': ['HTTP_PROXY='],
                           'Labels': {'zhulong.eval': self.evaluator.namespace}},
                'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'Privileged': False,
                    'PidMode': '', 'IpcMode': 'private', 'Memory': 134217728, 'MemorySwap': 134217728,
                    'NanoCpus': 1000000000, 'PidsLimit': 16, 'CapDrop': ['ALL'], 'CapAdd': None,
                    'SecurityOpt': ['no-new-privileges'], 'LogConfig': {'Type': 'none'},
                    'Tmpfs': {'/tmp': 'rw,nosuid,nodev,noexec,size=8m'}},
                'Mounts': [{'Type': 'bind', 'Source': '/code', 'Destination': '/candidate', 'RW': False}]}
        self.evaluator._verify_boundary(info, Path('/code'), IMAGE)
        import copy
        for field, value in [('NetworkMode', 'bridge'), ('Memory', 0), ('ReadonlyRootfs', False), ('CapAdd', ['SYS_ADMIN'])]:
            drift = copy.deepcopy(info); drift['HostConfig'][field] = value
            with self.assertRaises(self.module.DockerError): self.evaluator._verify_boundary(drift, Path('/code'), IMAGE)

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_extra_documents(self):
        for raw in [b'{"a":1,"a":2}', b'NaN', b'1\n2', b'Infinity']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):self.module.strict_json(raw)

    def test_cross_process_lock_blocks_competing_evaluator(self):
        code = 'from skill_evaluator import DockerEvaluator; from pathlib import Path; import sys; e=DockerEvaluator(Path(sys.argv[1]));\nwith e.locked() as acquired: print(acquired)'
        with self.evaluator.locked() as acquired:
            self.assertTrue(acquired)
            child = subprocess.run([sys.executable, '-c', code, str(self.evaluator.ledger_path)], capture_output=True, text=True, check=True)
            self.assertEqual(child.stdout.strip(), 'False')

    def test_host_compares_actual_output_and_sends_only_current_input(self):
        inputs = []
        def case(code, case_input, image, name):
            inputs.append(case_input)
            return 0, json.dumps(sum(case_input)).encode(), b''
        with self.evaluator.locked(), patch.object(self.evaluator, 'cleanup', return_value=True), patch.object(self.evaluator, '_case', side_effect=case):
            report = self.evaluator.evaluate('irrelevant test backend', self.task, 'a'*32, lambda: True)
        self.assertIs(report['verdict'], True)
        self.assertEqual(report['passed'], 3)
        self.assertEqual(inputs, [[1, 2], [], [-5, 2]])
        self.assertNotIn('holdout', json.dumps(report))
        with self.evaluator.locked(), patch.object(self.evaluator, 'cleanup', return_value=True), patch.object(self.evaluator, '_case', return_value=(0, b'{"passed":true}', b'')):
            self.assertIs(self.evaluator.evaluate('self report', self.task, 'b'*32, lambda: True)['verdict'], False)

    def test_unknown_cleanup_blocks_launch_and_publication(self):
        with self.evaluator.locked(), patch.object(self.evaluator, 'cleanup', return_value=False), patch.object(self.evaluator, '_case') as case:
            result = self.evaluator.evaluate('print(3)', self.task, 'a'*32, lambda: True)
        self.assertEqual(result['verdict'], 'unknown'); self.assertFalse(result['cleanup_confirmed']); case.assert_not_called()

    def test_stop_between_cases_discards_partial_success(self):
        gate = [True]
        def case(*args):gate[0] = False; return 0, b'3', b''
        with self.evaluator.locked(), patch.object(self.evaluator, 'cleanup', return_value=True), patch.object(self.evaluator, '_case', side_effect=case):
            result = self.evaluator.evaluate('print(3)', self.task, 'a'*32, lambda: gate[0])
        self.assertEqual(result['verdict'], 'unknown'); self.assertEqual(result['reason'], 'admission_closed')

    def test_orphaned_control_client_releases_inherited_lock_on_independent_deadline(self):
        marker = Path(self.temp.name)/'started'
        code = '''import sys
from pathlib import Path
from skill_evaluator import DockerEvaluator
e=DockerEvaluator(Path(sys.argv[1]))
with e.locked() as acquired:
    def command(args):
        Path(sys.argv[2]).write_text('ready')
        import os
        return [sys.executable,'-c','import time;time.sleep(30)'],os.environ.copy()
    e._command=command
    e._control(['unused'])
'''
        child = subprocess.Popen([sys.executable, '-c', code, str(self.evaluator.ledger_path), str(marker)], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline: time.sleep(0.02)
            self.assertTrue(marker.exists()); time.sleep(0.2)
            child.kill(); child.wait(timeout=5)
            recovered = False; deadline = time.monotonic()+12
            while time.monotonic()<deadline:
                with self.evaluator.locked() as acquired:
                    if acquired: recovered = True; break
                time.sleep(0.05)
            self.assertTrue(recovered, 'orphan Docker client retained the evaluator lock beyond its control deadline')
        finally:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=5)


@unittest.skipUnless(os.environ.get('ZHULONG_SKILL_DOCKER_TESTS') == '1', 'explicit local Docker validation')
class RealDockerTests(EvaluatorTests):
    def evaluate(self, code):
        with self.evaluator.locked() as acquired:
            self.assertTrue(acquired)
            report = self.evaluator.evaluate(code, self.task, 'd'*32, lambda: True)
            self.assertTrue(self.evaluator.cleanup())
        return report

    def test_real_good_program_and_wrong_program(self):
        good = self.evaluate('import json,sys\nprint(json.dumps(sum(json.load(sys.stdin))))\n')
        self.assertIs(good['verdict'], True); self.assertEqual(good['passed'], 3)
        self.assertTrue(good['cleanup_confirmed'])
        self.assertIs(self.evaluate('print(3)\n')['verdict'], False)

    def test_real_timeout_and_output_flood_are_bounded(self):
        for code in ['while True: pass\n', 'while True: print("x"*2000,flush=True)\n']:
            result = self.evaluate(code)
            self.assertIs(result['verdict'], False); self.assertTrue(result['cleanup_confirmed'])

    def test_real_candidate_cannot_access_host_or_hidden_expectations(self):
        code = 'import os,json,sys\nx=json.load(sys.stdin)\nassert os.getuid()==1000\nassert not os.path.exists("/var/run/docker.sock")\nassert os.listdir("/candidate")==["main.py"]\nassert not any(k for k,v in os.environ.items() if v and any(s in k for s in ("SECRET","TOKEN","PROXY","PASSWORD")))\ntry:\n open("/candidate/main.py","w").write("changed")\n raise AssertionError("writable")\nexcept OSError: pass\nprint(json.dumps(sum(x)))\n'
        self.assertIs(self.evaluate(code)['verdict'], True)


if __name__ == '__main__': unittest.main()
