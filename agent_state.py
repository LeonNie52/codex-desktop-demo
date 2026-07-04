from __future__ import annotations

import asyncio
import logging
import queue
from dataclasses import dataclass, field
from typing import Any, Callable

from app_server_client import AppServerClient

logger = logging.getLogger(__name__)


@dataclass
class TurnState:
    id: str
    status: str
    items: list[dict[str, Any]] = field(default_factory=list)
    agent_message_buffer: str = ""
    current_agent_message_id: str | None = None
    reasoning_buffer: str = ""
    current_reasoning_id: str | None = None


class AgentState:
    def __init__(self, client: AppServerClient, bg_loop: asyncio.AbstractEventLoop):
        self._client = client
        self._loop = bg_loop
        self._models: list[dict[str, Any]] = []
        self._threads: list[dict[str, Any]] = []
        self._current_thread_id: str | None = None
        self._current_turn: TurnState | None = None
        self._item_buffer: dict[str, dict[str, Any]] = {}
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        self._client.on_notification("item/started", self._handle_item_started)
        self._client.on_notification("item/completed", self._handle_item_completed)
        self._client.on_notification("item/agentMessage/delta", self._handle_agent_delta)
        self._client.on_notification("item/reasoning/summaryTextDelta", self._handle_reasoning_delta)
        self._client.on_notification("turn/completed", self._handle_turn_completed)

    @property
    def is_ready(self) -> bool:
        return self._client.is_ready

    @property
    def current_thread_id(self) -> str | None:
        return self._current_thread_id

    @property
    def current_turn(self) -> TurnState | None:
        return self._current_turn

    @property
    def threads(self) -> list[dict[str, Any]]:
        return self._threads

    @property
    def models(self) -> list[dict[str, Any]]:
        return self._models

    @property
    def event_queue(self) -> queue.Queue[dict[str, Any]]:
        return self._event_queue

    def _run_async(self, coro) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=120)

    async def list_models(self) -> list[dict[str, Any]]:
        result = await self._client.request("model/list", {"includeHidden": False})
        self._models = result.get("data", [])
        return self._models

    def sync_list_models(self) -> list[dict[str, Any]]:
        return self._run_async(self.list_models())

    async def list_threads(self, archived: bool = False) -> list[dict[str, Any]]:
        result = await self._client.request("thread/list", {
            "archived": archived,
            "limit": 50,
        })
        self._threads = result.get("data", [])
        return self._threads

    def sync_list_threads(self) -> list[dict[str, Any]]:
        return self._run_async(self.list_threads())

    async def start_thread(self, model: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
            "serviceName": "codex_desktop_demo",
        }
        if model:
            params["model"] = model
        if cwd:
            params["cwd"] = cwd
        result = await self._client.request("thread/start", params)
        thread = result.get("thread", {})
        self._current_thread_id = thread.get("id")
        self._current_turn = None
        self._threads.insert(0, thread)
        return thread

    def sync_start_thread(self, model: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        return self._run_async(self.start_thread(model, cwd))

    async def resume_thread(self, thread_id: str) -> dict[str, Any]:
        result = await self._client.request("thread/resume", {"threadId": thread_id})
        thread = result.get("thread", {})
        self._current_thread_id = thread_id
        self._current_turn = None
        return thread

    def sync_resume_thread(self, thread_id: str) -> dict[str, Any]:
        return self._run_async(self.resume_thread(thread_id))

    async def read_thread(self, thread_id: str, include_turns: bool = True) -> dict[str, Any]:
        result = await self._client.request("thread/read", {
            "threadId": thread_id,
            "includeTurns": include_turns,
        })
        return result.get("thread", {})

    def sync_read_thread(self, thread_id: str, include_turns: bool = True) -> dict[str, Any]:
        return self._run_async(self.read_thread(thread_id, include_turns))

    async def archive_thread(self, thread_id: str) -> None:
        await self._client.request("thread/archive", {"threadId": thread_id})
        self._threads = [t for t in self._threads if t.get("id") != thread_id]

    def sync_archive_thread(self, thread_id: str) -> None:
        self._run_async(self.archive_thread(thread_id))

    async def delete_thread(self, thread_id: str) -> None:
        await self._client.request("thread/delete", {"threadId": thread_id})
        self._threads = [t for t in self._threads if t.get("id") != thread_id]
        if self._current_thread_id == thread_id:
            self._current_thread_id = None
            self._current_turn = None

    def sync_delete_thread(self, thread_id: str) -> None:
        self._run_async(self.delete_thread(thread_id))

    async def set_thread_name(self, thread_id: str, name: str) -> None:
        await self._client.request("thread/name/set", {
            "threadId": thread_id,
            "name": name,
        })

    def sync_start_turn(self, text: str, cwd: str | None = None) -> str:
        async def _start() -> str:
            if not self._current_thread_id:
                raise RuntimeError("无活动 thread")
            params: dict[str, Any] = {
                "threadId": self._current_thread_id,
                "input": [{"type": "text", "text": text}],
                "approvalPolicy": "never",
            }
            if cwd:
                params["cwd"] = cwd
            result = await self._client.request("turn/start", params)
            turn_data = result.get("turn", {})
            turn_id = turn_data.get("id", "")
            logger.info("turn/start 成功, turnId=%s, status=%s", turn_id, turn_data.get("status"))
            self._current_turn = TurnState(id=turn_id, status=turn_data.get("status", "inProgress"))
            self._item_buffer.clear()
            self._event_queue = queue.Queue()
            return turn_id
        return self._run_async(_start())

    def sync_interrupt_turn(self) -> None:
        async def _interrupt() -> None:
            if not self._current_thread_id or not self._current_turn:
                return
            await self._client.request("turn/interrupt", {
                "threadId": self._current_thread_id,
                "turnId": self._current_turn.id,
            })
        self._run_async(_interrupt())

    async def _handle_item_started(self, params: dict[str, Any]) -> None:
        item = params.get("item", {})
        item_id = item.get("id", "")
        item_type = item.get("type", "")
        logger.info("item/started: type=%s, id=%s", item_type, item_id)
        self._item_buffer[item_id] = item

        if item_type == "agentMessage":
            self._current_agent_message_id = item_id
        elif item_type == "reasoning":
            self._current_reasoning_id = item_id

        self._event_queue.put({"type": "item", "event": "started", "item": item})

    async def _handle_item_completed(self, params: dict[str, Any]) -> None:
        item = params.get("item", {})
        item_id = item.get("id", "")
        item_type = item.get("type", "")

        if item_id in self._item_buffer:
            self._item_buffer[item_id] = {**self._item_buffer[item_id], **item}

        if item_type == "agentMessage" and item_id == self._current_agent_message_id:
            item["text"] = self._current_turn.agent_message_buffer if self._current_turn else ""
            self._current_agent_message_id = None
        elif item_type == "reasoning" and item_id == self._current_reasoning_id:
            if self._current_turn and self._current_turn.reasoning_buffer:
                item["summary"] = self._current_turn.reasoning_buffer
            self._current_reasoning_id = None

        if self._current_turn:
            self._current_turn.items.append(self._item_buffer.get(item_id, item))

        self._event_queue.put({"type": "item", "event": "completed", "item": self._item_buffer.get(item_id, item)})

    async def _handle_agent_delta(self, params: dict[str, Any]) -> None:
        delta_text = params.get("delta", "")
        item_id = params.get("itemId", "")
        if self._current_turn and item_id == self._current_agent_message_id:
            self._current_turn.agent_message_buffer += delta_text
            self._event_queue.put({"type": "item", "event": "delta", "item": {
                "type": "agentMessage", "id": item_id,
                "delta": delta_text,
                "accumulated": self._current_turn.agent_message_buffer,
            }})

    async def _handle_reasoning_delta(self, params: dict[str, Any]) -> None:
        delta_text = params.get("delta", "")
        item_id = params.get("itemId", "")
        if self._current_turn and item_id == self._current_reasoning_id:
            self._current_turn.reasoning_buffer += delta_text
            self._event_queue.put({"type": "item", "event": "delta", "item": {
                "type": "reasoning", "id": item_id,
                "delta": delta_text,
                "accumulated": self._current_turn.reasoning_buffer,
            }})

    async def _handle_turn_completed(self, params: dict[str, Any]) -> None:
        turn_data = params.get("turn", {})
        status = turn_data.get("status", "unknown")
        logger.info("turn/completed 收到, status=%s, error=%s", status, turn_data.get("error"))
        if self._current_turn:
            self._current_turn.status = status
        self._event_queue.put({"type": "turn_done", "status": status})
