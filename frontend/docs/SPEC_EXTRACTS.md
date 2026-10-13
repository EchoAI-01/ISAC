# 规范摘录 (页面实现所需的最小集合)

> 本文件是 `../docs/CONTROL_PLANE_SPEC.md` 与 `../docs/DEVELOPMENT_PLAN.md` 的**定向摘录**,
> 供页面实现者直接引用, 避免翻阅大文档。**不要去读** `docs/ARCHITECTURE.md` (101KB)、
> `docs/DEVELOPMENT_PLAN.md` (272KB)、`docs/PROGRESS.md` (124KB)、`docs/SPECIFICATION.md` (50KB)
> —— 你需要的内容都在这里 + `PAGE_CONTRACT.md` 里。

---

## 一、§8.1 信息架构 (十域的核心内容与主要操作)

| 页面 | 核心内容 | 主要操作 |
|------|----------|----------|
| Dashboard | Agent/Channel/Provider 健康、消息与任务、Token/成本、错误与告警趋势 | 时间范围、Agent/Provider 筛选、跳转详情 |
| Agents | 状态、人格、门控、模型能力、工具/插件/MCP、记忆命名空间 | 创建、复制、启停、编辑、导入导出 |
| Channels & Routing | 连接状态、绑定、默认 Agent、触发词、primary/observer/candidate | 测试连接、绑定、路由预演、保存规则 |
| Providers & Models | Provider 健康、模型能力、模态、限制、成本/延迟层级 | 新增/编辑、替换密钥、健康测试、启停 |
| Usage & Cost | Token、缓存、推理 Token、音视频时长、图片/视频数量、估算成本 | 聚合、明细、趋势、导出、预算告警 |
| Extensions | 插件、MCP Server、工具、命令及 Agent × Channel 启用矩阵 | 安装/加载、启停、权限编辑、连通测试 |
| Memory | 命名空间、Episode、人物画像、行话、索引健康和容量 | 查询、查看来源、纠正、删除、重建索引 |
| Sessions & Tasks | 活跃会话、Agent 状态、工具链、`ProgressEvent`、中断与错误 | 查看时间线、中断任务、重试安全操作 |
| Logs & Audit | 结构化日志、告警、审计、Webhook 发送结果 | 检索、关联 trace、导出、确认告警 |
| System | 全局配置、存储、备份、版本、运行环境 | 校验、差异预览、备份、恢复、重启提示 |

> 表格里"主要操作"若后端无对应端点 (如 Channel 绑定、导入导出、预算告警、备份/恢复、
> 重建索引), **不要伪造按钮**: 用 `<Callout tone="info">` 说明该能力目前仅 MCP 工具提供
> 或后端未实现, 并给出对应配置项/工具名。

## 二、§8.2 配置编辑事务 (7 条规则, 逐条落实)

```text
GET resource + schema + revision
  → 表单编辑（敏感字段只显示"已配置"）
  → POST /config/validate
  → POST /config/diff
  → 用户确认高影响变更
  → PATCH resource (If-Match: revision)
  → 持久化 + reload/restart plan + AuditEvent
```

1. UI 表单由服务端 JSON Schema 驱动, 复杂资源允许专用编辑器; **前端不能复制一套独立校验规则作为唯一真相**。
2. 所有写操作显示影响范围和结构化 diff; 删除、停机、解绑、清空记忆、替换 Provider、批量权限修改**必须二次确认**。
3. 使用 `revision` / `ETag` 做乐观并发; 版本冲突返回 `409 CONFIG_CONFLICT`, UI 展示服务器版本与本地变更, **不静默覆盖**。
4. API Key、Bot Token、Webhook Secret 只允许设置/替换/清除, **永不从 API 回显**; 浏览器不得把管理 Token 或 Provider 密钥写入 `localStorage`。
5. 同源 WebUI 用 `POST /auth/session` 换 `HttpOnly + SameSite` 会话 Cookie; 所有写请求校验 CSRF Token; 纯 API 客户端继续用 Bearer。
6. 修改结果明确区分 `applied`、`reload_required`、`restart_required`, **禁止假装热更新成功**。
7. 批量操作必须逐项返回结果并产生审计事件; 失败项可重试, 已成功项不可重复执行。

## 三、§8.3 实时状态 (+ 后端实现现状)

目录事件: `agent.status_changed`、`channel.status_changed`、`provider.health_changed`、
`task.progress`、`model.usage_recorded`（默认聚合刷新, 不逐 Token 推送）、`alert.triggered`、
`audit.created`。客户端断线后用 `Last-Event-ID` 恢复; 高频指标采用 5–15 秒聚合快照;
日志按需订阅并设置**速率和行数上限**; 实时通道只发送当前 Token scope 可读的资源。

**实现现状 (必须在 UI 上说明, 否则用户会误判故障)**:
- SSE `/events/stream` 桥接 EventBus **全部**事件, 事件名取 payload 的 `event_type`;
  未登记者落 `unknown` 兜底名, **仅 `"*"` 通配 scope 可见** (fail-closed)。
- 生产事件 (`POST_MESSAGE` 的 ISACMessage / `ON_START` 的 config dict) 都不带 `event_type`,
  实际即以 `unknown` 发出 → 窄 scope token 常常一条也看不到, 这是预期行为。
- 上列目录事件多数**尚无生产者**; 当前仅 Webhook 侧 `message.responded` / `message.sent` 已接线。
- `channel.status_changed` 是唯一显式公开 (无需 scope) 的事件类型。
- `/logs/tail` 在 `tokens[]` 模式下要求 `"*"` 通配 scope (系统日志含聊天原文/堆栈/审计明细)。
- SSE 连接数有上限 (events 100 / logs 50), 超限返回 `429 TOO_MANY_CONNECTIONS`。

