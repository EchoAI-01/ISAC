"""Command 基类 (SPECIFICATION.md 2.11)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage
    from isac.core.types import AgentContext


class Command(ABC):
    """命令抽象基类 (用户斜杠命令 / 管理命令)。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """命令名 (不含 '/')"""
        ...

    @property
    def description(self) -> str:
        return ""

    @property
    def usage(self) -> str:
        return f"/{self.name}"

    @abstractmethod
    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """执行命令，返回回复文本。"""
        ...
