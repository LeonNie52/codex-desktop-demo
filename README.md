# Codex Desktop Agent Demo

基于 [Codex App Server](https://developers.openai.com/codex/app-server) 的桌面 Agent 最小化 Demo，提供图形化会话管理和对话交互。

## 功能

- **会话管理**：创建、列表、切换、归档、删除 Thread
- **对话交互**：发起 Turn，流式接收 Agent 输出（文本、命令执行、文件变更等）
- **流式渲染**：实时展示 Agent 的思考过程和操作结果
- **自定义模型**：自动读取 `~/.codex/config.toml` 中的模型配置

## 架构

```
┌──────────────┐    JSON-RPC/WS    ┌───────────────────┐
│   gui.py     │◄──────────────────►│  Codex App Server  │
│   (Gradio)   │                   │  (codex CLI)       │
├──────────────┤                   └───────────────────┘
│ agent_state  │
├──────────────┤
│ app_server   │
│ _client.py   │
└──────────────┘
```

## 使用

```bash
uv sync
uv run codex-demo
# 浏览器打开 http://127.0.0.1:7860
```

## 依赖

- Python >= 3.10
- Codex CLI（`codex app-server` 命令可用）
- 已认证的 Codex 账号（`codex login`）

## 开发模板

- [Codex Python Hook 标准模板](./examples/codex-hooks-python/README.md)：覆盖当前 hook
  事件、配置与输入输出字段，并内置结构化轮转日志、脱敏、校验和冒烟测试。
