"""J2 制品存储 (SPECIFICATION.md 2.4)。

生成结果写入 ArtifactStore, 返回 ``ArtifactRef``, 再由 Channel Adapter 按平台能力
发送或降级为受控下载链接。二进制内容不得直接塞入对话历史、日志或记忆。

本地 FS + SQLite 元数据实现:
- 文件路径: ``<root_dir>/<sha256[:2]>/<sha256>.bin`` (分桶避免单目录文件过多)
- 元数据 DB: ``<root_dir>/meta.db`` (SQLite, artifact_id PK + expires_at 索引)
- TTL: 默认 7 天, 可经 ttl_days 配置; start_ttl_sweep 周期扫描过期制品
- 写盘幂等: 同内容 sha256 相同, 重复 put 不会覆盖正在被读的文件
- 同步文件 I/O 经 asyncio.to_thread 包装, 不阻塞 event loop (ruff ASYNC240)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite

from isac.artifacts.models import ArtifactRef
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id      TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    mime_type        TEXT,
    size_bytes       INTEGER,
    duration_seconds REAL,
    created_at       INTEGER NOT NULL,
    expires_at       INTEGER NOT NULL DEFAULT 0,
    uri              TEXT,
    metadata         TEXT
);
CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);
"""

_DEFAULT_TTL_DAYS = 7
_DEFAULT_SWEEP_INTERVAL_SECONDS = 3600


def _ensure_dir_sync(path: Path) -> None:
    """同步 mkdir (parents=True, exist_ok=True)。"""
    path.mkdir(parents=True, exist_ok=True)


