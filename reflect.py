"""Zhulong reflection engine (S4): daily digests, proposals, scheduler, budget.

- Digest: deterministic markdown built from the journal + calibration ledgers.
- Narrative: optional one-shot LLM call (ctx.llm), clearly labelled as model-generated.
- Proposals: appended to reflections/PROPOSALS.md — human review only, never auto-executed.
- Budget: shared daily LLM-call cap (default 40/day, config.json: llm_daily_cap).
- Scheduler: background thread; cross-process task claims prevent double runs.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULTS = {
    "allow_shell_verifiers": False,
    "llm_daily_cap": 40,
    "probe_weekday": 0,      # Monday (python weekday()); -1 disables
    "probe_hour": 9,
    "narrative": True,
    "scheduler": True,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def load_config(base: Path) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        f = base / "config.json"
        if f.exists():
            cfg.update(json.loads(f.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


@dataclass(frozen=True)
class TaskLease:
    task: str
    owner: str
    generation: int
    expires_at: float


class Db:
    """S4 handle; every cross-process decision uses a SQLite write transaction."""
    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute("CREATE TABLE IF NOT EXISTS tasks(task TEXT PRIMARY KEY, claimed_at TEXT, attempts INTEGER DEFAULT 0)")
                columns = {r[1] for r in self.conn.execute("PRAGMA table_info(tasks)")}
                additions = {"state": "TEXT DEFAULT 'ready'", "owner": "TEXT", "generation": "INTEGER DEFAULT 0", "lease_until": "REAL"}
                for name, definition in additions.items():
                    if name not in columns:
                        self.conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
                if "state" not in columns:
                    self.conn.execute("UPDATE tasks SET state='completed' WHERE claimed_at IS NOT NULL")
                self.conn.execute("CREATE TABLE IF NOT EXISTS llm_daily(day TEXT PRIMARY KEY, calls INTEGER)")
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def close(self) -> None:
        with self.lock: self.conn.close()


class Tasks:
    def __init__(self, db: Db, max_attempts: int = 5, *, clock=time.time,
                 lease_seconds: float = 900, heartbeat_seconds: float = 30) -> None:
        self.db, self.max_attempts, self.clock = db, max_attempts, clock
        self.owner = uuid.uuid4().hex
        self.lease_seconds, self.heartbeat_seconds = lease_seconds, heartbeat_seconds
        self._claims: dict[str, TaskLease] = {}

    def acquire(self, task: str) -> TaskLease | None:
        now = self.clock()
        with self.db.lock:
            self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                self.db.conn.execute("INSERT OR IGNORE INTO tasks(task) VALUES(?)", (task,))
                cursor = self.db.conn.execute(
                    "UPDATE tasks SET state='running', owner=?, generation=generation+1, lease_until=?, claimed_at=? "
                    "WHERE task=? AND attempts<? AND (state='ready' OR (state='running' AND lease_until<=?))",
                    (self.owner, now + self.lease_seconds, iso(utcnow()), task, self.max_attempts, now))
                row = self.db.conn.execute("SELECT generation FROM tasks WHERE task=?", (task,)).fetchone()
                self.db.conn.commit()
                return TaskLease(task, self.owner, row[0], now+self.lease_seconds) if cursor.rowcount else None
            except BaseException:
                self.db.conn.rollback()
                raise

    def _valid(self, lease: TaskLease) -> bool:
        return self.db.conn.execute(
            "SELECT 1 FROM tasks WHERE task=? AND owner=? AND generation=? AND state='running' AND lease_until>?",
            (lease.task, lease.owner, lease.generation, self.clock())).fetchone() is not None

    @contextmanager
    def fence(self, lease: TaskLease):
        with self.db.lock:
            self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                if not self._valid(lease): raise RuntimeError("stale_task_lease")
                yield
                self.db.conn.commit()
            except BaseException:
                self.db.conn.rollback()
                raise

    def _update(self, lease: TaskLease, assignments: str, values=()) -> bool:
        with self.db.lock:
            cursor = self.db.conn.execute(
                "UPDATE tasks SET " + assignments +
                " WHERE task=? AND owner=? AND generation=? AND state='running' AND lease_until>?",
                (*values, lease.task, lease.owner, lease.generation, self.clock()))
            self.db.conn.commit()
            return bool(cursor.rowcount)

    def renew(self, lease: TaskLease) -> bool:
        return self._update(lease, "lease_until=?", (self.clock()+self.lease_seconds,))

    def complete(self, lease: TaskLease) -> bool:
        return self._update(lease, "state='completed', owner=NULL, lease_until=NULL")

    def fail(self, lease: TaskLease) -> bool:
        return self._update(lease, "state='ready', owner=NULL, lease_until=NULL, claimed_at=NULL, attempts=attempts+1")

    @contextmanager
    def heartbeat(self, lease: TaskLease):
        stop = threading.Event()
        def pulse():
            while not stop.wait(self.heartbeat_seconds):
                try:
                    if not self.renew(lease): break
                except Exception: break
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try: yield lease
        finally:
            stop.set()
            thread.join(timeout=5)

    def claim(self, task: str) -> bool:
        lease = self.acquire(task)
        if lease is None: return False
        self._claims[task] = lease
        return True

    def unclaim(self, task: str) -> None:
        lease = self._claims.pop(task, None)
        if lease is not None: self.fail(lease)

    def last_with_prefix(self, prefix: str) -> str | None:
        with self.db.lock:
            row = self.db.conn.execute("SELECT task FROM tasks WHERE task LIKE ? ORDER BY task DESC LIMIT 1", (prefix+"%",)).fetchone()
        return row[0] if row else None


class Budget:
    def __init__(self, db: Db, cap: int = 40) -> None:
        if type(cap) is not int or cap < 0: raise ValueError("invalid_llm_daily_cap")
        self.db, self.cap = db, cap

    def take(self) -> bool:
        day = utcnow().date().isoformat()
        with self.db.lock:
            cursor = self.db.conn.execute(
                "INSERT INTO llm_daily(day,calls) SELECT ?,1 WHERE ?>0 "
                "ON CONFLICT(day) DO UPDATE SET calls=COALESCE(calls,0)+1 WHERE COALESCE(calls,0)<?",
                (day, self.cap, self.cap))
            self.db.conn.commit()
            return bool(cursor.rowcount)

    def used_today(self) -> tuple[int, int]:
        with self.db.lock:
            row = self.db.conn.execute("SELECT calls FROM llm_daily WHERE day=?", (utcnow().date().isoformat(),)).fetchone()
        return (row[0] if row else 0, self.cap)


class Reflector:
    def __init__(self, journal, calibration, db: Db, cfg: dict, llm=None,
                 budget: Budget | None = None, tasks: Tasks | None = None) -> None:
        self.j = journal
        self.cal = calibration
        self.db = db
        self.cfg = cfg
        self.llm = llm
        self.budget = budget or Budget(db, cfg.get("llm_daily_cap", 40))
        self.tasks = tasks or Tasks(db)
        self.dir = journal.base / "reflections"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ digest
    def digest_text(self, day: str) -> str:
        like = day + "%"
        with self.j._lock:
            by_event = self.j._conn.execute(
                "SELECT event, COUNT(*) FROM events WHERE ts LIKE ? GROUP BY event ORDER BY 2 DESC", (like,)
            ).fetchall()
            tools = self.j._conn.execute(
                "SELECT name, COUNT(*), SUM(CASE WHEN status='error' THEN 1 ELSE 0 END), AVG(duration_ms) "
                "FROM events WHERE event='tool_call' AND ts LIKE ? GROUP BY name ORDER BY 2 DESC LIMIT 15",
                (like,),
            ).fetchall()
            sessions = self.j._conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM events WHERE event='session_start' AND ts LIKE ?", (like,)
            ).fetchone()[0]
            skills = [r[0] for r in self.j._conn.execute(
                "SELECT DISTINCT name FROM events WHERE event='skill' AND ts LIKE ? AND name IS NOT NULL", (like,)
            ).fetchall()]
            subs = self.j._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event='subagent_stop' AND ts LIKE ?", (like,)
            ).fetchone()[0]
            api_err = self.j._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event='api_error' AND ts LIKE ?", (like,)
            ).fetchone()[0]
            err_rows = [json.loads(p[0]) for p in self.j._conn.execute(
                "SELECT payload FROM events WHERE event='tool_call' AND status='error' AND ts LIKE ? LIMIT 10", (like,)
            ).fetchall()]
        with self.cal._lock:
            pred_new = self.cal._conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE made_at LIKE ?", (like,)).fetchone()[0]
            pred_res = self.cal._conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE resolved_at LIKE ?", (like,)).fetchone()[0]
            pred_open = self.cal._conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE status='pending'").fetchone()[0]
        lines = [f"# 烛龙日记 · {day}", ""]
        lines.append(f"- 事件总数：{sum(c for _, c in by_event)} ｜ 会话：{sessions} ｜ 子代理运行：{subs} ｜ API 错误：{api_err}")
        lines.append(f"- 校准账：新增预测 {pred_new} ｜ 当日结算 {pred_res} ｜ 未结 {pred_open}")
        if skills:
            lines.append(f"- 触及技能：{', '.join(skills[:10])}")
        lines.append("")
        lines.append("## 事件构成")
        for ev, c in by_event[:12]:
            lines.append(f"- {ev}: {c}")
        lines.append("")
        lines.append("## 工具（次数 / 错误 / 平均耗时）")
        for name, c, err, avg in tools:
            avg_s = f"{avg:.0f}ms" if avg else "—"
            lines.append(f"- {name}: {c} / {err or 0} / {avg_s}")
        if err_rows:
            lines.append("")
            lines.append("## 错误明细（前 10）")
            for e in err_rows:
                lines.append(f"- {(e.get('ts') or '')[11:19]} {e.get('name')} · {e.get('error_type') or 'error'}")
        return "\n".join(lines)

    # --------------------------------------------------------------- narrative
    def _narrative(self, digest: str) -> str | None:
        if self.llm is None or not self.cfg.get("narrative", True):
            return None
        if not self.budget.take():
            return None
        try:
            result = self.llm.complete(
                messages=[
                    {"role": "system", "content": (
                        "你是「烛龙」——Hermes agent 的自我观测层。只依据给出的客观统计写作，"
                        "不编造未列出的信息，不做拟人化意识宣称。输出三段，每段一行："
                        "观察：≤2 条值得注意的模式；提案：≤1 条具体可执行的改进；不确定：≤1 条。总长≤220字。")},
                    {"role": "user", "content": digest[:6000]},
                ],
                max_tokens=450, timeout=45, temperature=0.3, purpose="zhulong.digest",
            )
            text = (getattr(result, "text", "") or "").strip()
            return text or None
        except Exception:
            return None

    # -------------------------------------------------------------------- run
    def run(self, day: str | None = None, with_narrative: bool = True, lease: TaskLease | None = None) -> dict[str, Any]:
        day = day or utcnow().date().isoformat()
        digest = self.digest_text(day)
        narrative = self._narrative(digest) if with_narrative else None
        path = self.dir / f"digest-{day}.md"
        body = digest + (f"\n\n## 自我复盘（模型生成，未经核验）\n{narrative}\n" if narrative else "\n")
        with self.tasks.fence(lease) if lease is not None else nullcontext():
            path.write_text(body, encoding="utf-8")
            if narrative:
                with open(self.dir / "PROPOSALS.md", "a", encoding="utf-8") as fh:
                    fh.write(f"\n## {day}\n{narrative}\n")
        try:
            self.j.append({"event": "digest", "name": day,
                           "status": "narrative" if narrative else "plain"})
        except Exception:
            pass
        return {"day": day, "path": str(path), "narrative": bool(narrative)}

    def last_digest(self) -> dict[str, Any]:
        files = sorted(self.dir.glob("digest-*.md"))
        if not files:
            return {}
        f = files[-1]
        return {"day": f.stem.replace("digest-", ""), "path": str(f)}


# --------------------------------------------------------------------- sched
def scheduler_loop(reflector: Reflector, calibration, probes, cfg: dict, *,
                   interval: int = 1800, initial: int = 90, stop_event=None) -> None:
    """Background loop: autosweep + daily digest + weekly probes (best-effort)."""
    def tick() -> None:
        try:
            calibration.run_sweep()
            calibration.snapshot()
        except Exception:
            pass
        if stop_event.is_set(): return
        day = (utcnow() - timedelta(days=1)).date().isoformat()
        task = f"digest:{day}"
        lease = reflector.tasks.acquire(task)
        if lease is not None:
            try:
                with reflector.tasks.heartbeat(lease):
                    reflector.run(day=day, with_narrative=True, lease=lease)
                reflector.tasks.complete(lease)
            except Exception:
                reflector.tasks.fail(lease)
        if stop_event.is_set(): return
        try:
            weekday = int(cfg.get("probe_weekday", 0))
            hour = int(cfg.get("probe_hour", 9))
            if probes is not None and weekday >= 0 and utcnow().weekday() == weekday and utcnow().hour >= hour:
                isoy, isow, _ = utcnow().isocalendar()
                ptask = f"probe:{isoy}-W{isow:02d}"
                please = reflector.tasks.acquire(ptask)
                if please is not None:
                    try:
                        with reflector.tasks.heartbeat(please):
                            probes.run(lease=please, stop_event=stop_event)
                        reflector.tasks.complete(please)
                    except Exception:
                        reflector.tasks.fail(please)
        except Exception:
            pass

    stop_event = stop_event or threading.Event()
    if stop_event.wait(initial): return
    while not stop_event.is_set():
        try:
            tick()
        except Exception:
            pass
        if stop_event.wait(interval): break
