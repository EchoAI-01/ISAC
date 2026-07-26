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
        # CR3-Fix: 仅 fsync 文件数据不够 —— os.replace 产生的目录项 (rename) 也要落盘,
        # 否则崩溃/掉电后重启可能读不到刚写入的文件, 与本模块 "重启仍能读上一份完整
        # 配置" 的承诺不符。best-effort 对父目录 fsync (POSIX); 平台不支持时忽略。
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # Windows 等不支持对目录 fsync 的平台: 静默降级
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
