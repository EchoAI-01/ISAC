# ISAC 插件开发指南

ISAC 支持三种插件格式:

| 格式 | 入口特征 | 优势 |
|------|---------|------|
| ISAC 原生 (Native SDK v2) | `manifest.jsonc` | 能力最强: Hooks/Injectors/Tools/Commands/互联钩子/Admin Routes |
| AstrBot 兼容 | `metadata.yaml` | 直接复用 AstrBot 现有插件生态 |
| MaiBot 兼容 | `mai_plugin.yaml` | 复用 MaiBot 插件生态 |

---

## 1. ISAC 原生插件 (推荐)

### 1.1 目录结构

```
plugins/my_plugin/
├── manifest.jsonc       # 插件清单 (SPECIFICATION.md 2.7)
└── plugin.py            # 入口, 含一个 ISACPlugin 子类
```

### 1.2 manifest.jsonc

```jsonc
{
    "name": "my_plugin",
    "version": "1.0.0",
    "description": "示例插件",
    "author": "your_name",
    "trust": "sandboxed",           // U6: sandboxed (默认, 子进程隔离) | hosted (宿主进程, 需部署方确认)
    "isac_version": ">=1.0.0",      // 兼容的 ISAC 版本 (PEP 440)
    "entry": "plugin.py",          // 入口文件 (默认 plugin.py)
    "hooks": ["pre_llm", "post_tool"],
    "tools": ["my_tool"],
    "injectors": ["my_injector"],
    "commands": ["my_command"],
    "inter_agent_hooks": ["on_inter_agent_message"],
    "admin_routes": ["/my_plugin/status"],  // 预留: Admin API 扩展
    "permissions": [
        "filesystem:read:data/",
        "network:https"
    ],
    "config_schema": {              // 配置 Schema (自动生成配置界面)
        "type": "object",
        "properties": {
            "api_key": {"type": "string", "description": "API Key"}
        }
    }
}
```

### 1.3 plugin.py

```python
from isac.plugin.native.api import (
    ISACPlugin, PluginContext, Tool, ToolContext, ToolResult,
    Command, PromptInjector, InjectionContext,
)


class MyPlugin(ISACPlugin):
    """自定义插件。"""

    async def on_load(self, context: PluginContext) -> None:
        """插件加载时注册能力。"""
        # 注册工具 (供 LLM 调用)
        context.register_tool(MyTool())
        # 注册斜杠命令
        context.register_command(MyCommand())
        # 注册 Prompt 注入器
        context.register_injector(MyInjector())
        # 订阅事件 (Intercept 可拦截主流程, Async 不阻塞)
        context.on_event_intercept(...)

    async def on_unload(self) -> None:
        """插件卸载时清理资源。"""


class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "示例工具"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"input": {"type": "string"}},
            "required": ["input"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content=f"处理: {context.args.get('input')}")


class MyCommand(Command):
    @property
    def name(self) -> str:
        return "my_cmd"

    async def execute(self, message, args, context) -> str:
        return f"命令执行: {args}"


class MyInjector(PromptInjector):
    @property
    def key(self) -> str:
        return "my_injector"

    async def build(self, context: InjectionContext) -> str:
        return "【自定义注入】提示内容"
```

### 1.4 启用矩阵

插件在 Agent 上是否启用由 `AgentConfig.plugins_allow/deny` 控制:

```jsonc
// data/agents/<agent_id>/config.jsonc
{
    "plugins_allow": ["my_plugin", "another_plugin"],
    "plugins_deny": ["evil_plugin"]
}
```

通过 Admin API 修改:

```bash
curl -X PUT http://127.0.0.1:8765/api/v1/agents/<agent_id>/plugins \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"plugins_allow": ["my_plugin"], "plugins_deny": []}'
```

---

## 2. AstrBot 插件兼容

### 2.1 目录结构

```
plugins/astrbot_hello/
├── metadata.yaml
└── plugin.py
```

### 2.2 plugin.py (使用 AstrBot 装饰器)

```python
from isac.plugin.compatibility.astrbot.star import Star, filter


class HelloStar(Star):
    """AstrBot 兼容插件。"""

    @filter.llm_tool(name="hello_tool", description="打招呼工具")
    async def hello_tool(self, ctx, args):
        return f"hello {args.get('name', 'world')}"

    @filter.on_message()
    async def on_msg(self, ctx):
        # 消息事件回调
        pass
```

### 2.3 桥接说明

ISAC 兼容层:
- `@filter.llm_tool` → `FunctionToolAdapter` 包装为 ISAC Tool
- `Star` 子类被自动发现并实例化
- `context.send_message/get_platform/get_provider` 映射到 ISAC services
- `@filter.on_message` → EventBus ON_MESSAGE 订阅

---

## 3. MaiBot 插件兼容

### 3.1 目录结构

```
plugins/maibot_hello/
├── mai_plugin.yaml
└── plugin.py
```

### 3.2 plugin.py (使用 MaiBot 装饰器)

```python
from isac.plugin.compatibility.maibot.plugin import (
    MaiBotPlugin, register_action, register_command,
)


class HelloMaiBot(MaiBotPlugin):
    """MaiBot 兼容插件。"""

    @register_action(name="greet", description="打招呼")
    async def greet(self, args):
        return f"hello {args.get('name')}"

    @register_command(name="hello")
    async def hello_cmd(self, message, args):
        return f"hello {args}"
```

### 3.3 桥接说明

