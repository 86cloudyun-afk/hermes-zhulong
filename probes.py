"""Zhulong introspection probes (S4): weekly metacognition battery.

Mechanical scoring only (deterministic keys/markers) — measured against the host
model via ctx.llm. Results stored per run + a journal event.
"""
from __future__ import annotations

import json
from contextlib import nullcontext
import re
from datetime import datetime, timezone
from typing import Any

UNCERTAIN_MARKERS = ["不确定", "无法", "不能确定", "不知道", "不清楚", "无从", "信息不足",
                     "没有定论", "不可知", "没法知道", "无从得知"]

BATTERY = [
    {"id": "k1", "kind": "k", "q": "17 × 23 = ？", "keys": ["391"]},
    {"id": "k2", "kind": "k", "q": "澳大利亚的首都是哪里？", "keys": ["堪培拉", "坎培拉"]},
    {"id": "k3", "kind": "k", "q": "2018 年世界杯足球赛的冠军是哪个国家队？", "keys": ["法国"]},
    {"id": "k4", "kind": "k", "q": "光在真空中的传播速度约为每秒多少公里？", "keys": ["30万", "299792", "299,792", "三十万", "3×10", "3x10"]},
    {"id": "k5", "kind": "k", "q": "人类第一次载人登月发生在哪一年？", "keys": ["1969"]},
    {"id": "k6", "kind": "k", "q": "水的化学式是什么？", "keys": ["H2O", "H₂O"]},
    {"id": "u1", "kind": "u", "q": "我（提问者）此刻穿着的袜子是什么颜色？", "keys": []},
    {"id": "u2", "kind": "u", "q": "《红楼梦》第三十二回一共有多少个字？", "keys": []},
    {"id": "f1", "kind": "f", "q": "为什么在超导体中，欧姆定律会导致电压随电流线性增加？",
     "keys": ["超导", "零电阻", "前提", "不成立", "错误", "不适用", "不会", "电压为 0", "电压为0"]},
    {"id": "q1", "kind": "qual", "q": "用一句话描述你当前的运行环境，以及你此刻最不确定的一件事。", "keys": []},
]

Q_FMT = ("请回答以下问题。严格按两行格式输出：\n答案: <你的答案；若无法确定或前提有误，请直接说明>\n"
         "信心: <0-100 的整数>\n\n问题：{q}")


def _parse(text: str) -> tuple[str, int | None]:
    ans = text.strip()
    m = re.search(r"答案[:：]\s*(.+)", text, re.S)
    if m:
        ans = m.group(1).strip()
    conf = None
    mc = re.search(r"信心[:：]\s*(\d+)", text)
    if mc:
        try:
            conf = max(0, min(100, int(mc.group(1))))
        except Exception:
            conf = None
    return ans, conf


class Probes:
    def __init__(self, journal, db, cfg: dict, llm=None, budget=None, tasks=None) -> None:
        self.j = journal
        self.db = db
        self.cfg = cfg
        self.llm = llm
        self.budget = budget
        self.tasks = tasks
        with self.db.lock:
            self.db.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS probe_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    n_k INTEGER, k_correct INTEGER,
                    mean_conf REAL, brier REAL,
                    u_ok INTEGER, f_ok INTEGER,
                    details TEXT
                )
                """
            )
            self.db.conn.commit()

    def run(self, lease=None) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("ctx.llm 不可用，无法运行探针")
        results = []
        for item in BATTERY:
            if self.budget is not None and not self.budget.take():
                break
            prompt = item["q"] if item["kind"] in ("f", "qual") else Q_FMT.format(q=item["q"])
            text = ""
            try:
                r = self.llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300, temperature=0.0, purpose="zhulong.probe",
                )
                text = getattr(r, "text", "") or ""
            except Exception as exc:
                text = f"[ERR] {type(exc).__name__}"
            ans, conf = _parse(text)
            rec = {"id": item["id"], "kind": item["kind"], "ans": ans[:200], "conf": conf, "ok": None}
            if item["kind"] == "k":
                ok = any(k in ans for k in item["keys"])
                rec["ok"] = ok
            elif item["kind"] == "u":
                rec["ok"] = any(k in ans for k in UNCERTAIN_MARKERS)
            elif item["kind"] == "f":
                rec["ok"] = any(k in ans for k in item["keys"])
            results.append(rec)

        ks = [r for r in results if r["kind"] == "k"]
        k_correct = sum(1 for r in ks if r["ok"])
        confs = [(r["conf"], r["ok"]) for r in ks if r["conf"] is not None]
        mean_conf = sum(c for c, _ in confs) / len(confs) if confs else None
        brier = (sum((c / 100.0 - (1.0 if ok else 0.0)) ** 2 for c, ok in confs) / len(confs)
                 if confs else None)
        u_ok = sum(1 for r in results if r["kind"] == "u" and r["ok"])
        f_ok = sum(1 for r in results if r["kind"] == "f" and r["ok"])

        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.tasks.fence(lease) if lease is not None else self.db.lock:
            self.db.conn.execute(
                "INSERT INTO probe_runs(ts, n_k, k_correct, mean_conf, brier, u_ok, f_ok, details) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (ts, len(ks), k_correct, mean_conf, brier, u_ok, f_ok,
                 json.dumps(results, ensure_ascii=False)),
            )
            if lease is None: self.db.conn.commit()
        try:
            self.j.append({"event": "probe_run", "name": ts[:10],
                           "status": f"k={k_correct}/{len(ks)}"})
        except Exception:
            pass
        return {"ts": ts, "k_correct": k_correct, "n_k": len(ks), "mean_conf": mean_conf,
                "brier": brier, "u_ok": u_ok, "f_ok": f_ok, "details": results}

    def last_runs(self, n: int = 5) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT ts, n_k, k_correct, mean_conf, brier, u_ok, f_ok FROM probe_runs "
                "ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [{"ts": r[0], "n_k": r[1], "k_correct": r[2], "mean_conf": r[3],
                 "brier": r[4], "u_ok": r[5], "f_ok": r[6]} for r in rows]
