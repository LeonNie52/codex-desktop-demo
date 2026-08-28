# codex-integration 服务端数据收集对接方案

> 配套文档：[`telemetry-data-contract.md`](./telemetry-data-contract.md)（OTEL 数据类型与字段规格，供服务端解析实现参考）

## 一、目标与范围

codex-integration 作为 codex 应用集成，向**自建 Java Spring Boot 服务端**集中上报统计数据，覆盖：

- skill 使用次数（核心目标）
- turn 性能与 token 用量
- tool 调用行为
- 完整 trace 调用链（排障）

服务端能在按"用户/实例"维度分组统计。

## 二、架构总览

```
codex-integration（可 N 实例）                    Java Spring Boot 服务端
┌─────────────────────────────────────┐         ┌──────────────────────────────────┐
│ main.py                              │         │ Controller（OTLP/HTTP receiver）  │
│  └ codex app-server 子进程           │         │   POST /v1/metrics  ← 必需        │
│     └─ OTLP/HTTP·JSON exporter       │ OTLP    │   POST /v1/traces   ← 必需        │
│        endpoint = SpringBoot:4318    │──HTTP──►│   POST /v1/logs     ← 可选        │
│        [otel].environment = 用户标识 │  JSON   │ Service:                          │
│        绝不用 statsig                 │         │   - protojson 反序列化            │
└─────────────────────────────────────┘         │   - delta→cumulative 累积         │
                                                │   - 从 resource.env 提取用户标识   │
                                                │   - 持久化（DB/TSDB，自定）        │
                                                └──────────────────────────────────┘
```

**数据时延**：metrics ≤60s 一批，trace/log ≤5s 一批（codex 用 SDK 默认，不可配）。

## 三、codex 端配置

### 3.1 `main.py` 改动（必需）

`main.py:42` 的 app-server 启动命令加 `--analytics-default-enabled`：

```python
[
    "codex", "app-server",
    "--listen", f"ws://127.0.0.1:{APP_SERVER_PORT}",
    "--analytics-default-enabled",   # 必需：否则 metrics_exporter 被强制 None
],
```

### 3.2 `~/.codex/config.toml` 模板

每实例一份；仓库内放 `config.example.toml` 作为部署参考。

```toml
[analytics]
enabled = true   # metrics 双重开关之一

[otel]
# 每个用户/租户实例填不同值 —— 这是 metric 区分来源的唯一手段
environment = "integration-alice"

[otel.span_attributes]
deployment = "codex-integration"   # 仅作用于 trace span

# 绝不能留默认 statsig（会发到 ab.chatgpt.com，服务端收不到）
[otel.trace_exporter]
otlp-http = { endpoint = "https://your-springboot:4318/v1/traces",
              protocol = "json",
              headers = { "x-api-key" = "CHANGE_ME" } }

[otel.metrics_exporter]
otlp-http = { endpoint = "https://your-springboot:4318/v1/metrics",
              protocol = "json",
              headers = { "x-api-key" = "CHANGE_ME" } }

# 可选：启用 log 通道可拿到真实 user.account_id / user.email
# [otel.exporter]
# otlp-http = { endpoint = "https://your-springboot:4318/v1/logs",
#               protocol = "json",
#               headers = { "x-api-key" = "CHANGE_ME" } }
```

## 四、Spring Boot 需提供的 API 端点

| 方法 | 路径 | Content-Type | 请求体（protojson）| 成功响应 |
|---|---|---|---|---|
| POST | `/v1/metrics` | `application/json` | `ExportMetricsServiceRequest` | 200 + `{}` |
| POST | `/v1/traces` | `application/json` | `ExportTraceServiceRequest` | 200 + `{}` |
| POST | `/v1/logs` | `application/json` | `ExportLogsServiceRequest` | 200 + `{}` |

