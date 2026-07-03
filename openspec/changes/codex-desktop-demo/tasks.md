## 1. 项目初始化

- [x] 1.1 创建 `pyproject.toml`，声明 Python 版本（>=3.10）、依赖（gradio、websockets）、项目元数据
- [x] 1.2 创建 `main.py` 骨架：argparse 入口，启动 app-server 子进程，初始化各模块，启动 Gradio

## 2. App Server 客户端（app_server_client.py）

- [x] 2.1 实现 `AppServerClient` 类：`connect()` 通过 `websockets.connect` 连接 `ws://127.0.0.1:4500`
- [x] 2.2 实现 JSON-RPC 请求/响应匹配：自增 `id` 计数器，`_pending` 字典存 `Future`，消息循环按 `id` 分发
- [x] 2.3 实现 `initialize()` 方法：发送 `initialize`（含 `clientInfo`），等待响应后发送 `initialized` 通知
- [x] 2.4 实现 `on_notification(method, callback)`：注册通知回调，消息循环中无 `id` 的消息按 method 分发
- [x] 2.5 实现 `disconnect()` 清理和连接状态管理（connected / disconnected / ready）

## 3. Agent 状态机（agent_state.py）

- [x] 3.1 实现 `AgentState` 类：持有 `AppServerClient` 实例，管理 `threads` 列表、`current_thread_id`、`current_turn_id`
- [x] 3.2 实现会话管理方法：`list_threads()`、`start_thread(model, cwd)`、`resume_thread(thread_id)`、`read_thread(thread_id, include_turns)`、`archive_thread(thread_id)`、`delete_thread(thread_id)`、`set_thread_name(thread_id, name)`
- [x] 3.3 实现 `start_turn(text)`：构造 `turn/start` 参数，返回 turnId，注册 item 通知处理
- [x] 3.4 实现 `interrupt_turn()`：发送 `turn/interrupt`
- [x] 3.5 实现 `list_models()`：调用 `model/list` 并缓存结果
- [x] 3.6 实现 item 事件处理：收到 `item/started` 时创建 item 记录，收到 `item/agentMessage/delta` 时累积文本，收到 `item/completed` 时标记完成并调用回调通知 GUI

## 4. Gradio GUI（gui.py）

- [x] 4.1 使用 `gr.Blocks` 创建三区布局：左侧会话侧栏、右侧对话面板、底部输入区
- [x] 4.2 实现会话侧栏：加载 thread 列表渲染为可点击列表，每项显示名称和预览。含"新建会话"按钮触发模型选择对话框
- [x] 4.3 实现对话面板（`gr.Chatbot`）：展示当前 thread 的消息历史，区分用户消息和 Agent 消息
- [x] 4.4 实现 Agent 输出流式渲染：通过 Gradio `yield` 机制实时追加 delta 文本到 Chatbot 最后一条消息
- [x] 4.5 实现 item 类型差异化渲染：agentMessage 显示文本、commandExecution 显示命令和输出、fileChange 显示 diff 摘要、reasoning 折叠展示
- [x] 4.6 实现底部输入区：文本框 + 发送按钮，Enter 键发送，Agent 运行中禁用并显示"停止"按钮
- [x] 4.7 实现连接状态指示器和错误 toast 提示

## 5. 端到端集成与验证

- [x] 5.1 在 `main.py` 中完成 app-server 子进程生命周期管理（启动、健康检查、优雅关闭）
- [x] 5.2 将 `AgentState` 与 Gradio 事件绑定串联完整交互流程
- [x] 5.3 端到端烟雾测试：启动 demo → 新建会话 → 发送消息 → 观察流式输出 → 中断 → 切换历史会话
