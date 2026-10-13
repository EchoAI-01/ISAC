"""L2 (2026-10-13 review): MaiBot maibot_sdk import 重定向沙箱测试。

背景: MaiBot 兼容层此前零 import 重定向 (与 M12 修复前的 AstrBot 同构) ——
真实 MaiBot 插件 (SDK v2) 的 ``from maibot_sdk import MaiBotPlugin, Tool,
Command`` 在 ISAC 内加载必然 ModuleNotFoundError, 兼容层只服务直接 import
ISAC 路径的自写插件。本文件用**真实 SDK 形态**的插件源码端到端验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from isac.plugin.compatibility.maibot.sandbox import install_maibot_sandbox

# 真实 MaiBot SDK v2 插件形态 (docs.mai-mai.org/plugin 取证): 顶层 import +
# 生命周期三件 + @Tool/@Command 装饰器 + ToolParameterInfo 参数声明 +
# create_plugin() 工厂。
_REAL_SDK_PLUGIN = '''
from maibot_sdk import MaiBotPlugin, Tool, Command
from maibot_sdk.types import ToolParameterInfo, ToolParamType


class HelloPlugin(MaiBotPlugin):
    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        pass

    @Tool(
        "greet",
        brief_description="向用户打招呼",
        detailed_description="参数: name 必填",
        parameters=[
            ToolParameterInfo(
                name="name",
                param_type=ToolParamType.STRING,
                description="对方称呼",
                required=True,
            ),
            ToolParameterInfo(name="polite", param_type=ToolParamType.BOOLEAN),
        ],
    )
    async def handle_greet(self, args):
        return f"hello {args.get('name')}"

    @Command("hello", pattern=r"^/hello")
    async def handle_hello(self, message, args):
        return "hello!"


def create_plugin():
    return HelloPlugin({})
'''


@pytest.fixture(autouse=True)
def _sandbox_installed():
    install_maibot_sandbox()
    # 清理重定向产生的 sys.modules 双名, 隔离测试间状态。
    yield
    for key in [k for k in sys.modules if k.startswith("maibot_sdk")]:
        sys.modules.pop(key, None)


def test_maibot_sdk_top_level_names_importable() -> None:
    import maibot_sdk

    for name in ("MaiBotPlugin", "Tool", "Command", "Action", "CONFIG_RELOAD_SCOPE_SELF"):
        assert hasattr(maibot_sdk, name), name
    # 与 ISAC 兼容层同源 (基类真身, 不是平行复制)。
    from isac.plugin.compatibility.maibot.plugin import MaiBotPlugin

    assert maibot_sdk.MaiBotPlugin is MaiBotPlugin


def test_maibot_sdk_types_submodule_importable() -> None:
    from maibot_sdk.types import ToolParameterInfo, ToolParamType

    assert ToolParamType.STRING.value == "string"
    info = ToolParameterInfo(name="x", param_type=ToolParamType.INTEGER, required=True)
    assert info.required is True


def test_unsupported_submodule_raises_with_coverage_list() -> None:
    with pytest.raises(ImportError, match="仅覆盖"):
        import maibot_sdk.rpc  # noqa: F401


@pytest.mark.asyncio
async def test_real_sdk_form_plugin_loads_end_to_end(tmp_path: Path) -> None:
    """真实 SDK 形态插件: 不改一行经 PluginLoader 加载 + 装饰器桥接 + 参数
    schema 进 LLM 面 (修复前 import 即 ModuleNotFoundError)。"""
    from isac.agent.tools.registry import ToolRegistry
    from isac.commands.registry import CommandRegistry
    from isac.plugin.runtime.loader import PluginLoader

    plugin_dir = tmp_path / "hello_sdk"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(_REAL_SDK_PLUGIN, encoding="utf-8")

    loader = PluginLoader()
    loaded = await loader._load_maibot(plugin_dir)
    assert loaded.format.value == "maibot"
    assert type(loaded.instance).__name__ == "HelloPlugin"

    # 经适配器桥接 (与 plugin_manager.adapt_one 内部同路径)。
    from isac.plugin.compatibility.maibot.plugin import MaiBotPluginAdapter

    tools = ToolRegistry()
    commands = CommandRegistry()
    adapter = MaiBotPluginAdapter(loaded.instance)
    result = await adapter.adapt(tools, commands)
    assert result["tools"] == ["greet"]
    assert result["commands"] == ["hello"]

    # @Tool 参数声明映射进 LLM function-calling schema (修复前恒空 schema)。
    greet = tools.get("greet")
    assert greet is not None
    schema = greet.parameters
    assert schema["properties"]["name"] == {
        "type": "string", "description": "对方称呼",
    }
    assert schema["required"] == ["name"]
    assert schema["properties"]["polite"]["type"] == "boolean"

    # 执行链路: args dict 原样传给 handle_greet。
    from isac.agent.tools.base import ToolContext

    context = ToolContext(
        args={"name": "ISAC"},
        agent_context=None,  # type: ignore[arg-value]
        services={},
    )
    tool_result = await greet.execute(context)
    assert tool_result.is_error is False
    assert tool_result.content == "hello ISAC"


def test_ctx_capability_proxy_boundary_errors_clearly() -> None:
    """SDK ctx 能力代理 (Runner RPC) 无对等物: 访问得到明确 RuntimeError 而非
    AttributeError (加载/注册不受影响, 只有点到 ctx 的路径才报)。"""
    from isac.plugin.compatibility.maibot.plugin import MaiBotPlugin

    plugin = MaiBotPlugin({})
    with pytest.raises(RuntimeError, match="ctx 能力代理"):
        plugin.ctx  # noqa: B018


def test_sandbox_install_idempotent() -> None:
    install_maibot_sandbox()
    finders = [f for f in sys.meta_path if type(f).__name__ == "MaiBotImportFinder"]
    assert len(finders) == 1
