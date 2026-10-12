"""v0.9 观测增强测试：失败分类、memory 容量读数/预警、失败聚合报告。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import Journal  # noqa: E402
from calibrate import Calibration  # noqa: E402
from sensor import Sensor, classify_error, parse_usage  # noqa: E402
from reflect import (Db, Tasks, Budget, Reflector, load_config,  # noqa: E402
                     failure_report, last_memory_usage, memory_pressure, utcnow)


class TestFailureModes(unittest.TestCase):
    def test_classify_rules(self):
        cases = [
            ({"error": "Applying all 4 operations would put memory at 2,276/2,200 chars: free at least 76 chars more."}, "capacity"),
            ({"error": "Replacement would put memory at 2,201/2,200 chars"}, "capacity"),
            ({"error": "operations[0] needs a 'name' (the skill it targets)."}, "params"),
            ({"error": "operations[0] (patch on 'x'): old_string is required for 'patch'"}, "params"),
            ({"error": "operations[5] (patch on 'iosying-campaign') failed: Could not find a match for old_string in the file"}, "anchor"),
            ({"error": "Operation 2 (replace): No entry matched '搬家已完成'. Retry the replace with old_text copied verbatim"}, "anchor"),
            ({"error": "Refusing background curator patch for pinned skill 'io': pinned skills are off-limits"}, "refusal"),
            ({"error": "Operation 1: Blocked: content matches threat pattern 'ssh_backdoor'."}, "refusal"),
            ({"error": "Command timed out after 240s"}, "backend"),
            ({"error": "sqlite3.OperationalError: database is locked"}, "backend"),
            ({"error": "完全没有线索的裸错误"}, "other"),
        ]
        for result, expected in cases:
            klass, sig = classify_error(result["error"])
            self.assertEqual(klass, expected, (result, klass))
            self.assertLessEqual(len(sig), 120)
            self.assertNotIn("2,276", sig)  # 数字已归一化

    def test_parse_usage(self):
        self.assertEqual(parse_usage({"usage": "2,151/2,200"}), (2151, 2200))
        self.assertEqual(parse_usage({"usage": "95/100 chars"}), (95, 100))
        self.assertIsNone(parse_usage({"usage": "n/a"}))
        self.assertIsNone(parse_usage("2151/2200"))
        self.assertIsNone(parse_usage({}))

    def test_sensor_records_class_and_usage(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            s = Sensor(j)
            s.on_post_tool_call(tool_name="memory", status="error",
                                result={"success": False,
                                        "error": "Applying all 1 operations would put memory at 2,460/2,200 chars",
                                        "usage": "2,460/2,200"})
            s.on_post_tool_call(tool_name="memory", status="ok",
                                result={"success": True, "usage": "2,151/2,200"})
            s.on_post_tool_call(tool_name="terminal", status="ok", result={"output": "hi"})
            rows = [r for r in j.tail(10) if r["event"] == "tool_call"]
            err = [r for r in rows if r.get("status") == "error"][0]
            self.assertEqual(err["error_class"], "capacity")
            self.assertIn("N", err["error_sig"])
            self.assertNotIn("2,460", err["error_sig"])
            ok = [r for r in rows if r.get("usage")]
            self.assertEqual(len(ok), 2)  # 错误与成功两条都带 memory 容量读数
            self.assertEqual(ok[0]["usage"], "2460/2200")
            self.assertEqual(ok[1]["usage"], "2151/2200")
            self.assertAlmostEqual(ok[1]["usage_ratio"], 0.9777, places=4)
            plain = [r for r in rows if r.get("name") == "terminal"][0]
            self.assertNotIn("error_class", plain)

    def test_digest_failure_section_and_memory_warning(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            c = Calibration(j)
            db = Db(j.db_path)
            cfg = load_config(j.base)
            today = utcnow().date().isoformat()
            j.append({"event": "tool_call", "name": "memory", "status": "error",
                      "error_class": "capacity",
                      "error_sig": "Applying all N operations would put memory at N/N chars: free at least N chars more."})
            j.append({"event": "tool_call", "name": "memory", "status": "ok",
                      "usage": "2,120/2,200", "usage_ratio": 0.9636})
            r = Reflector(j, c, db, cfg, llm=None, budget=Budget(db, cap=40), tasks=Tasks(db))
            text = r.digest_text(today)
            self.assertIn("失败分类", text)
            self.assertIn("memory · capacity ×1", text)
            self.assertIn("容量预警", text)
            self.assertIn("2120/2200", text)

    def test_memory_pressure_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            j.append({"event": "tool_call", "name": "memory", "status": "ok",
                      "usage": "2,050/2,200", "usage_ratio": 0.9318})
            self.assertIsNotNone(last_memory_usage(j))
            self.assertIsNone(memory_pressure(j))
            j.append({"event": "tool_call", "name": "memory", "status": "ok",
                      "usage": "2,100/2,200", "usage_ratio": 0.9545})
            mp = memory_pressure(j)
            self.assertIsNotNone(mp)
            self.assertEqual((mp["used"], mp["limit"]), (2100, 2200))

    def test_failure_report(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            for _ in range(3):
                j.append({"event": "tool_call", "name": "skill_manage", "status": "error",
                          "error_class": "params", "error_sig": "operations[N] needs a '…'"})
            j.append({"event": "tool_call", "name": "terminal", "status": "error",
                      "error_class": "backend", "error_sig": "Command timed out after Ns"})
            j.append({"event": "tool_call", "name": "read_file", "status": "ok"})
            rep = failure_report(j, days=7)
            self.assertEqual(rep["total"], 4)
            top = rep["items"][0]
            self.assertEqual((top["tool"], top["class"], top["count"]), ("skill_manage", "params", 3))
            self.assertIn("operations[N]", top["sample"])


if __name__ == "__main__":
    unittest.main()
