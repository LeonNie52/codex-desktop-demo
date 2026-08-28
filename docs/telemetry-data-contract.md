# codex OTEL 数据契约参考

> 配套文档：[`telemetry-integration.md`](./telemetry-integration.md)（对接方案与配置）
>
> 本文档供 **Java Spring Boot 服务端**解析/存储实现参考，定义 codex app-server 通过 OTLP/HTTP·JSON 上报的数据类型、字段、间隔与 temporality。所有结论基于 codex 源码（`codex-rs/otel/`、`codex-rs/analytics/`、`codex-rs/core-skills/`）确认。

## 一、上报间隔与批处理（不可配置）

| 信号 | 处理器 | 默认间隔 | 批次/队列上限 | 数据丢失风险 |
|---|---|---|---|---|
| **metrics** | `PeriodicReader` | **60 秒** | — | 强杀进程丢未导出批次 |
| **traces** | `BatchSpanProcessor` | **5 秒**（`scheduled_delay`）| 队列 2048，导出批 512 | 队列满提前触发；强杀丢 |
| **logs** | `BatchLogProcessor` | **5 秒** | 同 trace | 同上 |

- codex **不覆盖**这些默认值（`provider.rs:452` 无 `with_batch_config`，`client.rs:494` `interval=None` 跳过 `with_interval`）。
- `config.toml` **不暴露间隔字段**（`OtelConfigToml` 无 interval）；`with_export_interval` 仅测试用。
- 正常退出 `force_flush`（`provider.rs:64`），数据不丢；`kill -9` 丢未导出批次。
- 服务端按"数据滞后 60s（metric）/5s（trace、log）到达"设计，不要假设实时。

## 二、Resource 属性差异（三信号）

每个请求的 `resource{Spans|Metrics|Logs}[].resource.attributes[]` 含以下属性：

| 属性 key | trace | metric | log | 来源 |
|---|---|---|---|---|
| `service.name` | ✅ | ✅ | ✅ | 固定 `codex-app-server`（app-server 的 `OTEL_SERVICE_NAME`）|
| `service.version` | ✅ | ✅ | ✅ | app-server 包版本 |
| `env` | ✅ | ✅ | ✅ | `[otel].environment`（**用户/实例标识**）|
| `os` | ❌ | ✅ | ❌ | `os_info` crate 探测（metric 在 `client.rs:468`）|
| `os_version` | ❌ | ✅ | ❌ | 同上 |
| `host.name` | ❌ | ❌ | ✅ | `gethostname` 自动探测（仅 log，`provider.rs:235`）|

> `service.instance.id`（OTel 标准多实例属性）codex **不设置**。服务端须从 `env` 自行归一为实例标识。

**protojson 取值示例**：
```json
{ "key": "env", "value": { "stringValue": "integration-alice" } }
```

## 三、Scope（Instrumentation Scope）

`resource*Spans[].scope*Spans[].scope.name`：

| 信号 | scope.name |
|---|---|
| traces | `codex-app-server`（= service.name，`provider.rs:133`）|
| metrics | `codex`（`METER_NAME`，`client.rs:45`）|
| logs | `codex-app-server` |

## 四、Metrics 完整清单（53 个）

> 全部源自 `otel/src/metrics/names.rs`；metric 名**点号原样传输**。`★` = 推荐优先落库的核心指标。

### 进程
| metric 名 | 类型 | tags |
|---|---|---|
| `codex.process.start` ★ | counter | `originator` |

### API / 网络
| metric 名 | 类型 | 单位 |
|---|---|---|
| `codex.api_request` ★ | counter | 1 |
| `codex.api_request.duration_ms` | histogram | ms |
| `codex.sse_event` | counter | 1 |
| `codex.sse_event.duration_ms` | histogram | ms |
| `codex.websocket.request` | counter | 1 |
| `codex.websocket.request.duration_ms` | histogram | ms |
| `codex.websocket.event` | counter | 1 |
| `codex.websocket.event.duration_ms` | histogram | ms |

