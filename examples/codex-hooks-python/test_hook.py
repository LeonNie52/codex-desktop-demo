#!/usr/bin/env python3
"""无需第三方依赖的模板冒烟测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
HOOK = HERE / "hook.py"


def common(event: str) -> dict[str, Any]:
    return {
        "session_id": "thr_test",
        "turn_id": "turn_test",
        "transcript_path": None,
        "cwd": str(HERE),
        "hook_event_name": event,
        "model": "test-model",
        "permission_mode": "default",
    }


def samples() -> list[dict[str, Any]]:
    session_start = common("SessionStart")
    session_start.pop("turn_id")
    session_start["source"] = "startup"

    session_end = {
        "session_id": "thr_test",
        "transcript_path": None,
        "cwd": str(HERE),
        "hook_event_name": "SessionEnd",
        "reason": "other",
    }
    subagent_start = common("SubagentStart") | {
        "agent_id": "agent_test",
        "agent_type": "worker",
    }
    pre_tool = common("PreToolUse") | {
        "agent_id": "agent_test",
        "agent_type": "worker",
        "tool_name": "Bash",
        "tool_input": {"command": "echo ok", "api_key": "must-not-leak"},
        "tool_use_id": "call_test",
    }
    permission = common("PermissionRequest") | {
        "tool_name": "Bash",
        "tool_input": {"command": "curl example.com", "description": "network"},
    }
    post_tool = common("PostToolUse") | {
        "tool_name": "Bash",
        "tool_input": {"command": "echo ok"},
        "tool_response": {"output": "ok", "exit_code": 0},
        "tool_use_id": "call_test",
    }
    pre_compact = common("PreCompact")
    pre_compact.pop("permission_mode")
    pre_compact["trigger"] = "auto"
    post_compact = common("PostCompact")
    post_compact.pop("permission_mode")
    post_compact["trigger"] = "manual"
    prompt = common("UserPromptSubmit") | {"prompt": "hello"}
    subagent_stop = common("SubagentStop") | {
        "agent_id": "agent_test",
        "agent_type": "worker",
        "agent_transcript_path": None,
        "stop_hook_active": False,
        "last_assistant_message": "done",
    }
    stop = common("Stop") | {
        "stop_hook_active": False,
        "last_assistant_message": "done",
    }
    interrupt = common("Interrupt")
    return [
        session_start,
        session_end,
        subagent_start,
        pre_tool,
        permission,
        post_tool,
        pre_compact,
        post_compact,
        prompt,
        subagent_stop,
        stop,
        interrupt,
    ]


class HookTemplateTests(unittest.TestCase):
    def test_every_known_event_returns_protocol_json_and_writes_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["CODEX_HOOK_LOG_DIR"] = temp_dir
            env["CODEX_HOOK_LOG_LEVEL"] = "ERROR"
            env["CODEX_HOOK_LOG_PAYLOADS"] = "1"
            for payload in samples():
                with self.subTest(event=payload["hook_event_name"]):
                    completed = subprocess.run(
                        [sys.executable, str(HOOK)],
                        input=json.dumps(payload),
                        text=True,
                        capture_output=True,
                        env=env,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(json.loads(completed.stdout), {})

            log_path = Path(temp_dir) / "codex-hooks.jsonl"
            self.assertTrue(log_path.is_file())
            lines = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertTrue(any(line["message"] == "hook 开始" for line in lines))
            self.assertNotIn("must-not-leak", log_path.read_text())
            self.assertIn("<redacted>", log_path.read_text())

    def test_missing_required_field_fails_without_fake_success_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["CODEX_HOOK_LOG_DIR"] = temp_dir
            payload = common("PreToolUse")
            completed = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "")
            self.assertIn("缺少必填字段", completed.stderr)


if __name__ == "__main__":
    unittest.main()
