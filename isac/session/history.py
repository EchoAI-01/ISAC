"""U1 SessionHistoryDeriver: 从事件流派生会话历史 (三种策略)。

派生策略:
- **全量折叠** ``fold``: 按 seq 重放全部事件 → user/assistant 消息列表, 压缩事件
  (turn.compressed) 以摘要替代其 source_seqs 引用的原始事件区间。
- **滑动窗口** ``derive_window``: 全量折叠后保留最近 N 轮 + budget 感知截断
  (从最旧丢弃, 至少保留最近一条)。这是 U1 验收"滑动窗口历史开箱可用"的直接落点 ——
  此前 LLM 每回合只看到当前 burst, 无任何历史窗口。
- **压缩溯源校验** ``validate_compression``: 摘要不小于原文时拒绝提交 (压缩必须真压缩)。

未知事件类型默认拒绝重建 (raise UnknownSessionEventError), 仅 IGNORABLE_EVENT_TYPES
可跳过 —— 前向兼容且防止静默吞掉语义变化。
"""

from __future__ import annotations

from typing import Any

from isac.session.models import (
    EVENT_TOOL_CALLED,
    EVENT_TOOL_OUTCOME,
    EVENT_TURN_ABORTED,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_COMPRESSED,
    EVENT_USER_MESSAGE,
    SessionEvent,
)
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class UnknownSessionEventError(ValueError):
    """重建时遇到未知事件类型 (不在白名单且不可忽略) → 拒绝重建。"""


def estimate_tokens(text: str) -> int:
    """粗略 token 估算 (budget 截断用)。中文为主的场景按 ~2 字符/token 估。

    不追求精确 (精确需 tokenizer), 只用于窗口 budget 的保守截断。
    """
    return max(1, len(text) // 2)


class SessionHistoryDeriver:
    """会话历史派生器 (无状态, 纯函数式折叠 + 窗口策略)。"""

    def __init__(self, *, window_turns: int = 10, budget_tokens: int | None = None) -> None:
        # 一轮 ≈ 一条 user + 一条 assistant。window_turns 轮 ≈ 2*window_turns 条消息。
        self._window_turns = max(1, int(window_turns))
        self._budget_tokens = budget_tokens

    # ── 全量折叠 ──────────────────────────────────────────────

    def fold(self, events: list[SessionEvent]) -> list[dict[str, Any]]:
        """按 seq 重放事件 → 消息列表 (应用压缩)。未知事件类型拒绝重建。

        压缩处理: turn.compressed 事件的 source_seqs 引用的原始事件被跳过, 由该
        压缩事件的 summary 在压缩事件自身 seq 位置替代。tool.* 事件不进聊天历史
        (仅审计/torn-tail 用), ignorable 事件安全跳过。
        Fix-100: turn.aborted 事件的 aborted_user_seq 指向被作废的孤儿 user 事件
        (回合被打断、回复抑制), 一并跳过, 避免接替回合重复落同一 burst 后历史窗口
        出现重复用户内容。
        """
        superseded, aborted_user_seqs = self._collect_superseded(events)
        messages: list[dict[str, Any]] = []
        for e in sorted(events, key=lambda ev: ev.seq):
            if e.seq in superseded:
                continue
            if e.event_type == EVENT_USER_MESSAGE and e.seq in aborted_user_seqs:
                continue  # Fix-100: 被打断回合的孤儿 user 事件不进历史
            message = self._event_to_message(e)
            if message is not None:
                messages.append(message)
        return messages

    @staticmethod
    def _collect_superseded(events: list[SessionEvent]) -> tuple[set[int], set[int]]:
        """预扫描: 压缩替代的 source_seqs 集合 + Fix-100 被作废的孤儿 user seq 集合。"""
        superseded: set[int] = set()
        aborted_user_seqs: set[int] = set()
        for e in events:
            if e.event_type == EVENT_TURN_COMPRESSED:
                superseded.update(int(s) for s in e.payload.get("source_seqs", []))
            elif e.event_type == EVENT_TURN_ABORTED:
                aborted_seq = e.payload.get("aborted_user_seq")
                if aborted_seq is not None:
                    aborted_user_seqs.add(int(aborted_seq))
        return superseded, aborted_user_seqs

    @staticmethod
    def _event_to_message(e: SessionEvent) -> dict[str, Any] | None:
        """单事件 → 聊天消息映射。不进历史窗口返回 None; 未知类型拒绝重建。"""
        if e.event_type == EVENT_USER_MESSAGE:
            return {"role": "user", "content": str(e.payload.get("content", ""))}
        if e.event_type == EVENT_TURN_COMPLETED:
            return {"role": "assistant", "content": str(e.payload.get("content", ""))}
        if e.event_type == EVENT_TURN_COMPRESSED:
            return {"role": "assistant", "content": str(e.payload.get("summary", ""))}
        if e.event_type in (EVENT_TOOL_CALLED, EVENT_TOOL_OUTCOME, EVENT_TURN_ABORTED):
            return None  # 工具事件与 Fix-100 补偿标记不进聊天历史窗口
        if e.is_ignorable():
            return None
        raise UnknownSessionEventError(
            f"未知会话事件类型, 拒绝重建: {e.event_type} (seq={e.seq}, session={e.session_key})"
        )

    # ── 滑动窗口 ──────────────────────────────────────────────

    def derive_window(self, events: list[SessionEvent]) -> list[dict[str, Any]]:
        """全量折叠 → 保留最近 N 轮 → budget 感知截断。返回派生的历史消息列表。

        memory 关闭时仍可用 (派生只依赖事件流, 不依赖记忆检索) —— 这是 U1 验收的
        底线场景。
        """
        messages = self.fold(events)
        window_size = self._window_turns * 2
        if len(messages) > window_size:
            messages = messages[-window_size:]
        if self._budget_tokens is not None:
            messages = self._truncate_by_budget(messages)
        return messages

    def _truncate_by_budget(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """budget 感知截断: 从最旧丢弃直到估算 token 总量 ≤ budget, 至少保留最近一条。"""
        budget = int(self._budget_tokens or 0)
        if budget <= 0 or not messages:
            return messages
        total = sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
        start = 0
        while total > budget and start < len(messages) - 1:
            total -= estimate_tokens(str(messages[start].get("content", "")))
            start += 1
        return messages[start:]

    # ── 压缩溯源校验 ──────────────────────────────────────────

    @staticmethod
    def validate_compression(original_content: str, summary: str) -> bool:
        """压缩溯源校验: 摘要不小于原文时拒绝提交 (压缩必须真压缩, 防"负压缩")。

        返回 True = 可提交 (summary 比 original 短); False = 拒绝。
        """
        return len(summary) < len(original_content)
