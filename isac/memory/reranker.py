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
        usage_recorder: Any = None,
    ) -> None:
        self.config = config
        self._provider = provider
        # R1-③: 多模态用量计量 (record_rerank); None 时 no-op。
        self._usage_recorder = usage_recorder

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
        # R1-③: 计 rerank 用量 (model/provider 取 config, 与 pricing 对齐)
        self._record_rerank(n_candidates=len(candidates))
        if len(scores) != len(candidates):
            return candidates
        # Fix-65: 后处理也纳入降级保护 —— 脏分数 (None/字符串混杂) 会让 sort 抛
        # TypeError 冒泡到 pipeline.search 外层 except → 整次检索返回 [] 而非
        # 降级原序 (与"rerank 失败回退原顺序"承诺相悖)。先强制转 float, 不可
        # 数值化的分数按 0.0 计; 整体转换异常则回退原顺序。
        try:
            numeric = [float(s) if s is not None else 0.0 for s in scores]
        except (TypeError, ValueError):
            return candidates
        # 按分数倒序排 (provider 返回相关性分数, 越大越相关)
        paired = list(zip(candidates, numeric, strict=False))
        paired.sort(key=lambda x: x[1], reverse=True)
        return [hit for hit, _ in paired]

    def _record_rerank(self, *, n_candidates: int) -> None:
        """R1-③: 计 rerank 用量。"""
        if self._usage_recorder is None:
            return
        try:
            self._usage_recorder.record_rerank(
                model=str(self.config.get("model", "")),
                provider=str(self.config.get("provider", "")),
                n_candidates=n_candidates,
            )
        except Exception:  # noqa: BLE001 计量失败不阻塞检索
            pass

    def is_available(self) -> bool:
        """注入了 Provider 视为可用。"""
        return self._provider is not None
