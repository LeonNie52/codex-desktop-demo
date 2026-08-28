# Codex Hook 字段标注规范

以下字段名区分大小写。输入字段采用 `snake_case`，JSON 输出的公共字段和
`hookSpecificOutput` 采用 `camelCase`。本页以当前发布文档为行为基准，同时标注
Codex `main` 源码中已出现但尚未在发布文档承诺的内容。

## 配置字段

### 顶层和 matcher group

| 层级 | 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `hooks.json` | `description` | string | 否 | 元数据，不影响执行 |
| `hooks.json` | `hooks` | object | 是 | 事件名到 matcher group 数组的映射 |
| matcher group | `matcher` | string | 否 | 正则；`"*"`、空串或省略表示全部 |
| matcher group | `hooks` | array | 是 | 一个或多个 handler；匹配的 command handler 会并发启动 |

### command handler

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `type` | `"command"` | 是 | — | handler 类型 |
| `command` | string | 是 | — | macOS/Linux 及默认命令 |
| `commandWindows` | string | 否 | `command` | Windows 覆盖命令；TOML 也接受 `command_windows` |
| `timeout` | integer | 否 | 600 | 秒；`SessionEnd` 默认 1，最大 3 |
| `async` | boolean | 否 | false | 后台运行；后台 hook 不能阻断、审批、改写或续跑 |
| `statusMessage` | string | 否 | — | hook 运行时展示的状态文本 |
| `additionalContextLimit` | integer | 否 | 2500 | `additionalContext` 近似 token 阈值；`0` 表示不 spill |

大输出超过阈值时，Codex 会把全文 spill 到临时文件，并只向模型提供头尾预览和文件
路径。`additionalContextLimit` 仅适用于能返回 `additionalContext` 的事件。

### MCP tool handler

Python 模板使用 command handler，但当前配置还支持 MCP tool handler：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `type` | `"mcp_tool"` | 是 | — | handler 类型 |
| `server` | string | 是 | — | 已连接的 MCP server 名称 |
| `tool` | string | 是 | — | server 暴露的工具名 |
| `input` | object | 否 | `{}` | 参数模板，支持 `${field.nested}` 占位符 |
| `timeout` | integer | 否 | 600 | 活跃执行超时秒数 |
| `statusMessage` | string | 否 | — | 运行状态文本 |

`prompt` 和 `agent` handler 当前会被解析但跳过。`SessionEnd` 不支持 MCP tool hook。

## 输入字段

### 公共字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session_id` | string | 当前 session id；subagent hook 使用父 session id |
| `transcript_path` | string \| null | transcript 文件路径；格式不是稳定接口 |
| `cwd` | string | session 工作目录，也是 command handler 的运行目录 |
| `hook_event_name` | string | 当前事件名 |
| `model` | string | Codex 扩展，当前模型 slug |
| `turn_id` | string | Codex 扩展，仅 turn-scoped 事件 |
| `permission_mode` | string | `default`、`acceptEdits`、`plan`、`dontAsk`、`bypassPermissions` |
| `agent_id` | string | 在 subagent 上下文执行时的 agent id |
| `agent_type` | string | 在 subagent 上下文执行时的 agent 类型或 profile |

`PreToolUse`、`PermissionRequest`、`PostToolUse`、`PreCompact`、
`PostCompact` 和 `UserPromptSubmit` 在 subagent 上下文中可额外包含可选的
`agent_id`、`agent_type`。模板保留未知字段并告警，以便向前兼容。

### 事件字段矩阵

表中字段均是在公共字段之外增加或需要特别说明的字段。

