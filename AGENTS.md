# AGENTS.md

Always use the OpenAI developer documentation MCP server when working with the Codex App Server API — the protocol is version-specific and docs change frequently.

## Commands

```bash
uv sync              # install deps + build project (required before first run / after pyproject changes)
uv run codex-demo    # launch app (starts codex app-server subprocess + Gradio UI on :7860)
```

No test suite. Verify changes via `gradio_client` API calls against `http://127.0.0.1:7860`.

## Architecture: dual event loop (critical)

WebSocket client runs in a **background asyncio loop** (`bg_loop` thread). Gradio handlers run in Gradio's own loop. All RPC calls use `run_coroutine_threadsafe(coro, bg_loop)` via `AgentState.sync_*` methods. Notifications from app-server push into a thread-safe `queue.Queue`, consumed by Gradio async generators in `_handle_send`.

Never call `AppServerClient.request()` directly from a Gradio handler — it will cross event loops and hang. Always go through `AgentState.sync_*` wrappers.

## Gradio 6 gotchas

- Chatbot message format is `{"role": "user", "content": [{"type": "text", "text": "..."}]}` — plain string content silently fails
- `demo.queue()` is mandatory for async generator streaming to work in the browser
- Use `async def` + `yield` for streaming handlers; sync generators do not stream to the frontend
- `gr.Chatbot` no longer accepts `type="messages"` parameter (Gradio 6)
- Returning `gr.Button(...)` / `gr.skip()` from handlers can get silently dropped — keep output counts exact and prefer plain values over component constructors

## Codex App Server quirks

- `sandbox` param uses kebab-case: `"workspace-write"`, `"read-only"`, `"danger-full-access"` — not camelCase
- **Do not pass `model` from `model/list`** to `thread/start` — those are OpenAI catalog models. The user's `~/.codex/config.toml` may configure a custom provider (e.g. `MiniMax-M3`). Read the model name from config.toml and pass that instead.
- `thread/list` does not immediately include a newly created thread — manually insert it into the choices
- `thread/resume` on a freshly created thread may fail ("no rollout found") — tolerate the error gracefully

## Item rendering

Agent output items (agentMessage, commandExecution, mcpToolCall, etc.) arrive interleaved in time. Render them in **arrival order** using an ordered blocks list keyed by `item_id` — do not separate agentMessage text from tool results into different variables, or tool output will appear out of order or get overwritten by subsequent agentMessage deltas.
