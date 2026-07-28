"""GraphStore: 关系图存储 (最小实现: 用户-群-话题关系边)。

EXP-2: 真实实现。用 SQLite 三元组表 graph_edges(agent_id, subject, relation,
object, weight, created_at); subject → relation → object 方向边, weight 表示
关系强度 (默认 1.0)。neighbors 查询节点作为 subject 的所有 object (可选按
relation 过滤)。按 agent_id 命名空间隔离。

设计参考 ARCHITECTURE.md 3.6; 预留图数据库 (Neo4j 等) 切换接口 (本节点用
SQLite 嵌入式方案)。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class GraphStore:
    """SQLite 三元组表关系图存储。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Any = None
        # C1: init_schema TOCTOU 竞态消除 (同 VectorStore 模式)
        self._lock = asyncio.Lock()

    async def init_schema(self) -> None:
        """打开持久连接 + 创建 graph_edges 表。"""
        if self._db is not None:
            return
        async with self._lock:
            if self._db is not None:
                return
            import aiosqlite

            db = await aiosqlite.connect(self.db_path)
            # R6: WAL + busy_timeout (持久连接, 一次设置该连接全程生效)。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_edges (
                    agent_id   TEXT NOT NULL,
                    subject    TEXT NOT NULL,
                    relation   TEXT NOT NULL,
                    object     TEXT NOT NULL,
                    weight     REAL DEFAULT 1.0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (agent_id, subject, relation, object)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_graph_edges_agent_subject ON graph_edges(agent_id, subject)"
            )
            await db.commit()
            self._db = db
        logger.info("GraphStore schema 已初始化", path=self.db_path)

    async def close(self) -> None:
        """关闭持久连接。

        Fix-26: 与 add_edge/delete_by_namespace/neighbors 共享同一把锁 (同
        VectorStore 的问题与修复, 见 vector.py close() 的注释)——之前 close()
        不持锁, 可能在另一协程持锁写入/查询中途把连接关掉。
        """
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None

    async def add_edge(
        self, agent_id: str, subject: str, relation: str, object_: str, weight: float = 1.0
    ) -> None:
        """写入/更新边 (同 (agent_id, subject, relation, object) UPSERT weight)。

        Args:
            agent_id: 命名空间隔离
            subject: 起点 (如 user:u1 / group:g1)
            relation: 关系名 (如 member_of / friend_of)
            object_: 终点
            weight: 关系强度 (默认 1.0)
        """
        await self.init_schema()
        async with self._lock:
            assert self._db is not None
            await self._db.execute(
                "INSERT OR REPLACE INTO graph_edges (agent_id, subject, relation, object, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, subject, relation, object_, weight, int(time.time())),
            )
            await self._db.commit()

    async def neighbors(
        self, agent_id: str, node: str, relation: str | None = None
    ) -> list[tuple[str, float]]:
        """查询节点作为 subject 的所有 object 邻居, 返回 [(object, weight)]。

        Args:
            agent_id: 命名空间隔离
            node: 起点节点
            relation: 可选, 过滤特定关系 (None 表示所有关系)
        """
        await self.init_schema()
        # Fix-26: 读路径纳入锁保护, 避免 close() 在查询执行中途把连接关掉。
        async with self._lock:
            if self._db is None:
                return []
            if relation is None:
                cursor = await self._db.execute(
                    "SELECT object, weight FROM graph_edges WHERE agent_id = ? AND subject = ? ORDER BY weight DESC",
                    (agent_id, node),
                )
            else:
                cursor = await self._db.execute(
                    "SELECT object, weight FROM graph_edges WHERE agent_id = ? AND subject = ? AND relation = ? "
                    "ORDER BY weight DESC",
                    (agent_id, node, relation),
                )
            rows = await cursor.fetchall()
            await cursor.close()
        return [(str(row[0]), float(row[1])) for row in rows]

    async def delete_by_namespace(self, agent_id: str) -> None:
        """删除某 agent_id 命名空间下的所有边。"""
        await self.init_schema()
        async with self._lock:
            assert self._db is not None
            await self._db.execute("DELETE FROM graph_edges WHERE agent_id = ?", (agent_id,))
            await self._db.commit()
