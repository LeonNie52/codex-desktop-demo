## Why

我们需要评估 Codex App Server 对外暴露的 RPC 接口能力，以确定是否能在其基础上构建一个带 GUI 的桌面 Agent。需要一个可运行的最小化 demo 来验证完整的会话生命周期（Thread/Turn/Item）和流式事件处理在 Python 客户端中的可行性。

## What Changes

- 新增 `app_server_client.py`：基于 asyncio WebSocket 的 JSON-RPC 客户端，封装 initialize 握手、请求/响应匹配、事件分发
- 新增 `agent_state.py`：Agent 核心状态机，管理连接状态和 thread/turn 生命周期
- 新增 `gui.py`：基于 Gradio 的最小化 Web GUI，提供会话列表、对话界面、Agent 输出渲染
- 新增 `main.py`：CLI 入口，启动 app-server 子进程，初始化各模块，启动 Gradio
- 新增 `pyproject.toml`：项目元数据和依赖声明（gradio、websockets 等）

## Capabilities

### New Capabilities

- `app-server-client`: Codex App Server 的 JSON-RPC WebSocket 客户端，支持请求/响应匹配、通知分发、重连
- `session-management`: 会话（Thread）管理，包括新建、列表、恢复、读取、归档、删除、命名
- `conversation-turn`: 对话轮次（Turn）管理，包括发起对话、流式文本接收、Item 事件渲染、中断
- `agent-gui`: 基于 Gradio 的最小化图形界面，包含会话侧栏、对话面板、Agent 输出流

### Modified Capabilities

<!-- 无现有 spec 需修改 -->

## Impact

- 新增代码文件于项目根目录：`main.py`, `gui.py`, `agent_state.py`, `app_server_client.py`, `pyproject.toml`
- 依赖外部进程：`codex app-server --listen ws://127.0.0.1:4500`
- 依赖 Python 包：`gradio`, `websockets`（或内置 `asyncio`）
- 无现有代码受影响
