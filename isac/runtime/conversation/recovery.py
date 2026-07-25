"""ConversationStateStore: 会话拟人状态恢复骨架 (L5, HUMANLIKE_RUNTIME.md §7)。

[框架已搭建 / scaffolding] 重启后恢复会话拟人状态 (未决 wait / 打断标记 / 主动任务 /
最近 N 条消息 + 恢复提示) 的持久化挂接点就位;真正的落盘 schema、恢复编排与
"中断后不续跑旧进度" 策略留待 L5 实现节点 (见 TODO)。默认 no-op, 对主链路零行为变化。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from isac.runtime.conversation.models import WaitState


@dataclass
class ConversationSnapshot:
    """一次会话拟人状态的可持久化快照 (L5)。"""

    agent_id: str
    session_id: str
    state: str = "idle"
    pending_wait: WaitState | None = None
    recent_message_ids: list[str] = field(default_factory=list)
    recovery_hint: str = ""  # 注入下一轮 Prompt 的 "上次中断/恢复" 提示


class ConversationStateStore:
    """会话拟人状态持久化/恢复骨架。

    与 D9/J4 "中断后不恢复旧进度" 思路一致: 恢复时应把运行态标为终止/复位
    (idle) 而非续跑, 只带回参考消息与提示。骨架阶段全部 no-op。
    """

    def save(self, snapshot: ConversationSnapshot) -> None:
        """持久化一次快照。

        TODO(L5): 落盘到 data/agents/<id>/conversation/ 的 SQLite/JSON;
        骨架阶段 no-op (不落盘, 不影响关闭流程)。
        """

    def load(self, agent_id: str, session_id: str) -> ConversationSnapshot | None:
        """启动时恢复某会话快照; 无则 None。

        TODO(L5): 从持久化读回, 过滤过期窗口 (short/medium/long), 复位运行态,
        生成 recovery_hint。骨架阶段恒返回 None (无恢复, 等价于全新会话)。
        """
        return None
