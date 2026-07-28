"""图谱召回 _graph_search 骨架单测 (S3, TODO(P3))。

验证图谱邻居召回的默认关闭语义与融合安全: enable_graph_recall=False 时 _graph_search
恒空; 开启时骨架仍恒空 (零行为变化); _merge_results 接受第四路 graph_rows 且
graph_rows=None/[] 与既有三路结果完全一致 (未启用时零贡献)。
"""

from __future__ import annotations

import pytest

from isac.core.types import MemoryHit
from isac.memory.pipeline import MemoryRetrievalPipeline


class _StubGraph:
    """neighbors 不应在骨架阶段被调用 (调用即失败, 证明骨架不触达图谱)。"""

    async def neighbors(self, agent_id: str, node: str, relation: str | None = None):  # noqa: ANN201
        raise AssertionError("骨架阶段不应调用 graph.neighbors")


def _pipeline(*, enable_graph_recall: bool) -> MemoryRetrievalPipeline:
    return MemoryRetrievalPipeline(
        namespace="a1",
        metadata=object(),  # type: ignore[arg-type]
        vector=object(),  # type: ignore[arg-type]
        sparse=object(),  # type: ignore[arg-type]
        graph=_StubGraph(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        enable_graph_recall=enable_graph_recall,
    )


@pytest.mark.asyncio
async def test_graph_search_disabled_returns_empty() -> None:
    assert await _pipeline(enable_graph_recall=False)._graph_search("q", top_k=10) == []


@pytest.mark.asyncio
async def test_graph_search_enabled_skeleton_still_empty() -> None:
    """开启开关后骨架仍恒空, 且不触达 graph.neighbors (未实现前零行为变化)。"""
    assert await _pipeline(enable_graph_recall=True)._graph_search("q", top_k=10) == []


def test_merge_results_graph_rows_none_matches_three_way() -> None:
    """graph_rows 缺省 (None) 时融合结果与三路完全一致。"""
    fts = [{"id": "m1", "content": "c1", "session_id": "s"}]
    sparse = [("m2", 1.0)]
    dense = [("m1", 0.2)]
    three = MemoryRetrievalPipeline._merge_results(fts, sparse, dense)
    four = MemoryRetrievalPipeline._merge_results(fts, sparse, dense, None)
    assert [h.id for h in three] == [h.id for h in four]


def test_merge_results_graph_rows_only_scores_mapped_ids() -> None:
    """graph_rows 里未补齐行数据的候选 (不在 fts_rows) 被 rows_by_id 检查丢弃。"""
    fts = [{"id": "m1", "content": "c1", "session_id": "s"}]
    hits = MemoryRetrievalPipeline._merge_results(fts, [], None, [("m_ghost", 0.9)])
    assert all(isinstance(h, MemoryHit) for h in hits)
    assert [h.id for h in hits] == ["m1"]  # 幽灵候选无行数据, 不出现在结果里
