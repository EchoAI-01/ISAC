"""U5 单调 Deny Guard: 会话内工具拒绝不可翻回。

四段管线的第二段: 一旦某工具在某会话被拒 (人工拒绝/超时 fail-closed/策略拒绝
中需人工介入的档), 该会话内该工具后续调用一律拒绝 —— 任何代码路径 (包括再次
ask、配置热更新、LLM 重试) 都不能把已记录的拒绝翻回放行。

单调性实现: 拒绝记录只增不删 (无 remove API); 进程重启后由 U1 事件表重建
(``restore_from_events`` 读 tool.outcome 的 DENIED 记录) —— 拒绝跨重启仍不可翻回。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.session.models import SessionEvent

logger = get_logger(__name__)

# tool.outcome 事件 payload 里"被拒"的 outcome 标记值 (与 event_store.OUTCOME_UNKNOWN
# 区分: UNKNOWN 是 torn-tail 修复的"不知道结果", DENIED 是权限管线的"明确拒绝")。
OUTCOME_DENIED = "DENIED"


class DenyGuard:
    """会话级单调拒绝账本 (session_key × tool_name, 只增不删)。"""

    def __init__(self) -> None:
        self._denials: dict[str, set[str]] = {}

    def register_denial(self, session_key: str, tool_name: str) -> None:
        """记录一次拒绝 (幂等)。调用后 is_denied 恒 True, 无任何撤销路径。"""
        if not session_key or not tool_name:
            return
        self._denials.setdefault(session_key, set()).add(tool_name)

    def is_denied(self, session_key: str, tool_name: str) -> bool:
        """该会话的该工具是否已被拒绝过。"""
        return tool_name in self._denials.get(session_key, set())

    def restore_from_events(self, session_key: str, events: list[SessionEvent | Any]) -> int:
        """从 U1 事件流重建拒绝账本 (启动时逐分区调用)。

        读 ``tool.outcome`` 且 payload.outcome == DENIED 的事件, 按其 payload.tool_name
        登记拒绝。返回重建的拒绝条数。事件流是拒绝的唯一持久化载体 —— 与
        "决策留痕经 U1 事件表" 的审计设计同源。
        """
        restored = 0
        for event in events:
            if getattr(event, "event_type", "") != "tool.outcome":
                continue
            payload = getattr(event, "payload", None) or {}
            if payload.get("outcome") != OUTCOME_DENIED:
                continue
            tool_name = str(payload.get("tool_name", "") or "")
            if tool_name:
                self.register_denial(session_key, tool_name)
                restored += 1
        if restored:
            logger.info("DenyGuard 已从事件流重建拒绝记录", session_key=session_key, count=restored)
        return restored

    async def restore_from_store(self, store: Any, *, page_size: int = 1000) -> None:
        """Fix-120: 从事件存储**全量**重建拒绝账本 (逐分区分页扫描)。

        单调拒绝是安全不变量, 重建必须扫全量事件流 —— 此前启动只取每分区最近 500 条,
        长会话里较早的 DENIED 事件落在窗口之外, 重启后该拒绝丢失、被拒工具翻回放行,
        瓦解 U5 的核心保证。现按 seq 分页 (page_size 只控制单次内存占用) 顺序扫完整个
        分区; 拒绝记录幂等 (set), 重复扫描无害。store 需提供 list_session_keys/fetch。
        """
        for session_key in await store.list_session_keys():
            after_seq = 0
            while True:
                events = await store.fetch(session_key, after_seq=after_seq, limit=page_size)
                if not events:
                    break
                self.restore_from_events(session_key, events)
                after_seq = events[-1].seq
                if len(events) < page_size:
                    break  # 最后一页, 该分区已扫完
