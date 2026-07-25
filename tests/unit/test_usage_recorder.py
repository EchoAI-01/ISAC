"""J1 模型用量计量框架骨架测试。

覆盖数据契约、定价 (未知价 → None)、缓冲/落库/失败隔离, 以及 ProviderManager
在成功/失败两条路径都记录一次物理请求。真实多维聚合属实现节点范畴, 不在此覆盖。
"""

from __future__ import annotations

import pytest

from isac.core.types import LLMResponse, TokenUsage
from isac.observability.usage.models import ModelUsageEvent
from isac.observability.usage.pricing import PriceSnapshot, PricingCatalog
from isac.observability.usage.recorder import UsageRecorder
from isac.observability.usage.storage import UsageStore
from isac.provider.manager import ProviderManager


class _FakeProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def chat(self, **kwargs) -> LLMResponse:
        if self._fail:
            raise RuntimeError("boom")
        return LLMResponse(content="ok", usage=TokenUsage(prompt_tokens=3, completion_tokens=5), model="m")

    def get_model_name(self) -> str:
        return "fake-model"

    def get_capabilities(self):
        return None

    def chat_stream(self, *a, **k):
        raise NotImplementedError


def _event(**kw) -> ModelUsageEvent:
    base = dict(
        event_id="e1",
        trace_id="",
        request_id="",
        agent_id="a1",
        session_id="s1",
        provider="P",
        model="m",
        modality="text",
        operation="chat",
    )
    base.update(kw)
    return ModelUsageEvent(**base)  # type: ignore[arg-type]


def test_model_usage_event_defaults() -> None:
    event = _event()
    assert event.estimated_cost is None
    assert event.status == "success"
    assert event.usage.total_tokens == 0


def test_pricing_unknown_model_returns_none() -> None:
    catalog = PricingCatalog(version="2026-07")
    assert catalog.estimate_cost(_event()) is None


def test_pricing_known_model_computes_cost() -> None:
    catalog = PricingCatalog(
        [PriceSnapshot("P", "m", "text", "2026-07", input_price_per_unit="0.01", output_price_per_unit="0.03")],
        version="2026-07",
    )
    event = _event(usage=TokenUsage(prompt_tokens=2, completion_tokens=1))
    # 0.01*2 + 0.03*1 = 0.05
    assert catalog.estimate_cost(event) == "0.05"


def test_pricing_cache_read_tokens_priced_at_discounted_rate() -> None:
    """J1: cache_read_tokens 是 prompt_tokens 子集, 按专属 (更低) 价计价, 不重复计入基础价。"""
    catalog = PricingCatalog(
        [
            PriceSnapshot(
                "P", "m", "text", "v1",
                input_price_per_unit="0.01",
                output_price_per_unit="0.03",
                cache_read_price_per_unit="0.001",
            )
        ],
        version="v1",
    )
    # prompt_tokens=100, 其中 80 是 cache_read (子集); 20 非缓存按基础价, 80 按缓存价
    event = _event(usage=TokenUsage(prompt_tokens=100, completion_tokens=0, cache_read_tokens=80))
    # 20*0.01 + 80*0.001 = 0.200 + 0.080 = 0.280 (Decimal 加法保留两个乘数中较高精度的小数位)
    assert catalog.estimate_cost(event) == "0.280"


def test_pricing_cache_read_tokens_fall_back_to_input_price_when_unset() -> None:
    """未配置专属缓存价时回退到基础 input 价, 向后兼容。"""
    catalog = PricingCatalog(
        [PriceSnapshot("P", "m", "text", "v1", input_price_per_unit="0.01", output_price_per_unit="0.03")],
        version="v1",
    )
    event = _event(usage=TokenUsage(prompt_tokens=100, completion_tokens=0, cache_read_tokens=80))
    # 未设专属价 → 100 全按 input 价: 100*0.01 = 1.00
    assert catalog.estimate_cost(event) == "1.00"


def test_pricing_audio_tokens_priced_separately() -> None:
    """audio_input/output_tokens 是 prompt/completion_tokens 子集, 按专属价计价。"""
    catalog = PricingCatalog(
        [
            PriceSnapshot(
                "P", "m", "text", "v1",
                input_price_per_unit="0.01",
                output_price_per_unit="0.03",
                audio_input_price_per_unit="0.1",
                audio_output_price_per_unit="0.2",
            )
        ],
        version="v1",
    )
    event = _event(
        usage=TokenUsage(prompt_tokens=10, completion_tokens=10, audio_input_tokens=4, audio_output_tokens=2)
    )
    # prompt: (10-4)*0.01 + 4*0.1 = 0.06 + 0.4 = 0.46
    # completion: (10-2)*0.03 + 2*0.2 = 0.24 + 0.4 = 0.64
    # total = 1.10
    assert catalog.estimate_cost(event) == "1.10"


