"""AstrBot FunctionTool 桥接 (P0 兼容策略, ARCHITECTURE.md 3.8)。

TODO(Day 48-49): AstrBot @filter.llm_tool 装饰的函数 → ISAC Tool。
"""

from __future__ import annotations

from typing import Any

from isac.agent.tools.base import Tool


def bridge_function_tool(name: str, description: str, func: Any) -> Tool:
    """将 AstrBot FunctionTool 桥接为 ISAC Tool。"""
    raise NotImplementedError("TODO(Day 48): 实现 FunctionTool 桥接")
