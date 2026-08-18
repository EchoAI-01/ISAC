"""OpenAI 兼容 Reranker Provider (EXP-3, SPECIFICATION.md 2.4)。

真实 HTTP 调用实现, 支持任意 OpenAI 兼容 ``/rerank`` API:
- Cohere 协议: POST /rerank, body {model, query, documents, top_n}, response
  ``result: [{index, relevance_score: float}, ...]``
- Jina 协议: POST /rerank, body {model, query, documents, top_n}, response
  ``results: [{index, relevance_score: float}, ...]``
两种协议响应差异在字段名 (result vs results), 请求 schema 相同。scores 数组按
原始 index 还原成与 candidates 等长的列表, 缺失位置填 0.0。
错误分类复用 OpenAICompatProvider._map_http_error / _wrap_network_error。
"""

from __future__ import annotations

import json
from typing import Any

from isac.core.exceptions import LLMError
from isac.provider.base import RerankerProvider
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 60.0
SUPPORTED_PROTOCOLS = ("cohere", "jina")


class OpenAICompatRerankerProvider(RerankerProvider):
    """OpenAI 兼容重排序 Provider (Cohere / Jina 双协议)。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        protocol: str = "cohere",
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(
                f"不支持的 rerank 协议: {protocol!r}, 只支持 {SUPPORTED_PROTOCOLS}"
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.protocol = protocol
        self.timeout = timeout
        self.extra = kwargs
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover
                raise LLMError("httpx 未安装, RerankerProvider 不可用") from exc
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """批量重排序: POST /rerank, 解析 result/results 还原成 scores 数组。

        空输入返回空列表 (不调 HTTP); scores 按 candidates 长度对齐, 缺失 index 填 0.0。
        """
        if not candidates:
            return []
        payload = {
            "model": self.model,
            "query": query,
            "documents": candidates,
            "top_n": len(candidates),
        }
        client = self._get_client()
        import httpx

        try:
            response = await client.post("/rerank", json=payload)
        except httpx.TimeoutException as exc:
            # CR2-Fix-21: httpx 真实抛出的是 httpx.TimeoutException (及其子类
            # ReadTimeout/ConnectTimeout/WriteTimeout/PoolTimeout), 不是内建
            # TimeoutError —— 此前 except TimeoutError 是死代码, 真实超时会
            # 落入下面的通用 except Exception 分支 (retriable 结果相同, 但
            # 消息借用了 LLM Provider 上下文的措辞, 不提及"超时")。
            raise LLMError(f"Rerank 请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise OpenAICompatProvider._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise OpenAICompatProvider._map_http_error(
                response.status_code, response.content
            )
        return self._parse_response(response, len(candidates))

    def _parse_response(self, response: Any, expected_len: int) -> list[float]:
        """解析 /rerank 响应: JSON → result/results → list[float] (按 index 还原)."""
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(
                f"Rerank 响应 JSON 解析失败: {exc}",
                retriable=False,
                context={"body": response.text[:500]},
            ) from exc
        # Fix-64: Cohere v1/v2 /rerank 与 Jina 实际都返回 "results" (复数);
        # 此前 cohere 协议取 "result" (单数) —— 对真实 Cohere/vLLM 兼容端点
        # 必然取不到 → 每次 rerank 抛不可重试 LLMError → 上层吞异常回退原序,
        # 记忆召回重排序被静默关闭 (测试 fixture 用 {"result":...} 自造形状
        # 与实现互相印证, 同 Fix-37/56 协议假设错误模式)。现: 优先取官方
        # "results", 兼容回退 "result" (不破坏既有自托管端点)。
        items = data.get("results")
        if items is None:
            items = data.get("result")
        if not isinstance(items, list):
            raise LLMError(
                f"Rerank 响应无 results/result 字段或非 list (protocol={self.protocol})",
                retriable=False,
                context={"body": json.dumps(data)[:500]},
            )
        # 按 index 还原成与 candidates 等长的 scores 数组
        scores: list[float] = [0.0] * expected_len
        for item in items:
            try:
                idx = int(item.get("index", -1))
                score = float(item.get("relevance_score", 0.0))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < expected_len:
                scores[idx] = score
        return scores

    def get_model_name(self) -> str:
        return self.model

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