def _write_file_atomic_sync(file_path: Path, data: bytes) -> None:
    """同步原子写 (tmp + replace); 调用方用 asyncio.to_thread 包装。

    tmp 文件名每次唯一 (含 pid + 随机后缀), 防止并发 put 相同内容时一方抢先
    rename 走另一方的 tmp 抛 FileNotFoundError (虽结果文件已成功, 但调用方
    会误判失败)。file 已存在则跳过 (同内容幂等)。
    """
    if file_path.exists():
        return
    import os
    import uuid

    tmp_path = file_path.with_name(
        f".{file_path.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        tmp_path.write_bytes(data)
        tmp_path.replace(file_path)
    except FileNotFoundError:
        # tmp 被并发 put 抢先 rename 走, 或最终路径已被其他协程创建; 检查目标
        # 是否已存在, 已存在则视为成功 (同内容幂等), 否则真失败再抛。
        if file_path.exists():
            return
        raise
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _read_file_sync(file_path: Path) -> bytes | None:
    """同步读; 文件不存在返回 None (调用方无需 try/except)。"""
    try:
        return file_path.read_bytes()
    except FileNotFoundError:
        return None


def _delete_file_sync(file_path: Path) -> None:
    """同步删文件 (FileNotFoundError 静默); 顺手清理空分桶目录。"""
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass
    try:
        file_path.parent.rmdir()
    except OSError:
        pass  # 非空目录 (还有其他制品) 或已被删, 忽略


class ArtifactStore:
    """多模态制品存储 (本地 FS + SQLite 元数据)。

    生命周期 start/stop 对齐 ApplicationRuntime.register_lifecycle; 也可不经 start
    直接调用 put/get/sweep_expired (内部按需 aiosqlite.connect + 建表)。
    """

    def __init__(self, root_dir: str, *, ttl_days: int = _DEFAULT_TTL_DAYS) -> None:
        self.root_dir = root_dir
        self.ttl_days = ttl_days
        self._db_path = str(Path(root_dir) / "meta.db")
        self._initialized = False
        self._ttl_task: asyncio.Task[Any] | None = None
        self._running = False

    async def _ensure_schema(self) -> None:
        """首次调用建表 + 父目录; 后续调用幂等跳过 (SCHEMA_SQL 都是 IF NOT EXISTS)。"""
        await asyncio.to_thread(_ensure_dir_sync, Path(self.root_dir))
        if self._initialized:
            return
        async with aiosqlite.connect(self._db_path) as db:
            # Fix-28: metadata/vector/graph/usage 四处存储都设了 WAL, 本store 是
            # 唯一遗漏的一个——journal_mode 是数据库文件级持久属性 (不像
            # busy_timeout 是连接级, 只设一次即对该文件之后的所有连接生效),
            # 这里只需在 schema 初始化这一次性代码路径设置。put/get/sweep_expired
            # 各自开短连接, 不设 WAL 时默认走 rollback-journal, 写事务互斥更容易
            # 在多模态制品并发写入量大时触发 database is locked。busy_timeout 不用
            # 显式设置: aiosqlite.connect 透传 stdlib sqlite3 默认 timeout=5.0s,
            # 与其它 store 显式设置的 busy_timeout=5000 等价。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(SCHEMA_SQL)
            await db.commit()
        self._initialized = True

    @staticmethod
    def _compute_artifact_id(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _file_path(self, artifact_id: str) -> Path:
        return Path(self.root_dir) / artifact_id[:2] / f"{artifact_id}.bin"

    def _compute_expires_at(self, explicit: int | None) -> int:
        if explicit is None:
            return int(time.time()) + self.ttl_days * 86400
        return explicit

    async def put(
        self,
        data: bytes,
        *,
        kind: str,
        mime_type: str = "",
        metadata: dict | None = None,
        duration_seconds: float = 0.0,
        expires_at: int | None = None,
    ) -> ArtifactRef:
        """保存二进制制品并返回受控引用。

        Args:
            data: 二进制内容
            kind: image | audio | video | file
            mime_type: 标准 MIME 类型 (image/png 等)
            metadata: 可选业务元数据 (写入 DB, JSON 序列化)
            duration_seconds: 音视频时长 (可选)
            expires_at: None → 按 ttl_days 默认; 0 → 不过期; 正数 → 指定 unix 时间戳
        """
        await self._ensure_schema()
        artifact_id = self._compute_artifact_id(data)
        file_path = self._file_path(artifact_id)
        # 幂等写: 文件已存在则跳过 (同内容重复 put 不覆盖正在被读的文件)
        if not file_path.exists():
            await asyncio.to_thread(_ensure_dir_sync, file_path.parent)
            await asyncio.to_thread(_write_file_atomic_sync, file_path, data)
        now = int(time.time())
        exp = self._compute_expires_at(expires_at)
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                    artifact_id, kind, mime_type, size_bytes, duration_seconds,
                    created_at, expires_at, uri, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, kind, mime_type, len(data), duration_seconds,
                    now, exp, str(file_path), meta_json,
                ),
            )
            await db.commit()
        return ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            mime_type=mime_type,
            uri=str(file_path),
            size_bytes=len(data),
            duration_seconds=duration_seconds,
            created_at=now,
            expires_at=exp,
            metadata=metadata or {},
        )

    async def get(self, artifact_id: str) -> bytes | None:
        """按 artifact_id 读取二进制内容; 不存在或已过期返回 None (并清理过期行)。"""
        await self._ensure_schema()
        now = int(time.time())
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT expires_at FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            exp = row[0]
            if exp > 0 and exp < now:
                await self._delete_artifact(db, artifact_id)
                await db.commit()
                return None
        file_path = self._file_path(artifact_id)
        got = await asyncio.to_thread(_read_file_sync, file_path)
        if got is None:
            # 文件丢失 (可能被外部清理); 同步删 DB 行避免残留
            async with aiosqlite.connect(self._db_path) as db:
                await self._delete_artifact(db, artifact_id)
                await db.commit()
        return got

    async def _delete_artifact(self, db: aiosqlite.Connection, artifact_id: str) -> None:
        """删 DB 行 + 对应磁盘文件 (文件不存在时静默)。"""
        await db.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        await asyncio.to_thread(_delete_file_sync, self._file_path(artifact_id))

    async def sweep_expired(self) -> int:
        """扫描并删除已过期制品 (文件 + DB 行); 返回删除数量。"""
        await self._ensure_schema()
        now = int(time.time())
        deleted = 0
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT artifact_id FROM artifacts WHERE expires_at > 0 AND expires_at < ?",
                (now,),
            )
            rows = await cursor.fetchall()
            for (artifact_id,) in rows:
                await self._delete_artifact(db, artifact_id)
                deleted += 1
            if deleted > 0:
                await db.commit()
        if deleted > 0:
            logger.info("ArtifactStore 清理过期制品", deleted=deleted)
        return deleted

    async def start_ttl_sweep(
        self, *, interval_seconds: int = _DEFAULT_SWEEP_INTERVAL_SECONDS
    ) -> None:
        """启动周期性 TTL 扫描任务 (仿 AlertManager._check_loop)。"""
        if self._running:
            return
        self._running = True
        self._ttl_task = asyncio.create_task(self._ttl_loop(interval_seconds))
        logger.info("ArtifactStore TTL 扫描已启动", interval=interval_seconds)

    async def _ttl_loop(self, interval_seconds: int) -> None:
        while self._running:
            try:
                await self.sweep_expired()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("ArtifactStore TTL 扫描异常", error=str(exc))
            await asyncio.sleep(interval_seconds)

    async def start(self) -> None:
        """生命周期 start: 初始化 schema + 启动周期扫描 (供 ApplicationRuntime)。"""
        await self._ensure_schema()
        await self.start_ttl_sweep()

    async def stop(self) -> None:
        """生命周期 stop: 取消扫描任务 + 兜底 sweep + 关闭。"""
        self._running = False
        if self._ttl_task is not None and not self._ttl_task.done():
            self._ttl_task.cancel()
            try:
                await self._ttl_task
            except asyncio.CancelledError:
                pass
        self._ttl_task = None
        # 兜底: 关闭前再 sweep 一次 (短 TTL 场景下可能清掉刚写入的过期制品)
        try:
            await self.sweep_expired()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ArtifactStore 关闭前 sweep 异常", error=str(exc))

    def make_ref(
        self,
        artifact_id: str,
        *,
        kind: str,
        mime_type: str = "",
        uri: str = "",
    ) -> ArtifactRef:
        """为已存在制品构造一个受控引用 (不落盘, 不查 DB)。"""
        if not uri:
            uri = str(self._file_path(artifact_id))
        return ArtifactRef(artifact_id=artifact_id, kind=kind, mime_type=mime_type, uri=uri)


def make_lifecycle_hooks(
    store: ArtifactStore,
) -> tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[None]]]:
    """构造 (start, stop) 钩子对, 供 ApplicationRuntime.register_lifecycle 使用。"""
    return store.start, store.stop
