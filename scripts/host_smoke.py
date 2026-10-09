"""Exercise the installed Hermes plugin API in a disposable, offline profile."""
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--hermes-root',required=True,type=Path)
args=parser.parse_args()
REPO=Path(__file__).resolve().parents[1]
HOST=args.hermes_root.resolve()
sys.path.insert(0, str(HOST))
import hermes_bootstrap

with tempfile.TemporaryDirectory(prefix="zhulong-smoke-", dir="/tmp") as temporary:
    profile = Path(temporary)
    os.environ["HERMES_HOME"] = str(profile)
    os.environ["ZHULONG_NO_AUTOSWEEP"] = "1"
    (profile / "config.yaml").write_text("plugins:\n  enabled: [zhulong]\n", encoding="utf-8")
    data = profile / "zhulong"
    data.mkdir()
    (data / "config.json").write_text(
        json.dumps({"scheduler": False, "narrative": False}), encoding="utf-8"
    )
    subprocess.run(["bash", str(REPO / "scripts" / "install.sh")], check=True, capture_output=True)

    from hermes_cli.plugins import get_plugin_command_handler, get_plugin_manager, invoke_hook
    from tools.registry import registry

    manager = get_plugin_manager()
    manager.discover_and_load()
    plugin = next(item for item in manager.list_plugins() if item["name"] == "zhulong")
    assert plugin["enabled"] and plugin["error"] is None, plugin
    assert (plugin["hooks"], plugin["tools"], plugin["commands"]) == (11, 4, 1), plugin
    command = get_plugin_command_handler("zhulong")
    assert command is not None
    assert "烛龙" in command("status")

    private = "private-payload-must-not-be-persisted"
    invoke_hook("on_session_start", session_id="onboarding", platform="cli")
    invoke_hook("post_tool_call", session_id="onboarding", tool_name="onboarding-check",
                status="ok", args={"command": private}, result=private, duration_ms=5)
    with sqlite3.connect(data / "zhulong.db") as connection:
        rows = connection.execute("SELECT event, payload FROM events ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["session_start", "tool_call"], rows
    event = json.loads(rows[-1][1])
    assert event["name"] == "onboarding-check" and event["result_chars"] == len(private)
    assert event["args_keys"] == ["command"] and private not in rows[-1][1]
    journal = "".join(path.read_text(encoding="utf-8") for path in (data / "journal").glob("*.jsonl"))
    assert private not in journal and journal.count("\n") == 2
    assert "onboarding-check" in command("tail 2")

    def dispatch(name, arguments):
        result = registry.dispatch(name, arguments, session_id="onboarding")
        result = json.loads(result) if isinstance(result, str) else result
        assert result.get("ok") is True, result
        return result

    model=dispatch('zhulong_model',{})['model']
    assert model['domains']['code']['verified_samples']==0
    autonomy=dispatch('zhulong_autonomy',{'action':'status'})
    assert autonomy['enabled'] is False and autonomy['active_executions']==0
    assert dispatch('zhulong_autonomy',{'action':'tick'})['new_dispatches']==0
    assert 'evidence_revision' in command('model')
    assert 'enabled' in command('autonomy status')

    evidence = profile / "evidence.txt"
    evidence.write_text("onboarding verified", encoding="utf-8")
    prediction = dispatch("zhulong_predict", {
        "claim": "The onboarding evidence file contains the expected text",
        "confidence": 90,
        "verify": {"type": "file_contains", "path": str(evidence), "text": "onboarding verified"},
    })
    sweep = dispatch("zhulong_calibration", {"action": "run"})
    assert sweep["sweep"]["resolved"] == 1, sweep
    report = dispatch("zhulong_calibration", {"action": "report"})
    assert report["metrics"]["n_resolved"] == 1, report
    assert math.isclose(report["metrics"]["brier"], 0.01, abs_tol=1e-8), report
    items = dispatch("zhulong_calibration", {"action": "list"})["items"]
    assert any(item["id"] == prediction["id"] and item["outcome"] == 1 for item in items)
    assert "已结 1" in command("status")
    digest = dispatch("zhulong_calibration", {"action": "reflect"})
    assert digest["narrative"] is False, digest
    assert "onboarding-check" in Path(digest["path"]).read_text(encoding="utf-8")
    with sqlite3.connect(data / "zhulong.db") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COALESCE(SUM(calls), 0) FROM llm_daily").fetchone()[0] == 0
    print(json.dumps({"plugin": plugin["name"], "version": plugin["version"],
                      "hooks": plugin["hooks"], "tools": plugin["tools"],
                      "commands": plugin["commands"], "journal": "passed",
                      "privacy": "passed", "calibration": "passed", "digest": "passed",
                      "sqlite_integrity": "ok", "external_llm_calls": 0}, ensure_ascii=False))
