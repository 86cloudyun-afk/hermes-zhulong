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
    from .autonomy_store import Ledger
    from .autonomy_checks import validate_config, Verifier
    from .hermes_runs import RunsClient
    from .self_model import SelfModel
    from .autonomy import Controller, LLMPlanner
    from .runtime_channel import ServiceChannel
    from .experience_store import ExperienceStore
    from .experience import ExperienceLearner
    from .skill_store import SkillStore
    from .skill_evaluator import DockerEvaluator
    from .skill_learning import SkillLearner
except ImportError:
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    from storage import Journal
    from sensor import Sensor
    from calibrate import Calibration
    from commands import build_commands
    from reflect import Db, Tasks, Budget, Reflector, load_config, scheduler_loop
    from probes import Probes
    from autonomy_store import Ledger
    from autonomy_checks import validate_config, Verifier
    from hermes_runs import RunsClient
    from self_model import SelfModel
    from autonomy import Controller, LLMPlanner
    from runtime_channel import ServiceChannel
    from experience_store import ExperienceStore
    from experience import ExperienceLearner
    from skill_store import SkillStore
    from skill_evaluator import DockerEvaluator
    from skill_learning import SkillLearner

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


MODEL_SCHEMA = {
    "name": "zhulong_model", "description": "读取烛龙的证据型自我模型；只报告有限验收范围和样本。",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
AUTONOMY_SCHEMA = {
    "name": "zhulong_autonomy", "description": "查看自主目标/状态，或推进一个有界自主循环；不能直接评分或改验收。",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["status", "goals", "tick", "experience", "skills"]}}, "additionalProperties": False},
}


def _public_goals(ledger):
    try:
        from .task_inputs import public_goals
    except ImportError:
        from task_inputs import public_goals
    return public_goals(ledger)


def _model_handler(model):
    def handler(params, **kwargs):
        if not isinstance(params, dict) or params:
            return json.dumps({"ok": False, "reason": "invalid_model_action"})
        try:return json.dumps({"ok": True, "model": model.snapshot()}, ensure_ascii=False)
        except Exception:return json.dumps({"ok": False, "reason": "model_unavailable"})
    return handler


def _autonomy_handler(controller, ledger, error=None):
    def handler(params, **kwargs):
        if not isinstance(params, dict) or set(params)-{'action'}:
            return json.dumps({"ok": False, "reason": "invalid_autonomy_action"})
        action=params.get('action','status')
        if action not in ('status','goals','tick','experience','skills'):
            return json.dumps({"ok": False, "reason": "invalid_autonomy_action"})
        try:
            if action=='goals':return json.dumps({"ok": True, "goals": _public_goals(ledger)},ensure_ascii=False)
            if controller is None:return json.dumps({"ok": False,"enabled": False,"blocked_reason":error or 'runtime_unavailable'})
            result=controller.tick() if action=='tick' else (controller.experience_status() if action=='experience' else
                (controller.skills_status() if action=='skills' else controller.status()))
            return json.dumps({"ok": True, **result},ensure_ascii=False)
        except Exception:return json.dumps({"ok": False,"reason": "autonomy_unavailable"})
    return handler


