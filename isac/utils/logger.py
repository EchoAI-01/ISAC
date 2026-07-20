"""结构化日志 (DEVELOP.md 六)。

开发环境: 彩色控制台输出；生产环境: JSON 格式 (log_level/format 由配置决定)。
structlog 不可用时回退到标准库 logging，保证框架可导入。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover
    _HAS_STRUCTLOG = False

_configured = False


def setup_logger(debug: bool = False, log_format: str = "console") -> None:
    """初始化全局日志配置。

    Args:
        debug: 是否 DEBUG 级别
        log_format: "console" (开发，彩色) | "json" (生产，ELK/Loki 采集)
    """
    global _configured
    level = logging.DEBUG if debug else logging.INFO

    if _HAS_STRUCTLOG:
        processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ]
        if log_format == "json":
            processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=True))
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=structlog.PrintLoggerFactory(sys.stderr),
            cache_logger_on_first_use=True,
        )
    else:
        logging.basicConfig(stream=sys.stderr, level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    _configured = True


def get_logger(name: str) -> Any:
    """获取带模块名的 logger。用法见 DEVELOP.md 2.1 日志规范。"""
    if not _configured:
        setup_logger()
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name)
