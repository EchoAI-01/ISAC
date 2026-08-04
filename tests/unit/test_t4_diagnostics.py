"""T4 错误可诊断测试: LogBuffer + /health 聚合 + LLM 错误中文可操作提示。

覆盖:
- LogBuffer 单例 append/snapshot_after/subscribe 推送
- /health 返回各子系统聚合状态 (agents/llm/channels/control)
- /api/v1/logs/tail SSE 返回 text/event-stream (LogBuffer 启用时)
- LLM _map_http_error 401/429/连接失败 → 引用真实配置路径的中文提示
- _degraded_reply_from_error 按错误类型映射可操作降级文案
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from isac.control.api import routes_logs
from isac.control.api.server import _aggregate_health, create_control_app
from isac.observability import get_default_metrics
from isac.utils.log_buffer import (
    LogBuffer,
    enable_log_buffer,
    get_log_buffer,
    reset_log_buffer,
)


class _StubAM:
    def list(self) -> list[Any]:
        return []

    async def get(self, _: Any) -> None:
        return None


class _StubPM:
    def list(self) -> list[Any]:
        return []

    def for_agent(self, _: Any) -> Any:
        return None


class _StubChannelReg:
    def list(self) -> list[Any]:
        return []

    def get(self, _: Any) -> None:
        return None


class TestLogBuffer:
    def teardown_method(self) -> None:
        reset_log_buffer()

    def test_enable_creates_singleton(self) -> None:
        reset_log_buffer()
        assert get_log_buffer() is None
        buf = enable_log_buffer()
        assert get_log_buffer() is buf
        # 幂等
        assert enable_log_buffer() is buf

    def test_append_and_snapshot_after(self) -> None:
        buf = LogBuffer(max_buffer=10)
        buf.append({"level": "info", "event": "a"})
        buf.append({"level": "warning", "event": "b"})
        assert buf.seq == 2
        after1 = buf.snapshot_after(1)
        assert len(after1) == 1
        assert after1[0]["event"] == "b"
        assert after1[0]["_seq"] == 2

    def test_buffer_drops_oldest_at_max(self) -> None:
        buf = LogBuffer(max_buffer=3)
        for i in range(5):
            buf.append({"event": f"e{i}"})
        snap = buf.snapshot_after(0)
        assert len(snap) == 3  # 超限丢最旧
        assert snap[0]["event"] == "e2"

    def test_subscribe_receives_new_entries(self) -> None:
        async def _run() -> None:
            buf = LogBuffer()
            q = await buf.subscribe()
            buf.append({"level": "info", "event": "hello"})
            entry = await asyncio.wait_for(q.get(), timeout=1.0)
            assert entry["event"] == "hello"
            await buf.unsubscribe(q)

        asyncio.run(_run())


class TestHealthEndpoint:
    def test_health_returns_aggregated_status(self) -> None:
        reset_log_buffer()
        app = create_control_app(
            _StubAM(), object(), object(), object(),
            {"api_token": "", "enabled": False},
            metrics=get_default_metrics(),
            provider_manager=_StubPM(),
            channel_registry=_StubChannelReg(),
        )
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "subsystems" in body
        assert "agents" in body["subsystems"]
        assert "llm" in body["subsystems"]
        assert "channels" in body["subsystems"]
        assert "control" in body["subsystems"]
        # 无 Agent 无 Channel → degraded
        assert body["status"] == "degraded"

    def test_aggregate_health_with_running_agent_is_ok(self) -> None:
        class _A:
            status = "running"

        class _AM:
            def list(self) -> list[Any]:
                return [_A()]

        result = _aggregate_health(_AM(), _StubPM(), {"enabled": False}, _StubChannelReg())
        assert result["status"] == "ok"
        assert result["subsystems"]["agents"]["running"] == 1


class TestLogsTailSSE:
    def teardown_method(self) -> None:
        reset_log_buffer()

    def test_logs_tail_returns_sse_when_buffer_enabled(self) -> None:
        reset_log_buffer()
        buf = enable_log_buffer()
        # 预填一条日志, 让 SSE generator 回放 snapshot 后立即有 chunk 可读 (max_chunks=1 退出)
        buf.append({"level": "info", "event": "boot", "logger": "test"})
        app = create_control_app(
            _StubAM(), object(), object(), object(),
            {"api_token": "", "enabled": False},
            metrics=get_default_metrics(),
            channel_registry=_StubChannelReg(),
        )
        client = TestClient(app)
        with client.stream(
            "GET", "/api/v1/logs/tail?heartbeat_seconds=0.05&max_chunks=1",
            headers={"Accept": "text/event-stream"},
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            chunk = next(resp.iter_bytes(), None)
            assert chunk is not None

    def test_logs_router_not_mounted_when_buffer_disabled(self) -> None:
        """LogBuffer 未启用时 routes_logs.build_router 返回 None。"""
        reset_log_buffer()
        assert get_log_buffer() is None
        assert routes_logs.build_router() is None


class TestLLMErrorMapping:
    """T4: LLM 错误映射成引用真实配置路径的中文可操作提示。"""

    def test_401_references_api_key_path(self) -> None:
        from isac.provider.llm.openai_compat import OpenAICompatProvider

        err = OpenAICompatProvider._map_http_error(401, b'{"error":"invalid api key"}')
        assert "鉴权失败" in str(err)
        assert "llm.api_key" in str(err)
        assert err.retriable is False

    def test_429_is_rate_limit_with_chinese(self) -> None:
        from isac.core.exceptions import RateLimitError
        from isac.provider.llm.openai_compat import OpenAICompatProvider

        err = OpenAICompatProvider._map_http_error(429, b"slow down")
        assert isinstance(err, RateLimitError)
        assert "限流" in str(err)

    def test_network_error_references_base_url(self) -> None:
        from isac.provider.llm.openai_compat import OpenAICompatProvider

        err = OpenAICompatProvider._wrap_network_error(ConnectionError("refused"))
        assert "无法连接" in str(err)
        assert "llm.base_url" in str(err)
        assert err.retriable is True

    def test_degraded_reply_from_401_is_actionable(self) -> None:
        from isac.provider.llm.openai_compat import OpenAICompatProvider
        from isac.provider.manager import _degraded_reply_from_error

        err = OpenAICompatProvider._map_http_error(401, b"bad key")
        reply = _degraded_reply_from_error(err)
        assert "api_key" in reply  # 引用配置路径, 可操作

    def test_degraded_reply_from_rate_limit_is_friendly(self) -> None:
        from isac.core.exceptions import RateLimitError
        from isac.provider.manager import _degraded_reply_from_error

        reply = _degraded_reply_from_error(RateLimitError("429"))
        assert "限流" in reply