def test_pricing_cache_write_tokens_added_as_extra_charge() -> None:
    """cache_write_tokens 目前无 Provider 产生非 0 值; 公式按专属价 (或回退 input 价)
    作为额外加项计入, 不从 prompt_tokens 等字段中减去 (它不是任何字段的子集)。"""
    catalog = PricingCatalog(
        [
            PriceSnapshot(
                "P", "m", "text", "v1",
                input_price_per_unit="0.01",
                output_price_per_unit="0.03",
                cache_write_price_per_unit="0.02",
            )
        ],
        version="v1",
    )
    event = _event(usage=TokenUsage(prompt_tokens=10, completion_tokens=0, cache_write_tokens=5))
    # 10*0.01 + 5*0.02 = 0.10 + 0.10 = 0.20
    assert catalog.estimate_cost(event) == "0.20"


def test_pricing_reasoning_tokens_do_not_double_count() -> None:
    """reasoning_tokens 是 completion_tokens 子集, 按输出价整体计费一次, 不额外加价。"""
    catalog = PricingCatalog(
        [PriceSnapshot("P", "m", "text", "v1", input_price_per_unit="0.01", output_price_per_unit="0.03")],
        version="v1",
    )
    with_reasoning = _event(usage=TokenUsage(prompt_tokens=0, completion_tokens=10, reasoning_tokens=7))
    without_reasoning = _event(usage=TokenUsage(prompt_tokens=0, completion_tokens=10, reasoning_tokens=0))
    assert catalog.estimate_cost(with_reasoning) == catalog.estimate_cost(without_reasoning) == "0.30"


def test_recorder_buffers_and_applies_pricing() -> None:
    catalog = PricingCatalog(
        [PriceSnapshot("P", "m", "text", "v1", input_price_per_unit="0.01", output_price_per_unit="0")],
        version="v1",
    )
    recorder = UsageRecorder(store=None, pricing=catalog)
    recorder.record(_event(usage=TokenUsage(prompt_tokens=10, completion_tokens=0)))
    assert recorder.pending_count == 1


def test_recorder_keeps_none_cost_when_unknown() -> None:
    recorder = UsageRecorder(store=None, pricing=PricingCatalog())
    event = _event()
    recorder.record(event)
    assert event.estimated_cost is None


def test_record_llm_failure_keeps_zero_usage() -> None:
    captured: list[ModelUsageEvent] = []
    recorder = UsageRecorder(store=None)
    recorder.record = lambda e: captured.append(e)  # type: ignore[method-assign]
    recorder.record_llm(model="m", provider="P", response=None, status="failed", latency_ms=12)
    assert captured[0].status == "failed"
    assert captured[0].usage.total_tokens == 0
    assert captured[0].latency_ms == 12


def test_record_llm_passes_through_correlation_ids_and_fallback() -> None:
    """J1: trace_id/request_id/agent_id/session_id/fallback_from 不再恒为空/None。"""
    captured: list[ModelUsageEvent] = []
    recorder = UsageRecorder(store=None)
    recorder.record = lambda e: captured.append(e)  # type: ignore[method-assign]
    recorder.record_llm(
        model="m",
        provider="P",
        response=None,
        status="success",
        latency_ms=5,
        agent_id="a1",
        session_id="s1",
        trace_id="t1",
        request_id="r1",
        fallback_from="primary-model",
    )
    event = captured[0]
    assert event.agent_id == "a1"
    assert event.session_id == "s1"
    assert event.trace_id == "t1"
    assert event.request_id == "r1"
    assert event.fallback_from == "primary-model"


async def test_recorder_flush_without_store_clears_buffer() -> None:
    recorder = UsageRecorder(store=None)
    recorder.record(_event())
    await recorder.flush()
    assert recorder.pending_count == 0
    assert await recorder.aggregate() == []


async def test_recorder_flush_swallows_store_errors() -> None:
    class _BoomStore:
        async def insert(self, event) -> None:
            raise RuntimeError("db down")

        async def aggregate(self, filters=None):
            return []

    recorder = UsageRecorder(store=_BoomStore())  # type: ignore[arg-type]
    recorder.record(_event())
    await recorder.flush()  # 不得抛异常
    assert recorder.pending_count == 0


