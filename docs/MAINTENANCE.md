# ISAC 维护与运维手册 (MAINTENANCE)

> 面向**部署后运维**的操作手册:健康检查、日志排查树、常见故障、备份恢复、升级迁移。
> 首次部署见 [deployment.md](./deployment.md);配置详解见 [usage.md](./usage.md);日志分级与字段见 [LOGGING.md](./LOGGING.md)。
>
> 最近更新: 2026-07-26

## 一、日常巡检

| 检查项 | 方法 | 正常表现 |
|--------|------|---------|
| 进程存活 | `GET /health` | `{"status":"ok"}` (200,无需认证) |
| 指标快照 | `GET /metrics` (Prometheus 文本) 或 `GET /api/v1/metrics` (JSON,需认证) | 见 §二指标清单 |
| 优雅关闭 | `kill -TERM <pid>` 或 Ctrl-C | 日志出现关闭序列,无 pending task / resource warning |
| 审计流水 | `GET /api/v1/audit?limit=100` (需认证) | 控制面写操作有记录 |
| 磁盘占用 | `du -sh data/` | artifacts/memory 增长可控 (见 §五) |

启动方式与信号: `python -m isac` 常驻,支持 SIGINT/SIGTERM 优雅关闭 (ApplicationRuntime 统一 start/close 所有后台任务)。

## 二、关键指标 (metrics)

`GET /metrics` 暴露 Prometheus 文本;`GET /api/v1/metrics` 暴露 JSON 快照。核心指标:

| 指标 | 含义 | 关注点 |
|------|------|--------|
| `isac_messages_received_total` | 收到消息数 | 断崖式归零 → Channel 断连 |
| `isac_messages_processed_total` | 成功处理数 | 与 received 差距大 → 门控/异常 |
| `isac_messages_dropped_total` | 被门控丢弃数 | 突增 → 门控阈值或频控异常 |
| `isac_messages_failed_total` | 处理失败数 | 持续 >0 → 看 error 日志 |
| `isac_agents_active` | 运行中 Agent 数 | 与预期不符 → 恢复失败 |
| `isac_llm_calls_total` / `isac_llm_errors_total` | LLM 调用/错误 | error 占比高 → Provider 问题 |
| `isac_llm_latency_seconds` | LLM 延迟 | P99 飙升 → 上游或网络 |
| `isac_llm_tokens_total` | Token 消耗 | 异常增长 → 成本告警 |
| `isac_tool_calls_total` / `isac_tool_errors_total` | 工具调用/错误 | error 突增 → 工具或权限 |
| `isac_memory_searches_total` / `isac_memory_store_errors_total` | 记忆检索/写入错误 | store_errors >0 → 存储降级 |
| `isac_memory_acl_rejections_total` | 记忆 ACL 拒绝 | 突增 → 跨用户越权尝试 |

`AlertManager` (`observability/alerting.py`) 会周期比对这些指标触发告警;阈值在配置的 `observability.alerting` 段。

## 三、日志排查树

ISAC 日志已做**框架级增强**:`trace_id` / `session_id` / `agent_id` 经 `contextvars` 贯穿一次消息处理的全链路 (路由→门控→Loop→工具→记忆→回复),无需逐处手传。排查任一问题的通用第一步:

```bash
# 1. 从一条异常回复/报错里拿到 trace_id,串起整条链路
grep '"trace_id": "<trace_id>"' <日志文件> | sort

# 2. 若只有 session_id,先聚合该会话
grep '"session_id": "<session_id>"' <日志文件>
```

**开启 debug**: 默认 `INFO`。要看"每步做了什么"(即便无报错),把对应模块调到 `debug`(见 [LOGGING.md](./LOGGING.md) 的 `logging.per_module`),而非全局开 debug(噪音大)。

### 排查树 (症状 → 定位)

