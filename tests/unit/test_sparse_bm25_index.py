"""SparseBM25Index 单元测试。"""

from __future__ import annotations

from isac.memory.storage.sparse import SparseBM25Index


def test_sparse_search_returns_ranked_matches() -> None:
    index = SparseBM25Index()
    index.add("mem_1", "ISAC 记忆系统 支持 keyword 检索")
    index.add("mem_2", "插件兼容 AstrBot MaiBot")
    index.add("mem_3", "ISAC 记忆 记忆 画像")

    results = index.search("ISAC 记忆", top_k=2)

    assert [memory_id for memory_id, _score in results] == ["mem_3", "mem_1"]
    assert results[0][1] > results[1][1]


def test_sparse_search_respects_top_k_and_remove() -> None:
    index = SparseBM25Index()
    index.add("mem_1", "记忆 检索")
    index.add("mem_2", "记忆 治理")
    index.remove("mem_1")

    results = index.search("记忆", top_k=5)

    assert [memory_id for memory_id, _score in results] == ["mem_2"]


def test_sparse_search_empty_query_returns_empty() -> None:
    index = SparseBM25Index()
    index.add("mem_1", "记忆 检索")

    assert index.search("", top_k=5) == []
