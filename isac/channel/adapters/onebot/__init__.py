"""OneBot v11 适配器 (QQ，通过 NapCat 等实现连接)。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isac.channel.adapters.onebot.adapter import OneBotAdapter

__all__ = ["OneBotAdapter"]


def __getattr__(name: str) -> type:
    """惰性导入，避免未安装 aiocqhttp 时导入本包失败。"""
    if name == "OneBotAdapter":
        from isac.channel.adapters.onebot.adapter import OneBotAdapter

        return OneBotAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
