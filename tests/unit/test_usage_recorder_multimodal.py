"""J2 阶段 4: UsageRecorder 多模态计量方法测试。

覆盖:
- record_image_gen / record_stt / record_tts / record_video / record_embed / record_rerank
  各自产生正确 modality/operation/unit_name/input_units/output_units 的事件
- PricingCatalog.estimate_cost 扩展支持非 token 单位 (image/audio/embed/rerank)
  的事件成本计算
"""

from __future__ import annotations

from decimal import Decimal

from isac.observability.usage.pricing import PriceSnapshot, PricingCatalog
from isac.observability.usage.recorder import UsageRecorder


def _make_recorder(pricing: PricingCatalog | None = None) -> UsageRecorder:
    """构造不带 store 的 recorder (事件停留在 buffer 供测试断言)。"""
    return UsageRecorder(store=None, pricing=pricing)


def _buffer(recorder: UsageRecorder):
    return list(recorder._buffer)


def test_record_image_gen_produces_image_event() -> None:
    rec = _make_recorder()
    rec.record_image_gen(
        model="dall-e-3", provider="openai", n_images=2,
        latency_ms=500, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    assert rec.pending_count == 1
    e = _buffer(rec)[0]
    assert e.modality == "image"
    assert e.operation == "generate"
    assert e.input_units == 2
    assert e.output_units == 2
    assert e.unit_name == "image"
    assert e.model == "dall-e-3"
    assert e.provider == "openai"
    assert e.agent_id == "a1"
    assert e.session_id == "s1"
    assert e.trace_id == "t1"
    assert e.request_id == "r1"
    assert e.latency_ms == 500
    assert e.status == "success"


def test_record_stt_produces_audio_transcribe_event() -> None:
    rec = _make_recorder()
    rec.record_stt(
        model="whisper-1", provider="openai",
        duration_seconds=12.5,
        latency_ms=300, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.modality == "audio"
    assert e.operation == "transcribe"
    assert e.input_units == 12.5
    assert e.unit_name == "second"
    assert e.model == "whisper-1"


def test_record_tts_produces_audio_synthesize_event() -> None:
    rec = _make_recorder()
    rec.record_tts(
        model="tts-1", provider="openai",
        duration_seconds=8.3,
        latency_ms=250, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.modality == "audio"
    assert e.operation == "synthesize"
    assert e.output_units == 8.3
    assert e.unit_name == "second"
    assert e.model == "tts-1"


def test_record_video_understand_event() -> None:
    rec = _make_recorder()
    rec.record_video(
        operation="understand", model="gpt-4o", provider="openai",
        duration_seconds=30.0,
        latency_ms=2000, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.modality == "video"
    assert e.operation == "understand"
    assert e.input_units == 30.0
    assert e.unit_name == "second"


def test_record_video_generate_event() -> None:
    rec = _make_recorder()
    rec.record_video(
        operation="generate", model="sora-1", provider="openai",
        duration_seconds=10.0,
        latency_ms=5000, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.modality == "video"
    assert e.operation == "generate"
    assert e.output_units == 10.0
    assert e.unit_name == "second"


def test_record_embed_event() -> None:
    rec = _make_recorder()
    rec.record_embed(
        model="text-embedding-3-small", provider="openai",
        n_texts=5, dim=1536,
        latency_ms=120, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.modality == "embedding"
    assert e.operation == "embed"
    assert e.input_units == 5
    assert e.output_units == 1536
    assert e.unit_name == "vector"


def test_record_rerank_event() -> None:
    rec = _make_recorder()
    rec.record_rerank(
        model="rerank-1", provider="openai",
        n_candidates=10,
        latency_ms=80, status="success",
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.modality == "rerank"
    assert e.operation == "rerank"
    assert e.input_units == 10
    assert e.unit_name == "candidate"


def test_record_image_gen_with_fallback_from() -> None:
    rec = _make_recorder()
    rec.record_image_gen(
        model="dall-e-3", provider="openai", n_images=1,
        latency_ms=500,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
        fallback_from="sora-1",
    )
    e = _buffer(rec)[0]
    assert e.fallback_from == "sora-1"


def test_pricing_estimate_cost_for_image_event() -> None:
    snap = PriceSnapshot(
        provider="openai", model="dall-e-3", modality="image",
        pricing_version="v1",
        input_price_per_unit="0.04",  # $0.04 per image (input_units = n_images)
        unit_name="image",
    )
    pricing = PricingCatalog([snap], version="v1")
    rec = _make_recorder(pricing=pricing)
    rec.record_image_gen(
        model="dall-e-3", provider="openai", n_images=2,
        latency_ms=500,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    # input_units=2, output_units=2, input_price=0.04, output_price=0 (默认)
    # 非 token 公式: 2 * 0.04 + 2 * 0 = 0.08
    assert e.estimated_cost is not None
    assert Decimal(e.estimated_cost) == Decimal("0.08")
    assert e.pricing_version == "v1"


def test_pricing_estimate_cost_precise_for_fractional_units() -> None:
    """Fix-27 回归: input_units/output_units 是 float 字段, 之前直接
    Decimal(event.input_units) 会保留二进制浮点的原始误差 (Decimal(0.1) 不是
    精确的 0.1), 与本模块文档"Decimal 避免浮点误差"的意图相悖——真实音视频
    时长基本不会是整数秒, 修复前 estimated_cost 会带一长串二进制浮点垃圾尾数。"""
    snap = PriceSnapshot(
        provider="openai", model="whisper-1", modality="audio",
        pricing_version="v1",
        input_price_per_unit="0.000002",
        unit_name="second",
    )
    pricing = PricingCatalog([snap], version="v1")
    rec = _make_recorder(pricing=pricing)
    rec.record_stt(
        model="whisper-1", provider="openai",
        duration_seconds=0.1,
        latency_ms=300,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.estimated_cost is not None
    assert Decimal(e.estimated_cost) == Decimal("2E-7")
    # 修复前的典型浮点误差尾数特征串, 确认结果不是"凑巧数值相等但字符串仍带垃圾"
    assert "111022302463" not in e.estimated_cost


def test_pricing_estimate_cost_for_audio_stt_event() -> None:
    snap = PriceSnapshot(
        provider="openai", model="whisper-1", modality="audio",
        pricing_version="v1",
        input_price_per_unit="0.006",  # $0.006 per second
        unit_name="second",
    )
    pricing = PricingCatalog([snap], version="v1")
    rec = _make_recorder(pricing=pricing)
    rec.record_stt(
        model="whisper-1", provider="openai",
        duration_seconds=100.0,
        latency_ms=300,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    # input_units=100, input_price=0.006 → 0.6
    assert e.estimated_cost is not None
    assert Decimal(e.estimated_cost) == Decimal("0.6")


def test_pricing_estimate_cost_for_tts_event() -> None:
    snap = PriceSnapshot(
        provider="openai", model="tts-1", modality="audio",
        pricing_version="v1",
        input_price_per_unit="0",
        output_price_per_unit="0.015",  # $0.015 per second (合成后语音时长)
        unit_name="second",
    )
    pricing = PricingCatalog([snap], version="v1")
    rec = _make_recorder(pricing=pricing)
    rec.record_tts(
        model="tts-1", provider="openai",
        duration_seconds=10.0,
        latency_ms=250,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    # output_units=10, output_price=0.015 → 0.15
    assert e.estimated_cost is not None
    assert Decimal(e.estimated_cost) == Decimal("0.15")


def test_pricing_estimate_cost_for_embed_event() -> None:
    snap = PriceSnapshot(
        provider="openai", model="text-embedding-3-small", modality="embedding",
        pricing_version="v1",
        input_price_per_unit="0.0001",  # $0.0001 per text
        unit_name="vector",
    )
    pricing = PricingCatalog([snap], version="v1")
    rec = _make_recorder(pricing=pricing)
    rec.record_embed(
        model="text-embedding-3-small", provider="openai",
        n_texts=1000, dim=1536,
        latency_ms=120,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    # input_units=1000, input_price=0.0001 → 0.1
    assert e.estimated_cost is not None
    assert Decimal(e.estimated_cost) == Decimal("0.1")


def test_pricing_estimate_cost_unknown_returns_none() -> None:
    # 未注册价格快照时 estimated_cost 保持 None (不伪造成本)
    rec = _make_recorder(pricing=PricingCatalog([], version="v1"))
    rec.record_image_gen(
        model="unknown-model", provider="unknown", n_images=1,
        latency_ms=500,
        agent_id="a1", session_id="s1", trace_id="t1", request_id="r1",
    )
    e = _buffer(rec)[0]
    assert e.estimated_cost is None