## 四、§8.4 SubAgent 任务与日志 (隐私边界)

Sessions & Tasks 页应展示: 父 Agent、task_id、状态、阶段、耗时、预算、Token、工具次数、
错误、证据和时间线, 并支持取消; 默认折叠参数与结果摘要, **敏感字段永不渲染**。

接口不得返回模型原始 reasoning、密钥、Cookie、Authorization Header、完整文件内容或未清洗
工具结果。日志默认返回事件摘要和 `evidence_ref`。取消是**幂等请求**, 任务进入终态后返回原
终态, **不能伪造成功取消**。scope: `subagent:run` / `subagent:read` / `subagent:cancel` /
`subagent:log:read`。

## 五、§8.5 前端工程与体验约束 (验收直接对照这几条)

- 路由化 SPA + 可复用设计系统; 服务端状态集中缓存; **筛选/分页写入 URL**; 避免单个 `app.js` 持续膨胀。
- 桌面优先但支持 **320 / 768 / 1024 / 1440px**; 复杂表格在小屏切换为摘要列表, 不强制横向挤压。
- 所有页面具备 **loading、empty、error、stale、permission-denied** 状态; 长任务显示 ProgressEvent 时间线。
- 满足 **WCAG 2.1 AA**: 语义结构、键盘导航、焦点管理、对比度、非颜色状态提示、reduced-motion。
- **图表必须同时提供表格/文本摘要**; 成本与 Token 明确单位、时区、价格版本和"估算"标识。
- 前端测试包括组件、API contract、权限矩阵、配置冲突和浏览器端黄金路径; **不能只检查静态文件包含字符串**。

## 六、§九 验收标准 (与前端相关的行)

| 能力 | 验收 |
|------|------|
| WebUI IA | 十个管理/观测领域均有独立入口, 权限不足显示明确状态 |
| Config UX | Schema 校验、diff、确认、ETag 冲突、审计和 reload/restart 结果完整 |
| Web Auth | 管理 Token 不持久化到 localStorage; 生产使用 HttpOnly/Secure/SameSite Cookie + CSRF |
| Realtime | SSE/WebSocket 可断线恢复、限流, 并按 scope 过滤资源 |
| Accessibility | 键盘、焦点、语义、对比度和图表文本替代满足 WCAG 2.1 AA |
| Usage | 可按 Provider/模型/Agent/模态查询实际用量; 重试和回退不漏记 |
| Cost | 价格快照可追溯; **未知价格不伪造成本** |
| Privacy | 用量接口和事件不泄露 Prompt、响应、工具参数与凭据 |
| Model Catalog | 可列出模型模态、operation、限制和健康状态 |
| SubAgent | 可创建、查询、取消隔离子任务; 可按 task_id 读取脱敏日志与证据且无需重跑 |
| SubAgent Privacy | 日志不含 reasoning、凭据、完整敏感输入或未清洗工具结果 |

## 七、F1–F4 验收 (DEVELOPMENT_PLAN §四 FE)

- **F1** 前端项目初始化 + 登录/setup 向导: 独立项目/目录; 消费 `/api/v1` + SSE;
  登录页 + 首登强制设密码向导页; 与后端 T3-backend 联调通过。
- **F2** 十域页面迁移: Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/
  Logs/System 十域在前端项目重实现; 配置编辑事务接真实 API (Schema 校验 + Diff + 二次确认 +
  乐观锁, 消费 `GET /agents/{id}/config` 的真实 revision); 同步修复 Q5 遗留假数据;
  完成后移除后端 `control/webui/` 静态托管。
- **F3** 实时体验: 实时日志台 (`/logs/tail` SSE) + 事件流页面化 (`/events/stream`)。
- **F4** 插件市场 UI: 插件市场列表 + 一键安装 + 热重载操作 + 失败插件可重试。

## 八、后端已知的"文档 vs 实现"差异 (页面必须如实反映, 不要按文档臆造 UI)

| 项 | 状态 |
|----|------|
| `/channels*` REST 端点 | **未实现**; Channel 摘要只在 `/health` 里; 绑定仅 MCP 工具 `channel_bind_agent` / `channel_unbind_agent` |
| Webhook HMAC 签名 (§5.3) | **未实现**; 当前仅 JSON POST 推送, 接收方无法校验来源 |
| Webhook 事件目录 | 仅 `message.responded` / `message.sent` 已接线, 其余为预留 |
| MCP 工具统一包络 (`success`/`trace_id`) | 未实现 (与本前端无关, 但别在 UI 里承诺) |
| `/subagent-runs/{id}/artifacts` | **未实现**; 制品经 `/artifacts*` 访问 |
| `message:send` scope | 规划中未实现 |
| 创建 Agent 的能力字段 | 被后端**丢弃** (受限默认模板), 需创建后 PATCH 授予 |
| `/plugins/failed` 的 `failures` | 是**对象** `name → 错误信息`, 不是数组; 进程内不持久化 |
| `/usage/models/*`、`/subagent-runs`、`/tenants`、`/workflows`、`/identity/conflicts` | 返回**数组** (不是 `{key: []}`) |
| `estimated_cost` / `estimated_cost_sum` | **字符串** (Decimal) 或 null; 组内价格全未知时为 null, 不得当 0 |
| 版本号 | `/health` **不含**版本号字段; 不许在前端硬编码版本 |
| `identity.conflicts[].candidates` | 是 **JSON 字符串**, 需前端解析 |
