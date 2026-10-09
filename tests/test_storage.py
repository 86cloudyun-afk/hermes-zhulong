import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import Journal  # noqa: E402
from sensor import Sensor  # noqa: E402


class TestJournal(unittest.TestCase):
    def test_append_stats_tail(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            j.append({"event": "tool_call", "name": "terminal", "status": "ok"})
            j.append({"event": "turn", "session_id": "s1"})
            s = j.stats()
            self.assertEqual(s["total"], 2)
            self.assertEqual(s["today"], 2)
            t = j.tail(10)
            self.assertEqual(len(t), 2)
            self.assertEqual(t[-1]["event"], "turn")
            self.assertTrue((Path(td) / "zhulong" / "journal").exists())

    def test_sensor_is_quiet_on_empty_and_stores_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            sn = Sensor(j)
            sn.on_post_tool_call()  # no kwargs -> must not raise
            sn.on_post_tool_call(
                tool_name="terminal",
                status="ok",
                args={"command": "echo hi"},
                result="x" * 10,
                duration_ms=5,
            )
            rows = j.tail(10)
            self.assertEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual(last["name"], "terminal")
            self.assertEqual(last["result_chars"], 10)
            self.assertEqual(last["args_keys"], ["command"])
            self.assertNotIn("result", last)  # raw content never stored

    def test_retention_prunes(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(home=Path(td))
            old = Path(td) / "zhulong" / "journal" / "events-2000-01-01.jsonl"
            old.write_text("{}\n", encoding="utf-8")
            j._maybe_rotate()
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
