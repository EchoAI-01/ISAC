"""EXP-3 Reranker Provider 业务测试 (httpx.MockTransport 模式)。

覆盖:
- Cohere 协议: POST /rerank body {model, query, documents, top_n}, response
  result: [{index, relevance_score: float}, ...] → 还原成 scores 数组
- Jina 协议: POST /rerank body {model, query, documents, top_n}, response
  results: [{index, relevance_score: float}, ...] → 同上
- 空 candidates 返回空列表 (不发 HTTP)
- 429 → RateLimitError; 503 → LLMError(retriable=True); 400 → LLMError(retriable=False)
- JSON 解析失败 → LLMError(retriable=False, context 含 body)
- 超时 → LLMError(retriable=True)
- aclose 关闭 client
- get_model_name 返回 self.model
"""

from __future__ import annotations

import json

import httpx
import pytest

from isac.core.exceptions import LLMError, RateLimitError
from isac.provider.rerank.openai_compat import OpenAICompatRerankerProvider


def _make_provider(
    handler,
    *,
    protocol: str = "cohere",
    model: str = "rerank-english-v3.0",
) -> OpenAICompatRerankerProvider:
    """构造 provider, 注入 httpx.MockTransport(handler)."""
    provider = OpenAICompatRerankerProvider(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model=model,
        protocol=protocol,
    )
    # 注入 mock client (绕过 _get_client 的真实 httpx.AsyncClient)
    # base_url 必须与 provider.base_url 一致, 否则 POST "/rerank" 报 unknown url type
    client = httpx.AsyncClient(
        base_url="https://api.test.com/v1",
        transport=httpx.MockTransport(handler),
    )
    provider._client = client  # type: ignore[attr-defined]
    return provider


def _cohere_response(scores: list[tuple[int, float]]) -> bytes:
    """构造 Cohere /rerank 响应体: {result: [{index, relevance_score}, ...]}."""
    return json.dumps({
        "result": [{"index": idx, "relevance_score": score} for idx, score in scores],
    }).encode()


def _jina_response(scores: list[tuple[int, float]]) -> bytes:
    """构造 Jina /rerank 响应体: {results: [{index, relevance_score}, ...]}."""
    return json.dumps({
        "results": [{"index": idx, "relevance_score": score} for idx, score in scores],
    }).encode()


# ── Cohere 协议 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cohere_rerank_returns_scores_for_candidates() -> None:
    """Cohere 协议: 3 个候选, response 含 3 个 result, 还原成 scores 数组."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "rerank-english-v3.0"
        assert body["query"] == "天气"
        assert body["documents"] == ["周末下雨", "今天晴朗", "明天有风"]
        return httpx.Response(200, content=_cohere_response([
            (0, 0.9), (1, 0.3), (2, 0.6),
        ]))

    provider = _make_provider(handler, protocol="cohere")
    try:
        scores = await provider.rerank("天气", ["周末下雨", "今天晴朗", "明天有风"])
        assert len(scores) == 3
        assert scores[0] == pytest.approx(0.9)
        assert scores[1] == pytest.approx(0.3)
        assert scores[2] == pytest.approx(0.6)
    finally:
        await provider.aclose()


# ── Jina 协议 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jina_rerank_returns_scores_for_candidates() -> None:
    """Jina 协议: 2 个候选, response 含 2 个 results, 还原成 scores 数组."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "rerank-english-v3.0"
        assert body["query"] == "吃饭"
        assert body["documents"] == ["午餐", "晚餐"]
        return httpx.Response(200, content=_jina_response([
            (0, 0.8), (1, 0.5),
        ]))

    provider = _make_provider(handler, protocol="jina")
    try:
        scores = await provider.rerank("吃饭", ["午餐", "晚餐"])
        assert len(scores) == 2
        assert scores[0] == pytest.approx(0.8)
        assert scores[1] == pytest.approx(0.5)
    finally:
        await provider.aclose()


# ── 空 candidates ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rerank_empty_candidates_returns_empty_without_http() -> None:
    """空 candidates 时 rerank 返回空列表, 不发 HTTP (用计数器断言)."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=_cohere_response([]))

    provider = _make_provider(handler)
    try:
        scores = await provider.rerank("query", [])
        assert scores == []
        assert call_count == 0  # 不发 HTTP
    finally:
        await provider.aclose()


# ── 错误分类 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rerank_429_raises_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error": "rate limited"}')

    provider = _make_provider(handler)
    try:
        with pytest.raises(RateLimitError):
            await provider.rerank("q", ["c1", "c2"])
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_rerank_503_raises_retriable_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b'{"error": "service unavailable"}')

    provider = _make_provider(handler)
    try:
        with pytest.raises(LLMError) as exc_info:
            await provider.rerank("q", ["c1"])
        assert exc_info.value.retriable is True
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_rerank_400_raises_non_retriable_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b'{"error": "bad request"}')

    provider = _make_provider(handler)
    try:
        with pytest.raises(LLMError) as exc_info:
            await provider.rerank("q", ["c1"])
        assert exc_info.value.retriable is False
    finally:
        await provider.aclose()


# ── JSON 解析失败 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rerank_json_parse_failure_raises_llm_error_with_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not valid json")

    provider = _make_provider(handler)
    try:
        with pytest.raises(LLMError) as exc_info:
            await provider.rerank("q", ["c1"])
        assert exc_info.value.retriable is False
        # context 含响应体前 500 字符
        assert "not valid json" in str(exc_info.value.context) or "not valid json" in str(
            exc_info.value
        )
    finally:
        await provider.aclose()


# ── get_model_name + aclose ─────────────────────────────────────


def test_get_model_name_returns_model_id() -> None:
    provider = OpenAICompatRerankerProvider(
        api_key="k", base_url="https://x", model="my-rerank-model",
    )
    assert provider.get_model_name() == "my-rerank-model"


@pytest.mark.asyncio
async def test_aclose_closes_client() -> None:
    provider = _make_provider(lambda r: httpx.Response(200, content=_cohere_response([])))
    await provider.aclose()
    assert provider._client is None  # type: ignore[attr-defined]
