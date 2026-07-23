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


def test_incremental_updates_match_full_rebuild() -> None:
    """add/remove/覆盖更新等操作序列后, 增量维护的结果应与只 add 最终状态的全新索引一致。

    mem_3 的旧内容故意与 mem_2 共享 "插件" 一词: 如果 remove() 没有正确清理倒排索引,
    "插件" 的 document_frequency 会被残留的 mem_3 污染, 从而让 mem_2 的 idf/score 出现偏差。
    """
    incremental = SparseBM25Index()
    incremental.add("mem_1", "ISAC 记忆系统 支持 keyword 检索")
    incremental.add("mem_2", "插件兼容 AstrBot MaiBot")
    incremental.add("mem_3", "插件 占位符")
    incremental.remove("mem_3")
    incremental.add("mem_3", "ISAC 记忆 记忆 画像")  # 重新 add 同一个 id (新内容不再含 "插件")
    incremental.add("mem_4", "临时文档")
    incremental.remove("mem_4")  # add 后又整体删除

    fresh = SparseBM25Index()
    fresh.add("mem_1", "ISAC 记忆系统 支持 keyword 检索")
    fresh.add("mem_2", "插件兼容 AstrBot MaiBot")
    fresh.add("mem_3", "ISAC 记忆 记忆 画像")

    assert incremental.search("ISAC 记忆", top_k=5) == fresh.search("ISAC 记忆", top_k=5)
    assert incremental.search("插件 AstrBot", top_k=5) == fresh.search("插件 AstrBot", top_k=5)
