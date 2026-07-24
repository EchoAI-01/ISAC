"""/focus 命令: 开启/关闭 Focus Mode (ARCHITECTURE.md 3.7)。"""

from __future__ import annotations

from isac.channel.model import ISACMessage
from isac.commands.base import Command
from isac.core.types import AgentContext

_DEFAULT_FOCUS_DURATION = 300  # 5 分钟


class FocusCommand(Command):
    """专注模式开关。需要 gating 实例 (经 services 注入) 时生效。"""

    @property
    def name(self) -> str:
        return "focus"

    @property
    def description(self) -> str:
        return "开启/关闭专注模式 (Bot 在该会话积极参与)"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """经注入的 GatingSystem.focus_mode enter/exit。

        args 为空 / on / <秒数> 时开启; off / close / exit 关闭。
        """
        gating = context.services.get("gating")
        if gating is None:
            return "门控系统未注入, 无法切换 Focus Mode。"
        session_id = context.session.session_id if context.session else ""
        if not session_id:
            return "当前会话上下文缺失, 无法切换 Focus Mode。"

        arg = (args or "").strip().lower()
        if arg in ("off", "close", "exit", "cancel"):
            gating.focus_mode.exit(session_id)
            return "已关闭专注模式。"

        # 解析秒数; 无参数用默认时长
        duration = _DEFAULT_FOCUS_DURATION
        if arg and arg not in ("on", "start"):
            try:
                duration = max(30, int(arg))
            except ValueError:
                return f"无效参数: {args!r}; 用法 /focus [on|off|<秒数>]"

        gating.focus_mode.enter(session_id, duration=duration)
        return f"已开启专注模式, 持续 {duration} 秒。"
