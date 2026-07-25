"""J4 子任务追加式日志 (SPECIFICATION.md 2.5)。

按 ``(task_id, seq)`` 追加持久化; 重启后可恢复终态日志。日志记录可审计事实, 不记录
模型原始 reasoning; 凭据和敏感工具参数必须在持久化前脱敏。

骨架状态: Schema + append/fetch_after/upsert_run/restore 就位, append/fetch 已可用于
测试; 脱敏为基础键名过滤占位, 统一脱敏器与 max_log_bytes 截断留待 J4 实现节点。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.core.types import TokenUsage
from isac.runtime.subagent.models import SubAgentEvent, SubAgentRun
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite

logger = get_logger(__name__)

# 脱敏时从 metadata 中剔除的敏感键 (占位; 实现节点接入统一脱敏器 / SecretStore)。
_SENSITIVE_KEYS = frozenset({"api_key", "token", "authorization", "cookie", "secret", "password", "arguments"})

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subagent_events (
    task_id       TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    event_type    TEXT,
    timestamp     INTEGER,
    summary       TEXT,
    tool_name     TEXT,
    usage_total   INTEGER,
    evidence_refs TEXT,
    metadata      TEXT,
    PRIMARY KEY (task_id, seq)
);
CREATE TABLE IF NOT EXISTS subagent_runs (
    task_id        TEXT PRIMARY KEY,
    status         TEXT,
    phase          TEXT,
    started_at     INTEGER,
    updated_at     INTEGER,
    finished_at    INTEGER,
    tokens_used    INTEGER,
    tool_calls_used INTEGER,
    error_code     TEXT,
    error_summary  TEXT,
    result_summary TEXT
);
"""

# J4-2: result_summary 列由 _ensure_column() 按需 ALTER TABLE 补齐 (旧库无此列)
_NEW_RUN_COLUMNS: tuple[tuple[str, str], ...] = (("result_summary", "TEXT"),)


class SubAgentJournal:
    """子任务事件与运行状态的持久化日志。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        """打开连接并建表 (生命周期 start)。"""
        import aiosqlite

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA_SQL)
        # J4-2: 旧库迁移补 result_summary 列
        for col, decl in _NEW_RUN_COLUMNS:
            await self._ensure_column(self._db, "subagent_runs", col, decl)
        await self._db.commit()
        logger.info("SubAgentJournal schema 已初始化", path=self.db_path)

    @staticmethod
    async def _ensure_column(db: Any, table: str, column: str, decl_type: str) -> None:
        """SQLite ALTER TABLE ADD COLUMN 没有 IF NOT EXISTS, 需先探测再决定是否执行。"""
        cursor = await db.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        await cursor.close()
        existing = {row[1] for row in rows}
        if column not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl_type}")

    async def stop(self) -> None:
        """提交并关闭连接 (生命周期 stop)。"""
        if self._db is not None:
            await self._db.commit()
            await self._db.close()
            self._db = None

    async def append(self, event: SubAgentEvent) -> None:
        """追加一条已脱敏事件。未 start 时静默跳过 (不阻塞主任务)。

        seq 自动分配: event.seq<=0 时由 DB 查 MAX(seq)+1 分配; >0 时保留调用方值
        (用于测试或幂等重放)。
        """
        if self._db is None:
            return
        event = self._sanitize(event)
        # seq<=0 视为"自动分配", 避免覆盖同 (task_id, 0) 的旧行
        if event.seq <= 0:
            cursor = await self._db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM subagent_events WHERE task_id = ?",
                (event.task_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            seq = int(row[0]) if row is not None else 1
        else:
            seq = event.seq
        await self._db.execute(
            "INSERT OR REPLACE INTO subagent_events "
            "(task_id, seq, event_type, timestamp, summary, tool_name, usage_total, evidence_refs, metadata) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                event.task_id,
                seq,
                event.event_type,
                event.timestamp,
                event.summary,
                event.tool_name,
                event.usage.total_tokens if event.usage is not None else 0,
                json.dumps(event.evidence_refs, ensure_ascii=False),
                json.dumps(event.metadata, ensure_ascii=False),
            ),
        )
        await self._db.commit()

    async def fetch_after(self, task_id: str, after_seq: int, limit: int) -> list[SubAgentEvent]:
        """按 seq 分页读取某任务的事件 (after_seq 之后, 最多 limit 条)。"""
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT task_id, seq, event_type, timestamp, summary, tool_name, usage_total, evidence_refs, metadata "
            "FROM subagent_events WHERE task_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
            (task_id, after_seq, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [self._row_to_event(row) for row in rows]

    async def upsert_run(self, run: SubAgentRun) -> None:
        """写入 / 更新运行状态, 供重启恢复终态。未 start 时静默跳过。"""
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO subagent_runs "
            "(task_id, status, phase, started_at, updated_at, finished_at, tokens_used, tool_calls_used, "
            "error_code, error_summary, result_summary) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.task_id,
                run.status,
                run.phase,
                run.started_at,
                run.updated_at,
                run.finished_at,
                run.tokens_used,
                run.tool_calls_used,
                run.error_code,
                run.error_summary,
                run.result_summary,
            ),
        )
        await self._db.commit()

    async def restore(self) -> list[SubAgentRun]:
        """恢复已持久化的运行状态 (供 Supervisor 重启后重建索引)。

        TODO(J4): 运行中任务按配置恢复或标记中断; 当前返回全部持久化 run。
        """
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT task_id, status, phase, started_at, updated_at, finished_at, tokens_used, tool_calls_used, "
            "error_code, error_summary, result_summary FROM subagent_runs"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            SubAgentRun(
                task_id=row[0],
                status=row[1],
                phase=row[2],
                started_at=row[3],
                updated_at=row[4],
                finished_at=row[5],
                tokens_used=row[6],
                tool_calls_used=row[7],
                error_code=row[8],
                error_summary=row[9],
                result_summary=row[10] if len(row) > 10 else "",
            )
            for row in rows
        ]

    def _sanitize(self, event: SubAgentEvent) -> SubAgentEvent:
        """剔除敏感 metadata 键 (占位; 不记录 reasoning, max_log_bytes 截断留待实现节点)。"""
        if event.metadata:
            event.metadata = {k: v for k, v in event.metadata.items() if k.lower() not in _SENSITIVE_KEYS}
        return event

    @staticmethod
    def _row_to_event(row: Any) -> SubAgentEvent:
        return SubAgentEvent(
            task_id=row[0],
            seq=row[1],
            event_type=row[2],
            timestamp=row[3],
            summary=row[4],
            tool_name=row[5] or "",
            usage=TokenUsage(total_tokens=row[6] or 0),
            evidence_refs=json.loads(row[7]) if row[7] else [],
            metadata=json.loads(row[8]) if row[8] else {},
        )