### Responses API 性能
| metric 名 | 类型 | 单位 |
|---|---|---|
| `codex.responses_api_overhead.duration_ms` | histogram | ms |
| `codex.responses_api_inference_time.duration_ms` | histogram | ms |
| `codex.responses_api_engine_iapi_ttft.duration_ms` | histogram | ms |
| `codex.responses_api_engine_service_ttft.duration_ms` | histogram | ms |
| `codex.responses_api_engine_iapi_tbt.duration_ms` | histogram | ms |
| `codex.responses_api_engine_service_tbt.duration_ms` | histogram | ms |

### Turn 级
| metric 名 | 类型 | 单位 |
|---|---|---|
| `codex.turn.e2e_duration_ms` ★ | histogram | ms |
| `codex.turn.ttft.duration_ms` ★ | histogram | ms |
| `codex.turn.ttfm.duration_ms` | histogram | ms |
| `codex.turn.network_proxy` | counter | 1 |
| `codex.turn.memory` | counter | 1 |
| `codex.turn.tool.call` | counter | 1 |
| `codex.turn.token_usage` ★ | counter/gauge | 1 |

### Tool
| metric 名 | 类型 | tags |
|---|---|---|
| `codex.tool.call` ★ | counter | `tool` |
| `codex.tool.call.duration_ms` | histogram(ms) | `tool` |
| `codex.tool.unified_exec` | counter | |

### Skill（核心目标）
| metric 名 | 类型 | tags | 备注 |
|---|---|---|---|
| `codex.skill.injected` ★ | counter | `skill`, `status`(ok/error), `invoke_type`(仅隐式) | 硬编码字符串，不在 `names.rs`（`core-skills/src/injection.rs:142` + `core/src/skills.rs:107`）|

> `invoke_type=implicit` 仅隐式调用有；显式调用无此 label，区分显式/隐式靠 label 存在性。

### Guardian
| metric 名 | 类型 |
|---|---|
| `codex.guardian.review` | counter |
| `codex.guardian.review.duration_ms` | histogram(ms) |
| `codex.guardian.review.ttft.duration_ms` | histogram(ms) |
| `codex.guardian.review.token_usage` | counter |

### Goal
| metric 名 | 类型 |
|---|---|
| `codex.goal.created` | counter |
| `codex.goal.resumed` | counter |
| `codex.goal.completed` | counter |
| `codex.goal.budget_limited` | counter |
| `codex.goal.usage_limited` | counter |
| `codex.goal.blocked` | counter |
| `codex.goal.token_count` | counter |
| `codex.goal.duration_s` | histogram(s) |

### Plugin
| metric 名 | 类型 |
|---|---|
| `codex.plugins.install_elicitation.sent` | counter |
| `codex.plugins.install_suggestion` | counter |
| `codex.plugins.startup_sync` | counter |
| `codex.plugins.startup_sync.final` | counter |

### Hook
| metric 名 | 类型 |
|---|---|
| `codex.hooks.run` | counter |
| `codex.hooks.run.duration_ms` | histogram(ms) |

### Startup
| metric 名 | 类型 | tags |
|---|---|---|
| `codex.startup.phase.duration_ms` | histogram(ms) | `phase`, `status` |
| `codex.startup_prewarm.duration_ms` | histogram(ms) | `status` |
| `codex.startup_prewarm.age_at_first_turn_ms` | histogram(ms) | `outcome` |

### Thread
| metric 名 | 类型 | tags |
|---|---|---|
| `codex.thread.started` ★ | counter | `is_git` |
| `codex.thread.skills.enabled_total` | counter | |
| `codex.thread.skills.kept_total` | counter | |
| `codex.thread.skills.description_truncated_chars` | counter | |
| `codex.thread.skills.truncated` | counter | |

