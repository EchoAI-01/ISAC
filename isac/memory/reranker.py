"""Reranker: 重排序管理 (ARCHITECTURE.md 3.6)。

J2 改造: 接受 RerankerProvider 注入; 未注入时 is_available=False, rerank 保持
原顺序 (跳过重排序), 与 D6 行为一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.core.types import MemoryHit

if TYPE_CHECKING:
    from isac.provider.base import RerankerProvider


class Reranker:
    """重排序管理器: 委托注入的 RerankerProvider, 未注入时跳过。"""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        provider: RerankerProvider | None = None,
    ) -> None:
        self.config = config
        self._provider = provider

    async def rerank(self, query: str, candidates: list[MemoryHit]) -> list[MemoryHit]:
        """对候选结果重排序。

        未注入 Provider 时保持原顺序 (跳过); 注入时调 provider.rerank(query,
        [c.content for c in candidates]) 取分数, 按分数倒序重排 candidates。
        """
        if self._provider is None or not candidates:
            return candidates
        texts = [c.content for c in candidates]
        try:
            scores = await self._provider.rerank(query, texts)
        except Exception:  # noqa: BLE001
            # 任何异常 (网络/解析) 都不阻塞主链路: 回退到原顺序
            return candidates
        if len(scores) != len(candidates):
            return candidates
        # 按分数倒序排 (provider 返回相关性分数, 越大越相关)
        paired = list(zip(candidates, scores, strict=False))
        paired.sort(key=lambda x: x[1], reverse=True)
        return [hit for hit, _ in paired]

    def is_available(self) -> bool:
        """注入了 Provider 视为可用。"""
        return self._provider is not None
