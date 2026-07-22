"""AstrBot FunctionTool 桥接 (P0 兼容策略, ARCHITECTURE.md 3.8)。

将 AstrBot @filter.llm_tool 装饰的函数 → ISAC Tool。
"""

from __future__ import annotations

from typing import Any

from isac.agent.tools.base import Tool


def bridge_function_tool(name: str, description: str, func: Any) -> Tool:
    """将 AstrBot FunctionTool 桥接为 ISAC Tool。"""
    raise NotImplementedError("bridge_function_tool 尚未实现")
