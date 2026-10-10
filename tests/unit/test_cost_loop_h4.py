"""阶段3-3 (H4) 成本闭环: 用量 provider 键三口径统一为实例类名。

背景: LLM 记 type(provider).__name__, 媒体工具记 descriptor.provider_id, embed/rerank
记 config["provider"] (默认配置无该键 → 恒空) —— 三种口径无法用同一份价目表命中,
开箱 estimated_cost 恒 None。本批把 embed/rerank/media 统一为**实例类名**, 与 LLM 及
pricing.jsonc 键口径一致。

验收:
- embedder/reranker/media 记录 provider = provider 实例类名;
- provider 缺失时回退旧口径 (向后兼容);
- pricing.jsonc 登记的 provider 键与真实 Provider 类名一致 (查表可命中)。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from isac.agent.tools.base import ToolContext
from isac.agent.tools.media import _record_media_usage
from isac.memory.embedder import EmbeddingManager
from isac.memory.reranker import Reranker
from isac.observability.usage.pricing import PricingCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]


class _CapturingRecorder:
    def __init__(self) -> None:
        self.embed_calls: list[dict] = []
        self.rerank_calls: list[dict] = []
        self.image_calls: list[dict] = []

    def record_embed(self, **kw: Any) -> None:
        self.embed_calls.append(kw)

    def record_rerank(self, **kw: Any) -> None:
        self.rerank_calls.append(kw)

    def record_image_gen(self, **kw: Any) -> None:
        self.image_calls.append(kw)


# ── embedder: provider 记实例类名 ──────────────────────────────


class _FakeEmbedProvider:
    def dimension(self) -> int:
        return 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]

    async def embed_query(self, query: str) -> list[float]:
        return [0.1] * 8


@pytest.mark.asyncio
async def test_embedder_records_provider_class_name() -> None:
    rec = _CapturingRecorder()
    em = EmbeddingManager({}, provider=_FakeEmbedProvider(), usage_recorder=rec)
    await em.embed(["hello"])
    assert rec.embed_calls[0]["provider"] == "_FakeEmbedProvider"


@pytest.mark.asyncio
async def test_embedder_no_provider_no_record() -> None:
    rec = _CapturingRecorder()
    em = EmbeddingManager({}, provider=None, usage_recorder=rec)
    await em.embed(["hello"])  # 降级返回空, 不计量
    assert rec.embed_calls == []


# ── reranker: provider 记实例类名 ──────────────────────────────


class _FakeRerankProvider:
    async def rerank(self, query: str, texts: list[str]) -> list[float]:
        return [0.5 for _ in texts]


@pytest.mark.asyncio
async def test_reranker_records_provider_class_name() -> None:
    rec = _CapturingRecorder()
    rk = Reranker({}, provider=_FakeRerankProvider(), usage_recorder=rec)
    candidates = [SimpleNamespace(content="a"), SimpleNamespace(content="b")]
    await rk.rerank("q", candidates)
    assert rec.rerank_calls[0]["provider"] == "_FakeRerankProvider"


# ── media: provider 传实例 → 类名; 缺失回退 provider_id ─────────


class _FakeMediaProvider:
    pass


class _Desc:
    provider_id = "cfg_provider_id"
    model_id = "img-model"


def _tool_context(rec: _CapturingRecorder) -> ToolContext:
    agent_ctx = SimpleNamespace(session=SimpleNamespace(agent_id="a1", session_id="s1"))
    return ToolContext(args={}, agent_context=agent_ctx, services={"usage_recorder": rec})  # type: ignore[arg-type]


def test_media_records_provider_class_name() -> None:
    rec = _CapturingRecorder()
    _record_media_usage(
        "image_gen", _tool_context(rec), _Desc(), status="success", latency_ms=1,
        provider=_FakeMediaProvider(),
    )
    assert rec.image_calls[0]["provider"] == "_FakeMediaProvider"


def test_media_falls_back_to_provider_id_when_no_instance() -> None:
    rec = _CapturingRecorder()
    _record_media_usage(
        "image_gen", _tool_context(rec), _Desc(), status="success", latency_ms=1,
    )  # provider 缺省 None → 回退 descriptor.provider_id (向后兼容)
    assert rec.image_calls[0]["provider"] == "cfg_provider_id"


# ── pricing.jsonc 键与真实 Provider 类名一致 (查表可命中) ──────


def test_pricing_keys_match_real_provider_class_names() -> None:
    from isac.provider.embed.openai_compat import OpenAICompatEmbeddingProvider
    from isac.provider.llm.openai_compat import OpenAICompatProvider

    catalog = PricingCatalog.load(str(REPO_ROOT / "data" / "pricing.jsonc"))
    # 登记的 provider 键必须等于真实类名, 与用量记录口径 (type(provider).__name__) 对齐。
    assert catalog.lookup(OpenAICompatProvider.__name__, "gpt-4o-mini", "text") is not None
    assert (
        catalog.lookup(
            OpenAICompatEmbeddingProvider.__name__, "text-embedding-3-small", "embedding"
        )
        is not None
    )
