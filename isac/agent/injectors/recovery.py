"""recovery 注入器: 启动恢复的"上次中断/恢复"内部参考提示 (L5)。

启动恢复后第一轮注入 ConversationSnapshot.recovery_hint 到 System Prompt,
让 Agent 知道刚醒、不是用户发来新消息。注入后清空快照, 避免下一轮重复注入。

需要 manager/assembly 在启动时调 store.load 填充 snapshots dict 后注入本 Injector。
默认无快照时返回空串 (零行为变化)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext

if TYPE_CHECKING:
    from isac.runtime.conversation import ConversationSnapshot, ConversationStateStore


class RecoveryInjector(PromptInjector):
    """注入"启动恢复"内部参考 (L5)。"""

    def __init__(
        self,
        *,
        store: ConversationStateStore | None = None,
        snapshots: dict[str, ConversationSnapshot] | None = None,
    ) -> None:
        self._store = store
        # snapshots: 按 session_id 索引的快照字典; 由 manager 启动时调
        # store.load 填充, 注入后从中删除该 session_id 的快照。
        self._snapshots: dict[str, ConversationSnapshot] = snapshots if snapshots is not None else {}

    @property
    def key(self) -> str:
        return "recovery_hint"

    @property
    def priority(self) -> int:
        return 35  # 中等优先, 在 base_identity/tools 之后注入

    @property
    def tokens_estimate(self) -> int:
        return 150

    def add_snapshot(self, session_id: str, snapshot: ConversationSnapshot) -> None:
        """manager 启动恢复时把每个会话的快照加入 (供第一轮 build 注入)。"""
        self._snapshots[session_id] = snapshot

    async def build(self, context: InjectionContext) -> str:
        session_id = getattr(context.session, "session_id", "") if context.session else ""
        if not session_id:
            return ""
        snap = self._snapshots.pop(session_id, None)
        if snap is None or not snap.recovery_hint:
            return ""
        return snap.recovery_hint
