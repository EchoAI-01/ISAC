"""U1 SessionEventStore: append-only 会话事件表 (WAL + write-behind 批处理)。

范式升格自 SubAgentJournal (subagent/journal.py): ``(session_key, seq)`` 原子追加 +
脱敏 + fetch_after 增量读。差异: 分区键是会话 session_key (而非 task_id), 事件 payload
为任意 JSON, 并新增 write-behind 批处理与显式 flush (副作用前强制落盘)。

持久化保证:
- WAL 模式 + busy_timeout, 一写多读不互斥。
- seq 在单条 ``INSERT...SELECT COALESCE(MAX(seq),0)+1`` 内原子分配, 并发追加不冲突。
- write-behind: append 累计到 ``write_behind_batch`` 才 commit; ``flush()`` 强制 commit
  (工具执行前/LLM 请求前调用, 保证副作用发生前其前置事件已 durable)。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.session.models import SessionEvent
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite

logger = get_logger(__name__)

# 脱敏: payload 中按这些键名剔除 (占位, 与 subagent/journal.py 口径一致)。
_SENSITIVE_KEYS = frozenset(
    {"api_key", "token", "authorization", "cookie", "secret", "password"}
)
# 单条事件 payload 序列化后的字节上限 (防单条事件无限占用存储)。
_MAX_PAYLOAD_BYTES = 256_000

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_events (
    session_key TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    payload     TEXT,
    PRIMARY KEY (session_key, seq)
);
CREATE INDEX IF NOT EXISTS idx_session_events_key ON session_events(session_key, seq);
"""


