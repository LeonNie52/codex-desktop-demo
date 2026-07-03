## ADDED Requirements

### Requirement: 会话侧栏
系统 SHALL 在 GUI 左侧展示会话列表，支持切换、新建、删除操作。

#### Scenario: 加载并展示会话列表
- **WHEN** GUI 初始化完成并成功连接到 app-server
- **THEN** 左侧面板展示所有未归档 thread，每项显示名称和预览文本

#### Scenario: 点击切换会话
- **WHEN** 用户点击侧栏中的某个会话
- **THEN** 右侧对话面板加载该会话的历史消息，系统调用 `thread/resume`

#### Scenario: 新建会话按钮
- **WHEN** 用户点击"新建会话"按钮
- **THEN** 弹出模型选择器，确认后创建新 thread，侧栏刷新并自动选中新会话

### Requirement: 对话面板
系统 SHALL 在 GUI 右侧展示当前会话的对话历史，包含用户消息和 Agent 回复。

#### Scenario: 展示对话历史
- **WHEN** 用户切换到一个已有历史的 thread
- **THEN** 对话面板渲染所有历史 turns 的 messages（userMessage 和 agentMessage）

#### Scenario: 实时展示 Agent 流式输出
- **WHEN** Agent 正在生成回复且 `item/agentMessage/delta` 通知到达
- **THEN** 对话面板中当前消息实时追加显示新文本

#### Scenario: 展示命令执行结果
- **WHEN** Agent 执行命令（commandExecution item 完成）
- **THEN** 对话面板展示命令字符串和执行输出（stdout/stderr）

### Requirement: 消息输入和发送
系统 SHALL 在底部提供文本输入框和发送按钮。

#### Scenario: 发送消息
- **WHEN** 用户在输入框输入文本并点击发送（或按 Enter）
- **THEN** 消息作为 userMessage 显示在对话面板中，同时调用 `turn/start` 开始 Agent 推理

#### Scenario: 空消息阻止
- **WHEN** 用户尝试发送空文本
- **THEN** 系统不发送请求，输入框保持焦点

#### Scenario: Agent 运行中禁用输入
- **WHEN** 当前 thread 有活跃的 inProgress turn
- **THEN** 输入框和发送按钮变为禁用状态，显示"停止"按钮

### Requirement: 连接状态指示
系统 SHALL 在 GUI 中展示与 app-server 的连接状态。

#### Scenario: 连接中
- **WHEN** 系统正在建立 WebSocket 连接
- **THEN** 状态指示器显示"连接中..."

#### Scenario: 已连接
- **WHEN** 握手完成，状态为 ready
- **THEN** 状态指示器显示"已连接"，绿色标识

#### Scenario: 断开连接
- **WHEN** WebSocket 连接断开
- **THEN** 状态指示器显示"已断开"，红色标识，禁用交互控件

### Requirement: 错误提示
系统 SHALL 在操作失败时向用户展示错误信息。

#### Scenario: RPC 错误展示
- **WHEN** 任何 RPC 调用返回 error 响应
- **THEN** GUI 以 toast 或内联消息形式展示错误信息

#### Scenario: 连接失败
- **WHEN** 无法连接到 app-server（进程未启动或端口占用）
- **THEN** GUI 展示明确错误信息和排查建议