- **端口**：OTLP/HTTP 约定 `4318`，可自定义，与 codex 端 endpoint 对齐即可。
- **必选**：`/v1/metrics`、`/v1/traces`。
- **可选**：`/v1/logs`（仅当要拿真实 `user.account_id`/`user.email` 时实现）。

## 五、Spring Boot 实现要点

1. **protojson 反序列化**：用 `io.opentelemetry.proto:opentelemetry-proto` 生成 Java 类，别手写 POJO。请求体结构详见 [`telemetry-data-contract.md`](./telemetry-data-contract.md)。

2. **Delta temporality 处理**：codex metric 是 `AGGREGATION_TEMPORALITY_DELTA`（每 60s 一批增量）。若后端要 cumulative counter，按 `(service_instance_id, metric_name, label_set)` 维度自行累加。

3. **用户/实例标识提取**：在 `resourceMetrics[].resource.attributes[]` 里找 `key="env"`，其值即 `[otel].environment`（用户标识）。建议归一为 `service.instance.id` 存储。

4. **鉴权**：拦截器校验请求头 `x-api-key`（与 codex 端 `headers` 配置一致）。

5. **持久化**：由服务端自定（MySQL/PostgreSQL/InfluxDB/Prometheus remote write 等）。metric 建议 TSDB 或带时间戳的表，trace 建议 Jaeger/Tempo 兼容存储以便 Grafana 展示链路。

## 六、关键陷阱清单（实施必读）

1. **statsig 陷阱（最高优先级）**：`metrics_exporter` 默认 `statsig` → 数据发 `https://ab.chatgpt.com`（写死的公共 key），服务端收不到。**必须显式配 `otlp-http`**，留空也不行（fallback 到默认）。
2. **metrics 双重开关**：缺 `--analytics-default-enabled`（3.1）**或** `[analytics].enabled=false` → metric 不导出。
3. **Delta temporality**：不累积会导致 counter 数值无意义（每 60s 重置）。
4. **trace_exporter 不能用 statsig**：statsig endpoint 是 `/v1/metrics` 专用，发 trace 会失败。
5. **debug build statsig 自动失效**；本地调试用本地 Spring Boot 或 `CODEX_ANALYTICS_EVENTS_CAPTURE_FILE`。
6. **时延**：metrics ≤60s/批，trace/log ≤5s/批，强杀进程丢未导出批次。
7. **真实账号仅在 log 信号**：metric/trace 无 `account_id`/`email`，只有 `env`（实例标识）。
8. **skill 显式/隐式 tag 不一致**：隐式带 `invoke_type=implicit`，显式无此 label。

## 七、验证步骤

1. 启动服务端 Spring Boot 应用，确认 `/v1/metrics`、`/v1/traces` 可访问。
2. `uv run codex-demo` 启动 codex-integration。
3. 在 UI 触发一次带 `@skill-name` 的 turn。
4. 服务端侧确认 `/v1/metrics` 收到 `codex.skill.injected`，且 `env="integration-alice"`、`skill="<名字>"`。
5. 服务端侧确认 `/v1/traces` 收到 `session_init` / `app_server.request`(rpc.method=turn/start)。
6. 若查不到 metric：按陷阱清单逐项排查（statsig 是否覆盖、analytics 开关、endpoint 是否可达）。

## 八、实施清单

| # | 位置 | 动作 |
|---|---|---|
| 1 | `main.py:42` | 加 `--analytics-default-enabled` |
| 2 | 仓库根 `config.example.toml` | 新增（3.2 模板）|
| 3 | `docs/telemetry-integration.md` | 本文档 |
| 4 | `docs/telemetry-data-contract.md` | 数据契约参考 |
| 5 | `README.md` | 补"服务端统计对接"章节（endpoint + environment 命名规范）|
| 6 | `AGENTS.md` | 记录 statsig 陷阱 + 验证命令 |

> Spring Boot 服务端代码不在本仓库，由 Java 侧实现；本仓库仅提供 codex 端配置 + 对接文档。