```
消息发出去了,Bot 没反应
├── isac_messages_received_total 有涨吗?
│   ├── 没涨 → Channel 未收到 → 查 Channel 适配器连接日志 (onebot/telegram/discord)
│   └── 涨了 → 进入下一层
├── isac_messages_dropped_total 涨了吗?
│   └── 涨了 → 被门控丢弃 → 开 gating 模块 debug,看评分与决策日志 (kind != TRIGGER 的原因)
├── isac_messages_failed_total 涨了吗?
│   └── 涨了 → 处理异常 → 用 trace_id 串链路,定位抛错的环节 (Loop/工具/记忆)
└── 都正常但无回复 → 看 agent/loop.py 的迭代日志:是否 wait/预算耗尽/工具循环未收敛

回复很慢
├── isac_llm_latency_seconds P99 高 → Provider/网络 → 看 provider/manager.py 重试与回退日志
├── isac_tool_calls_total 多 → 工具链路长 → 看慢工具 (D9 tool_started 事件,阈值 2s)
└── isac_memory_search_latency_seconds 高 → 记忆检索慢 → 看 memory/pipeline.py 各路命中数

回复内容异常 / 越权
├── 记忆串了 → isac_memory_acl_rejections_total + 查 pipeline ACL 日志 (namespace/agent_id)
├── 工具越权 → 查 PRE_TOOL 权限拦截日志 (被权限策略阻止)
└── 多 Agent 误触发 → 查 router 匹配日志 (has_at/has_mention/trigger_words)

LLM 报错
├── 429 → RateLimitError → 看 ProviderManager 重试/回退是否生效
├── 5xx / 超时 → retriable → 看 fallback 是否切换到备用 Provider
└── 4xx 非法响应 → non-retriable → 检查模型名/请求体/Key

启动后 Agent 数不对
├── data/agents/*/config.jsonc 是否 enabled=true
├── 看 load_persisted_agents 恢复报告 (running/stopped/failed:<error>)
└── 单个 Agent 恢复失败不阻塞其他,错误已记日志 → grep "Agent 恢复失败"
```

**脱敏红线** (排查时注意,日志本身已遵守): 不打印密钥、完整工具参数、未清洗的模型输出、原始 reasoning。若在日志里看到疑似密钥,立即视为事故并轮换。

## 四、常见故障与处置

| 现象 | 可能原因 | 处置 |
|------|---------|------|
| `/health` 不通 | 进程挂了 / 端口占用 | 看启动日志;确认 `control.port` 未被占用 |
| 启动即退出 | 配置非法 / Provider 初始化失败 | 看启动回滚日志;校验 `data/config.jsonc` |
| Bot 不回复 | Channel 断连 / 门控丢弃 | 按 §三排查树逐层 |
| 回复慢 | LLM 延迟 / 工具慢 | 看 latency 指标 + 慢工具事件 |
| 记忆检索为空 | memory 未启用 / 索引未预热 | 确认 `memory.enabled`;BM25 预热在 create 时执行 (K3) |
| 用量无数据 | J1 未启用 | 设 `observability.usage.enabled=true`(否则不建 usage.db,零计量) |
| SubAgent 卡住 | 子任务超时 / 取消未传播 | 看 SubAgent Journal;重启后 running/queued 会被标为 cancelled (不续跑) |
| 控制面 401 | 缺 Bearer Token | 配 `control.api_token` 或用显式开发模式 |

## 五、备份与恢复

**需要备份的持久化数据** (均在 `data/` 下,按需存在):

| 路径 | 内容 | 何时存在 |
|------|------|---------|
| `data/config.jsonc` | 全局配置 | 总是 |
| `data/agents/*/config.jsonc` | 各 Agent 配置 (含 revision) | 有 Agent 时 |
| `data/routing*.jsonc` | 路由规则 / InterAgentLink | 配置路由时 |
| `data/memory/{metadata,vectors,graph}.db` | 记忆 (SQLite) | `memory.enabled` 时 |
| `data/usage/usage.db` | 模型用量 (SQLite) | `observability.usage.enabled` 时 |
| `data/artifacts/` + `meta.db` | 多模态制品 + 元数据 (有 TTL) | 生成过制品时 |
| SubAgent Journal (SQLite) | 子任务事件日志 | 用过 delegate_task 时 |

**备份建议**:

- SQLite 文件热备份用 `sqlite3 <db> ".backup <dst>"`(而非直接 cp,避免写入中途拷贝损坏)。
- 停机备份最稳:先 `kill -TERM` 优雅关闭 (提交并释放连接),再整目录打包 `data/`。
- 配置文件写入用原子替换 (tmp+fsync+os.replace),但备份仍以停机时刻为一致点最佳。

**恢复**: 还原 `data/` 后启动;启动时自动执行 SQLite schema init/migration (K3),并从 `data/agents/*/config.jsonc` 恢复 enabled=true 的 Agent (K4)。SubAgent 的 running/queued 任务恢复时标为 cancelled,不续跑旧进度。

**制品清理**: ArtifactStore 有 TTL (默认 7 天) + `sweep_expired()` 周期扫描;若磁盘紧张可缩短 TTL 或手动触发清理。

## 六、升级与迁移

1. **升级前**: 停机 + 备份 `data/` (见 §五)。
2. **SQLite schema**: 启动时自动 migration (`_ensure_column` 探测缺列并 `ALTER TABLE`),向后兼容旧库;无需手动跑迁移脚本。
3. **配置 schema**: 若新版本增配置项,对照 `data/config.sample.jsonc` 补齐;未知项按默认值处理。
4. **契约变更**: 若升级涉及 `core/` 契约或 ABC 签名变更,先读 [SPECIFICATION.md](./SPECIFICATION.md) 与 CHANGELOG(发版时重建)。
5. **验证**: 升级后跑一遍 §一日常巡检;确认 `isac_agents_active` 与预期一致、`/health` 正常。
6. **回滚**: 保留上一版本制品与 `data/` 备份;回滚 = 换回旧版本 + 还原备份 (注意新版本若已迁移过 schema,回滚需用迁移前备份)。

## 七、安全运维要点

- **密钥**: 用 SecretStore (AES-256-GCM);WebUI 密钥只可替换不可回显;日志/审计不落明文密钥。
  - **R5 接入** (2026-08-16): 配置中 `llm.api_key` (含 `llm.multimodal[*].api_key`) 可填 `secret:<key>` 引用 SecretStore 加密存储。
  - 步骤: ①生成 32 字节密钥 `python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"` → ②`export ISAC_SECRET_KEY=<上面输出>` → ③`isac secret set openai_api_key` (getpass 不回显输入明文) → ④配置 `llm.api_key: "secret:openai_api_key"`。
  - env `ISAC_LLM_API_KEY` 仍最高优先级 (直接覆盖 `llm.api_key`, 非 `secret:` 前缀)。未配 `ISAC_SECRET_KEY` 时 `secret:` 前缀值原样回退 + warning (走原明文路径向后兼容, 不静默降级)。
  - 密钥文件 `data/.secrets.enc` (加密 JSON), 备份时连同 `data/` 一并备份, 但**务必与 `ISAC_SECRET_KEY` env 分离存储** (env 在运维密钥管理, 不入 `data/` 备份)。
- **控制面**: 空 Token 仅限显式开发模式;生产必须配 Token;审计/JSON 指标端点需认证。
- **SSRF**: Webhook 与远程媒体下载有 SSRF 防护;新增出站请求务必走既有校验。
- **资源上限**: Bash/File/MCP 有字节/时间/进程/路径/pending 上限;Session/Lock/队列有 TTL/LRU。改配置时勿无限放大。
- **插件**: 当前插件是**兼容层,非安全沙箱**(进程内)。不要加载不可信插件;进程级隔离见 [ROADMAP.md](./ROADMAP.md) O2。

## 八、相关文档

- 部署: [deployment.md](./deployment.md)
- 配置与使用: [usage.md](./usage.md)
- 日志分级与字段: [LOGGING.md](./LOGGING.md)
- API 端点: [api.md](./api.md)
- 控制面自动化: [control_automation.md](./control_automation.md)
- 架构与安全边界: [ARCHITECTURE.md](./ARCHITECTURE.md) / [SPECIFICATION.md](./SPECIFICATION.md) §5
