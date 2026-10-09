import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import Journal  # noqa: E402
from calibrate import Calibration  # noqa: E402


class TestCalibration(unittest.TestCase):
    def _mk(self, td):
        j = Journal(home=Path(td))
        return j, Calibration(j)

    def test_manual_resolve_and_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            _j, c = self._mk(td)
            i1 = c.add("会成功", confidence=80, verify={"type": "manual"})["id"]
            i2 = c.add("会失败", confidence=60, verify={"type": "manual"})["id"]
            c.add("我不知道", confidence=None, verify={"type": "manual"})
            self.assertTrue(c.resolve(i1, True))
            self.assertTrue(c.resolve(i2, False))
            self.assertFalse(c.resolve(i1, True))  # 不可重复结算
            m = c.metrics()
            self.assertEqual(m["n_resolved"], 2)
            self.assertEqual(m["abstain"], 1)
            self.assertAlmostEqual(m["brier"], 0.2, places=6)
            self.assertAlmostEqual(m["accuracy"], 0.5, places=6)
            self.assertAlmostEqual(m["ece"], 0.4, places=6)

    def test_file_verifier_deadline_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            _j, c = self._mk(td)
            target = Path(td) / "goal.txt"
            c.add("文件会出现", confidence=90,
                  verify={"type": "file_exists", "path": str(target)})
            s = c.run_sweep()
            self.assertEqual(s["resolved"], 0)  # 未到截止，不仓促判假
            target.write_text("ok")
            s = c.run_sweep()
            self.assertEqual(s["resolved"], 1)  # 真 → 立即结算
            # 截止=0 时，判假立即生效
            c.add("不存在的文件", confidence=40,
                  verify={"type": "file_exists", "path": str(target) + ".nope", "deadline_seconds": 0})
            s = c.run_sweep()
            self.assertEqual(s["resolved"], 1)
            rows = c.recent(10)
            nope = [r for r in rows if "不存在" in r["claim"]][0]
            self.assertEqual(nope["outcome"], 0)

    def test_journal_event_verifier(self):
        with tempfile.TemporaryDirectory() as td:
            j, c = self._mk(td)
            c.add("terminal 会成功", confidence=70, verify={
                "type": "journal_event",
                "match": {"event": "tool_call", "name": "terminal", "status": "ok"},
                "within_seconds": 600})
            j.append({"event": "tool_call", "name": "terminal", "status": "ok"})
            s = c.run_sweep()
            self.assertEqual(s["resolved"], 1)

    def test_shell_gated_off_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            _j, c = self._mk(td)
            c.add("shell 测试", confidence=50, verify={"type": "shell", "command": "true"})
            s = c.run_sweep()
            self.assertEqual(s["resolved"], 0)
            self.assertTrue(any("shell" in n for n in s["notes"]))

    def test_snapshot_history(self):
        with tempfile.TemporaryDirectory() as td:
            _j, c = self._mk(td)
            pid = c.add("快照测试", confidence=100, verify={"type": "manual"})["id"]
            c.resolve(pid, True)
            c.snapshot()
            hist = c.history(7)
            self.assertTrue(hist)
            self.assertAlmostEqual(hist[0][1], 0.0, places=6)  # brier(100,true)=0


if __name__ == "__main__":
    unittest.main()
