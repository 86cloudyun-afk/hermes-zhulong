"""Chat command for the Zhulong layer: /zhulong [status|tail N|help]."""
from __future__ import annotations

from typing import Any

_USAGE = "用法：/zhulong [status | tail N | help]"


class Commands:
    def __init__(self, journal) -> None:
        self.j = journal

    def handle(self, raw: str) -> str:
        try:
            args = (raw or "").strip().split()
            sub = args[0].lower() if args else "status"
            if sub in ("status", "st", ""):
                return self._status()
            if sub == "tail":
                n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
                return self._tail(n)
            if sub in ("help", "-h", "--help"):
                return self._help()
            return _USAGE
        except Exception as exc:  # commands must degrade gracefully
            return f"烛龙：命令执行出错（{type(exc).__name__}）。{_USAGE}"

    # ------------------------------------------------------------------ views
    def _status(self) -> str:
        s = self.j.stats()
        return (
            "🐉 烛龙 · 观测层 v0.1\n"
            f"今日事件：{s['today']} ｜ 累计：{s['total']}\n"
            f"最近事件：{s['last_ts'] or '—'}\n"
            f"数据目录：{s['dir']}"
        )

    def _tail(self, n: int) -> str:
        rows = self.j.tail(min(n, 50))
        if not rows:
            return "🐉 烛龙：还没有事件。"
        lines = ["🐉 烛龙 · 最近事件："]
        for r in rows:
            ts = (r.get("ts") or "")[11:19]
            ev = str(r.get("event") or "?")
            name = str(r.get("name") or "")
            status = str(r.get("status") or "")
            extra = ""
            if r.get("duration_ms") is not None:
                extra = f" {r['duration_ms']}ms"
            elif r.get("result_chars") is not None:
                extra = f" out:{r['result_chars']}c"
            lines.append(f"{ts} {ev:<14} {name:<12} {status}{extra}".rstrip())
        return "\n".join(lines)

    def _help(self) -> str:
        return (
            "🐉 烛龙（Zhulong）· 自我观测层\n"
            "  /zhulong status    — 今日/累计统计\n"
            "  /zhulong tail N    — 最近 N 条事件\n"
            "  /zhulong help      — 本帮助"
        )


def build_commands(journal) -> Commands:
    return Commands(journal)
