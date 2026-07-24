"""/mute /unmute 命令: 会话静音开关。"""

from __future__ import annotations

import time

from isac.channel.model import ISACMessage
from isac.commands.base import Command
from isac.core.types import AgentContext

_DEFAULT_MUTE_DURATION = 3600  # 1 小时


class MuteCommand(Command):
    @property
    def name(self) -> str:
        return "mute"

    @property
    def description(self) -> str:
        return "在当前会话静音 (Bot 不再主动回复)"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """设置会话级静音标志 (muted_until), 门控强制 WAIT。

        args 可选秒数; 默认 1 小时。@bot 仍能穿透静音, 用户可用 @bot /unmute 解锁。
        """
        if context.session is None:
            return "当前会话上下文缺失, 无法静音。"
        arg = (args or "").strip().lower()
        duration = _DEFAULT_MUTE_DURATION
        if arg:
            try:
                duration = max(60, int(arg))
            except ValueError:
                return f"无效参数: {args!r}; 用法 /mute [秒数]"
        context.session.muted_until = time.monotonic() + duration
        return f"已静音当前会话, 持续 {duration} 秒。期间我不会主动发言, 但 @我 仍可解锁。"


class UnmuteCommand(Command):
    @property
    def name(self) -> str:
        return "unmute"

    @property
    def description(self) -> str:
        return "取消当前会话静音"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """清除会话级静音标志。"""
        if context.session is None:
            return "当前会话上下文缺失, 无法取消静音。"
        if not context.session.muted_until:
            return "当前会话并未静音。"
        context.session.muted_until = 0.0
        return "已取消静音, 我会恢复正常的发言节奏。"
