"""VectorStore: sqlite-vec 向量存储 (ADR-003 嵌入式方案)。

EXP-1: 真实实现。用 sqlite-vec 的 vec0 虚拟表存储向量, KNN 查询返回
(memory_id, distance)。

vectors 通过 memory_id 关联 MetadataStore; 按 agent_id 过滤在查询层完成
(VectorStore 本身不隔离 agent_id, 由调用方 SQL JOIN episodes 实现)。

生命周期: init_schema 打开持久连接 (复用, 支持 :memory: 内存库);
close 关闭连接。未 close 时进程退出连接自动释放。
"""

from __future__ import annotations

import asyncio
import struct
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class VectorStore:
    """sqlite-vec 向量存储。"""

    def __init__(self, db_path: str, dimension: int = 1024):
        self.db_path = db_path
        self.dimension = dimension
        self._db: Any = None  # 持久连接 (init_schema 后打开)
        # C1: init_schema TOCTOU 竞态消除。两个协程同时调 init_schema,
        # 都通过 `if self._db is not None: return` 检查后各自 await
        # aiosqlite.connect(...) (yield 点), 第一个完成赋值 self._db,
        # 第二个完成时覆盖 self._db 导致第一个连接泄漏 (FD + WAL/SHM 残留)。
        # 锁让 init_schema 串行化, 第二个协程等锁释放后检查 self._db
        # 已非 None, 直接 return。
        self._init_lock = asyncio.Lock()

    async def init_schema(self) -> None:
        """加载 sqlite-vec 扩展 + 创建 vec0 虚拟表 + 打开持久连接。"""
        if self._db is not None:
            return
        async with self._init_lock:
            # 双重检查: 等锁期间可能有别的协程完成了 init_schema
            if self._db is not None:
                return
            import aiosqlite
            import sqlite_vec

            db = await aiosqlite.connect(self.db_path)
            await db.enable_load_extension(True)
            await db.load_extension(sqlite_vec.loadable_path())
            await db.enable_load_extension(False)
            # R6: WAL + busy_timeout (持久连接, 一次设置该连接全程生效)。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vectors USING vec0("
                f"memory_id TEXT PRIMARY KEY, embedding float[{self.dimension}])"
            )
            await db.commit()
            self._db = db
        logger.info("VectorStore schema 已初始化", path=self.db_path, dim=self.dimension)

    async def close(self) -> None:
        """关闭持久连接。"""
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def upsert(self, memory_id: str, embedding: list[float]) -> None:
        """写入/更新向量 (同 memory_id 覆盖; vec0 不支持 INSERT OR REPLACE, 先 DELETE 再 INSERT)。

        Args:
            memory_id: 关联 MetadataStore.episodes.id
            embedding: float[self.dimension] 维度必须一致
        """
        await self.init_schema()
        if len(embedding) != self.dimension:
            raise ValueError(
                f"embedding 维度 {len(embedding)} 与 store.dimension {self.dimension} 不匹配"
            )
        # C1: upsert 的 DELETE→INSERT→commit 在共享持久连接上无锁, 并发
        # 写入交错 (A 的 DELETE→B 的 INSERT→A 的 INSERT→B 的 commit) 会让
        # A 的 INSERT 丢失 (B 的 commit 不含 A 的 INSERT)。用 _db 上的
        # execute 串行 (aiosqlite 单连接已序列化), 但 commit 仍可能交错;
        # 用 lock 包住整个事务消除竞态。
        async with self._init_lock:
            assert self._db is not None
            await self._db.execute("DELETE FROM vectors WHERE memory_id = ?", (memory_id,))
            await self._db.execute(
                "INSERT INTO vectors (memory_id, embedding) VALUES (?, ?)",
                (memory_id, self._encode_embedding(embedding)),
            )
            await self._db.commit()

    async def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """KNN 查询: 返回 [(memory_id, distance)], 按距离升序 (越小越相似)。

        Args:
            query_embedding: 查询向量 (维度必须与 store.dimension 一致)
            top_k: 返回前 K 个最近邻
        """
        await self.init_schema()
        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"query 维度 {len(query_embedding)} 与 store.dimension {self.dimension} 不匹配"
            )
        cursor = await self._db.execute(
            "SELECT memory_id, distance FROM vectors "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (self._encode_embedding(query_embedding), top_k),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [(str(row[0]), float(row[1])) for row in rows]

    async def delete(self, memory_id: str) -> None:
        """删除向量。"""
        await self.init_schema()
        async with self._init_lock:
            assert self._db is not None
            await self._db.execute("DELETE FROM vectors WHERE memory_id = ?", (memory_id,))
            await self._db.commit()

    def _encode_embedding(self, embedding: list[float]) -> bytes:
        """把 list[float] 编码为 vec0 接受的二进制格式 (float32 little-endian)。

        sqlite-vec 0.1.x 接受 struct.pack('<%df' % len, *embedding) 二进制格式。
        """
        return struct.pack(f"<{len(embedding)}f", *embedding)
