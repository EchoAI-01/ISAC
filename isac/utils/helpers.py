"""通用辅助函数。"""

from __future__ import annotations

import time
import uuid


def new_id(prefix: str) -> str:
    """生成带前缀的短唯一 ID，如 msg_3f2a1b9c。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def unix_now() -> int:
    """当前 Unix 时间戳 (秒)。"""
    return int(time.time())