> 另有 `codex.skills.shadow_selection*`（实验性，默认不开，`ext/skills/src/shadow_selection_experiment.rs`）。

## 五、Metric 数据点结构与 Temporality

### Temporality = `AGGREGATION_TEMPORALITY_DELTA`

`client.rs:324` 硬编码 Delta。服务端按 `(service_instance_id, metric_name, label_set)` 累加才能得到 cumulative counter。

### Counter 数据点
```
sum.dataPoints[].asInt  // int64，protojson 编码为字符串
```

### Histogram 数据点
```
count            // 字符串
sum              // number
bucketCounts[]
explicitBounds[]
```

### 公共 metric tag（附加到每个数据点）

当 `metrics_use_metadata_tags=true`（默认）时，`tags.rs:38-57` 附加：

| tag key | 取值 | 备注 |
|---|---|---|
| `auth_mode` | `api_key`/`oauth`/... | |
| `session_source` | `cli`/`exec`/... | |
| `originator` | `codex-app-server` 等 | bounded 到已知值表，未知归 `other`（`tags.rs:29-36`）|
| `service_name` | | 可选 |
| `model` | `gpt-5.1` 等 | |
| `app_version` | | |

### protojson 字段链
```
resourceMetrics[].resource.attributes[].value.{stringValue|...}
resourceMetrics[].scopeMetrics[].metrics[].{sum|histogram}.dataPoints[].attributes[].value.*
```

## 六、Trace Span 清单（典型）

| span.name | 级别 | 关键属性 | 源码 |
|---|---|---|---|
| `session_init` | info | — | `session.rs:474` |
| `app_server.request` | — | `rpc.method`∈{`thread/start`,`turn/start`,`turn/interrupt`} | `outgoing_message.rs:1109` |
| `turn_context.build` | trace | — | `turn_context.rs:694` |
| `session.flush_rollout` | trace | — | `session.rs:1136` |
| `outbound-parent` / `outbound-request` | — | — | `exec-server/src/rpc.rs:984` |
| `remote-operation` | — | — | `exec-server/src/remote.rs:750` |
| `get_model_info` | — | `model` | `models-manager/src/manager.rs:194` |
| Responses 处理 span | — | `gen_ai.usage.input_tokens`/`output_tokens`/`cache_*`、`codex.usage.reasoning_output_tokens`、`tool_name` | `session_telemetry.rs:432-465` |
| tool/plugin/hook/skill/mcp | trace | — | 各自 `#[instrument]` |

**额外注入属性**：`[otel].span_attributes` 通过 `SpanAttributesProcessor`（`provider.rs:261`）加到每个 span（如 `deployment=codex-integration`）。**注意：span_attributes 只作用于 trace，对 metric 无效。**

## 七、Log 字段清单

每个 log record 的 `attributes[]` 含（`log_event!` 宏，`shared.rs:4-22`），value 均为 `stringValue`：

| 字段 key | 含义 | 是否含真实用户标识 |
|---|---|---|
| `event.timestamp` | RFC3339 毫秒 | — |
| `conversation.id` | thread id | 会话级 |
| `app.version` | app-server 版本 | — |
| `auth_mode` | `api_key`/`oauth`/... | — |
| `originator` | `codex-app-server` | — |
| **`user.account_id`** | 账号 id | ✅ **唯一用户标识** |
| **`user.email`** | 账号邮箱 | ✅ **唯一用户标识** |
| `terminal.type` | 终端类型 | — |
| `model` / `slug` | 模型 | — |

> **关键**：`user.account_id` / `user.email` **仅在 log 信号**出现；trace/metric 无真实账号，只有 `env`（实例标识）。若需账号粒度，必须实现 `/v1/logs` 并启用 `[otel].exporter`。

## 八、数据契约对照服务端实现

