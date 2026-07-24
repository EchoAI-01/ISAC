"""J1 用量事件持久化 (SQLite / aiosqlite)。

骨架状态: Schema + 连接生命周期 + 单条 insert 已就位 (供 recorder flush 落库);
多维聚合查询 (``aggregate``) 是 J1 实现节点重点, 当前返回空列表并标注 TODO。
计量默认关闭, 未启用时本类不会被构造, 也不会创建任何 DB 文件。
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

_INSERT_SQL = """
INSERT OR REPLACE INTO model_usage_events (
    event_id, trace_id, request_id, agent_id, session_id,
    provider, model, modality, operation,
    prompt_tokens, completion_tokens, total_tokens,
    input_units, output_units, unit_name,
    estimated_cost, currency, pricing_version,
    latency_ms, status, fallback_from, created_at
) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?,?)
"""


class UsageStore:
    """模型用量事件持久化存储。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        """打开连接并建表 (ApplicationRuntime 生命周期 start)。"""
        import aiosqlite

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        logger.info("UsageStore schema 已初始化", path=self.db_path)

    async def stop(self) -> None:
        """提交并关闭连接 (生命周期 stop, LIFO)。"""
        if self._db is not None:
            await self._db.commit()
            await self._db.close()
            self._db = None

    async def insert(self, event: ModelUsageEvent) -> None:
        """写入一条用量事件。未 start 时静默跳过 (惰性, 不阻塞主调用)。"""
        if self._db is None:
            return
        await self._db.execute(
            _INSERT_SQL,
            (
                event.event_id,
                event.trace_id,
                event.request_id,
                event.agent_id,
                event.session_id,
                event.provider,
                event.model,
                event.modality,
                event.operation,
                event.usage.prompt_tokens,
                event.usage.completion_tokens,
                event.usage.total_tokens,
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
            ),
        )
        await self._db.commit()

    async def aggregate(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """按维度聚合用量与成本。

        TODO(J1): 按时间 / Provider / 模型 / Agent / 会话 / 模态 / 操作 / 状态 / 回退
        聚合 token、非 Token 单位与成本; 支持时间范围与分组维度参数。
        """
        return []
