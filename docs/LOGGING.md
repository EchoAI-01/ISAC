# ISAC 日志与可观测性手册

> 目标:即便没有报错,也能通过 debug 日志了解"系统这一步到底做了什么";出问题时能按一次消息处理串联、快速定位到具体环节。
> 实现见 `isac/utils/logger.py`(分级/按模块级别)与 `isac/utils/logging_context.py`(trace 贯穿)。

---

## 一、总览

- 日志库:`structlog`(不可用时自动降级为标准库 `logging`,保证可导入)。
- 输出格式:`console`(开发,彩色)或 `json`(生产,ELK/Loki 采集)。
- 关联字段:`trace_id` / `session_id` / `agent_id` 经 `contextvars` **自动贯穿**一次消息处理,无需在每个日志调用处手传。
- 分级:全局级别 + 可选按模块前缀单独设级。

---

## 二、日志级别约定

对齐 `DEVELOP.md` §六,四个级别各司其职:

| 级别 | 记什么 | 示例 |
|------|--------|------|
| `debug` | 每一步操作的事实,无异常也记录。用于"了解都做了什么" | Agent Loop 迭代、LLM 响应(工具数/token)、执行工具(仅工具名)、门控评分、路由匹配、记忆各路命中数 |
| `info` | 关键状态变更与里程碑 | 消息到达、Agent 创建/启停、配置热更新、模型用量事件 |
| `warning` | 容错降级、可恢复异常 | 记忆检索失败降级、注入器超时、单插件加载失败、取消宽限期超时 |
| `error` | 需要关注的严重故障 | LLM 调用失败、数据库错误、Hook 执行异常 |

**默认级别 `info`**:生产环境 debug 不输出,零性能开销。排查时临时调到 `debug`。

---

## 三、配置

`data/config.jsonc`:

```jsonc
{
  "logging": {
    "level": "info",           // debug | info | warning | error
    "format": "console",       // console | json
    "per_module": {            // 可选:只放开个别链路的 debug
      "isac.router": "debug",
      "isac.gating": "debug"
    }
  }
}
```

环境变量覆盖:

- `ISAC_DEBUG=true` —— 等价全局 `level=debug`(优先级最高)。
- `ISAC_LOG_LEVEL=warning` —— 覆盖全局级别。

优先级:`debug=true` > `log_level` / `logging.level` > 默认 `info`。

---

## 四、trace 贯穿(核心)

`runtime/manager.py::handle_message` 在处理入口绑定关联字段:

```python
from isac.utils.logging_context import bind_log_context

with bind_log_context(trace_id=uuid4().hex, session_id=sid, agent_id=aid):
    ...  # 期间路由→门控→Loop→工具→记忆→回复 的每一条日志都自动带这三个字段
```

- 绑定基于 `structlog.contextvars`,`logger.py` 处理器链已装配 `merge_contextvars`。
- 嵌套安全:内层退出恢复外层值;`None` 字段被忽略。
- 旁路容错:绑定/清理失败**绝不冒泡**到主链路,日志问题不会中断消息处理。

在自己的新链路里复用同一模式即可让日志自动带上关联字段。

---

## 五、按模块分级

`per_module` 按**最长前缀**匹配。例如:

```jsonc
"per_module": { "isac": "error", "isac.router": "debug" }
```

- `isac.router.*` 命中更长前缀 → 输出 debug 及以上。
- `isac.memory.*` 命中 `isac` → 只输出 error。

未配置 `per_module` 时走纯全局级别,**无额外开销**(不进过滤 processor);配置后 `get_logger(name)` 会把模块名绑定进事件供过滤使用。

---

## 六、结构化字段与脱敏红线

- 用结构化 kv,不要把变量拼进消息串:`logger.debug("执行工具", tool=name)`,不要 `logger.debug(f"执行 {name}")`。
- **脱敏红线**(debug 也不能违反):禁止记录 API Key / Token / Authorization / Cookie、原始工具参数(`arguments`)、完整文件路径、未清洗的工具结果或外部内容、模型原始 reasoning。工具日志只记工具名。

---

## 七、排查树

```
现象 → 拿到一次处理的 trace_id(任意一条相关日志里都有)
  │
  ├─ 消息没被回复?
  │   ├─ 有 "消息进入 Agent 处理" 吗?无 → 路由未命中/Agent 未运行(看 router DROP 日志)
  │   ├─ 有 "门控评分" 吗?score < threshold → 门控 WAIT(正常不回复)
  │   └─ 有 "Agent Loop 迭代开始" 吗?无 → 门控未 TRIGGER
  │
  ├─ 回复内容异常?
  │   ├─ 看 "LLM 响应"(tool_calls/content_len/total_tokens)判断是否走了工具
  │   └─ 看 "执行工具" 序列 + 各工具 warning/error
  │
  ├─ 记忆没召回?
  │   └─ 看 memory pipeline 的检索命中数 debug + EmbeddingManager 降级 warning
  │
  └─ 用 trace_id 过滤全部日志(json 格式下 `grep '"trace_id":"xxx"'`)
      即可看到这一次处理从进入到回复的完整操作序列。
```

生产建议:`format=json` + 采集到 ELK/Loki,按 `trace_id` 聚合即可还原单次处理全链路;`session_id`/`agent_id` 便于按会话或 Agent 维度聚合。
