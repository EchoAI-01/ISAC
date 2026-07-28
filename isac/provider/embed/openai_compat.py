"""OpenAI 兼容 Embedding Provider (J2, SPECIFICATION.md 2.4)。

真实 HTTP 调用实现, 支持任意 OpenAI 兼容 ``/embeddings`` API:
- POST /embeddings, 请求体含 model + input (list[str])
- 响应 data[].embedding → list[list[float]]
- dimension() 从首次 embed 响应推断 (未调用过返回 0)
- 错误分类复用 OpenAICompatProvider._map_http_error / _wrap_network_error

用户配置 api_base + api_key + model 即可接入 OpenAI text-embedding-3-small /
阿里通义 Embedding / 自托管等任意 OpenAI 兼容嵌入端点。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from isac.core.exceptions import LLMError
from isac.provider.base import EmbeddingProvider
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 60.0


class OpenAICompatEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容嵌入 Provider。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.extra = kwargs
        self._client: Any = None
        self._dim: int = 0  # 首次 embed 调用后从响应推断

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover
                raise LLMError("httpx 未安装, EmbeddingProvider 不可用") from exc
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化: POST /embeddings, 解析 data[].embedding。

        空输入返回空列表 (不调 HTTP)。
        """
        if not texts:
            return []
        payload = {"model": self.model, "input": texts}
        client = self._get_client()
        try:
            response = await client.post("/embeddings", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(f"Embedding 请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise OpenAICompatProvider._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise OpenAICompatProvider._map_http_error(
                response.status_code, response.content
            )
        return self._parse_response(response)

    def _parse_response(self, response: Any) -> list[list[float]]:
        """解析 /embeddings 响应: JSON → data[].embedding → list[list[float]]。"""
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(
                f"Embedding 响应 JSON 解析失败: {exc}",
                retriable=False,
                context={"body": response.text[:500]},
            ) from exc
        items = data.get("data") or []
        if not items:
            raise LLMError(
                "Embedding 响应无 data 字段或为空",
                retriable=False,
                context={"body": json.dumps(data)[:500]},
            )
        vecs: list[list[float]] = []
        for item in items:
            emb = item.get("embedding") or []
            if not isinstance(emb, list):
                continue
            vecs.append([float(x) for x in emb])
        if not vecs:
            raise LLMError("Embedding 响应中无可用 embedding 向量", retriable=False)
        # 缓存维度供后续 dimension() 调用
        if self._dim == 0:
            self._dim = len(vecs[0])
        return vecs

    async def embed_query(self, query: str) -> list[float]:
        """查询向量化: 调 embed([query]) 取第一个。"""
        vecs = await self.embed([query])
        return vecs[0] if vecs else []

    def dimension(self) -> int:
        """返回嵌入维度; 首次 embed 调用前为 0 (未推断)。"""
        return self._dim

    def get_model_name(self) -> str:
        return self.model

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
