"""Zhulong sensor: normalize observer-hook payloads into journal rows.

Privacy-first defaults: store metadata only (names, statuses, sizes, keys) —
never raw tool arguments, tool results, message bodies, or prompts.
"""
from __future__ import annotations

import re
from typing import Any, Callable

# --------------------------------------------------------------- failure classes
# 失败分类（只存元数据：类别 + 归一化短签名；引号内容与数字一律不落盘）。
_ERROR_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("capacity", ("would put memory at", "would exceed the limit", "memory at ", "/2,200",
                  "free at least", "exceeds the limit", "quota", "too long")),
    ("refusal", ("refusing", "blocked:", "threat pattern", "off-limits", "curator-managed",
                 "denied", "not permitted", "cannot ask the user", "prompt_unavailable",
                 "cannot restart", "protected system/credential")),
    ("anchor", ("no entry matched", "could not find a match", "not found", "no such",
                "does not exist", "not exists", "stale", "already registered")),
    ("params", ("is required", "needs a", "unknown action", "must be", "invalid",
                "unexpected keyword", "pass either", "not both", "expects", "missing")),
    ("backend", ("timeout", "timed out", "connection", "locked", "oserror", "ioerror",
                 "permission denied", "no space", "traceback", "errno", "signal")),
)

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")
_USAGE = re.compile(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)")


def _error_text(result: Any, error_type: Any) -> str:
    """从工具结果里取最可能的错误文本（仅用于分类/归一化，绝不原样落盘）。"""
    text = ""
    if isinstance(result, dict):
        for key in ("error", "message", "reason", "detail"):
            v = result.get(key)
            if isinstance(v, str) and v.strip():
                text = v
                break
        if not text:
            out = result.get("output")
            if isinstance(out, str) and out.strip():
                text = out.strip()[-300:]
    elif isinstance(result, str):
        text = result
    if not text and error_type:
        text = str(error_type)
    return text.strip()


def classify_error(text: str) -> tuple[str, str]:
    """→ (类别, 归一化短签名 ≤120 字符)。

    类别：capacity / refusal / anchor / params / backend / other。
    """
    low = (text or "").lower()
    klass = "other"
    for name, needles in _ERROR_RULES:
        if any(n in low for n in needles):
            klass = name
            break
    sig = _WS.sub(" ", _DIGITS.sub("N", _QUOTED.sub("…", text or ""))).strip()[:120]
    return klass, sig


def parse_usage(result: Any) -> tuple[int, int] | None:
    """memory 工具的容量计数 (used, limit)；取自结果里的 usage 字段。"""
    if not isinstance(result, dict):
        return None
    raw = result.get("usage")
    if not isinstance(raw, str):
        return None
    m = _USAGE.search(raw)
    if not m:
        return None
    try:
        used = int(m.group(1).replace(",", ""))
        limit = int(m.group(2).replace(",", ""))
    except ValueError:
        return None
    if limit <= 0 or used < 0 or used > 10 * limit:
        return None
    return used, limit


def _len(v: Any) -> int | None:
    try:
        return len(v) if v is not None else None
    except Exception:
        return None


def _keys(v: Any) -> list[str] | None:
    if isinstance(v, dict):
        return sorted(str(k) for k in v.keys())[:60]
    return None


