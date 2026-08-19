"""EmbeddingManager: 嵌入模型管理 (ARCHITECTURE.md 3.6)。

J2 改造: 接受 EmbeddingProvider 注入 (OpenAICompatEmbeddingProvider 或任意 ABC 子类);
未注入时保持降级 (is_degraded=True, embed 返回空), 触发 MemoryRetrievalPipeline
纯稀疏检索路径, 与 D6 行为一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.provider.base import EmbeddingProvider


class EmbeddingManager:
    """嵌入模型管理器: 委托注入的 EmbeddingProvider, 未注入时降级。"""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        provider: EmbeddingProvider | None = None,
        usage_recorder: Any = None,
    ) -> None:
        self.config = config
        self._provider = provider
        # R1-③: 多模态用量计量 (record_embed); None 时 no-op。
        self._usage_recorder = usage_recorder

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化; 未注入 Provider 时返回空 (触发降级)。"""
        if self._provider is None:
            return []
        result = await self._provider.embed(texts)
        self._record_embed(n_texts=len(texts))
        return result

    async def embed_query(self, query: str) -> list[float]:
        """查询向量化; 未注入 Provider 时返回空。"""
        if self._provider is None:
            return []
        result = await self._provider.embed_query(query)
        self._record_embed(n_texts=1)
        return result

    def _record_embed(self, *, n_texts: int) -> None:
        """R1-③: 计 embedding 用量 (H4: provider 取实例类名, 对齐 pricing.jsonc 键)。

        此前 provider 取 config.get("provider") —— 默认配置无该键 → 恒空串 →
        PricingCatalog.lookup (provider, model, modality) 永不命中, embed 成本恒 None。
        改用 provider 实例类名 (如 OpenAICompatEmbeddingProvider), 与价目表及 LLM 侧
        type(provider).__name__ 口径一致 (H4 三口径统一第一步)。provider 缺失时回退
        config["provider"] (向后兼容)。
        """
        if self._usage_recorder is None:
            return
        try:
            dim = self._provider_dim()
            provider_name = (
                type(self._provider).__name__
                if self._provider is not None
                else str(self.config.get("provider", ""))
            )
            self._usage_recorder.record_embed(
                model=str(self.config.get("model", "")),
                provider=provider_name,
                n_texts=n_texts,
                dim=dim,
            )
        except Exception:  # noqa: BLE001 计量失败不阻塞检索
            pass

    def get_fingerprint(self) -> dict:
        """返回模型指纹。"""
        return {
            "provider": self.config.get("provider", "none"),
            "model": self.config.get("model", "none"),
            "dimension": self._provider_dim(),
            "degraded": self.is_degraded(),
        }

    def _provider_dim(self) -> int:
        """从注入 Provider 取维度; 未注入或未调用过返回 0。"""
        if self._provider is None:
            return 0
        try:
            return int(self._provider.dimension())
        except Exception:  # noqa: BLE001
            return 0

    def is_degraded(self) -> bool:
        """未注入 Provider 视为降级 (纯稀疏检索)。"""
        return self._provider is None
