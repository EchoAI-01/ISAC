# ISAC 插件兼容设计

> 面向 AstrBot、MaiBot 与 ISAC Native SDK 的插件兼容范围、加载流程、权限模型与验收规范。
> 本文档补充 ARCHITECTURE.md 3.8、SPECIFICATION.md 2.7 / 2.8 与 plugins/README.md。

---

## 目录

- [一、设计目标](#一设计目标)
- [二、插件格式识别](#二插件格式识别)
- [三、兼容范围矩阵](#三兼容范围矩阵)
- [四、加载与生命周期](#四加载与生命周期)
- [五、权限模型](#五权限模型)
- [六、AstrBot 兼容层](#六astrbot-兼容层)
- [七、MaiBot 兼容层](#七maibot-兼容层)
- [八、ISAC Native SDK](#八isac-native-sdk)
- [九、兼容测试](#九兼容测试)

---

## 一、设计目标

ISAC 插件系统同时满足三类需求：

1. **复用存量生态**：尽可能运行 AstrBot 与 MaiBot 的常见插件。
2. **不牺牲安全边界**：兼容插件也必须进入 ISAC 权限、沙箱、启用矩阵和审计体系。
3. **提供原生扩展能力**：Native SDK 支持 Agent Mesh、PromptInjector、Admin Routes 等 ISAC 独有能力。

---

## 二、插件格式识别

插件加载器扫描 `plugins/` 目录时按以下顺序识别：

| 格式 | 识别条件 | 入口 |
|------|----------|------|
| ISAC Native | 存在 `manifest.jsonc` | manifest.entry (默认 `plugin.py`, 找 `ISACPlugin` 子类) |
| AstrBot | 存在 `metadata.yaml` | `plugin.py` (找 `Star` 子类) |
| MaiBot | 存在 `mai_plugin.yaml` | `plugin.py` (找 `MaiBotPlugin` 子类) |

> **实现状态 (2026-10-11)**: 识别优先级为 `manifest.jsonc` > `metadata.yaml` > `mai_plugin.yaml`
> (`plugin/runtime/loader.py::detect_format`, 三者都不匹配抛 ValueError)。MaiBot 识别**不读
> `config.toml`**; AstrBot 入口固定 `plugin.py` (不存在 `metadata.yml`/`main.py`/同名 `.py` 分支)。

```python
class PluginLoader:
    def detect_format(self, path: Path) -> PluginFormat: ...
    async def load(self, path: Path) -> LoadedPlugin: ...
    async def unload(self, plugin_id: str) -> None: ...
    async def reload(self, plugin_id: str) -> None: ...
```

---

## 三、兼容范围矩阵

### 3.1 AstrBot

| 插件能力 | 支持阶段 | ISAC 映射 | 说明 |
|----------|----------|-----------|------|
| Command/Event Handler | P0 | EventBus / CommandRegistry | 常见命令插件优先支持 |
| FunctionTool | P0 | ToolSpec / ToolRegistry | 作为 Agent Tool 暴露 |
| Star 生命周期 | P0 | Plugin lifecycle | initialize/terminate 映射 |
| metadata.yaml | P0 | Plugin metadata | 读取 name/version/author/desc |
| `_conf_schema.json` | P1 | config_schema | 转为 ISAC 配置 Schema |
| Context.send_message | P1 | Channel.send | 受权限控制 |
| Context.get_provider | P1 | ProviderManager | 只返回授权 Provider |
| Platform Adapter 插件 | P2 | ChannelAdapter bridge | 需单独适配 |
| Cron/Task 插件 | P2 | Scheduler / Control Plane | 需权限 |
| Dashboard pages | P3 | Admin Routes | 默认不支持 |
| 深层 astrbot.core import | P3 | Import sandbox mapping | 按需映射 |

### 3.2 MaiBot

| 插件能力 | 支持阶段 | ISAC 映射 | 说明 |
|----------|----------|-----------|------|
| Command | P0 | CommandRegistry | 用户命令 |
| Action | P0 | ToolSpec / AgentHooks | 动作转工具或 Hook |
| Plugin lifecycle | P0 | Plugin lifecycle | on_load/on_unload |
| config.toml | P1 | Plugin config | 支持热更新 |
| Hook | P1 | EventBus / AgentHooks | 按事件类型映射 |
| Proactive task | P1 | ConversationRuntime proactive | 主动聊天任务 |
| Capability | P2 | Host Capability API | 受权限限制 |
| Platform IO Adapter | P2 | ChannelAdapter bridge | 需单独适配 |
| Runner IPC | P3 | Plugin Supervisor | 后续增强隔离 |

### 3.3 ISAC Native

| 能力 | 支持阶段 | 说明 |
|------|----------|------|
| Hooks | P0 | AgentHooks / EventBus |
| Tools | P0 | ToolRegistry |
| Commands | P0 | CommandRegistry |
| Injectors | P1 | SystemPromptBuilder |
| Inter-Agent Hooks | P1 | Agent Mesh |
| Admin Routes | P2 | Control Plane |
| Memory Backend | P3 | 自定义记忆后端 |
| Provider | P3 | 自定义 Provider |
| Router Hook | P3 | 自定义路由 |

---

## 四、加载与生命周期

### 4.1 生命周期

```text
scan
  ↓
detect_format
  ↓
validate_manifest / metadata
  ↓
check_version
  ↓
check_permissions
  ↓
load_module_in_sandbox
  ↓
register hooks/tools/commands/injectors
  ↓
on_load
```

卸载流程：

```text
on_unload
  ↓
unregister hooks/tools/commands/injectors
  ↓
release resources
  ↓
remove module cache
```

### 4.2 错误隔离

1. 单个插件加载失败不影响其他插件。
2. 插件运行时错误记录到插件状态，不影响 Agent 主链路。
3. 插件连续失败达到阈值后熔断。
4. 热重载失败时保留旧版本，除非旧版本已卸载。

---

## 五、权限模型

### 5.1 权限计算

```text
effective_permission =
  manifest_requested
  ∩ global_policy
  ∩ agent_policy
  ∩ channel_policy
  ∩ conversation_policy
```

### 5.2 权限类型

| 权限 | 说明 | 默认 |
|------|------|------|
| `message:read` | 读取消息内容 | 按事件授权 |
| `message:send` | 发送 IM 消息 | 禁用 |
| `memory:read` | 读取记忆 | 禁用 |
| `memory:write` | 写入记忆 | 禁用 |
| `profile:read` | 读取用户画像 | 禁用 |
| `profile:write` | 修改用户画像 | 禁用 |
| `tool:execute` | 调用工具 | 禁用 |
| `agent:ask` | 调用其他 Agent | 禁用 |
| `agent:handoff` | 转交会话 | 禁用 |
| `mcp:call` | 调用 MCP 工具 | 禁用 |
| `network:fetch` | 网络请求 | 禁用 |
| `file:read` | 文件读取 | 禁用 |
| `file:write` | 文件写入 | 禁用 |
| `process:spawn` | 子进程 | 禁用 |
| `control:admin` | 控制面扩展 | 禁用 |

> **实现状态 (2026-10-11)**: §5.1 的五级 `effective_permission` 交集与 `PermissionSet` 类型均
> **未实现 (目标态)** —— 代码中没有按 `message:read`/`memory:read` 等权限位的插件授权与校验;
> 插件实际生效边界为 `EnableMatrix` 启停 (Agent/Channel 级) + 工具级 `ToolPermission`
> (allow/deny/restricted) + §5.4 的原生插件 trust 分级与进程隔离。§5.3 manifest 示例中的
> `permissions`/`network.allowed_domains` 字段当前被解析器忽略 (仅 name/entry/trust/isolated 生效)。

### 5.3 Manifest 示例

```jsonc
{
    "name": "weather",
    "version": "1.0.0",
    "entry": "plugin.py",
    "permissions": [
        "network:fetch",
        "message:send"
    ],
    "network": {
        "allowed_domains": ["api.weather.example"]
    }
}
```

### 5.4 信任分级与隔离默认化 (U6)

**信任分级倒转**: 有 manifest 的原生插件**默认隔离加载** (子进程 PluginIsolationHost,
资源限额 + IPC 超时), 市场/git/url/upload 安装的插件未显式声明 hosted 即进沙箱。

manifest `trust` 字段两档:

| trust | 加载方式 | 条件 |
|-------|---------|------|
| `sandboxed` (缺省) | 子进程隔离 | 无条件, 默认值 |
| `hosted` | 宿主进程内 | **还需**部署配置 `control.plugins.trust_hosted` 清单按目录名显式确认 (运营方显式确认信任); 未确认仍按 sandboxed 隔离 |

旧 `isolated: true` 字段向后兼容 (等价 sandboxed)。`control.plugins.isolated_plugins`
(目录名列表或 `"*"`) 仍可强制隔离任何插件, 优先级最高。

**隔离宿主参数**经 `control.plugins.isolation` 节部署配置接线: `rlimits`
(cpu/nofile/as, POSIX)、`ipc_timeout_seconds`、`max_restart_attempts`。

**兼容层处置决策 (Z3 收敛)**: AstrBot/MaiBot 兼容层插件**无 manifest.jsonc,
当前隔离机制无法真正隔离** —— 其代码依赖宿主进程内的兼容层 import 沙箱与
PluginContext 直接桥接, 搬入子进程需要重构整个 adapt 链路。U6 决策为
**文档化降级承诺** (而非复活 manifest 机制接入隔离):

1. 兼容层插件继续在宿主进程内加载, 启动日志显式告警信任责任在部署方;
2. 部署方可用 `isolated_plugins` 强制要求隔离兼容层插件 —— 此时**清晰报错拒绝**,
   不静默退回不受保护加载 (避免"以为隔离了其实没有");
3. 需要隔离治理的第三方代码建议封装为原生插件 (manifest + ISACPlugin) 或经
   MCP Server 外置;
4. 兼容层隔离迁移 (adapt 进子进程) 保留为架构债 (C7), 待后续节点评估。

---

## 六、AstrBot 兼容层

### 6.1 组件映射

| AstrBot | ISAC |
|---------|------|
| Star | Compatibility Star wrapper |
| Context | Host Capability Context |
| EventType.OnMessageEvent | EventBus.ON_MESSAGE |
| OnLLMRequestEvent | AgentHooks.PRE_LLM |
| FunctionTool | ToolSpec |
| metadata.yaml | PluginMetadata |
| `_conf_schema.json` | config_schema |

### 6.2 Import Sandbox

AstrBot 兼容层通过 `sys.meta_path` 拦截常见 `astrbot.*` import。

规则：

1. 只映射兼容层声明支持的模块。
2. 未支持模块抛出明确 ImportError。
3. 不允许插件直接访问 ISAC 内部未授权模块。
4. 映射表必须集中维护并覆盖测试。

### 6.3 不支持能力

第一阶段不支持：

- AstrBot Dashboard 页面直接迁移；
- 依赖 AstrBot 内部 DB 结构的插件；
- 依赖具体 Platform 实现私有方法的插件；
- 修改 AstrBot 全局配置的插件。

---

## 七、MaiBot 兼容层

### 7.1 组件映射

| MaiBot | ISAC |
|--------|------|
| Plugin | Compatibility Plugin wrapper |
| Action | ToolSpec / AgentHook |
| Command | CommandRegistry |
| on_message hook | EventBus.ON_MESSAGE |
| proactive task | ConversationRuntime.enqueue_proactive_task (**未实现目标态**: 该方法不存在, 实际队列入口为 `ProactiveTaskQueue.enqueue(tasks)` / `ProactiveScheduler`) |
| config.toml | Plugin config (**未实现目标态**: 当前 loader 以空 dict 构造 `MaiBotPlugin`, 不解析 config.toml) |
| capability | Host Capability API (**未实现目标态**) |

### 7.2 版本锁定

MaiBot 兼容层必须声明兼容的 MaiBot 插件 SDK 版本范围。

```jsonc
{
    "compatibility": {
        "maibot_plugin_sdk": ">=0.1,<0.2"
    }
}
```

版本变化只允许修改适配器，不允许把 MaiBot SDK 细节泄露到 ISAC 核心层。

### 7.3 主动任务映射

> **实现状态 (2026-10-11)**: 以下映射**未实现 (目标态)** —— `ConversationRuntime` 无
> `enqueue_proactive_task` 方法; 生产主动任务入口为 `ProactiveTaskQueue.enqueue(task)` /
> `ProactiveScheduler` (`runtime/conversation/`), MaiBot 兼容层当前不产出主动任务。

MaiBot 插件主动任务映射到：

```python
ConversationRuntime.enqueue_proactive_task(
    plugin_id=plugin_id,
    intent=intent,
    reason=reason,
    metadata=metadata,
)
```

---

## 八、ISAC Native SDK

### 8.1 插件基类

实际基类 (`isac/plugin/native/plugin.py`, Native SDK v2)：

```python
class ISACPlugin(ABC):
    """ISAC 原生插件基类。"""

    @property
    def name(self) -> str: ...

    async def on_load(self, context: PluginContext) -> None:
        """插件加载时调用: 在此经 context.register_* 注册能力。"""

    async def on_unload(self) -> None:
        """插件卸载时调用: 清理资源。"""
```

能力注册全部发生在 `on_load` 内，经 `PluginContext` 的注册方法完成：
`register_tool` / `register_command` / `register_injector` / `register_inter_agent_hook` /
`register_router_hook` (admin route 预留)。

```python
# 以下为目标态 (未实现), 保留作接口设计对照
class ISACPlugin:
    async def on_message(self, ctx: PluginContext, message: ISACMessage) -> None: ...
    async def provide_tools(self, ctx: PluginContext) -> list[ToolSpec]: ...
    async def provide_commands(self, ctx: PluginContext) -> list[Command]: ...
    async def provide_injectors(self, ctx: PluginContext) -> list[PromptInjector]: ...
```

> **实现状态 (2026-10-11)**: `provide_tools`/`provide_commands`/`provide_injectors`
> 三个 hook 式接口 **不存在于代码** (未实现目标态) —— 注册统一走 `on_load` 内的
> `register_*` 方法。

### 8.2 PluginContext

插件只能通过 PluginContext 访问 Host 能力。实际契约 (`plugin/native/plugin.py`)：

```python
@dataclass
class PluginContext:
    agent_hooks: AgentHooks
    event_bus: EventBus
    router: MessageRouter | None = None
    services: dict[str, Any] = field(default_factory=dict)
    # 内部注入的 Registry 引用 (register_* 方法使用)
    _tools: ToolRegistry | None = None
    _commands: CommandRegistry | None = None
    _prompt_builder: SystemPromptBuilder | None = None
    _inter_agent_bus: InterAgentBus | None = None
```

> **实现状态 (2026-10-11)**: 旧版的 `plugin_id`/`agent_id`/`platform`/`permissions`/`host`
> 字段 **不存在** (未实现目标态) —— `PermissionSet` 与 `HostCapabilityAPI` 均无对应类型;
> 插件经上述 Registry 引用与 `register_*` 方法访问能力，而非 Host 能力 API。

禁止插件直接获取：

- 原始数据库连接；
- AgentManager 实例；
- ChannelAdapter 实例；
- 未过滤的全局配置；
- 未授权环境变量。

---

## 九、兼容测试

### 9.1 测试插件集合

每个兼容层至少维护：

| 类型 | 数量 | 说明 |
|------|------|------|
| 简单命令插件 | 2 | 无外部依赖 |
| 工具插件 | 2 | 暴露 ToolSpec |
| 事件插件 | 1 | 监听消息事件 |
| 配置插件 | 1 | 验证配置 Schema |
| 错误插件 | 1 | 验证错误隔离 |

### 9.2 验收标准

| 能力 | 验收 |
|------|------|
| 格式识别 | loader 可区分三类插件 |
| 生命周期 | load/unload/reload 不泄漏 handler/tool |
| 权限 | 未授权插件无法发送消息/读记忆/访问文件 |
| AstrBot P0 | 简单 Star 命令和 FunctionTool 可运行 |
| MaiBot P0 | Command 和 Action 可运行 |
| Native P0 | Hooks/Tools/Commands 可注册 |
| 错误隔离 | 单插件异常不影响主链路 |
| 启用矩阵 | Agent/Channel 禁用后插件不生效 |

---

## 十、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-10-11 | Architect | 按代码实况勘误: §2 格式识别表改为 manifest.jsonc/metadata.yaml/mai_plugin.yaml (MaiBot 不读 config.toml, AstrBot 入口固定 plugin.py); §5.2 权限模型与 §7.1/§7.3 config.toml·proactive·capability 映射标注 "未实现目标态"; §8.1/§8.2 SDK 契约改为实际 `on_load` + `register_*` + PluginContext 注册表字段 |
| 2026-08-17 | Architect | U6 信任分级倒转: 新增 §5.4 (原生插件默认隔离、trust=hosted 需 trust_hosted 确认、隔离宿主参数部署接线、兼容层降级承诺处置决策) |
| 2026-07-22 | Architect | 新增插件兼容专项设计，补充三格式识别、兼容范围矩阵、权限模型、生命周期与兼容测试标准 |
