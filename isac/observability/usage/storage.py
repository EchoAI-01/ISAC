"""J1 用量事件持久化 (SQLite / aiosqlite)。

Schema + 连接生命周期 + 批量落库 (insert_many) + 分页查询 (list_events) 已实现;
多维聚合查询 (aggregate) 是下一个提交的重点, 当前仍返回空列表。计量默认关闭,
未启用时本类不会被构造, 也不会创建任何 DB 文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite

    from isac.observability.usage.models import ModelUsageEvent

logger = get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model_usage_events (
    event_id        TEXT PRIMARY KEY,
    trace_id        TEXT,
    request_id      TEXT,
    agent_id        TEXT,
    session_id      TEXT,
    provider        TEXT,
    model           TEXT,
    modality        TEXT,
    operation       TEXT,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    total_tokens    INTEGER,
    input_units     REAL,
    output_units    REAL,
    unit_name       TEXT,
    estimated_cost  TEXT,
    currency        TEXT,
    pricing_version TEXT,
    latency_ms      INTEGER,
    status          TEXT,
    fallback_from   TEXT,
    created_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_usage_created ON model_usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_agent ON model_usage_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_model ON model_usage_events(provider, model);
"""

# J1: cache/reasoning/audio 明细列由 _ensure_column() 按需 ALTER TABLE 补齐
# (旧库没有这些列; SQLite ALTER TABLE ADD COLUMN 没有 IF NOT EXISTS, 需先探测)。
_DETAIL_TOKEN_COLUMNS = (
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
)

_INSERT_SQL = """
INSERT OR REPLACE INTO model_usage_events (
    event_id, trace_id, request_id, agent_id, session_id,
    provider, model, modality, operation,
    prompt_tokens, completion_tokens, total_tokens,
    cache_read_tokens, cache_write_tokens, reasoning_tokens,
    audio_input_tokens, audio_output_tokens,
    input_units, output_units, unit_name,
    estimated_cost, currency, pricing_version,
    latency_ms, status, fallback_from, created_at
) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?)
"""

# J1: /usage/models/events 与 /usage/models/summary 共用的过滤字段白名单
# (REST 查询参数 → SQL 列名; 只允许这个固定映射表出现在拼接的 SQL 里)。
_FILTER_COLUMNS = {
    "provider": "provider",
    "model": "model",
    "agent_id": "agent_id",
    "session_id": "session_id",
    "modality": "modality",
    "operation": "operation",
    "status": "status",
}


class UsageStore:
    """模型用量事件持久化存储。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        """打开连接并建表 (ApplicationRuntime 生命周期 start); 迁移旧库缺失的明细列。"""
        import aiosqlite

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA_SQL)
        for column in _DETAIL_TOKEN_COLUMNS:
            await self._ensure_column(column)
        await self._db.commit()
        logger.info("UsageStore schema 已初始化", path=self.db_path)

    async def _ensure_column(self, column: str) -> None:
        """探测列是否存在, 不存在则 ALTER TABLE 补齐 (column 均为硬编码常量, 拼接安全)。"""
        assert self._db is not None
        cursor = await self._db.execute("PRAGMA table_info(model_usage_events)")
        existing_columns = {row[1] for row in await cursor.fetchall()}
        if column not in existing_columns:
            await self._db.execute(f"ALTER TABLE model_usage_events ADD COLUMN {column} INTEGER")

    async def stop(self) -> None:
        """提交并关闭连接 (生命周期 stop, LIFO)。"""
        if self._db is not None:
            await self._db.commit()
            await self._db.close()
            self._db = None

    async def insert(self, event: ModelUsageEvent) -> None:
        """写入一条用量事件 (insert_many 的单条特化, 兼容既有调用点)。"""
        await self.insert_many([event])

    async def insert_many(self, events: list[ModelUsageEvent]) -> None:
        """批量写入用量事件: 一次 executemany + 一次 commit, 避免逐事件提交的 N+1 开销。

        未 start 时静默跳过 (惰性, 不阻塞主调用)。失败时异常向上抛给调用方
        (UsageRecorder.flush 统一记日志丢弃整批), 存储层不重复捕获。
        """
        if self._db is None or not events:
            return
        rows = [self._event_to_row(event) for event in events]
        await self._db.executemany(_INSERT_SQL, rows)
        await self._db.commit()

    @staticmethod
    def _event_to_row(event: ModelUsageEvent) -> tuple[Any, ...]:
        usage = event.usage
        return (
            event.event_id,
            event.trace_id,
            event.request_id,
            event.agent_id,
            event.session_id,
            event.provider,
            event.model,
            event.modality,
            event.operation,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
            usage.reasoning_tokens,
            usage.audio_input_tokens,
            usage.audio_output_tokens,
            event.input_units,
            event.output_units,
            event.unit_name,
            event.estimated_cost,
            event.currency,
            event.pricing_version,
            event.latency_ms,
            event.status,
            event.fallback_from,
            event.created_at,
        )

    async def list_events(
        self, filters: dict[str, Any] | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """按过滤条件分页查询原始用量事件, 按 created_at 降序 (供 /usage/models/events)。"""
        if self._db is None:
            return []
        where_sql, params = self._build_where(filters or {})
        query = f"SELECT * FROM model_usage_events{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"  # noqa: S608
        cursor = await self._db.execute(query, (*params, limit, offset))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _build_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
        """把过滤字段安全拼成 WHERE 子句: 列名固定来自 _FILTER_COLUMNS 白名单,
        值全部走参数绑定, 不做任何用户输入的直接字符串拼接。"""
        clauses: list[str] = []
        params: list[Any] = []
        for key, column in _FILTER_COLUMNS.items():
            value = filters.get(key)
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if filters.get("from_ts") is not None:
            clauses.append("created_at >= ?")
            params.append(filters["from_ts"])
        if filters.get("to_ts") is not None:
            clauses.append("created_at <= ?")
            params.append(filters["to_ts"])
        if not clauses:
            return "", params
        return " WHERE " + " AND ".join(clauses), params

    async def aggregate(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """按维度聚合用量与成本。

        TODO(J1): 按时间 / Provider / 模型 / Agent / 会话 / 模态 / 操作 / 状态 / 回退
        聚合 token、非 Token 单位与成本; 支持时间范围与分组维度参数。
        """
        return []
