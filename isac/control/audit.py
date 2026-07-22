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


class AuditLog:
    """控制面审计日志。

    双写: 结构化日志 (structlog) + 持久化到 data/audit.ndjson
    (一行一条 JSON, 便于后续查询)。
    """

    def __init__(self, log_path: str | Path | None = None, in_memory_size: int = 1000) -> None:
        self.log_path = Path(log_path) if log_path else None
        self._buffer: deque[dict[str, Any]] = deque(maxlen=in_memory_size)
        self._lock = asyncio.Lock()

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
            self._append_to_file(entry)
        return entry

    def _append_to_file(self, entry: dict[str, Any]) -> None:
        """追加到 NDJSON 文件 (同步 IO, 但只写一行, 阻塞时间很短)。"""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
            with self.log_path.open("a", encoding="utf-8") as fp:  # type: ignore[union-attr]
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 审计失败不应影响主流程
            logger.warning("审计日志写入失败", error=str(exc))

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
