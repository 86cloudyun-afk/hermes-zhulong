"""烛龙 Zhulong — Hermes self-observation spine (S2 MVP).

观察层：把 observer hooks 规范化后写入本地日记（JSONL + SQLite）。
- 仅观测：不修改任何对话、不调用 LLM。
- 失败开放：任何回调异常都吞掉，绝不影响主循环。
- 数据仅在 $HERMES_HOME/zhulong/ 下。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
try:  # loaded as a package
    from .storage import Journal
    from .sensor import Sensor
    from .commands import build_commands
except ImportError:  # loaded as a plain module — make siblings importable
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    from storage import Journal
    from sensor import Sensor
    from commands import build_commands

_SENSOR = None


def register(ctx) -> None:
    """Wire the observation spine: 11 observer hooks + /zhulong command."""
    global _SENSOR
    try:
        journal = Journal()
        _SENSOR = Sensor(journal)

        for event, cb in _SENSOR.hook_table().items():
            ctx.register_hook(event, cb)

        try:
            ctx.register_command(
                name="zhulong",
                handler=build_commands(journal).handle,
                description="烛龙观测层：查看自己的行为日记与统计",
                args_hint="[status|tail N|help]",
            )
        except Exception:
            logger.warning("zhulong: /zhulong command registration failed", exc_info=True)
    except Exception:
        # never break startup
        logger.warning("zhulong: registration failed", exc_info=True)
