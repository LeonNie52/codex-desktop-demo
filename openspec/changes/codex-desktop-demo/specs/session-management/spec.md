## ADDED Requirements

### Requirement: 创建新会话
系统 SHALL 支持创建新的 Thread 会话，指定模型和工作目录。

#### Scenario: 创建新 thread
- **WHEN** 用户通过 GUI 点击"新建会话"并选择模型
- **THEN** 系统调用 `thread/start`，返回新 thread 的 id、preview、createdAt 等信息

#### Scenario: 创建时指定工作目录
- **WHEN** 创建 thread 时传入 `cwd` 参数为 `/Users/me/project`
- **THEN** 新 thread 的会话上下文限定在该目录

### Requirement: 列出历史会话
系统 SHALL 支持分页列出所有已保存的 Thread 会话。

#### Scenario: 首次加载会话列表
- **WHEN** 系统调用 `thread/list` 不带 cursor 参数
- **THEN** 返回第一页会话数据（按 createdAt 倒序），包含 id、preview、name、createdAt 等字段

#### Scenario: 加载更多会话
- **WHEN** 系统使用上一页返回的 `nextCursor` 再次调用 `thread/list`
- **THEN** 返回下一页会话数据

#### Scenario: 空列表
- **WHEN** 用户从未创建过任何 thread
- **THEN** `thread/list` 返回空的 data 数组，nextCursor 为 null

### Requirement: 恢复已存在的会话
系统 SHALL 支持通过 threadId 恢复一个已保存的 Thread 以继续对话。

#### Scenario: 恢复已有 thread
- **WHEN** 系统调用 `thread/resume` 传入有效的 `threadId`
- **THEN** 返回该 thread 的完整信息（含 name、turns 历史），订阅事件通知

#### Scenario: 恢复不存在的 thread
- **WHEN** 系统调用 `thread/resume` 传入无效的 `threadId`
- **THEN** 返回错误响应，GUI 显示错误提示

### Requirement: 读取会话详情（不恢复）
系统 SHALL 支持通过 `thread/read` 读取 thread 元数据和历史 turns，但不订阅事件。

#### Scenario: 读取会话含 turns 历史
- **WHEN** 系统调用 `thread/read` 传入 `includeTurns: true`
- **THEN** 返回 thread 详情及其所有历史 turns 和 items

### Requirement: 归档和删除会话
系统 SHALL 支持归档（软删除）和永久删除 Thread。

#### Scenario: 归档会话
- **WHEN** 用户选择"归档"操作，系统调用 `thread/archive`
- **THEN** 该 thread 从默认列表中消失（需 `archived: true` 才能查询到）

#### Scenario: 永久删除会话
- **WHEN** 用户选择"删除"操作，系统调用 `thread/delete`
- **THEN** 该 thread 及其后代 threads 被永久移除

### Requirement: 重命名会话
系统 SHALL 支持设置 Thread 的用户可见名称。

#### Scenario: 设置会话名称
- **WHEN** 系统调用 `thread/name/set` 传入有效的名称
- **THEN** 会话名称更新，后续查询反映新名称
