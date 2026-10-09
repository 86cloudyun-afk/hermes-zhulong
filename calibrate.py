"""Zhulong calibration ledger (S3): predictions -> outcomes -> Brier/ECE history.

Frozen-SPEC rules this module enforces:
- Predictions are recorded by the agent (tool) or the user (command).
- Predictions are resolved ONLY by mechanical verifiers or an explicit human
  command. The agent can never resolve its own prediction (anti self-certification).
- Verifiers: file_exists / file_contains / journal_event / manual / shell (gated OFF by default).
- Resolution rule: TRUE resolves immediately; FALSE resolves only after the
  prediction's deadline (deadline_seconds, default 3600) so "not yet" never
  becomes a premature "false".
- Metrics: Brier & ECE over numeric-confidence resolved predictions; abstentions
  (confidence=None) are recorded and counted separately, never scored.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

PENDING, RESOLVED, CANCELLED, ABSTAIN = "pending", "resolved", "cancelled", "abstain"
VERIFIER_TYPES = {"file_exists", "file_contains", "journal_event", "manual", "shell"}
SHELL_DEFAULT_TIMEOUT = 10
DEFAULT_DEADLINE = 3600
_JOURNAL_GRACE = 5  # seconds of pre-window to avoid second-boundary races


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Calibration:
    def __init__(self, journal) -> None:
        self.j = journal
        self.base = journal.base
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(journal.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                made_at TEXT NOT NULL,
                session_id TEXT,
                source TEXT NOT NULL DEFAULT 'agent',
                claim TEXT NOT NULL,
                confidence INTEGER,
                verify TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at TEXT,
                outcome INTEGER,
                note TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_status ON predictions(status)")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calib_metrics (
                day TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL,
                n INTEGER,
                computed_at TEXT,
                PRIMARY KEY (day, metric)
            )
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------- write
    def add(self, claim: str, confidence: int | None = None,
            verify: dict[str, Any] | None = None,
            session_id: str | None = None, source: str = "agent") -> dict[str, Any]:
        claim = (claim or "").strip()
        if not claim:
            raise ValueError("claim 不能为空")
        claim = claim[:500]
        if confidence is not None:
            confidence = int(confidence)
            if not 0 <= confidence <= 100:
                raise ValueError("confidence 必须在 0-100")
        verify = dict(verify or {"type": "manual"})
        vtype = str(verify.get("type", "manual"))
        if vtype not in VERIFIER_TYPES:
            raise ValueError(f"未知核验类型: {vtype}")
        status = ABSTAIN if confidence is None else PENDING
        made_at = _iso(_utcnow())
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO predictions(made_at, session_id, source, claim, confidence, verify, status)"
                " VALUES(?,?,?,?,?,?,?)",
                (made_at, session_id, source, claim, confidence,
                 json.dumps(verify, ensure_ascii=False), status),
            )
            self._conn.commit()
            pid = cur.lastrowid
        try:
            self.j.append({"event": "prediction_new", "name": f"#{pid}",
                           "status": vtype, "session_id": session_id, "confidence": confidence})
        except Exception:
            pass
        return {"id": pid, "status": status, "verifier": vtype}

    def resolve(self, pid: int, outcome: bool, note: str | None = None, actor: str = "human") -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE predictions SET status=?, resolved_at=?, outcome=?, note=? "
                "WHERE id=? AND status=?",
                (RESOLVED, _iso(_utcnow()), 1 if outcome else 0, note, int(pid), PENDING),
            )
            self._conn.commit()
            ok = cur.rowcount == 1
        if ok:
            try:
                self.j.append({"event": "prediction_resolved", "name": f"#{pid}",
                               "status": "true" if outcome else "false", "reason": actor})
            except Exception:
                pass
        return ok

    def cancel(self, pid: int, note: str | None = None) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE predictions SET status=?, resolved_at=?, note=? WHERE id=? AND status=?",
                (CANCELLED, _iso(_utcnow()), note, int(pid), PENDING),
            )
            self._conn.commit()
            return cur.rowcount == 1

    # -------------------------------------------------------------------- read
    def pending(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, made_at, claim, confidence, verify FROM predictions "
                "WHERE status=? ORDER BY id LIMIT ?", (PENDING, limit),
            ).fetchall()
        return [{"id": r[0], "made_at": r[1], "claim": r[2], "confidence": r[3],
                 "verify": json.loads(r[4])} for r in rows]

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, made_at, claim, confidence, status, resolved_at, outcome, note "
                "FROM predictions ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [{"id": r[0], "made_at": r[1], "claim": r[2], "confidence": r[3],
                 "status": r[4], "resolved_at": r[5], "outcome": r[6], "note": r[7]}
                for r in rows]

    # ---------------------------------------------------------------- verifiers
    def _allow_shell(self) -> bool:
        cfg = self.base / "config.json"
        try:
            if cfg.exists():
                return bool(json.loads(cfg.read_text(encoding="utf-8")).get("allow_shell_verifiers", False))
        except Exception:
            pass
        return False

    def _verify(self, spec: dict[str, Any], made_at: str) -> tuple[bool | None, str]:
        vtype = str(spec.get("type", "manual"))
        try:
            if vtype == "manual":
                return None, "需要人工裁决（/zhulong calibrate resolve）"
            if vtype == "file_exists":
                p = os.path.expanduser(str(spec.get("path", "")))
                return (os.path.exists(p) if p else None), f"file_exists {p}"
            if vtype == "file_contains":
                p = os.path.expanduser(str(spec.get("path", "")))
                text = str(spec.get("text", ""))
                max_bytes = int(spec.get("max_bytes", 200_000))
                if not p or not text:
                    return None, "file_contains 参数不足"
                with open(p, "rb") as fh:
                    chunk = fh.read(max_bytes)
                return text.encode("utf-8") in chunk, f"file_contains {p}"
            if vtype == "journal_event":
                match = dict(spec.get("match", {}))
                window = int(spec.get("within_seconds", 3600))
                lo = _iso(datetime.fromisoformat(made_at) - timedelta(seconds=_JOURNAL_GRACE))
                hi = _iso(datetime.fromisoformat(made_at) + timedelta(seconds=window))
                where, args = ["ts >= ?", "ts <= ?"], [lo, hi]
                for key in ("event", "name", "status"):
                    if key in match:
                        where.append(f"{key} = ?")
                        args.append(str(match[key]))
                sql = "SELECT COUNT(*) FROM events WHERE " + " AND ".join(where)
                with self.j._lock:
                    n = self.j._conn.execute(sql, args).fetchone()[0]
                return n > 0, f"journal_event {match} -> {n} 条匹配"
            if vtype == "shell":
                cmd = str(spec.get("command", ""))
                if not cmd or len(cmd) > 500:
                    return None, "shell 命令缺失或过长"
                if not self._allow_shell():
                    return None, "shell 核验未启用（默认安全关闭）"
                timeout = min(int(spec.get("timeout", SHELL_DEFAULT_TIMEOUT)), 30)
                rc = subprocess.run(cmd, shell=True, timeout=timeout,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
                return rc == 0, f"shell rc={rc}"
        except Exception as exc:
            return None, f"核验异常: {type(exc).__name__}"
        return None, "未知核验类型"

    def run_sweep(self, limit: int = 20) -> dict[str, Any]:
        checked = resolved_n = 0
        notes: list[str] = []
        now = _utcnow()
        for row in self.pending(limit=limit):
            checked += 1
            outcome, note = self._verify(row["verify"], row["made_at"])
            if outcome is None:
                notes.append(f"#{row['id']} 未结：{note}")
                continue
            deadline = int(row["verify"].get("deadline_seconds", DEFAULT_DEADLINE))
            due = now >= datetime.fromisoformat(row["made_at"]) + timedelta(seconds=deadline)
            if outcome is False and not due:
                notes.append(f"#{row['id']} 未到截止，保持待结（{note}）")
                continue
            if self.resolve(row["id"], outcome, note=note, actor="verifier"):
                resolved_n += 1
                notes.append(f"#{row['id']} → {'真' if outcome else '假'}（{note}）")
        return {"checked": checked, "resolved": resolved_n, "notes": notes}

    # ------------------------------------------------------------------ metrics
    def metrics(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT confidence, outcome FROM predictions WHERE status=? AND confidence IS NOT NULL",
                (RESOLVED,),
            ).fetchall()
            pending_n = self._conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE status=?", (PENDING,)).fetchone()[0]
            abstain_n = self._conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE status=?", (ABSTAIN,)).fetchone()[0]
        n = len(rows)
        out: dict[str, Any] = {"n_resolved": n, "pending": pending_n, "abstain": abstain_n,
                               "brier": None, "ece": None, "accuracy": None}
        if n:
            ps = [c / 100.0 for c, _ in rows]
            os_ = [float(o) for _, o in rows]
            out["brier"] = sum((p - o) ** 2 for p, o in zip(ps, os_)) / n
            out["accuracy"] = sum(os_) / n
            ece = 0.0
            for lo, hi in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]:
                idx = [i for i, (c, _) in enumerate(rows) if lo <= c < hi or (hi == 100 and c == 100)]
                if not idx:
                    continue
                avg_c = sum(ps[i] for i in idx) / len(idx)
                avg_o = sum(os_[i] for i in idx) / len(idx)
                ece += (len(idx) / n) * abs(avg_c - avg_o)
            out["ece"] = ece
        return out

    def snapshot(self) -> None:
        m = self.metrics()
        day = _utcnow().date().isoformat()
        pairs = [("brier", m["brier"], m["n_resolved"]), ("ece", m["ece"], m["n_resolved"]),
                 ("accuracy", m["accuracy"], m["n_resolved"]),
                 ("pending", float(m["pending"]), m["pending"]),
                 ("abstain", float(m["abstain"]), m["abstain"])]
        with self._lock:
            for metric, value, n in pairs:
                self._conn.execute(
                    "INSERT OR REPLACE INTO calib_metrics(day, metric, value, n, computed_at) VALUES(?,?,?,?,?)",
                    (day, metric, value, n, _iso(_utcnow())),
                )
            self._conn.commit()

    def history(self, days: int = 14) -> list[tuple[str, float | None, float | None, float | None, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, metric, value, n FROM calib_metrics ORDER BY day DESC LIMIT ?",
                (days * 5,),
            ).fetchall()
        by_day: dict[str, dict[str, Any]] = {}
        for day, metric, value, n in rows:
            by_day.setdefault(day, {})[metric] = (value, n)
        out = []
        for day in sorted(by_day, reverse=True)[:days]:
            d = by_day[day]
            out.append((day, d.get("brier", (None, 0))[0], d.get("ece", (None, 0))[0],
                        d.get("accuracy", (None, 0))[0], d.get("pending", (0, 0))[1]))
        return out
