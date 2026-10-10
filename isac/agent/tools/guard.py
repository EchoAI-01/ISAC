"""U5 单调 Deny Guard: 会话内工具拒绝不可翻回。

四段管线的第二段: 一旦某工具在某会话被拒 (人工拒绝/超时 fail-closed/策略拒绝
中需人工介入的档), 该会话内该工具后续调用一律拒绝 —— 任何代码路径 (包括再次
ask、配置热更新、LLM 重试) 都不能把已记录的拒绝翻回放行。

单调性实现: 拒绝记录只增不删 (无 remove API); 进程重启后由 U1 事件表重建
(``restore_from_events`` 读 tool.outcome 的 DENIED 记录) —— 拒绝跨重启仍不可翻回。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.session.models import SessionEvent

logger = get_logger(__name__)

# tool.outcome 事件 payload 里"被拒"的 outcome 标记值 (与 event_store.OUTCOME_UNKNOWN
# 区分: UNKNOWN 是 torn-tail 修复的"不知道结果", DENIED 是权限管线的"明确拒绝")。
OUTCOME_DENIED = "DENIED"

# Fix-136: 内存拒绝账本保留的会话数上限。单调拒绝是安全不变量 —— 单纯 LRU 逐出会把
# 已记录的拒绝"翻回", 因此逐出必须配对"可从事件流惰性重建"才安全 (见 is_denied)。
DEFAULT_MAX_DENIAL_SESSIONS = 10000


class DenyGuard:
    """会话级单调拒绝账本 (session_key × tool_name, 只增不删)。

    Fix-136: 账本按会话数 LRU 封顶 (DEFAULT_MAX_DENIAL_SESSIONS)。单调性不被逐出破坏
    的前提是逐出后可从 U1 事件流重建 —— 故仅在 ``bind_store`` 注入了事件存储时才逐出;
    未注入时保持不逐出 (等同旧行为, 绝不丢拒绝)。``is_denied`` 对内存缺失的会话先惰性
    重建其拒绝集再判定, 保证"曾被拒"恒为真。拒绝集允许为空集 (表示"已重建、无拒绝"),
    避免无拒绝的热点会话每次 is_denied 都全量扫事件流。
    """

    def __init__(self, max_sessions: int = DEFAULT_MAX_DENIAL_SESSIONS) -> None:
        # OrderedDict: 按最近访问排序, 供 LRU 逐出 (move_to_end + popitem(last=False))。
        self._denials: OrderedDict[str, set[str]] = OrderedDict()
        self._max_sessions = max(0, int(max_sessions))
        # Fix-136: 惰性重建用的事件存储 (bind_store/restore_from_store 注入)。
        self._store: Any = None

    def bind_store(self, store: Any) -> None:
        """Fix-136: 注入事件存储, 使 LRU 逐出后可经 is_denied 惰性重建拒绝集。"""
        self._store = store

    def register_denial(self, session_key: str, tool_name: str) -> None:
        """记录一次拒绝 (幂等)。调用后 is_denied 恒 True, 无任何撤销路径。"""
        if not session_key or not tool_name:
            return
        self._denials.setdefault(session_key, set()).add(tool_name)
        self._denials.move_to_end(session_key)
        self._evict_if_needed()

    async def is_denied(self, session_key: str, tool_name: str) -> bool:
        """该会话的该工具是否已被拒绝过。

        Fix-136: 内存命中直接判定 (并 LRU 置新); 未命中且已绑定事件存储时, 先惰性重建
        该会话的拒绝集 (可能被 LRU 逐出) 再判定 —— 保证逐出不会把"曾被拒"翻回放行。
        未绑定存储且未命中时返回 False (无持久化可重建, 维持旧语义)。
        """
        if session_key in self._denials:
            self._denials.move_to_end(session_key)
            return tool_name in self._denials[session_key]
        if self._store is not None and session_key:
            await self._restore_session(session_key)
            return tool_name in self._denials.get(session_key, set())
        return False

    def _evict_if_needed(self) -> None:
        """Fix-136: 超上限时从最旧会话开始逐出。

        仅在已绑定事件存储时逐出 (逐出后可经 is_denied 惰性重建, 单调性不破坏);
        未绑定存储时不逐出, 保持全量在内存 (绝不丢拒绝)。max_sessions<=0 表示不限制。
        """
        if self._store is None or self._max_sessions <= 0:
            return
        while len(self._denials) > self._max_sessions:
            evicted, _ = self._denials.popitem(last=False)
            logger.debug("DenyGuard 会话拒绝集超上限, LRU 逐出 (可惰性重建)", session_key=evicted)

    async def _restore_session(self, session_key: str) -> None:
        """Fix-136: 从事件流重建单个会话的拒绝集 (分页扫描), 结果缓存进账本。

        无论是否有拒绝都写入账本 (无拒绝 → 空集), 使热点会话后续 is_denied 走内存
        命中, 不重复扫事件流。store.fetch 失败时静默返回 (判定回落 False, 不阻塞工具)。
        """
        try:
            denied: set[str] = set()
            after_seq = 0
            while True:
                page = await self._store.fetch(session_key, after_seq=after_seq, limit=1000)
                if not page:
                    break
                for event in page:
                    if getattr(event, "event_type", "") != "tool.outcome":
                        continue
                    payload = getattr(event, "payload", None) or {}
                    if payload.get("outcome") != OUTCOME_DENIED:
                        continue
                    tool_name = str(payload.get("tool_name", "") or "")
                    if tool_name:
                        denied.add(tool_name)
                after_seq = page[-1].seq
                if len(page) < 1000:
                    break
        except Exception as exc:  # noqa: BLE001 重建失败不阻塞工具执行
            logger.warning("DenyGuard 惰性重建会话拒绝集失败", session_key=session_key, error=str(exc))
            return
        # 2026-08-19 (M1): 整体赋值改合并 —— 分页扫描期间存在 await(store.fetch),
        # 若同会话另一工具调用并发被拒并 register_denial 写入 _denials[session_key],
        # 收尾整体赋值会覆盖该并发写入 → 已登记拒绝丢失、is_denied 返回 False、被拒
        # 工具可再执行 (单调性在并发下被破坏)。setdefault().update() 保留并发写入。
        self._denials.setdefault(session_key, set()).update(denied)
        self._denials.move_to_end(session_key)
        self._evict_if_needed()

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

        Fix-136: 重建同时 ``bind_store(store)`` —— 让运行期 LRU 逐出后可惰性重建。
        """
        self.bind_store(store)
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
