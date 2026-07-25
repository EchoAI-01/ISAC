"""日志上下文贯穿测试 (可观测性增强)。"""

from __future__ import annotations

import structlog

from isac.utils.logging_context import bind_log_context, clear_log_context, get_log_context


def test_bind_adds_fields_to_context() -> None:
    clear_log_context()
    with bind_log_context(trace_id="t1", session_id="s1", agent_id="a1"):
        ctx = get_log_context()
        assert ctx.get("trace_id") == "t1"
        assert ctx.get("session_id") == "s1"
        assert ctx.get("agent_id") == "a1"


def test_context_cleared_after_exit() -> None:
    clear_log_context()
    with bind_log_context(trace_id="t1"):
        pass
    assert "trace_id" not in get_log_context()


def test_nested_bind_restores_outer_value_on_inner_exit() -> None:
    clear_log_context()
    with bind_log_context(trace_id="outer"):
        with bind_log_context(trace_id="inner"):
            assert get_log_context().get("trace_id") == "inner"
        # 内层退出后应恢复外层值, 而非清空
        assert get_log_context().get("trace_id") == "outer"


def test_none_fields_are_skipped() -> None:
    clear_log_context()
    with bind_log_context(trace_id="t1", agent_id=None):
        ctx = get_log_context()
        assert ctx.get("trace_id") == "t1"
        assert "agent_id" not in ctx


def test_bound_fields_appear_in_log_output() -> None:
    """端到端: 绑定的字段应经 merge_contextvars 出现在结构化日志事件里。"""
    clear_log_context()
    cap = structlog.testing.LogCapture()
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, cap])
    try:
        with bind_log_context(trace_id="t-log"):
            structlog.get_logger("test").info("hello")
    finally:
        structlog.reset_defaults()
    assert cap.entries[0]["trace_id"] == "t-log"


def test_clear_removes_all_fields() -> None:
    with bind_log_context(trace_id="t1", session_id="s1"):
        clear_log_context()
        assert get_log_context() == {}