async def test_usage_store_roundtrip(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage" / "usage.db"))
    await store.start()
    try:
        await store.insert(_event(usage=TokenUsage(prompt_tokens=1, completion_tokens=2)))
        # 聚合多维实现细节见 tests/unit/test_usage_storage.py, 这里只验证 insert 后能查到
        summary = await store.aggregate()
        assert summary[0]["request_count"] == 1
        assert summary[0]["prompt_tokens"] == 1
    finally:
        await store.stop()


async def test_provider_manager_records_on_success() -> None:
    recorder = UsageRecorder(store=None)
    manager = ProviderManager({}, usage_recorder=recorder)
    response = await manager.chat_with_retry(_FakeProvider())
    assert response.content == "ok"
    assert recorder.pending_count == 1


async def test_provider_manager_records_on_failure() -> None:
    recorder = UsageRecorder(store=None)
    manager = ProviderManager({}, usage_recorder=recorder)
    # 直接测记录接缝, 避开 chat_with_retry 的指数退避 sleep
    with pytest.raises(RuntimeError):
        await manager._call_and_record(_FakeProvider(fail=True))
    assert recorder.pending_count == 1


async def test_chat_with_retry_passes_agent_session_trace_id_to_usage_event() -> None:
    """J1: loop.py 传入的 agent_id/session_id/trace_id 要贯穿到记录的 ModelUsageEvent。"""
    captured: list[ModelUsageEvent] = []
    recorder = UsageRecorder(store=None)
    recorder.record = lambda e: captured.append(e)  # type: ignore[method-assign]
    manager = ProviderManager({}, usage_recorder=recorder)

    await manager.chat_with_retry(
        _FakeProvider(), agent_id="a1", session_id="s1", trace_id="t1", system="s", messages=[]
    )

    assert len(captured) == 1
    assert captured[0].agent_id == "a1"
    assert captured[0].session_id == "s1"
    assert captured[0].trace_id == "t1"
    assert captured[0].request_id != ""


async def test_streaming_call_records_usage_via_record_stream_result() -> None:
    """J1: loop.py 流式分支此前完全绕过计量; 补齐后流式调用也应记录一次用量。"""
    from types import SimpleNamespace

    from isac.agent.hooks import AgentHooks
    from isac.agent.loop import ISACAgentLoop
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry
    from isac.core.types import AgentContext, LLMChunk
    from tests.fixtures.fakes import FakeLLMProvider

    captured: list[ModelUsageEvent] = []
    recorder = UsageRecorder(store=None)
    recorder.record = lambda e: captured.append(e)  # type: ignore[method-assign]
    manager = ProviderManager({}, usage_recorder=recorder)

    provider = FakeLLMProvider(
        scripted_chunks=[
            [LLMChunk(delta_content="hi", finish_reason="stop", usage=TokenUsage(prompt_tokens=3, completion_tokens=2))]
        ]
    )
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=ToolRegistry(),
        provider_manager=manager,
    )
    ctx = AgentContext(
        session=SimpleNamespace(session_id="s1"),
        user_profile=None,
        current_message=object(),
        streaming=True,
        services={"agent_id": "a1", "task_id": "t1"},
    )

    result = await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert result.content == "hi"
    assert len(captured) == 1
    assert captured[0].agent_id == "a1"
    assert captured[0].session_id == "s1"
    assert captured[0].trace_id == "t1"
    assert captured[0].status == "success"
    assert captured[0].usage.total_tokens == 5


async def test_streaming_call_records_failed_status_when_stream_raises() -> None:
    """流式过程中抛异常时也要记一条 status=failed 的用量事件, 而不是完全不记录。"""
    from types import SimpleNamespace

    from isac.agent.hooks import AgentHooks
    from isac.agent.loop import ISACAgentLoop
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry
    from isac.core.types import AgentContext

    captured: list[ModelUsageEvent] = []
    recorder = UsageRecorder(store=None)
    recorder.record = lambda e: captured.append(e)  # type: ignore[method-assign]
    manager = ProviderManager({}, usage_recorder=recorder)

    loop = ISACAgentLoop(
        llm=_RaisingStreamProvider(),
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=ToolRegistry(),
        provider_manager=manager,
    )
    ctx = AgentContext(
        session=SimpleNamespace(session_id="s1"),
        user_profile=None,
        current_message=object(),
        streaming=True,
        services={"agent_id": "a1", "task_id": "t1"},
    )

    with pytest.raises(RuntimeError):
        await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert len(captured) == 1
    assert captured[0].status == "failed"
    assert captured[0].usage.total_tokens == 0


class _RaisingStreamProvider:
    """chat_stream() 产出一个 chunk 后抛异常, 模拟流式过程中失败。"""

    async def chat(self, **kwargs):
        raise NotImplementedError

    async def chat_stream(self, *a, **k):
        from isac.core.types import LLMChunk

        yield LLMChunk(delta_content="partial")
        raise RuntimeError("stream broke")

    def get_model_name(self) -> str:
        return "raising-stream"

    def get_capabilities(self):
        return None
