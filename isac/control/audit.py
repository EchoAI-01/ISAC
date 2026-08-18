"""控制面审计日志 (DEVELOP.md 7.4)。

记录所有写操作 (POST/PUT/DELETE) 的请求者、动作、目标资源、结果, 写入审计日志文件。
读操作 (GET) 不记录。审计日志可查询 (按时间/动作/资源过滤)。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# Fix-134: 审计 NDJSON 单文件上限与保留份数 —— 此前 audit.ndjson 只追加不轮转,
# 长期运行无界增长占满磁盘。超限后滚动为 audit.ndjson.1/.2/… (超出 backup_count 的
# 最旧份删除), 主文件重新计数。轮转是运维卫生, 不影响审计内容 (旧份仍可查)。
DEFAULT_AUDIT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_AUDIT_BACKUP_COUNT = 3


class AuditLog:
    """控制面审计日志。

    双写: 结构化日志 (structlog) + 持久化到 data/audit.ndjson
    (一行一条 JSON, 便于后续查询)。
    """

    def __init__(
        self,
        log_path: str | Path | None = None,
        in_memory_size: int = 1000,
        max_bytes: int = DEFAULT_AUDIT_MAX_BYTES,
        backup_count: int = DEFAULT_AUDIT_BACKUP_COUNT,
    ) -> None:
        self.log_path = Path(log_path) if log_path else None
        self._buffer: deque[dict[str, Any]] = deque(maxlen=in_memory_size)
        self._lock = asyncio.Lock()
        # Fix-134: 轮转参数 (非正值回落到默认, 保证至少能轮转)。
        self._max_bytes = max(1024, int(max_bytes))
        self._backup_count = max(1, int(backup_count))

    async def record(
        self,
        *,
        actor: str = "anonymous",
        method: str,
        path: str,
        action: str,
        target: str = "",
        status_code: int = 200,
        detail: str = "",
    ) -> dict[str, Any]:
        """记录一条审计日志。读操作 (GET) 不调用此方法。"""
        entry = {
            "timestamp": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "actor": actor,
            "method": method,
            "path": path,
            "action": action,
            "target": target,
            "status_code": status_code,
            "detail": detail,
        }
        async with self._lock:
            self._buffer.append(entry)
        logger.info(
            "控制面审计",
            actor=actor,
            method=method,
            path=path,
            action=action,
            target=target,
            status_code=status_code,
        )
        if self.log_path is not None:
            # R11: 文件 IO (mkdir/open/write) 是同步阻塞, 审计爆发时
            # 阻塞整个事件循环。用 asyncio.to_thread 包装到线程池。
            await asyncio.to_thread(self._append_to_file, entry)
        return entry

    def _append_to_file(self, entry: dict[str, Any]) -> None:
        """追加到 NDJSON 文件 (同步 IO, 但只写一行, 阻塞时间很短)。"""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
            self._rotate_if_needed()  # Fix-134: 超限先滚动, 再写新行
            with self.log_path.open("a", encoding="utf-8") as fp:  # type: ignore[union-attr]
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 审计失败不应影响主流程
            logger.warning("审计日志写入失败", error=str(exc))

    def _rotate_if_needed(self) -> None:
        """Fix-134: 主文件超 max_bytes 时滚动为编号备份 (同步 IO, 调用方已在线程池)。

        audit.ndjson → audit.ndjson.1, 既有 .1 → .2 … 依次后移, 超过 backup_count
        的最旧份删除。任一文件不存在/移动失败都静默跳过 (轮转失败不阻塞写入,
        最坏退化为不轮转)。
        """
        assert self.log_path is not None
        try:
            if not self.log_path.exists() or self.log_path.stat().st_size < self._max_bytes:
                return
        except OSError:
            return
        # 先删超出保留数的最旧份, 再从最旧到最新依次后移
        oldest = self.log_path.with_name(f"{self.log_path.name}.{self._backup_count}")
        try:
            if oldest.exists():
                oldest.unlink()
        except OSError:
            pass
        for idx in range(self._backup_count - 1, 0, -1):
            src = self.log_path.with_name(f"{self.log_path.name}.{idx}")
            dst = self.log_path.with_name(f"{self.log_path.name}.{idx + 1}")
            try:
                if src.exists():
                    src.rename(dst)
            except OSError:
                continue
        try:
            self.log_path.rename(self.log_path.with_name(f"{self.log_path.name}.1"))
        except OSError as exc:
            logger.warning("审计日志轮转失败, 继续追加原文件", error=str(exc))

    def query(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        path_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查询最近 N 条审计日志 (从内存缓冲)。

        过滤条件按全等匹配 (action/actor), path_prefix 按前缀匹配。
        返回最新到最旧的列表, 最多 limit 条。
        """
        results: list[dict[str, Any]] = []
        for entry in reversed(self._buffer):
            if action and entry["action"] != action:
                continue
            if actor and entry["actor"] != actor:
                continue
            if path_prefix and not entry["path"].startswith(path_prefix):
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results
