"""原子文件写入工具 (K4, DEVELOPMENT_PLAN.md)。

配置写入 (AgentConfig / RoutingRules / links.jsonc) 都通过本模块, 保证:
- 先写同目录临时文件
- fsync 后用 os.replace 原子替换目标文件 (POSIX 原子, Windows 同卷原子)
- 写盘崩溃不会污染目标文件, 重启时仍能读上一份完整配置
- 异常时清理临时文件, 不留垃圾
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from isac.utils.logger import get_logger

logger = get_logger(__name__)


def atomic_write_text(file_path: str | Path, content: str) -> None:
    """原子写入文本文件: tmp + fsync + os.replace。"""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(file_path: str | Path, data: object, *, indent: int = 2) -> None:
    """原子写入 JSON (utf-8 + ensure_ascii=False + indent)。"""
    import json

    atomic_write_text(file_path, json.dumps(data, ensure_ascii=False, indent=indent))