def register(ctx) -> None:
    global _SENSOR
    try:
        journal=Journal();cal=Calibration(journal);_SENSOR=Sensor(journal)
        for event,cb in _SENSOR.hook_table().items():ctx.register_hook(event,cb)
        cfg=load_config(journal.base);db=Db(journal.db_path);tasks=Tasks(db)
        try:budget=Budget(db,cfg.get('llm_daily_cap',40))
        except ValueError:budget=Budget(db,0)
        llm=getattr(ctx,'llm',None)
        reflector=Reflector(journal,cal,db,cfg,llm=llm,budget=budget,tasks=tasks)
        probes=Probes(journal,db,cfg,llm=llm,budget=budget,tasks=tasks)
        ledger=None;model=None;controller=None;autonomy_error=None
        experience=None;learner=None
        try:
            ledger=Ledger(journal.base/'autonomy.db')
            try:
                experience=ExperienceStore(ledger);learner=ExperienceLearner(experience,llm,budget)
            except Exception:logger.warning('zhulong: experience storage unavailable')
            model=SelfModel(ledger,journal.base,experience=experience);model.refresh()
        except Exception:
            ledger=None;model=None;autonomy_error='autonomy_storage_unavailable'
            logger.warning('zhulong: autonomy storage unavailable',exc_info=True)
        if ledger is not None:
            try:
                policy=validate_config(cfg.get('autonomy',{}),journal.base)
                runs=RunsClient(policy['api_url'],policy['api_key_env'],policy['api_identity_version'],
                    policy['request_timeout_seconds'],profile=policy['api_profile']) if policy['enabled'] else None
                controller=Controller(ledger,policy,LLMPlanner(llm,budget),runs,Verifier(policy),model,experience=learner)
                try:
                    skill_store=SkillStore(ledger,policy.get('executable_skills',[]),controller.execution_identity)
                    controller.skills=SkillLearner(skill_store,llm,budget,DockerEvaluator(ledger.path),
                        daily_evaluations=policy.get('skill_daily_evaluations',16))
                    model.skills=skill_store;model.refresh()
                except Exception:logger.warning('zhulong: skill storage unavailable')
            except (ValueError,TypeError):autonomy_error='invalid_autonomy_config'

        try:
            ctx.register_command(name='zhulong',handler=build_commands(journal,cal,reflector,probes,
                autonomy=controller,self_model=model).handle,
                description='烛龙观测、校准与自主核心',args_hint='[status|tail N|calibrate|reflect|probes|model|autonomy|help]')
        except Exception:logger.warning('zhulong: command registration failed',exc_info=True)
        for name,schema,handler in (
            ('zhulong_predict',PREDICT_SCHEMA,_predict_handler(cal)),
            ('zhulong_calibration',CALIB_SCHEMA,_calib_handler(cal,reflector,probes)),
            ('zhulong_model',MODEL_SCHEMA,_model_handler(model)),
            ('zhulong_autonomy',AUTONOMY_SCHEMA,_autonomy_handler(controller,ledger,autonomy_error))):
            try:ctx.register_tool(name=name,toolset='zhulong',schema=schema,handler=handler)
            except Exception:logger.warning('zhulong: tool registration failed',exc_info=True)

        stop_event=threading.Event();scheduler=None;service=None
        if os.environ.get('ZHULONG_SERVICE_DIR'):
            service=ServiceChannel(os.environ['ZHULONG_SERVICE_DIR'],os.environ.get('ZHULONG_BOOT_ID',''),controller,stop_event)
            service.start()
        def cleanup():
            stop_event.set()
            controller_stopped=controller is None or controller.stop()
            if scheduler is not None:scheduler.join(timeout=5)
            # Stop subsequent ticks and probe calls. A bounded in-flight call retains its resources
            # until it returns rather than racing a closed connection.
            if controller_stopped and (scheduler is None or not scheduler.is_alive()):
                db.close()
                with cal._lock:cal._conn.close()
                with journal._lock:journal._conn.close()
            if service is not None:service.stop()
        lifecycle=getattr(ctx,'on_unload',None)
        if callable(lifecycle):lifecycle(cleanup)
        if callable(lifecycle) and cfg.get('scheduler',True) and not os.environ.get('ZHULONG_NO_AUTOSWEEP'):
            scheduler=threading.Thread(target=scheduler_loop,args=(reflector,cal,probes,cfg),
                kwargs={'interval':1800,'initial':90,'stop_event':stop_event},daemon=True,name='zhulong-reflection')
            scheduler.start()
            if controller is not None and controller.policy.get('enabled'):
                controller.start(controller.policy['tick_interval_seconds'])
    except Exception:logger.warning('zhulong: registration failed',exc_info=True)