| 事件 | 事件专有字段 | matcher 作用对象 | stdout 语义 |
| --- | --- | --- | --- |
| `SessionStart` | `source: startup \| resume \| clear \| compact` | `source` | 文本或 `additionalContext` 进入 developer context |
| `SessionEnd` | `reason: other` | `reason` | advisory；输出不能控制 Codex |
| `SubagentStart` | `turn_id`, `agent_id`, `agent_type`, `permission_mode` | `agent_type` | 文本或 `additionalContext` 进入 subagent context |
| `PreToolUse` | `turn_id`, `tool_name`, `tool_input`, `tool_use_id`, `permission_mode` | `tool_name` | 可拒绝或改写工具调用；普通文本忽略 |
| `PermissionRequest` | `turn_id`, `tool_name`, `tool_input`, `permission_mode` | `tool_name` | 可 allow、deny 或不决策；普通文本忽略 |
| `PostToolUse` | `turn_id`, `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, `permission_mode` | `tool_name` | 可替换模型可见结果，不能撤销副作用 |
| `PreCompact` | `turn_id`, `trigger: manual \| auto` | `trigger` | `continue: false` 可在压缩前停止 |
| `PostCompact` | `turn_id`, `trigger: manual \| auto` | `trigger` | `continue: false` 可在压缩后停止 |
| `UserPromptSubmit` | `turn_id`, `prompt`, `permission_mode` | 不支持，配置值被忽略 | 可增加 context 或阻止 prompt |
| `SubagentStop` | `turn_id`, `agent_id`, `agent_type`, `agent_transcript_path`, `stop_hook_active`, `last_assistant_message`, `permission_mode` | `agent_type` | `decision:block` 要求 subagent 继续 |
| `Stop` | `turn_id`, `stop_hook_active`, `last_assistant_message`, `permission_mode` | 不支持，配置值被忽略 | `decision:block` 创建续跑 prompt |

两个容易误用的例外：

- 当前 `SessionEnd` 源码输入只有 `session_id`、`transcript_path`、`cwd`、
  `hook_event_name`、`reason`，没有 `model`、`permission_mode` 或 `turn_id`。
- `PreCompact`、`PostCompact` 当前没有 `permission_mode`。

Codex `main` 还定义了 `Interrupt` 预览事件，输入为 `session_id`、`turn_id`、
`transcript_path`、`cwd`、`hook_event_name`、`model`、`permission_mode`，输出当前只接受
`systemMessage`。发布文档尚未把它列入事件清单，稳定配置不应依赖它。

### tool 字段

- Bash 和 `apply_patch` 的 `tool_input` 使用 `tool_input.command`。
- MCP 和其他 local function tool 的 `tool_input` 是原始参数 JSON。
- `PermissionRequest.tool_input.description` 可能包含人类可读的审批原因，但并非每个
  工具都提供。
- `PostToolUse.tool_response` 是工具特定结果；MCP 工具返回 MCP call result，其他本地
  function tool 通常返回模型可见输出。
- `apply_patch` 的 canonical `tool_name` 是 `apply_patch`，matcher 也可使用 `Edit` 或
  `Write`。
- `spawn_agent` 还可匹配别名 `Agent`。hosted tool（例如 `WebSearch`）不走当前本地
  function-tool hook 路径。

## 输出字段

### 公共输出

| 字段 | 类型 | 默认值 | 当前语义 |
| --- | --- | --- | --- |
| `continue` | boolean | true | `false` 将该 hook 标为 stopped；只在指定事件有效 |
| `stopReason` | string | null | 停止原因 |
| `systemMessage` | string | null | 在 UI 或事件流中显示 warning |
| `suppressOutput` | boolean | false | 可解析，但当前尚未实现 |

`SessionStart`、`PreCompact`、`PostCompact`、`UserPromptSubmit`、
`SubagentStop` 和 `Stop` 接受公共形状。`SubagentStart` 接受 warning/context，
`continue: false` 会被解析但不能阻止 subagent 启动。`PostToolUse` 支持
`systemMessage`、`continue: false` 和 `stopReason`。`PreToolUse` 与
`PermissionRequest` 当前只支持公共字段中的 `systemMessage`。

### 事件专有输出

#### SessionStart、SubagentStart、UserPromptSubmit

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "给模型的附加上下文"
  }
}
```

`hookEventName` 必须与实际事件一致。`UserPromptSubmit` 还可用
`{"decision":"block","reason":"原因"}` 阻止 prompt。

#### PreToolUse

拒绝：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "阻断原因"
  }
}
```

改写并允许：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {"command": "echo rewritten"},
    "additionalContext": "可选上下文"
  }
}
```

旧形状 `{"decision":"block","reason":"原因"}` 仍被接受。`updatedInput` 只能与
`permissionDecision: allow` 一起使用；Bash 和 `apply_patch` 的替换对象必须包含
string `command`。`permissionDecision: ask`、旧的 `decision: approve`、
`continue: false`、`stopReason`、`suppressOutput` 当前均不支持；返回这些组合会把该
hook 标记为失败，并继续原工具调用。

#### PermissionRequest

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "deny",
      "message": "拒绝原因"
    }
  }
}
```

`behavior` 为 `allow` 或 `deny`。多个 hook 中任意 `deny` 优先，否则任意 `allow`
跳过正常审批 UI；没有决策则进入正常审批。schema 中的 `updatedInput`、
`updatedPermissions`、`interrupt` 是预留字段，当前返回会失败。

#### PostToolUse

```json
{
  "decision": "block",
  "reason": "原工具结果需要复核",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "补充上下文"
  }
}
```

`decision:block` 会用反馈替换原工具结果并让模型继续，不会撤销工具副作用。
`continue:false` 也会停止正常处理原结果。`updatedMCPToolOutput` 和
`suppressOutput` 当前只解析、不支持实际行为；返回它们会把该 hook 标记为失败，并
继续正常处理原工具结果。

#### Stop、SubagentStop

```json
{"decision":"block","reason":"再执行一轮的具体要求"}
```

`reason` 必须非空。任一匹配 hook 返回 `continue:false` 时，优先于其他 hook 的续跑
决策。

#### PreCompact、PostCompact

只使用公共输出。`continue:false` 分别在压缩前或压缩后停止当前处理。

#### SessionEnd

输出是 advisory，不会控制 Codex 或保持 thread 打开。模板固定返回 `{}`。

## matcher 速查

| 事件 | 推荐 matcher |
| --- | --- |
| `SessionStart` | `startup|resume|clear|compact` |
| `SessionEnd` | `other` 或省略 |
| `PreToolUse` / `PermissionRequest` / `PostToolUse` | `Bash`、`^apply_patch$`、`Edit|Write`、`mcp__server__.*`、其他 function tool 名 |
| `PreCompact` / `PostCompact` | `manual|auto` |
| `SubagentStart` / `SubagentStop` | agent type/profile 正则 |
| `UserPromptSubmit` / `Stop` | 省略；当前 matcher 被忽略 |

## 失败与并发语义

- 同一事件的多个匹配 command hook 会并发启动，不能假定声明顺序。
- 多个配置层的匹配 hook 都会运行，高优先级配置不会替换低优先级 hook。
- 同步 hook 默认阻塞触发操作，超时默认 600 秒。
- 后台 hook 每个 session 最多并发 8 个，完成顺序可能不同，不能控制触发操作。
- `SessionEnd` 始终同步，未完成的其他后台 hook 在 session 结束时会被取消。
- 退出码 `0` 且无输出表示成功继续。结构化阻断优先使用 JSON；官方也允许部分事件以
  退出码 `2` 加 stderr 原因实现阻断或续跑。
