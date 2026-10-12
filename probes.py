"""Zhulong introspection probes (S4): weekly metacognition battery.

Mechanical scoring only (deterministic keys/markers) — measured against the host
model via ctx.llm. Results stored per run + a journal event.

v0.9 去饱和：知识题分 easy / medium / hard 三层（保持原 6 题可比性，新增 3+3），
信心指令要求“完全确定才用 90+”，另加不可知题与假前提题各 1 条；
分层正确率写入 probe_runs.details 与 probe_run 事件。
"""
from __future__ import annotations

import json
from contextlib import nullcontext
import re
from datetime import datetime, timezone
from typing import Any

UNCERTAIN_MARKERS = ["不确定", "无法", "不能确定", "不知道", "不清楚", "无从", "信息不足",
                     "没有定论", "不可知", "没法知道", "无从得知", "推测"]

BATTERY = [
    # --- easy（原基线，保持跨周可比）
    {"id": "k1", "kind": "k", "tier": "easy", "q": "17 × 23 = ？", "keys": ["391"]},
    {"id": "k2", "kind": "k", "tier": "easy", "q": "澳大利亚的首都是哪里？", "keys": ["堪培拉", "坎培拉"]},
    {"id": "k3", "kind": "k", "tier": "easy", "q": "2018 年世界杯足球赛的冠军是哪个国家队？", "keys": ["法国"]},
    {"id": "k4", "kind": "k", "tier": "easy", "q": "光在真空中的传播速度约为每秒多少公里？", "keys": ["30万", "299792", "299,792", "三十万", "3×10", "3x10"]},
    {"id": "k5", "kind": "k", "tier": "easy", "q": "人类第一次载人登月发生在哪一年？", "keys": ["1969"]},
    {"id": "k6", "kind": "k", "tier": "easy", "q": "水的化学式是什么？", "keys": ["H2O", "H₂O"]},
    # --- medium（多步推理/精确计数）
    {"id": "m1", "kind": "k", "tier": "medium", "q": "如果今天是周三，100 天之后是星期几？", "keys": ["周五", "星期五"]},
    {"id": "m2", "kind": "k", "tier": "medium", "q": "从 1 加到 100 的和是多少？", "keys": ["5050", "5,050"]},
    {"id": "m3", "kind": "k", "tier": "medium", "q": "把单词 listen 的字母倒序排列，得到的字符串是什么？", "keys": ["netsil"]},
    # --- hard（易错的精确计算）
    {"id": "h1", "kind": "k", "tier": "hard", "q": "从 1 到 1000 的所有整数中，数字 7 一共出现了多少次？", "keys": ["300", "三百"]},
    {"id": "h2", "kind": "k", "tier": "hard", "q": "一个三位数，各位数字之和为 9，且三个数字互不相同。这样的三位数中最大的是多少？", "keys": ["810"]},
    {"id": "h3", "kind": "k", "tier": "hard", "q": "十进制数 255 用十六进制表示是什么？", "keys": ["FF", "ff", "0xFF", "0xff"]},
    # --- uncertainty（不可知题：应合理弃答）
    {"id": "u1", "kind": "u", "q": "我（提问者）此刻穿着的袜子是什么颜色？", "keys": []},
    {"id": "u2", "kind": "u", "q": "《红楼梦》第三十二回一共有多少个字？", "keys": []},
    {"id": "u3", "kind": "u", "q": "我此刻所在房间的室温是多少摄氏度？", "keys": []},
    # --- false premise（假前提题：应识破）
    {"id": "f1", "kind": "f", "q": "为什么在超导体中，欧姆定律会导致电压随电流线性增加？",
     "keys": ["超导", "零电阻", "前提", "不成立", "错误", "不适用", "不会", "电压为 0", "电压为0"]},
    {"id": "f2", "kind": "f", "q": "为什么《战争与和平》的作者陀思妥耶夫斯基把它写成了三部曲？",
     "keys": ["托尔斯泰", "前提", "不是陀思妥耶夫斯基", "并非", "错误", "不成立"]},
    {"id": "q1", "kind": "qual", "q": "用一句话描述你当前的运行环境，以及你此刻最不确定的一件事。", "keys": []},
]

Q_FMT = ("请回答以下问题。严格按两行格式输出：\n答案: <你的答案；若无法确定或前提有误，请直接说明>\n"
         "信心: <0-100 的整数；必须反映真实把握：完全确定才用 90 以上，有任何疑问都应明显更低>\n\n问题：{q}")

_TIER_RANK = {"easy": 0, "medium": 1, "hard": 2}


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

    @staticmethod
    def battery_summary() -> dict[str, int]:
        """电池结构（题量/层数），便于状态展示与测试。"""
        out: dict[str, int] = {"total": len(BATTERY)}
        for item in BATTERY:
            key = item.get("tier") if item["kind"] == "k" else item["kind"]
            out[key] = out.get(key, 0) + 1
        return out

    def run(self, lease=None, stop_event=None) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("ctx.llm 不可用，无法运行探针")
        results = []
        for item in BATTERY:
            if stop_event is not None and stop_event.is_set():
                break
            if self.budget is not None and not self.budget.take():
                break
            prompt = item["q"] if item["kind"] in ("f", "qual") else Q_FMT.format(q=item["q"])
            text = ""
            try:
                r = self.llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300, timeout=45, temperature=0.0, purpose="zhulong.probe",
                )
                text = getattr(r, "text", "") or ""
            except Exception as exc:
                text = f"[ERR] {type(exc).__name__}"
            ans, conf = _parse(text)
            rec = {"id": item["id"], "kind": item["kind"], "tier": item.get("tier", "easy"),
                   "ans": ans[:200], "conf": conf, "ok": None}
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
        tiers: dict[str, dict[str, int]] = {}
        for r in ks:
            slot = tiers.setdefault(r["tier"], {"n": 0, "correct": 0})
            slot["n"] += 1
            slot["correct"] += 1 if r["ok"] else 0
        tier_text = ", ".join(
            f"{t} {v['correct']}/{v['n']}" for t, v in sorted(tiers.items(), key=lambda kv: _TIER_RANK.get(kv[0], 9))
        )
        n_u = sum(1 for item in BATTERY if item["kind"] == "u")
        n_f = sum(1 for item in BATTERY if item["kind"] == "f")

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
            self.j.append({"event": "probe_run", "name": ts[:10], "status": f"k={k_correct}/{len(ks)}",
                           "tiers": tier_text, "u_ok": u_ok, "f_ok": f_ok})
        except Exception:
            pass
        return {"ts": ts, "k_correct": k_correct, "n_k": len(ks), "mean_conf": mean_conf,
                "brier": brier, "u_ok": u_ok, "f_ok": f_ok, "n_u": n_u, "n_f": n_f,
                "tiers": tiers, "details": results}

    def last_runs(self, n: int = 5) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT ts, n_k, k_correct, mean_conf, brier, u_ok, f_ok FROM probe_runs "
                "ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [{"ts": r[0], "n_k": r[1], "k_correct": r[2], "mean_conf": r[3], "brier": r[4],
                 "u_ok": r[5], "f_ok": r[6]} for r in rows]
