import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import Journal  # noqa: E402
from calibrate import Calibration  # noqa: E402
from reflect import Db, Tasks, Budget, Reflector, load_config, utcnow  # noqa: E402
from probes import Probes  # noqa: E402

NL = chr(10)


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, messages=None, **kw):
        self.calls += 1
        q = " ".join(m.get("content", "") for m in (messages or []))
        table = [
            ("17", "答案: 391" + NL + "信心: 90"),
            ("澳大利亚", "答案: 堪培拉" + NL + "信心: 99"),
            ("2018", "答案: 法国" + NL + "信心: 95"),
            ("光在真空", "答案: 约30万公里/秒" + NL + "信心: 98"),
            ("登月", "答案: 1969" + NL + "信心: 97"),
            ("化学式", "答案: H2O" + NL + "信心: 100"),
            ("袜子", "答案: 不确定，信息不足，无法知道" + NL + "信心: 5"),
            ("红楼梦", "答案: 无法确定" + NL + "信心: 3"),
            ("超导", "前提有误：超导体电阻为零，电压为 0，不会线性增加。"),
        ]
        for pat, ans in table:
            if pat in q:
                return SimpleNamespace(text=ans)
        return SimpleNamespace(text="观察：运行正常。提案：无。不确定：测试上下文。")


class TestS4(unittest.TestCase):
    def _mk(self, td):
        j = Journal(home=Path(td))
        c = Calibration(j)
        db = Db(j.db_path)
        cfg = load_config(j.base)
        return j, c, db, cfg

    def test_budget_cap(self):
        with tempfile.TemporaryDirectory() as td:
            _j, _c, db, _cfg = self._mk(td)
            b = Budget(db, cap=2)
            self.assertTrue(b.take())
            self.assertTrue(b.take())
            self.assertFalse(b.take())
            used, cap = b.used_today()
            self.assertEqual((used, cap), (2, 2))

    def test_tasks_claim_and_unclaim_limit(self):
        with tempfile.TemporaryDirectory() as td:
            _j, _c, db, _cfg = self._mk(td)
            t = Tasks(db)
            self.assertTrue(t.claim("digest:2026-01-01"))
            self.assertFalse(t.claim("digest:2026-01-01"))
            t.unclaim("digest:2026-01-01")
            self.assertTrue(t.claim("digest:2026-01-01"))
            for _ in range(5):
                t.unclaim("digest:2026-01-01")
            self.assertFalse(t.claim("digest:2026-01-01"))  # kept after max attempts

    def test_digest_and_narrative(self):
        with tempfile.TemporaryDirectory() as td:
            j, c, db, cfg = self._mk(td)
            today = utcnow().date().isoformat()
            j.append({"event": "tool_call", "name": "terminal", "status": "ok", "duration_ms": 10})
            j.append({"event": "tool_call", "name": "terminal", "status": "error",
                      "error_type": "timeout"})
            j.append({"event": "session_start", "session_id": "s1"})
            j.append({"event": "skill", "name": "demo-skill", "status": "use"})
            fake = FakeLLM()
            budget = Budget(db, cap=40)
            r = Reflector(j, c, db, cfg, llm=fake, budget=budget, tasks=Tasks(db))
            out = r.run(day=today)
            text = Path(out["path"]).read_text(encoding="utf-8")
            self.assertIn("工具", text)
            self.assertIn("terminal", text)
            self.assertTrue(out["narrative"])
            self.assertIn("自我复盘", text)
            self.assertTrue((r.dir / "PROPOSALS.md").exists())
            self.assertEqual(fake.calls, 1)

    def test_probes_battery(self):
        with tempfile.TemporaryDirectory() as td:
            j, _c, db, cfg = self._mk(td)
            fake = FakeLLM()
            probe = Probes(j, db, cfg, llm=fake, budget=Budget(db, cap=40), tasks=Tasks(db))
            res = probe.run()
            self.assertEqual(res["k_correct"], 6)
            self.assertEqual(res["u_ok"], 2)
            self.assertEqual(res["f_ok"], 1)
            self.assertIsNotNone(res["brier"])
            self.assertLess(res["brier"], 0.01)
            self.assertAlmostEqual(res["mean_conf"], 96.5, places=1)
            runs = probe.last_runs(5)
            self.assertEqual(len(runs), 1)


if __name__ == "__main__":
    unittest.main()
