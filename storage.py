"""Zhulong storage: daily JSONL (source of truth) + SQLite index.

Data lives under $HERMES_HOME/zhulong/ (or ~/.hermes/zhulong/ with no profile env).
Retention: rolling ZHULONG_RETENTION_DAYS (default 90).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "zhulong.journal.v1"
RETENTION_DAYS = int(os.environ.get("ZHULONG_RETENTION_DAYS", "90"))


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    return Path(env) if env else Path.home() / ".hermes"


class Journal:
    def __init__(self, home: Path | None = None) -> None:
        self.base = (home or hermes_home()) / "zhulong"
        self.journal_dir = self.base / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base / "zhulong.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                event TEXT NOT NULL,
                session_id TEXT,
                turn_id TEXT,
                task_id TEXT,
                name TEXT,
                status TEXT,
                payload TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_event ON events(event)")
        self._conn.commit()
        self._maybe_rotate()

    # ------------------------------------------------------------------ write
    def append(self, row: dict[str, Any]) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": SCHEMA,
            **row,
        }
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        day = row["ts"][:10]
        with self._lock:
            with open(self.journal_dir / f"events-{day}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._conn.execute(
                "INSERT INTO events(ts,event,session_id,turn_id,task_id,name,status,payload)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    row["ts"],
                    row["event"],
                    row.get("session_id"),
                    row.get("turn_id"),
                    row.get("task_id"),
                    row.get("name"),
                    row.get("status"),
                    json.dumps(row, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ read
    def stats(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            today_n = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts LIKE ?", (today + "%",)
            ).fetchone()[0]
            last = self._conn.execute("SELECT ts FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "total": total,
            "today": today_n,
            "last_ts": last[0] if last else None,
            "dir": str(self.base),
            "db": str(self.db_path),
        }

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        n = max(1, min(int(n), 200))
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        out = []
        for (payload,) in rows:
            try:
                out.append(json.loads(payload))
            except Exception:
                continue
        out.reverse()
        return out

    # ------------------------------------------------------------- retention
    def _maybe_rotate(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        cutoff_s = cutoff.isoformat(timespec="seconds")
        try:
            for f in self.journal_dir.glob("events-*.jsonl"):
                try:
                    d = datetime.strptime(f.stem.replace("events-", ""), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except Exception:
                    continue
                if d < cutoff:
                    f.unlink(missing_ok=True)
            with self._lock:
                self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff_s,))
                self._conn.commit()
        except Exception:
            pass