class Sensor:
    def __init__(self, journal) -> None:
        self.j = journal

    # ------------------------------------------------------------------ core
    def _emit(self, event: str, **fields: Any) -> None:
        try:
            row: dict[str, Any] = {"event": event}
            row.update({k: v for k, v in fields.items() if v is not None})
            self.j.append(row)
        except Exception:
            pass  # observer callbacks must never break the turn

    # ------------------------------------------------------------- callbacks
    def on_post_tool_call(self, **kw: Any) -> None:
        name = kw.get("tool_name")
        status = str(kw.get("status") or "")
        result = kw.get("result")
        error_class = error_sig = None
        if status.lower() not in ("", "ok", "success"):
            error_class, error_sig = classify_error(_error_text(result, kw.get("error_type")) or status)
        usage = parse_usage(result) if name == "memory" else None
        self._emit(
            "tool_call",
            session_id=kw.get("session_id"),
            turn_id=kw.get("turn_id"),
            task_id=kw.get("task_id"),
            name=name,
            status=kw.get("status"),
            duration_ms=kw.get("duration_ms"),
            args_keys=_keys(kw.get("args")),
            args_chars=_len(kw.get("args")),
            result_chars=_len(result),
            error_type=kw.get("error_type"),
            error_class=error_class,
            error_sig=error_sig,
            usage=f"{usage[0]}/{usage[1]}" if usage else None,
            usage_ratio=round(usage[0] / usage[1], 4) if usage else None,
        )

    def on_post_llm_call(self, **kw: Any) -> None:
        self._emit(
            "turn",
            session_id=kw.get("session_id"),
            turn_id=kw.get("turn_id"),
            task_id=kw.get("task_id"),
            status=kw.get("platform"),
            user_chars=_len(kw.get("user_message")),
            assistant_chars=_len(kw.get("assistant_response")),
            history_chars=_len(kw.get("conversation_history")),
        )

    def on_session_start(self, **kw: Any) -> None:
        self._emit(
            "session_start",
            session_id=kw.get("session_id"),
            status=kw.get("platform"),
            model=kw.get("model") if "model" in kw else None,
        )

    def on_session_end(self, **kw: Any) -> None:
        self._emit(
            "session_end",
            session_id=kw.get("session_id"),
            turn_id=kw.get("turn_id"),
            completed=kw.get("completed"),
            failed=kw.get("failed"),
            interrupted=kw.get("interrupted"),
            reason=kw.get("turn_exit_reason"),
        )

    def on_session_finalize(self, **kw: Any) -> None:
        self._emit(
            "session_finalize",
            session_id=kw.get("session_id"),
            status=kw.get("platform"),
            reason=kw.get("reason"),
        )

    def on_session_reset(self, **kw: Any) -> None:
        self._emit(
            "session_reset",
            session_id=kw.get("session_id"),
            status=kw.get("platform"),
            reason=kw.get("reason"),
        )

    def on_skill_lifecycle(self, **kw: Any) -> None:
        self._emit(
            "skill",
            session_id=kw.get("session_id"),
            task_id=kw.get("task_id"),
            name=kw.get("skill_name"),
            status=kw.get("action"),
            provenance=kw.get("provenance"),
            use_count=kw.get("use_count"),
            reused=kw.get("reused"),
            reuse_after_patch=kw.get("reuse_after_patch"),
        )

    def on_subagent_stop(self, **kw: Any) -> None:
        self._emit(
            "subagent_stop",
            session_id=kw.get("parent_session_id"),
            task_id=kw.get("parent_turn_id"),
            name=kw.get("child_role"),
            status=kw.get("child_status"),
            duration_ms=kw.get("duration_ms"),
            summary_chars=_len(kw.get("child_summary")),
        )

    def on_api_request_error(self, **kw: Any) -> None:
        self._emit(
            "api_error",
            session_id=kw.get("session_id"),
            turn_id=kw.get("turn_id"),
            name=kw.get("provider"),
            status=str(kw.get("status_code")) if kw.get("status_code") is not None else None,
            error_type=kw.get("error_type"),
            retryable=kw.get("retryable"),
            retry_count=kw.get("retry_count"),
        )

    def on_agent_loop_stopped(self, **kw: Any) -> None:
        self._emit(
            "loop_stopped",
            session_id=kw.get("session_key"),
            status=kw.get("platform"),
            reason=kw.get("reason"),
            invalidation_reason=kw.get("invalidation_reason"),
        )

    def on_pre_command(self, **kw: Any) -> None:
        self._emit(
            "command",
            session_id=kw.get("session_key"),
            name=kw.get("command"),
            status=kw.get("surface"),
            alias_used=kw.get("alias_used"),
            args_chars=_len(kw.get("args_raw")),
        )

    # ------------------------------------------------------------------ table
    def hook_table(self) -> dict[str, Callable]:
        return {
            "post_tool_call": self.on_post_tool_call,
            "post_llm_call": self.on_post_llm_call,
            "on_session_start": self.on_session_start,
            "on_session_end": self.on_session_end,
            "on_session_finalize": self.on_session_finalize,
            "on_session_reset": self.on_session_reset,
            "on_skill_lifecycle": self.on_skill_lifecycle,
            "subagent_stop": self.on_subagent_stop,
            "api_request_error": self.on_api_request_error,
            "agent_loop_stopped": self.on_agent_loop_stopped,
            "pre_command": self.on_pre_command,
        }
