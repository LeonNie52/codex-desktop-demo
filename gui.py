from __future__ import annotations

import asyncio
import queue
import time
from typing import Any

import gradio as gr

from agent_state import AgentState


def _format_item_for_display(item: dict[str, Any]) -> str:
    item_type = item.get("type", "")
    if item_type == "agentMessage":
        return item.get("text", "") or item.get("accumulated", "")
    elif item_type == "commandExecution":
        cmd = item.get("command", "")
        output = item.get("aggregatedOutput", "")
        exit_code = item.get("exitCode")
        lines = [f"```bash\n$ {cmd}\n```"]
        if output:
            lines.append(f"```\n{output[:2000]}\n```")
        if exit_code is not None:
            lines.append(f"*退出码: {exit_code}*")
        return "\n".join(lines)
    elif item_type == "fileChange":
        changes = item.get("changes", [])
        parts = []
        for c in changes:
            path = c.get("path", "")
            diff = c.get("diff", "")
            kind = c.get("kind", "")
            parts.append(f"**{kind}: `{path}`**\n```diff\n{diff[:1000]}\n```")
        return "\n\n".join(parts)
    elif item_type == "reasoning":
        summary = item.get("summary") or item.get("accumulated", "")
        content = item.get("content", "")
        if not summary and content:
            if isinstance(content, list):
                content = "\n".join(
                    c.get("text", str(c)) if isinstance(c, dict) else str(c)
                    for c in content
                )
            summary = content
        if not summary:
            return ""
        return f"<details><summary>🧠 推理过程</summary>\n\n{summary}\n\n</details>"
    elif item_type == "mcpToolCall":
        server = item.get("server", "")
        tool = item.get("tool", "")
        status = item.get("status", "")
        arguments = item.get("arguments", "")
        result = item.get("result", "")
        error = item.get("error", "")
        parts = [f"**🔧 MCP 工具: `{server}/{tool}`** ({status})"]
        if arguments:
            args_str = arguments if isinstance(arguments, str) else str(arguments)
            parts.append(f"<details><summary>参数</summary>\n\n```json\n{args_str[:1500]}\n```\n\n</details>")
        if result:
            result_str = result if isinstance(result, str) else str(result)
            parts.append(f"<details><summary>结果</summary>\n\n```\n{result_str[:1500]}\n```\n\n</details>")
        if error:
            parts.append(f"⚠️ **错误:** {error}")
        return "\n\n".join(parts)
    elif item_type == "dynamicToolCall":
        tool = item.get("tool", "")
        status = item.get("status", "")
        arguments = item.get("arguments", "")
        success = item.get("success")
        parts = [f"**⚡ 动态工具: `{tool}`** ({status})"]
        if arguments:
            args_str = arguments if isinstance(arguments, str) else str(arguments)
            parts.append(f"<details><summary>参数</summary>\n\n```json\n{args_str[:1500]}\n```\n\n</details>")
        if success is not None:
            parts.append(f"{'✅ 成功' if success else '❌ 失败'}")
        return "\n\n".join(parts)
    elif item_type == "webSearch":
        return f"**🔍 搜索:** {item.get('query', '')}"
    elif item_type == "plan":
        return f"**📋 计划:** {item.get('text', '')}"
    elif item_type == "contextCompaction":
        return "*上下文已压缩*"
    return f"*[{item_type}]*"


def _msg(role: str, text: str) -> dict:
    """构建 Gradio 6 Chatbot 消息格式"""
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _msg_text(msg: dict) -> str:
    """从 Gradio 6 消息中提取纯文本"""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _set_msg_text(msg: dict, text: str) -> None:
    """更新消息文本（就地修改）"""
    msg["content"] = [{"type": "text", "text": text}]


def _build_assistant_content(reasoning: str, body: str) -> str:
    """组装 assistant 消息：推理过程（折叠）+ 正文."""
    parts = []
    if reasoning:
        parts.append(f"<details><summary>🧠 推理过程</summary>\n\n{reasoning}\n\n</details>")
    if body:
        parts.append(body)
    return "\n\n".join(parts) if parts else ""


def _make_status_html(text: str, css_class: str) -> str:
    return f"<div style='padding:8px 12px;border-radius:6px;margin-bottom:8px;{_status_style(css_class)}'><b>状态:</b> {text}</div>"


def _status_style(css_class: str) -> str:
    if css_class == "connected":
        return "background:#d4edda;color:#155724"
    elif css_class == "disconnected":
        return "background:#f8d7da;color:#721c24"
    else:
        return "background:#fff3cd;color:#856404"


def _merge_item_into_text(item: dict[str, Any]) -> str:
    item_type = item.get("type", "")
    if item_type in ("userMessage",):
        return ""
    return _format_item_for_display(item)


