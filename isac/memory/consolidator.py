"""MemoryConsolidator: 后台记忆整合 (去重/合并/剪枝)。"""

from __future__ import annotations


class MemoryConsolidator:
    """后台整合任务。

    [桩] 定期去重/合并相似 Episode、剪枝低重要性记忆、更新 PersonProfile 聚合。
    """

    async def run_once(self, agent_id: str) -> None:
        raise NotImplementedError("MemoryConsolidator.run_once 尚未实现")
