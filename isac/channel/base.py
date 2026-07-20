"""平台适配器抽象基类 (SPECIFICATION.md 2.1)。

新增适配器步骤见 DEVELOP.md 3.3。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from isac.channel.model import ISACMessage


class PlatformAdapter(ABC):
    """平台适配器抽象基类。所有平台适配器必须实现此接口。"""

    # 框架注册的回调 (由 Gateway 注入)
    on_message: Callable[[ISACMessage], Awaitable[None]] | None = None
    on_error: Callable[[Exception], Awaitable[None]] | None = None

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台唯一标识"""
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动平台连接，开始接收消息"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止平台连接，清理资源"""
        ...

    @abstractmethod
    async def send(self, message: ISACMessage) -> bool:
        """发送消息到平台。返回是否成功。"""
        ...
