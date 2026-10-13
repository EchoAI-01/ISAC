"""L2 (2026-10-13 review): maibot_sdk 顶层兼容 shim。

真实 MaiBot 插件 (SDK v2, pip 包 maibot-plugin-sdk) 的 plugin.py 顶部:
``from maibot_sdk import MaiBotPlugin, Tool, Command``。
本模块提供同形 API, 由 sandbox.py 的 import 重定向指到此处 —— 真实插件不改一行
即可加载 (与 AstrBot M12 同构; 此前 MaiBot 兼容层零重定向, 真实插件 import
即 ModuleNotFoundError, 兼容层实际只服务"直接 import ISAC 路径"的自写插件)。

映射边界 (诚实声明, 见 PLUGIN_COMPATIBILITY.md §7):
- MaiBotPlugin → ISAC MaiBotPlugin 基类 (构造签名兼容);
- @Tool/@Action(name, brief_description=..., parameters=[ToolParameterInfo...])
  → _maibot_action 标记 + 参数 schema (MaiBotActionAdapter 消费);
- @Command(name, pattern=...) → _maibot_command 标记 (pattern 由 ISAC Command
  路由体系另行约定, 这里不吞不报);
- create_plugin() 工厂函数: 插件模块自带, loader 经"找 MaiBotPlugin 子类"路径
  加载, 不需要工厂参与;
- **ctx 能力代理不在映射面** —— SDK 的 self.ctx.send/db 等 17 种代理经 Runner
  子进程 RPC 到 MaiBot Host, ISAC 兼容层是宿主进程内桥接, 无对等物; 插件方法
  内调用 self.ctx.* 会得到明确报错 (见 MaiBotPlugin.ctx) 而非 AttributeError。
"""

from __future__ import annotations

from typing import Any

from isac.plugin.compatibility.maibot.plugin import MaiBotPlugin
from isac.plugin.compatibility.maibot.sdk_types import (
    ToolParameterInfo,  # noqa: F401 — re-export (SDK 插件可能从这里取)
    ToolParamType,  # noqa: F401
)

__all__ = [
    "MaiBotPlugin",
    "Tool",
    "Command",
    "Action",
    "CONFIG_RELOAD_SCOPE_SELF",
    "ToolParameterInfo",
    "ToolParamType",
]

CONFIG_RELOAD_SCOPE_SELF = "self"


def Tool(  # noqa: N802 — SDK 原名 (大写装饰器)
    name: str,
    *,
    brief_description: str = "",
    detailed_description: str = "",
    parameters: list[Any] | None = None,
    **_ignored: Any,
) -> Any:
    """SDK @Tool 装饰器 → _maibot_action 标记 (+参数 schema 供 LLM 面)。"""

    def decorator(func: Any) -> Any:
        func._maibot_action = (  # type: ignore[attr-defined]
            name, brief_description or detailed_description or func.__doc__ or ""
        )
        if parameters:
            func._maibot_tool_parameters = list(parameters)  # type: ignore[attr-defined]
        return func

    return decorator


def Action(  # noqa: N802 — SDK 旧名, 官方语义 "内部自动转换为 @Tool"
    name: str,
    **kwargs: Any,
) -> Any:
    """SDK @Action (旧插件兼容名) → 与 @Tool 同义。"""
    return Tool(name, **kwargs)


def Command(  # noqa: N802 — SDK 原名 (大写装饰器)
    name: str,
    *,
    pattern: str = "",
    **_ignored: Any,
) -> Any:
    """SDK @Command 装饰器 → _maibot_command 标记。"""

    def decorator(func: Any) -> Any:
        func._maibot_command = (name,)  # type: ignore[attr-defined]
        return func

    return decorator
