#!/usr/bin/env python3
import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import gradio as gr

from agent_state import AgentState
from app_server_client import AppServerClient
from gui import create_gui

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

APP_SERVER_PORT = 4500


def _load_config_model() -> str | None:
    """从 Codex config.toml 读取配置的模型名."""
    config_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    config_file = config_path / "config.toml"
    if not config_file.exists():
        return None
    import toml
    try:
        config = toml.load(config_file)
        return config.get("model")
    except Exception:
        return None
HEALTH_URL = f"http://127.0.0.1:{APP_SERVER_PORT}/readyz"


def start_app_server() -> subprocess.Popen[bytes]:
    logger.info("启动 codex app-server...")
    proc = subprocess.Popen(
        ["codex", "app-server", "--listen", f"ws://127.0.0.1:{APP_SERVER_PORT}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def wait_for_app_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(HEALTH_URL, method="GET")
            resp = urlopen(req, timeout=2)
            if resp.status == 200:
                logger.info("app-server 已就绪")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def cleanup(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    logger.info("正在关闭 app-server...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    logger.info("app-server 已关闭")


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def main() -> None:
    print("=== Codex Desktop Agent Demo ===\n")

    proc = start_app_server()
    print("等待 app-server 就绪...")
    if not wait_for_app_server():
        print("错误: app-server 启动超时", file=sys.stderr)
        cleanup(proc)
        sys.exit(1)

    bg_loop = asyncio.new_event_loop()
    bg_thread = threading.Thread(target=_run_loop, args=(bg_loop,), daemon=True)
    bg_thread.start()

    client = AppServerClient(f"ws://127.0.0.1:{APP_SERVER_PORT}")

    async def _connect() -> tuple[bool, str | None]:
        try:
            await client.connect()
            await client.initialize({
                "name": "codex_desktop_demo",
                "title": "Codex Desktop Agent Demo",
                "version": "0.1.0",
            })
            return True, None
        except Exception as e:
            return False, str(e)

    future = asyncio.run_coroutine_threadsafe(_connect(), bg_loop)
    connected, error = future.result(timeout=15)
    if not connected:
        print(f"错误: 连接 app-server 失败: {error}", file=sys.stderr)
        cleanup(proc)
        sys.exit(1)
    print("已连接 Codex App Server")

    state = AgentState(client, bg_loop)

    async def _init_state() -> int:
        await state.list_threads()
        return len(state.threads)

    future = asyncio.run_coroutine_threadsafe(_init_state(), bg_loop)
    thread_count = future.result(timeout=10)
    print(f"已有会话: {thread_count}")

    config_model = _load_config_model()
    if config_model:
        print(f"Codex 配置模型: {config_model}")

    demo = create_gui(state, bg_loop, config_model)
    demo.queue()

    try:
        demo.launch(
            server_name="127.0.0.1",
            server_port=7860,
            share=False,
            show_error=True,
        )
    finally:
        bg_loop.call_soon_threadsafe(bg_loop.stop)
        bg_thread.join(timeout=3)
        cleanup(proc)


if __name__ == "__main__":
    main()
