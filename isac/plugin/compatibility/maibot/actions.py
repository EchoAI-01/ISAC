"""MaiBot Action 映射 (ARCHITECTURE.md 3.8 兼容表)。

将 MaiBot Action (动作) 桥接为 ISAC Tool 或 AgentHooks。
"""

from __future__ import annotations

from typing import Any


def bridge_action(action: Any) -> Any:
    """将 MaiBot Action 桥接为 ISAC Tool 或 Hook。"""
    raise NotImplementedError("bridge_action 尚未实现")