class SessionEventStore:
    """append-only 会话事件存储。

    生命周期: ``start()`` 打开连接建表, ``stop()`` flush 并关闭。未 start 时
    append/fetch 安全降级 (append 静默丢弃, fetch 返回空) —— 便于无持久化的单测。
    """

    def __init__(self, db_path: str, *, write_behind_batch: int = 16) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        # write-behind: 累计多少条未 commit 事件后触发一次 commit。
        self._write_behind_batch = max(1, int(write_behind_batch))
        self._pending_commits = 0

    async def start(self) -> None:
        import aiosqlite

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        # U1: WAL 让并发读写不互斥, busy_timeout 在写锁竞争时等待而非立即 locked。
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        logger.info("SessionEventStore schema 已初始化", path=self.db_path)

    async def stop(self) -> None:
        await self.flush()
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def append(self, event: SessionEvent) -> int:
        """追加一条事件, 返回其 seq。未 start 时返回 0 (静默降级)。

        seq 自动分配 (event.seq<=0): 单条 INSERT...SELECT 内原子计算
        COALESCE(MAX(seq),0)+1, 同分区并发追加不冲突 (无读写间隙)。
        """
        if self._db is None:
            return 0
        event = self._sanitize(event)
        payload_json = json.dumps(event.payload, ensure_ascii=False)
        if event.seq <= 0:
            cursor = await self._db.execute(
                "INSERT INTO session_events (session_key, seq, event_type, timestamp, payload) "
                "SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ? "
                "FROM session_events WHERE session_key = ?",
                (event.session_key, event.event_type, event.timestamp, payload_json, event.session_key),
            )
            # 取回刚分配的 seq (该分区当前最大 seq)。
            seq_cursor = await self._db.execute(
                "SELECT MAX(seq) FROM session_events WHERE session_key = ?",
                (event.session_key,),
            )
            row = await seq_cursor.fetchone()
            await seq_cursor.close()
            await cursor.close()
            event.seq = int(row[0]) if row and row[0] is not None else 0
        else:
            await self._db.execute(
                "INSERT OR REPLACE INTO session_events (session_key, seq, event_type, timestamp, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (event.session_key, event.seq, event.event_type, event.timestamp, payload_json),
            )
        self._pending_commits += 1
        if self._pending_commits >= self._write_behind_batch:
            await self.flush()
        return event.seq

    async def flush(self) -> None:
        """强制 commit, 让已 append 的事件 durable (副作用前调用)。"""
        if self._db is None:
            return
        await self._db.commit()
        self._pending_commits = 0

    async def fetch(
        self, session_key: str, after_seq: int = 0, limit: int = 1000
    ) -> list[SessionEvent]:
        """按 seq 升序读取某会话分区的事件 (after_seq 之后, 最多 limit 条)。"""
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT session_key, seq, event_type, timestamp, payload "
            "FROM session_events WHERE session_key = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
            (session_key, after_seq, max(1, int(limit))),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [self._row_to_event(row) for row in rows]

    async def fetch_recent(self, session_key: str, limit: int = 200) -> list[SessionEvent]:
        """读取某会话分区**最近** limit 条事件, 按 seq 升序返回。

        U1 滑动窗口用: 长会话下历史窗口只需最近若干事件, 不能从最旧取 (fetch 的
        ASC+LIMIT 会取到最早的事件)。这里 ORDER BY seq DESC LIMIT 取最近再反转。
        """
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT session_key, seq, event_type, timestamp, payload "
            "FROM session_events WHERE session_key = ? ORDER BY seq DESC LIMIT ?",
            (session_key, max(1, int(limit))),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        events = [self._row_to_event(row) for row in rows]
        events.reverse()  # 转回 seq 升序
        return events

    async def max_seq(self, session_key: str) -> int:
        """返回某会话分区当前最大 seq (无事件返回 0)。"""
        if self._db is None:
            return 0
        cursor = await self._db.execute(
            "SELECT MAX(seq) FROM session_events WHERE session_key = ?", (session_key,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row and row[0] is not None else 0

    async def list_session_keys(self) -> list[str]:
        """返回有事件的全部会话分区键 (启动时逐分区 torn-tail repair 用)。"""
        if self._db is None:
            return []
        cursor = await self._db.execute("SELECT DISTINCT session_key FROM session_events")
        rows = await cursor.fetchall()
        await cursor.close()
        return [str(row[0]) for row in rows]

    async def repair_torn_tail(self, session_key: str) -> int:
        """U1 torn-tail 修复: 为孤儿 tool.called (无对应 tool.outcome) 追加
        OUTCOME_UNKNOWN 结果事件, 不猜结果。返回修复的孤儿数。

        判定: 统计该分区 tool.called 与 tool.outcome 条数, 差值即孤儿数 (简化: 按
        数量配对; 精确按 tool_call_id 配对留待事件携带 call_id 后升级)。
        """
        from isac.session.models import EVENT_TOOL_CALLED, EVENT_TOOL_OUTCOME, OUTCOME_UNKNOWN

        if self._db is None:
            return 0
        cursor = await self._db.execute(
            "SELECT event_type, COUNT(*) FROM session_events "
            "WHERE session_key = ? AND event_type IN (?, ?) GROUP BY event_type",
            (session_key, EVENT_TOOL_CALLED, EVENT_TOOL_OUTCOME),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        counts = {row[0]: int(row[1]) for row in rows}
        orphans = counts.get(EVENT_TOOL_CALLED, 0) - counts.get(EVENT_TOOL_OUTCOME, 0)
        for _ in range(max(0, orphans)):
            await self.append(
                SessionEvent(
                    session_key=session_key,
                    event_type=EVENT_TOOL_OUTCOME,
                    timestamp=int(time.time()),
                    payload={"outcome": OUTCOME_UNKNOWN, "repaired": True},
                )
            )
        await self.flush()
        return max(0, orphans)

    @staticmethod
    def _sanitize(event: SessionEvent) -> SessionEvent:
        """剔除 payload 敏感键, 并按 _MAX_PAYLOAD_BYTES 截断 (防单条事件膨胀)。"""
        if event.payload:
            event.payload = {
                k: v for k, v in event.payload.items() if k.lower() not in _SENSITIVE_KEYS
            }
        encoded = json.dumps(event.payload, ensure_ascii=False).encode("utf-8")
        if len(encoded) > _MAX_PAYLOAD_BYTES:
            # 超限只保留截断标记, 丢弃超大 payload 内容 (事件本身仍记录类型/时序)。
            event.payload = {"_truncated": True, "original_bytes": len(encoded)}
        return event

    @staticmethod
    def _row_to_event(row: Any) -> SessionEvent:
        return SessionEvent(
            session_key=row[0],
            seq=row[1],
            event_type=row[2],
            timestamp=row[3],
            payload=json.loads(row[4]) if row[4] else {},
        )
