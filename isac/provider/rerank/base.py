"""J2 重排序 Provider 桩 (填充空目录)。

真实实现 (bge-reranker / Cohere / Jina Rerank) 留待 J2 实现节点; 本桩声明能力描述符
并让方法显式 NotImplementedError。
"""

from __future__ import annotations

from isac.provider.base import RerankerProvider
from isac.provider.catalog import ModelDescriptor


class StubRerankerProvider(RerankerProvider):
    """占位重排序 Provider: 声明能力, 方法待实现节点接入真实模型。"""

    def __init__(self, model_id: str = "stub-rerank") -> None:
        self._model_id = model_id

    def descriptor(self) -> ModelDescriptor:
        """返回可注册到 ModelCatalog 的能力描述符。"""
        return ModelDescriptor(
            provider_id="stub",
            model_id=self._model_id,
            modalities_in={"text"},
            modalities_out={"score"},
            operations={"rerank"},
        )

    async def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError("StubRerankerProvider.rerank 待 J2 实现节点接入真实模型")
