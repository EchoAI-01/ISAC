"""MaiBot Command 映射 (ARCHITECTURE.md 3.8 兼容表)。

将 MaiBot Command (命令) 桥接为 ISAC Command (commands/)。
"""

from __future__ import annotations

from typing import Any


def bridge_command(command: Any) -> Any:
    """将 MaiBot Command 桥接为 ISAC Command。"""
    raise NotImplementedError("bridge_command 尚未实现")
