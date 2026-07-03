## ADDED Requirements

### Requirement: WebSocket 连接管理
系统 SHALL 通过 WebSocket 协议连接到 Codex App Server，支持连接、断开和状态查询。

#### Scenario: 成功连接 app-server
- **WHEN** app-server 在 `ws://127.0.0.1:4500` 上运行且客户端调用 `connect()`
- **THEN** WebSocket 连接建立，客户端状态变为 `connected`

#### Scenario: 连接断开通知
- **WHEN** WebSocket 连接因任何原因断开
- **THEN** 系统将内部状态设为 `disconnected` 并通知上层模块

### Requirement: JSON-RPC 初始化握手
系统 SHALL 在连接建立后立即执行 JSON-RPC initialize 握手，发送 `initialize` 请求和 `initialized` 通知。

#### Scenario: 完成握手
- **WHEN** WebSocket 连接建立后客户端发送 `initialize` 请求并收到响应
- **THEN** 客户端发送 `initialized` 通知，状态变为 `ready`

#### Scenario: 未初始化时拒绝其他请求
- **WHEN** 客户端在 `initialize` 前发送其他 RPC 请求
- **THEN** 收到错误响应（由 app-server 返回），请求被拒绝

### Requirement: JSON-RPC 请求/响应
系统 SHALL 支持发送带 `id` 的 JSON-RPC 请求，并将服务器响应按 `id` 匹配回对应的调用者。

#### Scenario: 发送请求并获得响应
- **WHEN** 客户端调用 `request("model/list", {})` 
- **THEN** 返回一个 awaitable 对象，当服务器返回匹配 `id` 的响应时 resolve 为结果值

#### Scenario: 请求超时
- **WHEN** 某个请求在配置的超时时间内未获得响应
- **THEN** 该请求的 awaitable 以 timeout 异常 reject

### Requirement: 服务器通知分发
系统 SHALL 接收并分发无 `id` 字段的服务器通知消息给已注册的回调函数。

#### Scenario: 注册回调并接收通知
- **WHEN** 客户端通过 `on_notification("item/agentMessage/delta", handler)` 注册回调，且服务器发送匹配 method 的通知
- **THEN** `handler` 被调用，参数为通知的 `params`

#### Scenario: 未注册的通知方法
- **WHEN** 服务器发送一条无对应回调的通知
- **THEN** 该通知被静默忽略（不抛出错误）
