#!/usr/bin/env python3
"""Codex command hook 的标准化 Python 模板。

约定：
1. stdin 只读取一个 Codex hook JSON 对象。
2. stdout 只写一个 hook 协议 JSON 对象，禁止输出普通日志。
3. 运行日志写 stderr 和轮转 JSONL 文件。
4. 业务逻辑只放在 ``on_*`` 事件函数中，公共处理不要重复实现。

该文件仅依赖 Python 标准库，兼容 Python 3.10+。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Literal, Mapping, Sequence, cast


HookEventName = Literal[
    "SessionStart",
    "SessionEnd",
    "SubagentStart",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "UserPromptSubmit",
    "SubagentStop",
    "Stop",
    # Codex main 分支已经定义，当前发布文档尚未承诺。保留用于向前兼容。
    "Interrupt",
]
PermissionMode = Literal[
    "default",
    "acceptEdits",
    "plan",
    "dontAsk",
    "bypassPermissions",
]
JsonObject = dict[str, Any]
Handler = Callable[["HookInput"], "HookOutput"]

DOCUMENTED_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "SessionStart",
        "SessionEnd",
        "SubagentStart",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "UserPromptSubmit",
        "SubagentStop",
        "Stop",
    }
)
MAIN_PREVIEW_EVENTS: Final[frozenset[str]] = frozenset({"Interrupt"})
SUPPORTED_EVENTS: Final[frozenset[str]] = DOCUMENTED_EVENTS | MAIN_PREVIEW_EVENTS

PERMISSION_MODES: Final[frozenset[str]] = frozenset(
    {"default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"}
)
SESSION_START_SOURCES: Final[frozenset[str]] = frozenset(
    {"startup", "resume", "clear", "compact"}
)
COMPACTION_TRIGGERS: Final[frozenset[str]] = frozenset({"manual", "auto"})

# 这些是每个事件在当前发布协议或 Codex main schema 中的必填字段。
REQUIRED_FIELDS: Final[dict[str, frozenset[str]]] = {
    "SessionStart": frozenset(
        {
            "session_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "source",
        }
    ),
    # 当前源码的 SessionEnd 有意不包含 model、permission_mode 和 turn_id。
    "SessionEnd": frozenset(
        {"session_id", "transcript_path", "cwd", "hook_event_name", "reason"}
    ),
    "SubagentStart": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "agent_id",
            "agent_type",
        }
    ),
    "PreToolUse": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "tool_name",
            "tool_input",
            "tool_use_id",
        }
    ),
    "PermissionRequest": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "tool_name",
            "tool_input",
        }
    ),
    "PostToolUse": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "tool_name",
            "tool_input",
            "tool_response",
            "tool_use_id",
        }
    ),
    "PreCompact": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "trigger",
        }
    ),
    "PostCompact": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "trigger",
        }
    ),
    "UserPromptSubmit": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "prompt",
        }
    ),
    "SubagentStop": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "agent_transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "stop_hook_active",
            "agent_id",
            "agent_type",
            "last_assistant_message",
        }
    ),
    "Stop": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "stop_hook_active",
            "last_assistant_message",
        }
    ),
    # 仅 Codex main 分支预览，不应写入面向稳定版本的 hooks.json。
    "Interrupt": frozenset(
        {
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
        }
    ),
}

# 当上述事件发生在 subagent 上下文时，源码会额外提供这两个字段。
OPTIONAL_SUBAGENT_CONTEXT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "UserPromptSubmit",
    }
)

NULLABLE_STRING_FIELDS: Final[frozenset[str]] = frozenset(
    {"transcript_path", "agent_transcript_path", "last_assistant_message"}
)
BOOLEAN_FIELDS: Final[frozenset[str]] = frozenset({"stop_hook_active"})
ARBITRARY_JSON_FIELDS: Final[frozenset[str]] = frozenset(
    {"tool_input", "tool_response"}
)
SENSITIVE_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)
MAX_LOG_STRING_CHARS: Final[int] = 4096
DEFAULT_MAX_INPUT_BYTES: Final[int] = 2 * 1024 * 1024
DEFAULT_LOG_MAX_BYTES: Final[int] = 5 * 1024 * 1024
DEFAULT_LOG_BACKUPS: Final[int] = 5


class HookProtocolError(ValueError):
    """输入或输出不满足 Codex hook 协议。"""


@dataclass(frozen=True)
class HookInput:
    """统一事件视图。

    ``raw`` 始终保留完整 JSON，事件专有字段通过属性读取。这样 Codex 新增字段时
    模板可以先记录告警并继续运行，而不需要立刻升级基础框架。
    """

    raw: Mapping[str, Any]
    event_name: HookEventName
    session_id: str
    cwd: Path
    transcript_path: Path | None
    model: str | None
    permission_mode: PermissionMode | str | None
    turn_id: str | None
    agent_id: str | None
    agent_type: str | None

    @classmethod
    def parse(cls, payload: JsonObject, logger: logging.Logger) -> "HookInput":
        event_value = payload.get("hook_event_name")
        if not isinstance(event_value, str) or event_value not in SUPPORTED_EVENTS:
            raise HookProtocolError(
                f"hook_event_name 必须是受支持事件，实际值为 {event_value!r}"
            )
        event_name = cast(HookEventName, event_value)
        required = REQUIRED_FIELDS[event_name]
        missing = sorted(field for field in required if field not in payload)
        if missing:
            raise HookProtocolError(f"{event_name} 缺少必填字段: {', '.join(missing)}")

        optional = (
            {"agent_id", "agent_type"}
            if event_name in OPTIONAL_SUBAGENT_CONTEXT_EVENTS
            else set()
        )
        unknown = sorted(set(payload) - required - optional)
        if unknown:
            logger.warning(
                "检测到协议未登记字段，将原样保留以便向前兼容",
                extra={"fields": unknown},
            )

        for field in required | optional:
            if field not in payload:
                continue
            value = payload[field]
            if field in ARBITRARY_JSON_FIELDS:
                continue
            if field in NULLABLE_STRING_FIELDS:
                if value is not None and not isinstance(value, str):
                    raise HookProtocolError(f"{field} 必须是 string 或 null")
            elif field in BOOLEAN_FIELDS:
                if not isinstance(value, bool):
                    raise HookProtocolError(f"{field} 必须是 boolean")
            elif not isinstance(value, str):
                raise HookProtocolError(f"{field} 必须是 string")

        if event_name == "SessionStart" and payload["source"] not in SESSION_START_SOURCES:
            logger.warning(
                "发现未知 SessionStart source，将继续处理",
                extra={"source": payload["source"]},
            )
        if event_name in {"PreCompact", "PostCompact"} and payload[
            "trigger"
        ] not in COMPACTION_TRIGGERS:
            logger.warning(
                "发现未知 compact trigger，将继续处理",
                extra={"trigger": payload["trigger"]},
            )
        permission_mode = payload.get("permission_mode")
        if permission_mode is not None and permission_mode not in PERMISSION_MODES:
            logger.warning(
                "发现未知 permission_mode，将继续处理",
                extra={"permission_mode": permission_mode},
            )

        transcript = payload.get("transcript_path")
        return cls(
            raw=payload,
            event_name=event_name,
            session_id=cast(str, payload["session_id"]),
            cwd=Path(cast(str, payload["cwd"])),
            transcript_path=Path(transcript) if isinstance(transcript, str) else None,
            model=cast(str | None, payload.get("model")),
            permission_mode=cast(str | None, permission_mode),
            turn_id=cast(str | None, payload.get("turn_id")),
            agent_id=cast(str | None, payload.get("agent_id")),
            agent_type=cast(str | None, payload.get("agent_type")),
        )

    def get(self, field: str, default: Any = None) -> Any:
        """读取事件专有字段，例如 tool_input、prompt、trigger。"""

        return self.raw.get(field, default)


@dataclass(frozen=True)
class HookOutput:
    """只生成官方当前支持的输出形状。"""

    payload: JsonObject

    @classmethod
    def success(cls, system_message: str | None = None) -> "HookOutput":
        payload: JsonObject = {}
        if system_message:
            payload["systemMessage"] = system_message
        return cls(payload)

    @classmethod
    def additional_context(
        cls, event_name: HookEventName, text: str, system_message: str | None = None
    ) -> "HookOutput":
        if event_name not in {
            "SessionStart",
            "SubagentStart",
            "PreToolUse",
            "PostToolUse",
            "UserPromptSubmit",
        }:
            raise HookProtocolError(f"{event_name} 不支持 additionalContext")
        payload: JsonObject = {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": _non_empty(text, "additionalContext"),
            }
        }
        if system_message:
            payload["systemMessage"] = system_message
        return cls(payload)

    @classmethod
    def pre_tool_deny(cls, reason: str) -> "HookOutput":
        return cls(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _non_empty(reason, "reason"),
                }
            }
        )

    @classmethod
    def pre_tool_rewrite(
        cls, updated_input: JsonObject, additional_context: str | None = None
    ) -> "HookOutput":
        specific: JsonObject = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
        }
        if additional_context:
            specific["additionalContext"] = additional_context
        return cls({"hookSpecificOutput": specific})

    @classmethod
    def permission_allow(cls) -> "HookOutput":
        return cls(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            }
        )

    @classmethod
    def permission_deny(cls, message: str) -> "HookOutput":
        return cls(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {
                        "behavior": "deny",
                        "message": _non_empty(message, "message"),
                    },
                }
            }
        )

    @classmethod
    def block(cls, event_name: HookEventName, reason: str) -> "HookOutput":
        if event_name not in {
            "PostToolUse",
            "UserPromptSubmit",
            "SubagentStop",
            "Stop",
        }:
            raise HookProtocolError(f"{event_name} 不支持 decision:block")
        return cls({"decision": "block", "reason": _non_empty(reason, "reason")})

    @classmethod
    def stop_processing(
        cls, event_name: HookEventName, reason: str, system_message: str | None = None
    ) -> "HookOutput":
        if event_name not in {
            "SessionStart",
            "PreCompact",
            "PostCompact",
            "UserPromptSubmit",
            "SubagentStop",
            "Stop",
            "PostToolUse",
        }:
            raise HookProtocolError(f"{event_name} 不支持 continue:false")
        payload: JsonObject = {
            "continue": False,
            "stopReason": _non_empty(reason, "stopReason"),
        }
        if system_message:
            payload["systemMessage"] = system_message
        return cls(payload)


def _non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HookProtocolError(f"{field} 必须是非空字符串")
    return value.strip()


class JsonLogFormatter(logging.Formatter):
    """每行一个 JSON，便于 jq、日志采集器和关联排障。"""

    EXTRA_FIELDS: Final[tuple[str, ...]] = (
        "event_name",
        "session_id",
        "turn_id",
        "duration_ms",
        "fields",
        "source",
        "trigger",
        "permission_mode",
        "log_path",
        "payload",
    )

    def format(self, record: logging.LogRecord) -> str:
        item: JsonObject = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.EXTRA_FIELDS:
            if hasattr(record, field):
                item[field] = sanitize_for_log(getattr(record, field))
        if record.exc_info:
            item["exception"] = self.formatException(record.exc_info)
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    """递归脱敏并限制日志体积；不修改实际 hook 输入。"""

    if key is not None and SENSITIVE_KEY_RE.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize_for_log(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_for_log(item) for item in value]
    if isinstance(value, str) and len(value) > MAX_LOG_STRING_CHARS:
        omitted = len(value) - MAX_LOG_STRING_CHARS
        return f"{value[:MAX_LOG_STRING_CHARS]}…<truncated {omitted} chars>"
    return value


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError as error:
        raise HookProtocolError(f"环境变量 {name} 必须是整数") from error
    if parsed < minimum:
        raise HookProtocolError(f"环境变量 {name} 必须 >= {minimum}")
    return parsed


def _find_project_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def resolve_log_path(payload: Mapping[str, Any]) -> Path:
    """日志目录优先级：显式环境变量、插件数据目录、项目 .codex 目录。"""

    explicit_dir = os.environ.get("CODEX_HOOK_LOG_DIR")
    if explicit_dir:
        log_dir = Path(explicit_dir).expanduser()
    elif os.environ.get("PLUGIN_DATA"):
        log_dir = Path(cast(str, os.environ["PLUGIN_DATA"])) / "logs"
    else:
        cwd_value = payload.get("cwd")
        cwd = Path(cwd_value) if isinstance(cwd_value, str) else Path.cwd()
        log_dir = _find_project_root(cwd) / ".codex" / "hooks" / "logs"
    return log_dir / os.environ.get("CODEX_HOOK_LOG_FILE", "codex-hooks.jsonl")


def configure_logging(payload: Mapping[str, Any]) -> tuple[logging.Logger, Path | None]:
    logger = logging.getLogger("codex_hook")
    logger.handlers.clear()
    logger.propagate = False
    configured_level = os.environ.get("CODEX_HOOK_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, configured_level, logging.INFO)
    logger.setLevel(logging.DEBUG)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s codex_hook: %(message)s")
    )
    logger.addHandler(stderr_handler)

    log_path = resolve_log_path(payload)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_env_int(
                "CODEX_HOOK_LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES, minimum=1024
            ),
            backupCount=_env_int(
                "CODEX_HOOK_LOG_BACKUPS", DEFAULT_LOG_BACKUPS, minimum=1
            ),
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JsonLogFormatter())
        logger.addHandler(file_handler)
        return logger, log_path
    except OSError:
        logger.exception("无法创建 hook 日志文件，将仅使用 stderr")
        return logger, None


def read_stdin_json() -> JsonObject:
    max_bytes = _env_int(
        "CODEX_HOOK_MAX_INPUT_BYTES", DEFAULT_MAX_INPUT_BYTES, minimum=1024
    )
    raw = sys.stdin.buffer.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HookProtocolError(f"stdin 超过上限 {max_bytes} bytes")
    if not raw.strip():
        raise HookProtocolError("stdin 为空")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HookProtocolError("stdin 必须是 UTF-8") from error
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise HookProtocolError(
            f"stdin 不是有效 JSON: line={error.lineno}, column={error.colno}"
        ) from error
    if not isinstance(payload, dict):
        raise HookProtocolError("stdin 顶层必须是 JSON object")
    return cast(JsonObject, payload)


def write_stdout_json(payload: Mapping[str, Any]) -> None:
    """stdout 是协议通道；整个程序只有这里可以写 stdout。"""

    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(serialized + "\n")
    sys.stdout.flush()


def validate_output(event_name: HookEventName, output: HookOutput) -> None:
    if not isinstance(output.payload, dict):
        raise HookProtocolError("handler 必须返回 JSON object")
    specific = output.payload.get("hookSpecificOutput")
    if specific is not None:
        if not isinstance(specific, dict):
            raise HookProtocolError("hookSpecificOutput 必须是 object")
        if specific.get("hookEventName") != event_name:
            raise HookProtocolError(
                "hookSpecificOutput.hookEventName 必须与输入事件一致"
            )

    if output.payload.get("decision") == "block" and not str(
        output.payload.get("reason", "")
    ).strip():
        raise HookProtocolError("decision:block 必须同时返回非空 reason")
    if event_name == "Interrupt" and set(output.payload) - {"systemMessage"}:
        raise HookProtocolError("Interrupt 预览 schema 当前只接受 systemMessage")
    if event_name == "SessionEnd" and output.payload:
        raise HookProtocolError("SessionEnd 输出不会影响 Codex，请返回空对象")


# ---------------------------------------------------------------------------
# 业务开发区：修改对应函数即可。默认全部放行/继续，不产生副作用。
# ---------------------------------------------------------------------------


def on_session_start(event: HookInput) -> HookOutput:
    # 示例：return HookOutput.additional_context(event.event_name, "先阅读 AGENTS.md")
    return HookOutput.success()


def on_session_end(event: HookInput) -> HookOutput:
    # 适合把会话摘要落到外部系统；超时最多 3 秒，输出不会控制 Codex。
    return HookOutput.success()


def on_subagent_start(event: HookInput) -> HookOutput:
    # 示例：return HookOutput.additional_context(event.event_name, "先运行相关测试")
    return HookOutput.success()


def on_pre_tool_use(event: HookInput) -> HookOutput:
    tool_name = cast(str, event.get("tool_name"))
    tool_input = event.get("tool_input")
    # 示例策略：
    # if tool_name == "Bash" and isinstance(tool_input, dict):
    #     if "禁止的命令" in str(tool_input.get("command", "")):
    #         return HookOutput.pre_tool_deny("命令违反仓库策略")
    _ = (tool_name, tool_input)
    return HookOutput.success()


def on_permission_request(event: HookInput) -> HookOutput:
    # 返回 success() 表示不代替用户决策，继续显示正常审批提示。
    # 明确允许：HookOutput.permission_allow()
    # 明确拒绝：HookOutput.permission_deny("违反仓库权限策略")
    return HookOutput.success()


def on_post_tool_use(event: HookInput) -> HookOutput:
    # PostToolUse 发生在工具执行后，无法撤销副作用。
    # 示例：return HookOutput.block(event.event_name, "输出需要模型复核")
    return HookOutput.success()


def on_pre_compact(event: HookInput) -> HookOutput:
    # 示例：return HookOutput.stop_processing(event.event_name, "暂不允许压缩")
    return HookOutput.success()


def on_post_compact(event: HookInput) -> HookOutput:
    return HookOutput.success()


def on_user_prompt_submit(event: HookInput) -> HookOutput:
    # 注意：prompt 可能含敏感信息，不建议默认写入日志。
    # 示例：return HookOutput.block(event.event_name, "提示中疑似包含密钥")
    return HookOutput.success()


def on_subagent_stop(event: HookInput) -> HookOutput:
    # decision:block 的语义是要求 subagent 再继续一轮。
    return HookOutput.success()


def on_stop(event: HookInput) -> HookOutput:
    # decision:block 的语义是要求当前 agent 继续，而不是拒绝本轮。
    return HookOutput.success()


def on_interrupt(event: HookInput) -> HookOutput:
    # Codex main 分支预览事件；稳定发布文档未承诺，默认不写 hooks.json。
    return HookOutput.success()


HANDLERS: Final[dict[HookEventName, Handler]] = {
    "SessionStart": on_session_start,
    "SessionEnd": on_session_end,
    "SubagentStart": on_subagent_start,
    "PreToolUse": on_pre_tool_use,
    "PermissionRequest": on_permission_request,
    "PostToolUse": on_post_tool_use,
    "PreCompact": on_pre_compact,
    "PostCompact": on_post_compact,
    "UserPromptSubmit": on_user_prompt_submit,
    "SubagentStop": on_subagent_stop,
    "Stop": on_stop,
    "Interrupt": on_interrupt,
}


def run() -> int:
    started = time.monotonic()
    payload: JsonObject = {}
    logger: logging.Logger | None = None
    try:
        payload = read_stdin_json()
        logger, log_path = configure_logging(payload)
        event = HookInput.parse(payload, logger)
        context = {
            "event_name": event.event_name,
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "log_path": str(log_path) if log_path else None,
        }
        logger.info("hook 开始", extra=context)
        if os.environ.get("CODEX_HOOK_LOG_PAYLOADS") == "1":
            logger.debug("hook 输入（已脱敏）", extra={**context, "payload": payload})

        output = HANDLERS[event.event_name](event)
        validate_output(event.event_name, output)
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        logger.info("hook 完成", extra={**context, "duration_ms": duration_ms})
        write_stdout_json(output.payload)
        return 0
    except Exception as error:
        if logger is None:
            try:
                logger, _ = configure_logging(payload)
            except Exception:
                print(f"codex_hook fatal: {error}", file=sys.stderr)
                return 1
        logger.exception("hook 失败: %s", error)
        # 非 0 退出让 Codex 将本次运行标记为失败；不要伪造成功 JSON。
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
