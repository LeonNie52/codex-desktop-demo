# Codex Python Hook 标准模板

这套模板把 hook 的协议层和业务层分开。日常开发只修改
[`hook.py`](./hook.py) 中的 `on_*` 函数，输入解析、字段校验、事件分发、输出序列化、
日志脱敏、日志轮转和异常退出由公共框架统一处理。

模板核对日期为 2026-08-28，依据如下：

- [Codex Hooks 官方文档](https://learn.chatgpt.com/docs/hooks)
- [Codex Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#hooks)
- [Codex main 分支 hook schema 源码](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/schema.rs)
- [Codex main 分支 hook 配置源码](https://github.com/openai/codex/blob/main/codex-rs/config/src/hook_config.rs)

官方文档是当前发布行为的基准。GitHub `main` 可能包含尚未发布的字段。模板默认配置
覆盖文档承诺的 11 个事件；代码额外识别 `main` 已定义、但当前发布文档尚未承诺的
`Interrupt`，不会主动把它写入稳定版 `hooks.json`。

完整字段、matcher 和输出语义见 [`FIELD_REFERENCE.md`](./FIELD_REFERENCE.md)。

## 文件

| 文件 | 用途 |
| --- | --- |
| `hook.py` | 无第三方依赖的统一 hook 入口和业务函数模板 |
| `hooks.json.example` | 覆盖 11 个当前文档事件的项目级配置 |
| `FIELD_REFERENCE.md` | 配置、输入、输出字段及支持状态 |
| `test_hook.py` | 覆盖全部 11 个发布事件和 `Interrupt` 预览事件的冒烟测试 |

## 安装

从仓库根目录执行：

```bash
mkdir -p .codex/hooks
cp examples/codex-hooks-python/hook.py .codex/hooks/hook.py
cp examples/codex-hooks-python/hooks.json.example .codex/hooks.json
chmod +x .codex/hooks/hook.py
```

同时把 `.codex/hooks/logs/` 加入项目 `.gitignore`，不要提交运行日志。

Windows 用户必须先把 `.codex/hooks.json` 中所有
`C:\ABSOLUTE\PATH\TO\REPO` 替换成真实绝对路径。macOS 和 Linux 使用
`git rev-parse --show-toplevel`，即使 Codex 从子目录启动也能找到脚本。

项目级 hook 只有在项目被信任后才会加载。首次启用或修改 hook 后，在 Codex CLI
执行 `/hooks` 检查并信任当前定义。若同一配置层同时存在 `hooks.json` 和
`config.toml` 内联 hooks，Codex 会合并二者并告警，因此同一层建议只保留一种形式。

## 开发约定

### 1. 只改业务函数

例如在 `PreToolUse` 阻止某类 Bash 命令：

```python
def on_pre_tool_use(event: HookInput) -> HookOutput:
    tool_name = event.get("tool_name")
    tool_input = event.get("tool_input")
    if tool_name == "Bash" and isinstance(tool_input, dict):
        command = str(tool_input.get("command", ""))
        if "your-forbidden-pattern" in command:
            return HookOutput.pre_tool_deny("命令违反仓库策略")
    return HookOutput.success()
```

推荐使用 `HookOutput` 工厂方法，不手写输出字典。工厂方法会限制事件与返回语义的
错误组合，例如 `PermissionRequest` 应使用 `permission_allow()` 或
`permission_deny()`，不能使用 `PreToolUse` 的 `permissionDecision`。

### 2. stdout 只能返回协议 JSON

Codex 通过 stdin/stdout 与 command hook 通信：

- `stdin` 是一个 UTF-8 JSON object。
- `stdout` 只能由 `write_stdout_json()` 输出一个 JSON object。
- 普通日志只能写 `stderr` 或日志文件。
- 输入错误或内部异常返回非零退出码，不伪造成功 JSON。
- 需要使用退出码 `2` 的阻断协议时，可以在具体策略中显式实现；常规情况优先返回
  结构化 JSON，便于测试和演进。

`SessionStart` 和 `UserPromptSubmit` 等少数事件支持纯文本 stdout，但统一模板仍只用
JSON，避免同一入口因事件不同产生两套输出规则。`Stop` 和 `SubagentStop` 在退出码
为 `0` 时必须返回 JSON，默认 `{}` 符合要求。

### 3. 默认放行

所有 `on_*` 默认返回 `{}`，不会拦截工具、自动审批、续跑 agent 或修改模型上下文。
策略必须显式返回以下结果之一：

- `HookOutput.pre_tool_deny(reason)`：工具执行前拒绝。
- `HookOutput.pre_tool_rewrite(updated_input)`：工具执行前改写参数。
- `HookOutput.permission_allow()` / `permission_deny(message)`：代替审批决策。
- `HookOutput.block(event_name, reason)`：按事件语义阻断提示、替换工具结果或要求续跑。
- `HookOutput.stop_processing(event_name, reason)`：返回 `continue: false`。
- `HookOutput.additional_context(event_name, text)`：向模型增加 developer context。

注意 `PostToolUse` 已经晚于工具副作用，不能回滚命令或文件变更。`Stop` 与
`SubagentStop` 的 `decision: block` 表示“继续运行”，并非拒绝本轮。

## 日志

模板同时提供两种日志：

- `stderr`：默认 `INFO`，便于在 hook 运行摘要中快速查看。
- JSONL 轮转文件：固定记录 `DEBUG` 及以上，默认路径为
  `<git-root>/.codex/hooks/logs/codex-hooks.jsonl`。

插件内运行时，若存在 `PLUGIN_DATA`，默认改写到 `$PLUGIN_DATA/logs`。日志文件默认
单个 5 MiB，保留 5 个备份。每条记录包含时间、级别、事件、session、turn、耗时及
异常栈。

可用环境变量：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `CODEX_HOOK_LOG_DIR` | 项目或插件日志目录 | 覆盖日志目录 |
| `CODEX_HOOK_LOG_FILE` | `codex-hooks.jsonl` | 覆盖日志文件名 |
| `CODEX_HOOK_LOG_LEVEL` | `INFO` | stderr 日志级别 |
| `CODEX_HOOK_LOG_MAX_BYTES` | `5242880` | 单个日志文件上限 |
| `CODEX_HOOK_LOG_BACKUPS` | `5` | 轮转文件数量 |
| `CODEX_HOOK_LOG_PAYLOADS` | 未启用 | 设置为 `1` 才记录脱敏后的完整输入 |
| `CODEX_HOOK_MAX_INPUT_BYTES` | `2097152` | stdin 最大字节数 |

完整 payload 默认不落日志。开启后，键名匹配 `token`、`secret`、`password`、
`authorization`、`cookie`、`credential` 或 `api_key` 的值会被替换为
`<redacted>`，超长字符串会截断。脱敏只能降低误泄露风险，不能替代调用方的数据
分级和访问控制。

## 校验

模板测试不依赖项目环境：

```bash
python3 examples/codex-hooks-python/test_hook.py
```

也可以手工发送一个事件：

```bash
printf '%s' '{"session_id":"thr_1","turn_id":"turn_1","transcript_path":null,"cwd":"/tmp","hook_event_name":"UserPromptSubmit","model":"test-model","permission_mode":"default","prompt":"hello"}' \
  | CODEX_HOOK_LOG_DIR=/tmp/codex-hook-logs python3 examples/codex-hooks-python/hook.py
```

预期 stdout 为 `{}`，stderr 显示开始和完成日志，详细 JSONL 位于指定日志目录。

## 上线检查清单

- 配置中的脚本路径在仓库根目录和子目录启动时都能解析。
- Windows 的 `commandWindows` 已替换为真实绝对路径。
- hook 超时时间小于业务可接受的阻塞时间，`SessionEnd` 不超过 3 秒。
- 需要阻断、审批、改写或续跑的 hook 未配置 `async: true`。
- 日志 payload 默认关闭；确需开启时已确认不会写入敏感正文。
- 每个阻断结果都有非空、可操作的原因。
- `updatedInput` 只与 `PreToolUse permissionDecision: allow` 一起返回。
- 修改后运行测试，并通过 `/hooks` 重新检查和信任定义。
