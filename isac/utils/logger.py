"""结构化日志 (DEVELOP.md 六)。

开发环境: 彩色控制台输出；生产环境: JSON 格式 (log_level/format 由配置决定)。
structlog 不可用时回退到标准库 logging，保证框架可导入。

分级:
- 全局级别由 ``level`` (字符串 debug/info/warning/error) 或 ``debug`` bool 决定。
- ``per_module`` 可按模块前缀单独设级 (如只放开 ``isac.router`` 的 debug),
  未配置时行为与全局级别完全一致、零额外开销。

trace 贯穿见 ``logging_context.bind_log_context`` —— 处理器链已装配
``merge_contextvars``,绑定的字段自动出现在其后每条日志。
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
_per_module_active = False

# 级别名 → stdlib 数值 (统一 debug/info/warning/error 的解析)
_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _resolve_level(level: str | None, debug: bool) -> int:
    """把配置里的级别字符串解析为 stdlib 数值;缺省时按 debug bool 推导。"""
    if level:
        return _LEVEL_MAP.get(level.strip().lower(), logging.INFO)
    return logging.DEBUG if debug else logging.INFO


def _make_module_filter(per_module: dict[str, int], default_level: int) -> Any:
    """构造按模块前缀过滤的 structlog processor。

    按最长前缀匹配模块阈值;事件级别低于阈值则丢弃 (DropEvent)。
    仅在 ``per_module`` 非空时挂入处理器链,默认路径不承担此开销。
    """
    items = sorted(per_module.items(), key=lambda kv: len(kv[0]), reverse=True)

    def _filter(logger: Any, method_name: str, event_dict: dict) -> dict:
        name = str(event_dict.get("logger", ""))
        threshold = default_level
        for prefix, lvl in items:
            if name.startswith(prefix):
                threshold = lvl
                break
        event_level = _LEVEL_MAP.get(str(event_dict.get("level", method_name)), default_level)
        if event_level < threshold:
            raise structlog.DropEvent
        return event_dict

    return _filter


def setup_logger(
    debug: bool = False,
    log_format: str = "console",
    level: str | None = None,
    per_module: dict[str, str] | None = None,
) -> None:
    """初始化全局日志配置。

    Args:
        debug: 是否 DEBUG 级别 (``level`` 未给时生效,向后兼容)。
        log_format: "console" (开发，彩色) | "json" (生产，ELK/Loki 采集)。
        level: 全局级别字符串 debug/info/warning/error;优先于 ``debug``。
        per_module: {模块前缀: 级别} 覆盖表,如 {"isac.router": "debug"}。
    """
    global _configured, _per_module_active
    global_level = _resolve_level(level, debug)
    per_module_int = {key: _resolve_level(str(val), False) for key, val in (per_module or {}).items()}
    _per_module_active = bool(per_module_int)

    if _HAS_STRUCTLOG:
        processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ]
        if per_module_int:
            # 全局 wrapper 放到最低阈值, 由 filter processor 按模块精确过滤。
            wrapper_level = min(global_level, *per_module_int.values())
            processors.append(_make_module_filter(per_module_int, global_level))
        else:
            wrapper_level = global_level
        if log_format == "json":
            processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=True))
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(wrapper_level),
            logger_factory=structlog.PrintLoggerFactory(sys.stderr),
            cache_logger_on_first_use=True,
        )
    else:
        logging.basicConfig(
            stream=sys.stderr, level=global_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )

    _configured = True


def get_logger(name: str) -> Any:
    """获取带模块名的 logger。用法见 DEVELOP.md 2.1 日志规范。

    仅当配置了 ``per_module`` 时才把模块名绑定进事件 (供 filter processor 使用),
    默认路径返回原始 logger,输出与历史行为一致。
    """
    if not _configured:
        setup_logger()
    if _HAS_STRUCTLOG:
        log = structlog.get_logger(name)
        if _per_module_active:
            return log.bind(logger=name)
        return log
    return logging.getLogger(name)
