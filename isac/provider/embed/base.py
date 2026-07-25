"""J2 嵌入 Provider 桩 (填充空目录)。

真实实现 (fastembed 本地 / OpenAI Embedding API) 留待 J2 实现节点; 本桩声明能力
描述符并让方法显式 NotImplementedError, 避免静默返回错误结果。
"""

from __future__ import annotations

from isac.provider.base import EmbeddingProvider
from isac.provider.catalog import ModelDescriptor


class StubEmbeddingProvider(EmbeddingProvider):
    """占位嵌入 Provider: 声明能力, 方法待实现节点接入真实模型。"""

    def __init__(self, model_id: str = "stub-embed", dimension: int = 1024) -> None:
        self._model_id = model_id
        self._dimension = dimension

    def descriptor(self) -> ModelDescriptor:
        """返回可注册到 ModelCatalog 的能力描述符。"""
        return ModelDescriptor(
            provider_id="stub",
            model_id=self._model_id,
            modalities_in={"text"},
            modalities_out={"embedding"},
            operations={"embed"},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("StubEmbeddingProvider.embed 待 J2 实现节点接入真实模型")

    async def embed_query(self, query: str) -> list[float]:
        raise NotImplementedError("StubEmbeddingProvider.embed_query 待 J2 实现节点接入真实模型")

    def dimension(self) -> int:
        return self._dimension
