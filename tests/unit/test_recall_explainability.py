"""阶段3-3 记忆进阶: 召回可解释性 (Y1 "用户可查为什么记得这个" 的基础)。

验收:
- _collect_recall_sources 正确汇总每条记忆的命中路径 (fts/bm25/vector/graph);
- _merge_results 把 recall_sources 写入 MemoryHit.metadata (排序去重);
- 无来源信息时不写 recall_sources 键 (不污染)。
"""

from __future__ import annotations

from isac.memory.pipeline import MemoryRetrievalPipeline, _collect_recall_sources

# ── _collect_recall_sources ────────────────────────────────────


def test_collect_sources_single_path() -> None:
    fts_rows = [{"id": "m1"}, {"id": "m2"}]
    sources = _collect_recall_sources(fts_rows, [], None, None)
    assert sources == {"m1": {"fts"}, "m2": {"fts"}}


def test_collect_sources_multi_path_merge() -> None:
    # m1 同时被 fts + bm25 + vector 命中; m2 仅 graph。
    fts_rows = [{"id": "m1"}]
    sparse_rows = [("m1", 0.9)]
    dense_rows = [("m1", 0.2)]
    graph_rows = [("m2", 0.7)]
    sources = _collect_recall_sources(fts_rows, sparse_rows, dense_rows, graph_rows)
    assert sources["m1"] == {"fts", "bm25", "vector"}
    assert sources["m2"] == {"graph"}


def test_collect_sources_skips_empty_id_and_none_rows() -> None:
    fts_rows = [{"id": ""}, {"no_id": 1}, {"id": "m1"}]
    sources = _collect_recall_sources(fts_rows, [], None, None)
    assert sources == {"m1": {"fts"}}


# ── _merge_results 写入 recall_sources ─────────────────────────


def test_merge_results_writes_recall_sources() -> None:
    fts_rows = [{"id": "m1", "content": "内容A", "session_id": "s1", "importance": 0.6}]
    sources = {"m1": {"bm25", "fts"}}
    hits = MemoryRetrievalPipeline._merge_results(  # noqa: SLF001
        fts_rows, sparse_rows=[("m1", 0.5)], sources=sources
    )
    assert len(hits) == 1
    # 排序后的路径列表
    assert hits[0].metadata["recall_sources"] == ["bm25", "fts"]


def test_merge_results_no_sources_no_key() -> None:
    fts_rows = [{"id": "m1", "content": "内容A", "session_id": "s1"}]
    hits = MemoryRetrievalPipeline._merge_results(fts_rows, sparse_rows=[])  # noqa: SLF001
    assert len(hits) == 1
    assert "recall_sources" not in hits[0].metadata


def test_merge_results_source_for_absent_id_ignored() -> None:
    # sources 里的 id 若不在最终命中 (rows_by_id) 中, 不产生条目。
    fts_rows = [{"id": "m1", "content": "A", "session_id": "s1"}]
    sources = {"m1": {"fts"}, "m_unknown": {"vector"}}
    hits = MemoryRetrievalPipeline._merge_results(fts_rows, sparse_rows=[], sources=sources)  # noqa: SLF001
    assert len(hits) == 1
    assert hits[0].metadata["recall_sources"] == ["fts"]
