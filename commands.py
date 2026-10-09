"""Chat commands for the Zhulong layer.

/zhulong status | tail N | calibrate [run|list|report|resolve id true|false|cancel id] | help
"""
from __future__ import annotations

_USAGE = "用法：/zhulong [status | tail N | calibrate ... | help]"


class Commands:
    def __init__(self, journal, calibration=None) -> None:
        self.j = journal
        if calibration is None:
            try:
                from calibrate import Calibration
            except ImportError:
                import sys
                from pathlib import Path
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from calibrate import Calibration
            calibration = Calibration(journal)
        self.c = calibration

    def handle(self, raw: str) -> str:
        try:
            args = (raw or "").strip().split()
            sub = args[0].lower() if args else "status"
            if sub in ("status", "st"):
                return self._status()
            if sub == "tail":
                n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
                return self._tail(n)
            if sub in ("calibrate", "cal"):
                return self._calibrate(args[1:])
            if sub in ("help", "-h", "--help"):
                return self._help()
            return _USAGE
        except Exception as exc:
            return f"烛龙：命令执行出错（{type(exc).__name__}）。{_USAGE}"

    # ------------------------------------------------------------------ status
    def _status(self) -> str:
        s = self.j.stats()
        m = self.c.metrics()
        brier = f"{m['brier']:.3f}" if m["brier"] is not None else "—"
        return (
            "🐉 烛龙 · 观测层 v0.2\n"
            f"今日事件：{s['today']} ｜ 累计：{s['total']}\n"
            f"校准账：已结 {m['n_resolved']} ｜ 未结 {m['pending']} ｜ 弃答 {m['abstain']} ｜ Brier {brier}\n"
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

    # --------------------------------------------------------------- calibrate
    def _calibrate(self, args: list[str]) -> str:
        sub = args[0].lower() if args else "report"
        if sub == "run":
            s = self.c.run_sweep()
            self.c.snapshot()
            notes = "\n".join("  " + n for n in s["notes"]) or "  （无待结项）"
            return f"🐉 校准对账完成：检查 {s['checked']}，结算 {s['resolved']}\n{notes}"
        if sub == "list":
            rows = self.c.recent(20)
            if not rows:
                return "🐉 校准账为空。"
            lines = ["🐉 校准账 · 最近 20 条："]
            for r in rows:
                conf = f"{r['confidence']}%" if r["confidence"] is not None else "弃答"
                mark = {"pending": "…", "resolved": "✓" if r["outcome"] else "✗",
                        "abstain": "—", "cancelled": "×"}.get(r["status"], "?")
                lines.append(f"  #{r['id']} {mark} {conf:>4} 「{r['claim'][:32]}」")
            return "\n".join(lines)
        if sub == "resolve" and len(args) >= 3:
            pid = int(args[1])
            truth = args[2].lower() in ("true", "1", "yes", "真", "对")
            ok = self.c.resolve(pid, truth, actor="human")
            return f"🐉 #{pid} → {'已判真' if truth else '已判假'}" if ok else f"🐉 #{pid} 不是待结状态。"
        if sub == "cancel" and len(args) >= 2:
            ok = self.c.cancel(int(args[1]), note="human cancel")
            return f"🐉 #{args[1]} 已取消。" if ok else f"🐉 #{args[1]} 不是待结状态。"
        return self._report()

    def _report(self) -> str:
        m = self.c.metrics()
        if m["n_resolved"] == 0 and m["pending"] == 0:
            return ("🐉 校准账为空。\n"
                    "记录方式：让 agent 调用工具 zhulong_predict；或等它自己提预测。\n"
                    f"{self._help()}")
        def fmt(v, pct=True):
            if v is None:
                return "—"
            return f"{v * 100:.1f}%" if pct else f"{v:.3f}"
        lines = [
            "🐉 烛龙 · 校准账报告",
            f"已结 {m['n_resolved']} ｜ 未结 {m['pending']} ｜ 弃答记录 {m['abstain']}",
            f"Brier {fmt(m['brier'], False)}（越低越好） ｜ ECE {fmt(m['ece'], False)} ｜ 命中率 {fmt(m['accuracy'])}",
        ]
        rows = [r for r in self.c.recent(8) if r["status"] in ("resolved", "pending")][:6]
        if rows:
            lines.append("最近条目：")
            for r in rows:
                conf = f"{r['confidence']}%" if r["confidence"] is not None else "弃答"
                if r["status"] == "resolved":
                    mk = "✓真" if r["outcome"] else "✗假"
                else:
                    mk = "…待结"
                lines.append(f"  #{r['id']} {mk} {conf:>4} 「{r['claim'][:30]}」")
        hist = self.c.history(7)
        if hist:
            lines.append("历史快照：")
            for day, brier, ece, acc, pending in hist:
                b = f"{brier:.3f}" if brier is not None else "—"
                lines.append(f"  {day}  Brier {b} ｜ 未结 {pending}")
        return "\n".join(lines)

    def _help(self) -> str:
        return (
            "🐉 烛龙（Zhulong）· 自我观测/校准层 v0.2\n"
            "  /zhulong status               — 概况\n"
            "  /zhulong tail N               — 最近 N 条事件\n"
            "  /zhulong calibrate            — 校准账报告\n"
            "  /zhulong calibrate list       — 最近条目\n"
            "  /zhulong calibrate run        — 立即对账（机械核验）\n"
            "  /zhulong calibrate resolve <id> true|false — 人工裁决\n"
            "  /zhulong calibrate cancel <id>"
        )


def build_commands(journal, calibration=None) -> Commands:
    return Commands(journal, calibration)