- `@register_action` → `MaiBotActionAdapter` 包装为 ISAC Tool
- `@register_command` → `MaiBotCommandAdapter` 包装为 ISAC Command
- `MaiBotPlugin` 子类被 `MaiBotPluginAdapter` 扫描装饰器并适配

---

## 4. 加载流程

### 4.1 自动发现

ISAC 启动时 (或通过 Admin API 触发), `PluginLoader` 扫描 `plugins/` 目录:

1. 检测格式: `manifest.jsonc` → Native; `metadata.yaml` → AstrBot; `mai_plugin.yaml` → MaiBot
2. 加载入口文件: `plugin.py`
3. 找到基类子类: `ISACPlugin` / `Star` / `MaiBotPlugin`
4. 多签名兜底实例化: `{}` / `{config: {}}` / `{context: None}`
5. 错误隔离: 单个插件失败不影响其他

### 4.2 生命周期

- `on_load(context)`: 加载完成时调用, 在此注册能力
- `on_unload()`: 卸载时调用, 清理资源

### 4.3 错误隔离

PluginManager 错误隔离:
- 加载失败 → 记录日志, 跳过该插件, 不影响其他
- `on_load` 异常 → 不影响 Agent 主链路
- 工具执行异常 → `ToolError` 包装后给 LLM

---

## 5. 安装与热重载

### 5.1 安装源 (四类)

控制面 `POST /api/v1/plugins/install` 接受 `source` dict, `type` ∈ `market` / `git` / `url` / `upload`:

| type | 参数 | 说明 |
|------|------|------|
| `market` | `name` | 从市场清单 (`data/plugin_marketplace.jsonc` + 可选远程 `marketplace_url`) 查条目安装 |
| `git` | `repo_url` (可选 `download_url` 兜底) | `git clone --depth 1`; git 不可用且有 `download_url` 时降级为 `url` |
| `url` | `url` | 下载 zip (SSRF 校验 + 超时 + 限 3 跳重定向) |
| `upload` | `zip_b64` (或已落地 zip 路径) | 控制面上传 (base64 传输, 不引 multipart 依赖) |

安全防护: 插件名白名单 (防路径穿越) + zip slip / symlink 校验 + 解压体积上限 + 失败回滚删半成品目录。

### 5.2 控制面端点

| 端点 | 操作 |
|------|------|
| `GET /api/v1/plugins/loaded` | 已加载插件 (含是否隔离) |
| `GET /api/v1/plugins/marketplace[?refresh=true]` | 市场清单 |
| `POST /api/v1/plugins/install` | 安装 (四类安装源) |
| `POST /api/v1/plugins/{name}/reload` | 热重载 |
| `DELETE /api/v1/plugins/{name}` | 卸载 (删目录) |
| `GET /api/v1/plugins/failed`、`POST /api/v1/plugins/{name}/retry` | 失败清单 / 重试加载 |

写操作需 `plugin:write` scope; `control.plugins.allow_install=false` 时不注册安装/重载/卸载写端点 (仅保留读)。

### 5.3 CLI (`python -m isac plugin ...`)

无 console script, 统一经 `python -m isac` 调用 (内部走控制面 API, 需服务运行中):

```bash
uv run python -m isac plugin list                  # 列出已加载
uv run python -m isac plugin marketplace --refresh # 市场清单 (强制刷新远程)
uv run python -m isac plugin install <市场名|git URL|zip URL>
uv run python -m isac plugin reload <name>         # 热重载
uv run python -m isac plugin uninstall <name>
uv run python -m isac plugin failed                # 加载失败清单
uv run python -m isac plugin retry <name>          # 重试加载失败插件
```

默认连 `http://127.0.0.1:8765` + `ISAC_API_TOKEN`, 可用 `--url` / `--token` 覆盖。

---

## 6. 信任分级 (U6)

| 插件形态 | 加载位置 | 条件 |
|----------|---------|------|
| 原生 (有 `manifest.jsonc`) | **子进程隔离** (默认) | `trust` 缺省或 `"sandboxed"`; 资源限额 + 崩溃自动重启 (最多重试上限) |
| 原生 + `trust: "hosted"` | 宿主进程内 | 且目录名在部署方 `control.plugins.trust_hosted` 确认清单中 |
| AstrBot / MaiBot 兼容层 (无 manifest) | 宿主进程内 (**无隔离**) | 启动时打印告警; 默认不隔离, 可用 `isolated_plugins` 显式强制 |

- 市场 / git / url / upload 安装的插件, 未声明 `"hosted"` 一律进入沙箱;
- 部署方可用 `control.plugins.isolated_plugins` (目录名列表, 或 `"*"` 表示全部) **强制隔离**,
  按目录名指定时对 AstrBot / MaiBot 兼容层插件同样生效;
- `hosted` 是显式信任决策: manifest 声明 `trust` **与** 部署配置确认缺一不可,
  信任责任在部署方 —— 不要对来源不明的插件开启。

---

## 7. 最佳实践

1. **插件边界清晰**: 一个插件只做一件事 (如翻译/搜索/特定业务)
2. **错误处理**: `execute` 内 try/except, 失败返回 `ToolResult(is_error=True)` 而非抛异常
3. **权限最小化**: manifest 只声明实际用到的 hooks/tools/permissions
4. **配置默认值**: `config_schema` 字段加默认值, 避免运行时 KeyError
5. **测试覆盖**: 工具/命令/注入器分别写单测, 用 `tests/unit/test_*` 覆盖

---

## 相关文档

- [原生 SDK v2 设计](./PLUGIN_COMPATIBILITY.md)
- [API 文档](./api.md) (含插件矩阵管理端点)
- [使用文档](./usage.md)
