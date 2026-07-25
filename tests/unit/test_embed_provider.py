"""J2 阶段 5c: OpenAICompatEmbeddingProvider + EmbeddingManager/Reranker 注入测试。

覆盖:
- OpenAICompatEmbeddingProvider.embed (批量) / embed_query / dimension
- 429/5xx/4xx 错误分类 / JSON 解析失败 / aclose
- EmbeddingManager 注入真实 Provider 后 is_degraded=False, embed 返回真实向量
- EmbeddingManager 未注入 Provider 时 is_degraded=True, embed 返回空 (降级)
- Reranker 注入真实 RerankerProvider 后 is_available=True, rerank 按分数排序
- Reranker 未注入时 is_available=False, rerank 保持原顺序 (跳过)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from isac.core.types import MemoryHit
from isac.memory.embedder import EmbeddingManager
from isac.memory.reranker import Reranker
from isac.provider.embed.openai_compat import OpenAICompatEmbeddingProvider


def _make_embed_provider(
    handler: Any,
    *,
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "text-embedding-3-small",
) -> OpenAICompatEmbeddingProvider:
    provider = OpenAICompatEmbeddingProvider(
        api_key=api_key, base_url=base_url, model=model, timeout=5.0,
    )
    provider._client = httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    return provider


def _embed_response(n: int, dim: int = 3) -> bytes:
    data = [{"embedding": [float(i + j) for j in range(dim)]} for i in range(n)]
    return json.dumps({"model": "text-embedding-3-small", "data": data}).encode("utf-8")


@pytest.mark.asyncio
async def test_embed_batch_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-3-small"
        assert body["input"] == ["hello", "world"]
        return httpx.Response(200, content=_embed_response(n=2, dim=3))

    provider = _make_embed_provider(handler)
    vecs = await provider.embed(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 3
    assert vecs[0] == [0.0, 1.0, 2.0]
    assert vecs[1] == [1.0, 2.0, 3.0]
    assert provider.dimension() == 3
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_query_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_embed_response(n=1, dim=4))

    provider = _make_embed_provider(handler)
    vec = await provider.embed_query("hello")
    assert len(vec) == 4
    assert vec == [0.0, 1.0, 2.0, 3.0]
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_429_raises_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b"rate limit")

    provider = _make_embed_provider(handler)
    from isac.core.exceptions import RateLimitError
    with pytest.raises(RateLimitError):
        await provider.embed(["hello"])
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_5xx_raises_retriable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"unavailable")

    provider = _make_embed_provider(handler)
    from isac.core.exceptions import LLMError
    with pytest.raises(LLMError) as exc:
        await provider.embed(["hello"])
    assert exc.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_4xx_raises_non_retriable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    provider = _make_embed_provider(handler)
    from isac.core.exceptions import LLMError
    with pytest.raises(LLMError) as exc:
        await provider.embed(["hello"])
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_json_parse_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    provider = _make_embed_provider(handler)
    from isac.core.exceptions import LLMError
    with pytest.raises(LLMError) as exc:
        await provider.embed(["hello"])
    assert exc.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_empty_data_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"data":[]}')

    provider = _make_embed_provider(handler)
    from isac.core.exceptions import LLMError
    with pytest.raises(LLMError):
        await provider.embed(["hello"])
    await provider.aclose()


@pytest.mark.asyncio
async def test_aclose_releases_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_embed_response(n=1))

    provider = _make_embed_provider(handler)
    assert provider._client is not None
    await provider.aclose()
    assert provider._client is None


# ── EmbeddingManager 注入改造 ────────────────────────────


class _FakeEmbeddingProvider:
    """桩 EmbeddingProvider 供 EmbeddingManager 注入测试用。"""

    def __init__(self, *, dim: int = 3) -> None:
        self._dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1 * i, 0.2, 0.3] for i in range(len(texts))]

    async def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def dimension(self) -> int:
        return self._dim


@pytest.mark.asyncio
async def test_embedding_manager_with_provider_not_degraded() -> None:
    mgr = EmbeddingManager(
        {"provider": "openai", "model": "text-embedding-3-small"},
        provider=_FakeEmbeddingProvider(dim=3),
    )
    assert not mgr.is_degraded()
    vecs = await mgr.embed(["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 3
    vec = await mgr.embed_query("query")
    assert len(vec) == 3
    fp = mgr.get_fingerprint()
    assert fp["degraded"] is False
    assert fp["dimension"] == 3


def test_embedding_manager_without_provider_degraded() -> None:
    mgr = EmbeddingManager({})
    assert mgr.is_degraded()


@pytest.mark.asyncio
async def test_embedding_manager_without_provider_returns_empty() -> None:
    mgr = EmbeddingManager({})
    assert await mgr.embed(["a"]) == []
    assert await mgr.embed_query("a") == []


# ── Reranker 注入改造 ─────────────────────────────────────


class _FakeRerankerProvider:
    """桩 RerankerProvider 供 Reranker 注入测试用。"""

    async def rerank(self, query: str, candidates: list[str]) -> list[float]:
        # 按文本长度倒序打分 (越短越相关)
        return [float(len(c)) for c in candidates]


def _make_hit(content: str, score: float = 0.5) -> MemoryHit:
    return MemoryHit(
        id=f"m-{content}",
        content=content,
        source="s1",
        hit_type="episode",
        score=score,
        metadata={},
    )


@pytest.mark.asyncio
async def test_reranker_with_provider_sorts_by_score() -> None:
    mgr = Reranker({"provider": "openai"}, provider=_FakeRerankerProvider())
    assert mgr.is_available()
    candidates = [
        _make_hit("short", score=0.9),
        _make_hit("this is a longer text", score=0.1),
        _make_hit("medium length", score=0.5),
    ]
    result = await mgr.rerank("query", candidates)
    # 按长度倒序 (长文本分数高)
    assert result[0].content == "this is a longer text"
    assert result[1].content == "medium length"
    assert result[2].content == "short"


def test_reranker_without_provider_unavailable() -> None:
    mgr = Reranker({})
    assert not mgr.is_available()


@pytest.mark.asyncio
async def test_reranker_without_provider_keeps_order() -> None:
    mgr = Reranker({})
    candidates = [_make_hit("a"), _make_hit("b"), _make_hit("c")]
    result = await mgr.rerank("q", candidates)
    # 不可用时跳过 rerank, 保持原顺序
    assert [h.content for h in result] == ["a", "b", "c"]