| 服务端需求 | 来源 | Spring Boot 处理 |
|---|---|---|
| 用户/实例分组统计 | resource `env` | 提取为 `service_instance_id` 落库 |
| 真实账号（邮箱/id）| log 的 `user.account_id`/`user.email` | 仅启用 log 通道时可用 |
| skill 次数 | metric `codex.skill.injected`（Delta）| 累加，按 `(instance, skill, status)` 维度 |
| turn 性能/token | metric `codex.turn.*`（Delta）| 累加/直存 |
| 调用链排障 | trace `app_server.request` 等 | 存 Jaeger/Tempo 兼容存储 |
| 时延容忍 | metric ≤60s，trace/log ≤5s | 不要假设实时 |

## 九、参考：典型 protojson 样例

### /v1/metrics（skill 调用）
```json
{
  "resourceMetrics": [{
    "resource": {
      "attributes": [
        { "key": "service.name",    "value": { "stringValue": "codex-app-server" } },
        { "key": "service.version", "value": { "stringValue": "0.50.0" } },
        { "key": "env",             "value": { "stringValue": "integration-alice" } },
        { "key": "os",              "value": { "stringValue": "macos" } },
        { "key": "os_version",      "value": { "stringValue": "15.0" } }
      ]
    },
    "scopeMetrics": [{
      "scope": { "name": "codex" },
      "metrics": [{
        "name": "codex.skill.injected",
        "unit": "1",
        "sum": {
          "dataPoints": [{
            "attributes": [
              { "key": "skill",       "value": { "stringValue": "paperclip" } },
              { "key": "status",      "value": { "stringValue": "ok" } },
              { "key": "invoke_type", "value": { "stringValue": "implicit" } }
            ],
            "startTimeUnixNano": "1722600000000000000",
            "timeUnixNano":      "1722600035000000000",
            "asInt": "1"
          }],
          "aggregationTemporality": "AGGREGATION_TEMPORALITY_DELTA",
          "isMonotonic": true
        }
      }]
    }]
  }]
}
```

### /v1/traces
```json
{
  "resourceSpans": [{
    "resource": {
      "attributes": [
        { "key": "service.name",    "value": { "stringValue": "codex-app-server" } },
        { "key": "service.version", "value": { "stringValue": "0.50.0" } },
        { "key": "env",             "value": { "stringValue": "integration-alice" } }
      ]
    },
    "scopeSpans": [{
      "scope": { "name": "codex-app-server" },
      "spans": [{
        "traceId": "5b8e4a2f9c1d7e3a6b0f2c4d8e9a1b3c",
        "spanId":  "a1b2c3d4e5f60718",
        "name": "session_init",
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": "1722600000000000000",
        "endTimeUnixNano":   "1722600012340000000",
        "attributes": [
          { "key": "deployment", "value": { "stringValue": "codex-integration" } }
        ],
        "status": { "code": "STATUS_CODE_UNSET" }
      }]
    }]
  }]
}
```

### /v1/logs
```json
{
  "resourceLogs": [{
    "resource": {
      "attributes": [
        { "key": "service.name", "value": { "stringValue": "codex-app-server" } },
        { "key": "env",          "value": { "stringValue": "integration-alice" } },
        { "key": "host.name",    "value": { "stringValue": "host-a" } }
      ]
    },
    "scopeLogs": [{
      "scope": { "name": "codex-app-server" },
      "logRecords": [{
        "timeUnixNano": "1722600010000000000",
        "severityNumber": 9,
        "severityText": "INFO",
        "body": { "stringValue": "conversation started" },
        "attributes": [
          { "key": "conversation.id", "value": { "stringValue": "thread-abc-123" } },
          { "key": "auth_mode",       "value": { "stringValue": "api_key" } },
          { "key": "originator",      "value": { "stringValue": "codex-app-server" } },
          { "key": "user.account_id", "value": { "stringValue": "acc_9f3k" } },
          { "key": "user.email",      "value": { "stringValue": "alice@example.com" } },
          { "key": "model",           "value": { "stringValue": "gpt-5.1" } }
        ]
      }]
    }]
  }]
}
```
