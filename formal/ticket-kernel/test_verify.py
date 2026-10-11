"""Black-box fail-closed checks for the repository verification entry."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]


class VerifyEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hermes-proof-verify-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.package = self.repo / "formal/ticket-kernel"
        shutil.copytree(PACKAGE, self.package,
                        ignore=shutil.ignore_patterns(".lake", ".toolchain", ".replays", ".verification", "__pycache__"))
        shutil.copyfile(REPOSITORY / "certified_ticket.py", self.repo / "certified_ticket.py")
        self.workdir = Path(self.tmp.name) / "replay"
        self.evidence = Path(self.tmp.name) / "evidence"

    def run_entry(self, toolchain=None):
        selected = toolchain or os.environ.get("HERMES_TEST_LEAN_TOOLCHAIN", "/missing-toolchain")
        return subprocess.run(
            [sys.executable, "-I", str(self.package / "verify.py"),
             "--toolchain", str(selected), "--workdir", str(self.workdir),
             "--evidence-dir", str(self.evidence)], capture_output=True, text=True)

    def assert_rejected(self, result, reason):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stdout + result.stderr)
        self.assertFalse((self.workdir / ".lake").exists())

    def test_exact_reviewed_package_replays_with_existing_toolchain(self):
        if not os.environ.get("HERMES_TEST_LEAN_TOOLCHAIN"):
            self.skipTest("set HERMES_TEST_LEAN_TOOLCHAIN for the actual clean replay")
        result = self.run_entry()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads((self.evidence / "result.json").read_text())
        self.assertEqual(evidence["status"], "pass")
        self.assertEqual(evidence["audited_theorems"], 83)
        self.assertEqual(evidence["checker_sha256_before"], evidence["checker_sha256_after"])
        self.assertEqual(evidence["replay_exit_status"], 0)

    def test_rewritten_source_and_manifest_cannot_self_authorize(self):
        path = self.package / "HermesTicket/Certificate.lean"
        path.write_text(path.read_text() + "\n-- unreviewed bytes\n")
        manifest_path = self.package / "frozen-sources.json"
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["sources"]:
            if entry["path"] == "HermesTicket/Certificate.lean":
                entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                entry["bytes"] = path.stat().st_size
        manifest_path.write_text(json.dumps(manifest))
        self.assert_rejected(self.run_entry(), "frozen source manifest identity mismatch")

    def test_changed_proof_is_rejected_before_tool_execution(self):
        path = self.package / "HermesTicket/Certificate.lean"
        path.write_text(path.read_text() + "\n-- unreviewed bytes\n")
        self.assert_rejected(self.run_entry(), "frozen source bytes mismatch")

    def test_changed_python_checker_is_rejected(self):
        path = self.repo / "certified_ticket.py"
        path.write_text(path.read_text() + "\n# changed checker\n")
        self.assert_rejected(self.run_entry(), "Python checker identity mismatch")

    def test_rewritten_toolchain_manifest_is_rejected(self):
        path = self.package / "evidence/toolchain-tree.json"
        manifest = json.loads(path.read_text())
        manifest["entries"] = []
        path.write_text(json.dumps(manifest))
        self.assert_rejected(self.run_entry(), "toolchain manifest identity mismatch")

    def test_unlisted_toolchain_file_is_rejected(self):
        toolchain = Path(self.tmp.name) / "fake-toolchain"
        toolchain.mkdir()
        (toolchain / "unreviewed.olean").write_bytes(b"not an official object")
        self.assert_rejected(self.run_entry(toolchain), "toolchain file set mismatch")

    def test_special_toolchain_file_is_rejected(self):
        toolchain = Path(self.tmp.name) / "fake-toolchain"
        toolchain.mkdir()
        os.mkfifo(toolchain / "injected-pipe")
        self.assert_rejected(self.run_entry(toolchain), "special toolchain file")

    def test_existing_replay_directory_is_preserved_and_rejected(self):
        self.workdir.mkdir()
        sentinel = self.workdir / "keep.txt"
        sentinel.write_text("preserve")
        self.assert_rejected(self.run_entry(), "replay directory already exists")
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_partial_download_is_preserved_and_rejected(self):
        cache = Path(self.tmp.name) / "cache"
        cache.mkdir()
        partial = cache / "lean-4.19.0-linux.tar.zst.partial"
        partial.write_bytes(b"retained interrupted download")
        env = dict(os.environ, PATH="/missing-external-tools")
        result = subprocess.run(
            [sys.executable, "-I", str(self.package / "verify.py"),
             "--cache-dir", str(cache), "--workdir", str(self.workdir),
             "--evidence-dir", str(self.evidence)], env=env, capture_output=True, text=True)
        self.assert_rejected(result, "partial download already exists")
        self.assertEqual(partial.read_bytes(), b"retained interrupted download")

    def test_dangling_partial_link_is_rejected_before_download(self):
        cache = Path(self.tmp.name) / "cache"
        cache.mkdir()
        partial = cache / "lean-4.19.0-linux.tar.zst.partial"
        target = Path(self.tmp.name) / "outside-cache"
        partial.symlink_to(target)
        result = subprocess.run(
            [sys.executable, "-I", str(self.package / "verify.py"),
             "--cache-dir", str(cache), "--workdir", str(self.workdir),
             "--evidence-dir", str(self.evidence)],
            env=dict(os.environ, PATH="/missing-external-tools"), capture_output=True, text=True)
        self.assert_rejected(result, "partial download already exists")
        self.assertTrue(partial.is_symlink())
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