class CodexGUI:
    def __init__(self, state: AgentState, bg_loop: asyncio.AbstractEventLoop, config_model: str | None = None):
        self._state = state
        self._loop = bg_loop
        self._config_model = config_model
        self._agent_running = False

    def build(self) -> gr.Blocks:
        thread_choices = self._get_thread_choices()
        connected = self._state.is_ready
        status_class = "connected" if connected else "disconnected"
        status_text = "已连接" if connected else "未连接"

        with gr.Blocks(title="Codex Desktop Agent Demo") as demo:
            status_html = gr.HTML(value=_make_status_html(status_text, status_class))

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 会话")

                    if self._config_model:
                        gr.Markdown(f"**模型:** {self._config_model}")

                    cwd_input = gr.Textbox(
                        label="工作目录 (可选)", placeholder="留空使用当前目录",
                    )
                    new_btn = gr.Button("+ 新建会话", variant="primary", size="sm")

                    thread_list = gr.Radio(
                        label="会话列表",
                        choices=thread_choices,
                        interactive=connected,
                    )
                    with gr.Row():
                        refresh_btn = gr.Button("刷新", size="sm")
                        archive_btn = gr.Button("归档", size="sm")
                        delete_btn = gr.Button("删除", size="sm")

                with gr.Column(scale=3):
                    chatbot = gr.Chatbot(label="对话", height=500)
                    with gr.Row():
                        msg_input = gr.Textbox(
                            label="输入",
                            placeholder="选择或新建会话后输入消息...",
                            scale=9,
                            interactive=connected,
                        )
                        send_btn = gr.Button("发送", variant="primary", scale=1, interactive=connected)
                        stop_btn = gr.Button("停止", variant="stop", scale=1, visible=False)

            send_ev = send_btn.click(
                fn=self._handle_send,
                inputs=[msg_input, chatbot],
                outputs=[msg_input, chatbot],
            )
            stop_btn.click(
                fn=self._handle_stop,
                inputs=[chatbot],
                outputs=[chatbot, msg_input],
                cancels=[send_ev],
            )
            msg_input.submit(
                fn=self._handle_send,
                inputs=[msg_input, chatbot],
                outputs=[msg_input, chatbot],
            )
            new_btn.click(
                fn=self._create_session,
                inputs=[cwd_input],
                outputs=[thread_list, chatbot, msg_input, send_btn],
            )
            thread_list.change(
                fn=self._switch_thread,
                inputs=[thread_list],
                outputs=[chatbot, msg_input, send_btn],
            )
            refresh_btn.click(
                fn=self._refresh_threads,
                outputs=[thread_list],
            )
            archive_btn.click(
                fn=self._archive_current,
                inputs=[thread_list],
                outputs=[thread_list, chatbot, msg_input, send_btn],
            )
            delete_btn.click(
                fn=self._delete_current,
                inputs=[thread_list],
                outputs=[thread_list, chatbot, msg_input, send_btn],
            )

        return demo

    def _create_session(self, cwd: str) -> tuple:
        if not self._state.is_ready:
            gr.Warning("尚未连接到 Codex App Server")
            return self._noop_4()

        cwd_val = cwd.strip() or None
        try:
            thread = self._state.sync_start_thread(self._config_model, cwd_val)
            thread_id = thread.get("id", "")
            self._state.sync_list_threads()
            choices = self._get_thread_choices()
            choice_values = [c[1] for c in choices]
            if thread_id not in choice_values:
                choices.insert(0, (thread.get("name") or "新会话", thread_id))
            self._agent_running = False
            return (
                gr.Radio(choices=choices, value=thread_id, interactive=True),
                [],
                gr.Textbox(interactive=True, placeholder="输入消息，Enter 发送..."),
                gr.Button(interactive=True),
            )
        except Exception as e:
            gr.Warning(f"创建会话失败: {e}")
            return self._noop_4()

    def _switch_thread(self, thread_id: str) -> tuple:
        if not thread_id or not self._state.is_ready:
            return [], gr.Textbox(interactive=False), gr.Button(interactive=False)
        try:
            self._state.sync_resume_thread(thread_id)
        except Exception:
            pass
        try:
            full = self._state.sync_read_thread(thread_id, include_turns=True)
            messages = self._render_history(full)
        except Exception:
            messages = []
        self._agent_running = False
        return messages, gr.Textbox(interactive=True, placeholder="输入消息，Enter 发送..."), gr.Button(interactive=True)

    def _refresh_threads(self) -> gr.Radio:
        if not self._state.is_ready:
            return gr.Radio(choices=[])
        self._state.sync_list_threads()
        choices = self._get_thread_choices()
        return gr.Radio(choices=choices, value=self._state.current_thread_id)

    def _archive_current(self, thread_id: str) -> tuple:
        if thread_id:
            try:
                self._state.sync_archive_thread(thread_id)
                self._state.sync_list_threads()
            except Exception as e:
                gr.Warning(f"归档失败: {e}")
        return (
            gr.Radio(choices=self._get_thread_choices(), value=None),
            [], gr.Textbox(interactive=False), gr.Button(interactive=False),
        )

    def _delete_current(self, thread_id: str) -> tuple:
        if thread_id:
            try:
                self._state.sync_delete_thread(thread_id)
                self._state.sync_list_threads()
            except Exception as e:
                gr.Warning(f"删除失败: {e}")
        return (
            gr.Radio(choices=self._get_thread_choices(), value=None),
            [], gr.Textbox(interactive=False), gr.Button(interactive=False),
        )

    async def _handle_send(self, message: str, history: list[dict[str, str]]):
        if not message or not message.strip():
            yield message, history
            return
        if not self._state.is_ready or not self._state.current_thread_id:
            gr.Warning("请先新建或选择一个会话")
            yield "", history
            return

        history = history or []
        history.append(_msg("user", message))
        self._agent_running = True
        yield "", history

        try:
            await asyncio.to_thread(self._state.sync_start_turn, message)
        except Exception as e:
            history.append(_msg("assistant", f"**错误:** {e}"))
            self._agent_running = False
            yield "", history
            return

        assistant_msg = _msg("assistant", "")
        history.append(assistant_msg)
        current_text = ""
        reasoning_text = ""
        rendered_ids: set[str] = set()

        eq: queue.Queue = self._state.event_queue

        while True:
            try:
                event = eq.get_nowait()
            except queue.Empty:
                if not self._agent_running:
                    break
                await asyncio.sleep(0.2)
                continue

            if event["type"] == "turn_done":
                self._agent_running = False
                status = event["status"]
                if status == "failed":
                    current_text += "\n\n*Turn 执行失败*"
                elif status == "interrupted":
                    current_text += "\n\n*已中断*"
                _set_msg_text(assistant_msg, _build_assistant_content(reasoning_text, current_text))
                break

            if event["type"] == "item":
                item = event["item"]
                ev = event["event"]
                item_id = item.get("id", "")
                item_type = item.get("type", "")

                if item_type == "agentMessage":
                    if ev == "delta":
                        current_text = item.get("accumulated", current_text)
                elif item_type == "reasoning":
                    if ev == "delta":
                        reasoning_text = item.get("accumulated", reasoning_text)
                elif item_type not in ("userMessage",) and ev == "completed" and item_id not in rendered_ids:
                    rendered_ids.add(item_id)
                    rendered = _format_item_for_display(item)
                    if rendered and rendered not in current_text:
                        current_text += f"\n\n{rendered}"

            _set_msg_text(assistant_msg, _build_assistant_content(reasoning_text, current_text))
            yield "", history

        _set_msg_text(assistant_msg, _build_assistant_content(reasoning_text, current_text or "*Agent 已响应*"))
        yield "", history

    async def _handle_stop(self, history: list[dict[str, str]]) -> tuple:
        try:
            await asyncio.to_thread(self._state.sync_interrupt_turn)
        except Exception:
            pass
        self._agent_running = False
        if history:
            last = history[-1]
            _set_msg_text(last, _msg_text(last) + "\n\n*用户已中断*")
        return history, ""

    def _get_thread_choices(self) -> list[tuple[str, str]]:
        return [
            (t.get("name") or t.get("preview") or t.get("id", ""), t.get("id", ""))
            for t in self._state.threads
        ]

    def _render_history(self, thread: dict[str, Any]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for turn in thread.get("turns", []):
            for item in turn.get("items", []) or []:
                item_type = item.get("type", "")
                if item_type == "userMessage":
                    content = item.get("content", [])
                    text = ""
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text += part.get("text", "")
                    if text:
                        messages.append(_msg("user", text))
                elif item_type == "agentMessage":
                    text = item.get("text", "")
                    if text:
                        messages.append(_msg("assistant", text))
                else:
                    rendered = _format_item_for_display(item)
                    if rendered and messages and messages[-1]["role"] == "assistant":
                        _set_msg_text(messages[-1], _msg_text(messages[-1]) + f"\n\n{rendered}")
        return messages

    def _noop_4(self) -> tuple:
        return tuple(gr.skip() for _ in range(4))


def create_gui(state: AgentState, bg_loop: asyncio.AbstractEventLoop, config_model: str | None = None) -> gr.Blocks:
    gui = CodexGUI(state, bg_loop, config_model)
    return gui.build()
