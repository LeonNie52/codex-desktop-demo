## ADDED Requirements

### Requirement: 发起对话 Turn
系统 SHALL 支持向指定 Thread 发起一个新的对话 Turn，传入用户输入并开始 Agent 推理。

#### Scenario: 发送文本消息开启 turn
- **WHEN** 用户在 GUI 输入框输入文本并发送
- **THEN** 系统调用 `turn/start`，传入 `threadId` 和 `input: [{type: "text", text: "..."}]`，返回 turnId

#### Scenario: turn 开始时收到确认通知
- **WHEN** `turn/start` 成功返回
- **THEN** 系统随后收到 `turn/started` 服务器通知，turn 状态为 `inProgress`

### Requirement: 流式接收 Agent 消息
系统 SHALL 通过 `item/agentMessage/delta` 通知实时接收并累积 Agent 的文本输出。

#### Scenario: 接收多个 delta 并拼接
- **WHEN** Agent 输出长文本时服务器发送多条 `item/agentMessage/delta` 通知
- **THEN** 系统按顺序累积 delta 文本并在 GUI 中实时更新显示

#### Scenario: agentMessage item 完成
- **WHEN** 服务器发送 `item/completed` 通知且 item.type 为 `agentMessage`
- **THEN** 系统标记该消息为完成状态，以最终完整文本替换流式累积文本

### Requirement: 渲染各类 Agent 输出 Item
系统 SHALL 解析并渲染以下 Item 类型：agentMessage、commandExecution、fileChange、reasoning、plan。

#### Scenario: 渲染命令执行 item
- **WHEN** 收到 `item/started` 通知且 `item.type` 为 `commandExecution`
- **THEN** GUI 展示命令字符串和执行状态，并在收到 `item/completed` 后展示 exitCode 和输出

#### Scenario: 渲染文件变更 item
- **WHEN** 收到 `item/started` 通知且 `item.type` 为 `fileChange`
- **THEN** GUI 展示变更文件路径和 diff 摘要

#### Scenario: 渲染未知类型 item
- **WHEN** 收到未知 `item.type` 的 `item/started` 通知
- **THEN** GUI 以通用格式展示 item 类型和 id，不崩溃

### Requirement: 中断进行中的 Turn
系统 SHALL 支持取消当前正在执行的 Turn。

#### Scenario: 用户中断 turn
- **WHEN** 用户在 Agent 运行中点击"停止"按钮
- **THEN** 系统调用 `turn/interrupt`，随后收到 `turn/completed` 通知且 status 为 `interrupted`

#### Scenario: 中断空闲 thread
- **WHEN** 当前 thread 无活跃 turn 时调用 `turn/interrupt`
- **THEN** 系统收到错误响应

### Requirement: Turn 完成处理
系统 SHALL 正确处理 `turn/completed` 通知，区分 completed、interrupted、failed 三种终态。

#### Scenario: Turn 正常完成
- **WHEN** Agent 完成所有工作后服务器发送 `turn/completed` 且 `turn.status` 为 `completed`
- **THEN** GUI 显示完成状态，启用输入框接受新消息

#### Scenario: Turn 失败
- **WHEN** 服务器发送 `turn/completed` 且 `turn.status` 为 `failed`
- **THEN** GUI 显示错误信息（来自 `turn.error.message`）

### Requirement: 列出可用模型
系统 SHALL 通过 `model/list` 获取可用模型列表。

#### Scenario: 获取模型列表
- **WHEN** 系统调用 `model/list`
- **THEN** 返回模型数组，每个模型包含 id、displayName、defaultReasoningEffort 等字段
