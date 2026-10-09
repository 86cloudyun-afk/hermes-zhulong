"""烛龙 Zhulong — Hermes 自我观测 (S2) + 自校准 (S3) + 反思/探针 (S4).

- 观测：11 个 observer hooks -> 日记（JSONL + SQLite）。
- 校准：zhulong_predict / zhulong_calibration；预测只能被机械核验或人工结算。
- 反思：每日 digest（确定性）+ 可选模型复盘（标注未核验）-> reflections/。
- 探针：每周一（可配）自动跑元认知电池；也可手动。
- 零常驻开销、失败开放、数据仅在 $HERMES_HOME/zhulong/。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
try:
    from .storage import Journal
    from .sensor import Sensor
    from .calibrate import Calibration
    from .commands import build_commands
    from .reflect import Db, Tasks, Budget, Reflector, load_config, scheduler_loop
    from .probes import Probes
except ImportError:
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    from storage import Journal
    from sensor import Sensor
    from calibrate import Calibration
    from commands import build_commands
    from reflect import Db, Tasks, Budget, Reflector, load_config, scheduler_loop
    from probes import Probes

_SENSOR = None

PREDICT_SCHEMA = {
    "name": "zhulong_predict",
    "description": (
        "向烛龙校准账登记一条可对账的预测/声明（自我校准统计用）。"
        "verify 指定机械核验：{type:'file_exists',path} / {type:'file_contains',path,text} / "
        "{type:'journal_event',match:{event,name,status},within_seconds} / {type:'manual'}。"
        "可选 deadline_seconds（默认3600）决定'判假'最早生效时间。"
        "不填 verify = 人工裁决。confidence 0-100；省略表示弃答（不计分）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim": {"type": "string", "description": "要登记的预测/声明（≤500字）"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100,
                           "description": "信心 0-100；省略=弃答"},
            "verify": {"type": "object", "description": "核验规格对象（见工具描述）"},
        },
        "required": ["claim"],
    },
}

CALIB_SCHEMA = {
    "name": "zhulong_calibration",
    "description": (
        "烛龙账本操作：action=report（指标）、run（对账）、list（条目）、"
        "reflect（生成今日反思 digest）、probes（最近探针结果）、run_probes（立即跑探针电池）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["report", "run", "list", "reflect", "probes", "run_probes"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    },
}


def _predict_handler(cal):
    def handler(params, **kwargs):
        try:
            claim = str(params.get("claim", "")).strip()
            conf = params.get("confidence")
            if conf is not None and str(conf).strip() == "":
                conf = None
            conf = int(conf) if conf is not None else None
            verify = params.get("verify")
            if isinstance(verify, str):
                verify = json.loads(verify) if verify.strip() else None
            if verify is not None and not isinstance(verify, dict):
                return json.dumps({"ok": False, "error": "verify 必须是对象"})
            rec = cal.add(claim, confidence=conf, verify=verify,
                          session_id=kwargs.get("session_id"), source="agent")
            return json.dumps({"ok": True, **rec}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
    return handler


def _calib_handler(cal, reflector=None, probes=None):
    def handler(params, **kwargs):
        action = str(params.get("action", "report"))
        try:
            if action == "run":
                s = cal.run_sweep()
                cal.snapshot()
                return json.dumps({"ok": True, "sweep": s}, ensure_ascii=False)
            if action == "list":
                return json.dumps({"ok": True, "items": cal.recent(int(params.get("limit", 10)))},
                                  ensure_ascii=False)
            if action == "reflect" and reflector is not None:
                r = reflector.run()
                return json.dumps({"ok": True, **r}, ensure_ascii=False)
            if action == "probes" and probes is not None:
                return json.dumps({"ok": True, "runs": probes.last_runs()}, ensure_ascii=False)
            if action == "run_probes" and probes is not None:
                res = probes.run()
                res.pop("details", None)
                return json.dumps({"ok": True, "result": res}, ensure_ascii=False)
            return json.dumps({"ok": True, "metrics": cal.metrics()}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
    return handler


def register(ctx) -> None:
    global _SENSOR
    try:
        journal = Journal()
        cal = Calibration(journal)
        _SENSOR = Sensor(journal)
        cfg = load_config(journal.base)
        db = Db(journal.db_path)
        tasks = Tasks(db)
        budget = Budget(db, cfg.get("llm_daily_cap", 40))
        llm = getattr(ctx, "llm", None)
        reflector = Reflector(journal, cal, db, cfg, llm=llm, budget=budget, tasks=tasks)
        probes = Probes(journal, db, cfg, llm=llm, budget=budget, tasks=tasks)

        for event, cb in _SENSOR.hook_table().items():
            ctx.register_hook(event, cb)

        try:
            ctx.register_command(
                name="zhulong",
                handler=build_commands(journal, cal, reflector, probes).handle,
                description="烛龙自我观测/校准/反思层",
                args_hint="[status|tail N|calibrate|reflect|probes|help]",
            )
        except Exception:
            logger.warning("zhulong: command registration failed", exc_info=True)

        try:
            ctx.register_tool(name="zhulong_predict", toolset="zhulong",
                              schema=PREDICT_SCHEMA, handler=_predict_handler(cal))
            ctx.register_tool(name="zhulong_calibration", toolset="zhulong",
                              schema=CALIB_SCHEMA, handler=_calib_handler(cal, reflector, probes))
        except Exception:
            logger.warning("zhulong: tool registration failed", exc_info=True)

        if cfg.get("scheduler", True) and not os.environ.get("ZHULONG_NO_AUTOSWEEP"):
            threading.Thread(
                target=scheduler_loop,
                args=(reflector, cal, probes, cfg),
                kwargs={"interval": 1800, "initial": 90},
                daemon=True,
            ).start()
    except Exception:
        logger.warning("zhulong: registration failed", exc_info=True)
