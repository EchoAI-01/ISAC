"""日志分级与按模块级别测试 (可观测性增强)。"""

from __future__ import annotations

import logging

import pytest
import structlog

from isac.utils import logger as logmod


def test_resolve_level_from_string() -> None:
    assert logmod._resolve_level("debug", False) == logging.DEBUG
    assert logmod._resolve_level("warning", False) == logging.WARNING
    assert logmod._resolve_level("ERROR", False) == logging.ERROR
    # 未给 level 时按 debug bool 推导
    assert logmod._resolve_level(None, True) == logging.DEBUG
    assert logmod._resolve_level(None, False) == logging.INFO
    # 未知级别名回退 INFO
    assert logmod._resolve_level("bogus", False) == logging.INFO


def test_module_filter_drops_below_threshold() -> None:
    _filter = logmod._make_module_filter({"isac.router": logging.DEBUG}, logging.INFO)
    # isac.router 阈值 DEBUG: debug 事件放行
    passed = _filter(None, "debug", {"logger": "isac.router", "level": "debug"})
    assert passed["level"] == "debug"
    # 其它模块用默认 INFO: debug 事件被丢弃
    with pytest.raises(structlog.DropEvent):
        _filter(None, "debug", {"logger": "isac.memory", "level": "debug"})


def test_module_filter_longest_prefix_wins() -> None:
    _filter = logmod._make_module_filter(
        {"isac": logging.ERROR, "isac.router": logging.DEBUG}, logging.INFO
    )
    # isac.router.* 命中更长前缀 DEBUG → debug 放行
    assert _filter(None, "debug", {"logger": "isac.router.x", "level": "debug"})["level"] == "debug"
    # isac.memory 命中 isac=ERROR → info 被丢
    with pytest.raises(structlog.DropEvent):
        _filter(None, "info", {"logger": "isac.memory", "level": "info"})


def test_per_module_activates_flag_and_resets() -> None:
    logmod.setup_logger(level="info", per_module={"isac.router": "debug"})
    assert logmod._per_module_active is True
    log = logmod.get_logger("isac.router")
    log.debug("smoke")  # 不抛异常即可
    # 复位, 避免污染后续测试的全局日志配置
    logmod.setup_logger(debug=False)
    assert logmod._per_module_active is False


def test_default_setup_has_no_per_module_overhead() -> None:
    logmod.setup_logger(debug=False)
    assert logmod._per_module_active is False
    # 默认路径 get_logger 不绑定 logger 字段, 与历史行为一致
    log = logmod.get_logger("isac.test")
    log.info("smoke")
