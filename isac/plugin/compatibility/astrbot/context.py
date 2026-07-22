"""AstrBot Context API 模拟 (P1 兼容策略, ARCHITECTURE.md 3.8)。

AstrBot 事件对象 (AstrMessageEvent 等) → ISACMessage 的适配。
"""

from __future__ import annotations

from typing import Any


class ContextAdapter:
    """AstrBot Context → ISAC 适配器。"""

    def __init__(self, services: dict[str, Any]):
        self.services = services
