## Context

Codex App Server 是 OpenAI Codex 的本地守护进程，通过 `codex app-server` 启动，对外暴露 JSON-RPC 2.0 协议。支持 stdio 和 WebSocket 传输。本项目需要在 Python 中构建客户端连接到该 server，并在此基础上封装一个最小化 GUI，以验证完整 Agent 交互流程。

当前代码库为空——这是一个全新项目。

## Goals / Non-Goals

**Goals:**
- 建立与 Codex App Server 的 WebSocket 连接，完成 initialize 握手
- 封装 JSON-RPC 请求/响应匹配和通知分发
- 实现 Thread CRUD：新建、列表、恢复、读取、归档、删除
- 实现 Turn 管理：发起对话、流式接收 Agent 输出、中断
- 在 Gradio 中展示会话列表和对话界面
- 代码结构清晰、模块化，为后续扩展打好基础

**Non-Goals:**
- 不涉及审批（Approval）流程的交互处理
- 不涉及沙箱策略的精细配置
- 不涉及 MCP 工具调用
- 不涉及插件/市场/技能系统
- 不实现生产级错误恢复和重连（demo 级别即可）
- 不做架构化数据持久层

## Decisions

### D1: WebSocket 传输层

**选择**: 客户端通过 `websockets` 库连接 `ws://127.0.0.1:4500`，app-server 由 main.py 作为子进程启动。

**理由**:
- 本机 localhost 无需 WebSocket 认证
- `websockets` 是 Python 生态最成熟的异步 WebSocket 库
- 子进程方式确保 demo 自包含（无需手动启动 server）

**替代方案**: 
- stdio 传输（通过 subprocess pipe）更简单但只能单连接，WebSocket 更灵活
- Unix socket 功能等价于 WebSocket 但调试不如 TCP 方便

### D2: Gradio 作为 GUI 框架

**选择**: Gradio 提供 Block API 构建自定义布局，`gr.Chatbot` 组件天然适合对话界面。

**理由**:
- 零前端代码，纯 Python 构建 UI
- 自带 Web 服务器，浏览器打开即可使用
- Chatbot 组件支持流式文本追加（`yield` 模式）
- 社区活跃，文档齐全

**替代方案**:
- **Textual** (TUI): 更符合终端用户习惯，但无 Web 界面，分享和演示不便
- **FastHTML**: 更灵活但需要写 HTML/JS，原型的开发速度不如 Gradio
- **Streamlit**: 状态模型较简单，复杂双向流控制不如 Gradio 的 Block API

### D3: asyncio 事件驱动架构

**选择**: 核心模块全部基于 `asyncio`，WebSocket 消息循环作为事件总线驱动状态机。

**理由**:
- Codex App Server 的通信模型是异步流式（请求→响应异步，通知持续到达）
- Gradio 的 Block API 天然支持 async 事件处理
- 单一事件循环避免线程竞态

**替代方案**:
- 多线程 + 队列：复杂度高, demo 没必要
- 同步阻塞：无法处理流式输出

### D4: 模块分层

```
┌────────────────────────────────────────┐
│                 gui.py                 │  Gradio UI 组件和事件绑定
│  (会话侧栏 + 对话面板 + 输入框)         │
├────────────────────────────────────────┤
│              agent_state.py            │  状态管理: 当前连接、当前 thread、
│  (状态机: 连接→会话→对话)              │  当前 turn、item 缓存
├────────────────────────────────────────┤
│           app_server_client.py         │  JSON-RPC 客户端: 请求/响应匹配、
│  (WebSocket + RPC 封装)               │  通知分发、消息序列化
└────────────────────────────────────────┘
```

数据流方向：
- GUI → AgentState（用户操作）
- AgentState → Client（RPC 请求）
- Client → AgentState（响应 + 通知回调）
- AgentState → GUI（状态更新 → UI 刷新）

### D5: JSON-RPC 客户端设计

`AppServerClient` 类封装：
- `connect()` / `disconnect()` — WebSocket 生命周期
- `initialize()` — 握手协议
- `request(method, params)` → `Future[result]` — 通用 RPC 请求
- `on_notification(method, callback)` — 事件订阅
- 内部维护 `id` 计数器、pending futures 映射

WS 消息处理流程：
```
收到消息 → JSON.parse → 有 id？
  ├── 有 → 匹配 pending future → resolve
  └── 无 → dispatch 给注册的回调
```

## Risks / Trade-offs

- **[R1] app-server 版本兼容**: Codex 更新可能改变接口 → 使用稳定 API（不含 `experimentalApi`），不依赖实验性字段
- **[R2] WebSocket 断开**: agent 崩溃或网络问题 → demo 级别仅做基础错误提示，不做自动重连
- **[R3] Gradio 不适合复杂桌面应用**: Chatbot 组件定制能力有限 → demo 阶段接受此限制，后续可迁移至 Electron/Tauri
- **[R4] item 类型繁多**: Codex 输出的 Item 类型超过 10 种 → 优先渲染核心类型（agentMessage、commandExecution、fileChange），其余做降级展示
