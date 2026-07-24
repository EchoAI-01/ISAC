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
        # 聚合是实现节点范畴, 骨架返回空列表
        assert await store.aggregate() == []
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
