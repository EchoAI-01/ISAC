# ISAC 插件兼容设计

> 面向 AstrBot、MaiBot 与 ISAC Native SDK 的插件兼容范围、加载流程、权限模型与验收规范。
> 本文档补充 ARCHITECTURE.md 3.8、SPECIFICATION.md 2.6 / 2.7 与 plugins/README.md。

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
| ISAC Native | 存在 `manifest.jsonc` | manifest.entry |
| AstrBot | 存在 `metadata.yaml` / `metadata.yml` 或 Star 子类 | `main.py` / 同名 `.py` |
| MaiBot | 存在 `config.toml` + Plugin 基类 / MaiBot manifest | `plugin.py` |

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
| proactive task | ConversationRuntime.enqueue_proactive_task |
| config.toml | Plugin config |
| capability | Host Capability API |

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

```python
class ISACPlugin:
    async def on_load(self, ctx: PluginContext) -> None: ...
    async def on_unload(self, ctx: PluginContext) -> None: ...
    async def on_message(self, ctx: PluginContext, message: ISACMessage) -> None: ...
    async def provide_tools(self, ctx: PluginContext) -> list[ToolSpec]: ...
    async def provide_commands(self, ctx: PluginContext) -> list[Command]: ...
    async def provide_injectors(self, ctx: PluginContext) -> list[PromptInjector]: ...
```

### 8.2 PluginContext

插件只能通过 PluginContext 访问 Host 能力。

```python
@dataclass
class PluginContext:
    plugin_id: str
    agent_id: str | None
    platform: str | None
    permissions: PermissionSet
    host: HostCapabilityAPI
```

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
| 2026-07-22 | Architect | 新增插件兼容专项设计，补充三格式识别、兼容范围矩阵、权限模型、生命周期与兼容测试标准 |
