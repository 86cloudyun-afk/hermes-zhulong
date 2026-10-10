"""Chat commands for the Zhulong layer.

/zhulong status | tail N | calibrate ... | reflect [run] | probes [run] | model | autonomy ... | help
"""
from __future__ import annotations

_USAGE = "用法：/zhulong [status | tail N | calibrate ... | reflect [run] | probes [run] | model | autonomy ... | help]"


class Commands:
    def __init__(self, journal, calibration=None, reflector=None, probes=None, autonomy=None, self_model=None) -> None:
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
        self.r = reflector
        self.p = probes
        self.a = autonomy
        self.model = self_model

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
            if sub == "reflect":
                return self._reflect(args[1:])
            if sub == "probes":
                return self._probes(args[1:])
            if sub == "model":
                import json
                return json.dumps(self.model.snapshot(),ensure_ascii=False,indent=2) if self.model else "自我模型不可用。"
            if sub == "autonomy":
                return self._autonomy(args[1:])
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
        lines = [
            "🐉 烛龙 · 自主核心 v0.4",
            f"今日事件：{s['today']} ｜ 累计：{s['total']}",
            f"校准账：已结 {m['n_resolved']} ｜ 未结 {m['pending']} ｜ 弃答 {m['abstain']} ｜ Brier {brier}",
        ]
        if self.r is not None:
            last = self.r.last_digest()
            lines.append(f"反思：最近 digest {last.get('day', '—')}")
        if self.p is not None:
            runs = self.p.last_runs(1)
            lines.append(f"探针：最近运行 {runs[0]['ts'][:10] if runs else '—'}")
        lines.append(f"最近事件：{s['last_ts'] or '—'}")
        lines.append(f"数据目录：{s['dir']}")
        return "\n".join(lines)

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
                    "记录方式：让 agent 调用工具 zhulong_predict。\n"
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
                mk = ("✓真" if r["outcome"] else "✗假") if r["status"] == "resolved" else "…待结"
                lines.append(f"  #{r['id']} {mk} {conf:>4} 「{r['claim'][:30]}」")
        hist = self.c.history(7)
        if hist:
            lines.append("历史快照：")
            for day, brier, ece, acc, pending in hist:
                b = f"{brier:.3f}" if brier is not None else "—"
                lines.append(f"  {day}  Brier {b} ｜ 未结 {pending}")
        return "\n".join(lines)

    # ----------------------------------------------------------------- reflect
    def _reflect(self, args: list[str]) -> str:
        if self.r is None:
            return "🐉 反思引擎未接线。"
        if args and args[0].lower() == "run":
            out = self.r.run()
            mode = "含模型复盘（未经核验）" if out["narrative"] else "纯统计"
            return f"🐉 反思已生成（{mode}）：{out['path']}"
        last = self.r.last_digest()
        if not last:
            return "🐉 还没有 digest。运行 /zhulong reflect run 立即生成。"
        return f"🐉 最近 digest：{last['day']}\n{last['path']}\n（/zhulong reflect run 可立即再生成）"

    # ------------------------------------------------------------------ probes
    def _probes(self, args: list[str]) -> str:
        if self.p is None:
            return "🐉 探针未接线。"
        if args and args[0].lower() == "run":
            res = self.p.run()
            brier = f"{res['brier']:.3f}" if res["brier"] is not None else "—"
            return (f"🐉 探针完成：知识 {res['k_correct']}/{res['n_k']} ｜ "
                    f"Brier {brier} ｜ 未知题合理弃答 {res['u_ok']}/2 ｜ 假前提识破 {res['f_ok']}/1")
        runs = self.p.last_runs(5)
        if not runs:
            return "🐉 探针还没有运行记录。运行 /zhulong probes run 立即执行。"
        lines = ["🐉 探针历史："]
        for r in runs:
            brier = f"{r['brier']:.3f}" if r["brier"] is not None else "—"
            lines.append(f"  {r['ts'][:16]}  知识 {r['k_correct']}/{r['n_k']} ｜ Brier {brier} ｜ 弃答 {r['u_ok']} ｜ 假前提 {r['f_ok']}")
        return "\n".join(lines)

    def _autonomy(self, args):
        import json
        if self.a is None:return '自主核心配置不可用；请检查 profile 的 zhulong/config.json。'
        action=args[0] if args else 'status'
        if action=='goals':
            try:
                from .task_inputs import public_goals
            except ImportError:
                from task_inputs import public_goals
            result={'goals':public_goals(self.a.ledger)}
        elif action=='experience':result=self.a.experience_status()
        elif action=='skills':result=self.a.skills_status()
        elif action in ('status','tick','pause','resume'):result=getattr(self.a,action)()
        elif action=='cancel' and len(args)==2:result=self.a.cancel(args[1])
        else:return '用法：/zhulong autonomy [status|goals|experience|skills|tick|pause|resume|cancel <id>]'
        return json.dumps(result,ensure_ascii=False,indent=2)

    def _help(self) -> str:
        return (
            "🐉 烛龙（Zhulong）· 观测/校准/自主核心 v0.6\n"
            "  /zhulong status               — 概况\n"
            "  /zhulong tail N               — 最近 N 条事件\n"
            "  /zhulong calibrate            — 校准账报告\n"
            "  /zhulong calibrate run        — 立即对账\n"
            "  /zhulong calibrate resolve <id> true|false\n"
            "  /zhulong reflect [run]        — 反思 digest 信息/生成\n"
            "  /zhulong probes [run]         — 探针历史/立即运行\n"
            "  /zhulong model                — 证据型自我模型（只读）\n"
            "  /zhulong autonomy [status|goals|experience|skills|tick|pause|resume|cancel <id>]"
        )


def build_commands(journal, calibration=None, reflector=None, probes=None, autonomy=None, self_model=None) -> Commands:
    return Commands(journal, calibration, reflector, probes, autonomy, self_model)
