import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets
import websockets.exceptions

logger = logging.getLogger(__name__)

NotificationHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class AppServerClient:
    def __init__(self, url: str = "ws://127.0.0.1:4500"):
        self._url = url
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._state = "disconnected"
        self._id_counter = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notify_handlers: dict[str, list[NotificationHandler]] = {}
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == "ready"

    async def connect(self) -> None:
        if self._ws is not None:
            raise RuntimeError("已连接，请先断开")
        self._state = "connecting"
        self._ws = await websockets.connect(self._url, max_size=10 * 1024 * 1024)
        self._state = "connected"
        self._reader_task = asyncio.create_task(self._read_messages())
        logger.info("已连接到 %s", self._url)

    async def initialize(self, client_info: dict[str, str]) -> dict[str, Any]:
        if self._state != "connected":
            raise RuntimeError(f"无法初始化，当前状态: {self._state}")
        result = await self.request("initialize", {
            "clientInfo": client_info,
        })
        await self._send_notification("initialized", {})
        self._state = "ready"
        logger.info("初始化完成")
        return result

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("未连接")
        self._id_counter += 1
        msg_id = self._id_counter
        payload = {"method": method, "id": msg_id, "params": params or {}}
        await self._ws.send(json.dumps(payload, ensure_ascii=False))
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending[msg_id] = future
        try:
            return await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise RuntimeError(f"请求超时: {method}")

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if self._ws is None:
            return
        payload = {"method": method, "params": params}
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    def on_notification(self, method: str, handler: NotificationHandler) -> None:
        handlers = self._notify_handlers.setdefault(method, [])
        handlers.append(handler)

    async def disconnect(self) -> None:
        self._state = "disconnected"
        for mid, future in self._pending.items():
            if not future.done():
                future.cancel()
        self._pending.clear()
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("已断开连接")

    async def _read_messages(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("无效 JSON 消息: %s", raw)
                    continue
                await self._dispatch(msg)
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        method = msg.get("method")

        if msg_id is not None and msg_id in self._pending:
            future = self._pending.pop(msg_id)
            if "error" in msg:
                future.set_exception(RuntimeError(msg["error"].get("message", str(msg["error"]))))
            else:
                future.set_result(msg.get("result", {}))
        elif method and method in self._notify_handlers:
            params = msg.get("params", {})
            for handler in self._notify_handlers[method]:
                try:
                    await handler(params)
                except Exception:
                    logger.exception("通知处理器异常: %s", method)
