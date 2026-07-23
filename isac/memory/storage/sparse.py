"""SparseBM25Index: 稀疏检索 (BM25)。

与 FTS5 互补的内存 BM25 索引；嵌入模型不可用时降级为纯稀疏搜索
(EmbeddingManager.is_degraded, ARCHITECTURE.md 3.6)。
"""

from __future__ import annotations

import math
import re
from collections import Counter


class SparseBM25Index:
    """BM25 稀疏索引。

    分词 + BM25 打分 (基于 token 频次与文档长度的 Okapi BM25)。
    add()/remove() 增量维护倒排索引与 DF/文档长度统计, search() 只计算 query 侧,
    避免每次搜索都要对全部文档重新分词 + 重新统计 (CODE_REVIEW_REPORT.md #15)。
    """

    def __init__(self) -> None:
        self._doc_terms: dict[str, list[str]] = {}  # memory_id -> 分词结果 (非空)
        self._doc_term_counts: dict[str, Counter[str]] = {}  # memory_id -> term 频次
        self._inverted_index: dict[str, set[str]] = {}  # term -> 包含该 term 的 memory_id 集合
        self._total_doc_length = 0  # 增量维护的全部文档 token 总长度

    def add(self, memory_id: str, content: str) -> None:
        """新增/覆盖文档, 增量更新倒排索引与统计量。"""
        self.remove(memory_id)
        terms = self._tokenize(content)
        if not terms:
            return  # 空文档不计入索引 (与原全量实现的过滤语义一致)
        self._doc_terms[memory_id] = terms
        self._doc_term_counts[memory_id] = Counter(terms)
        for term in set(terms):
            self._inverted_index.setdefault(term, set()).add(memory_id)
        self._total_doc_length += len(terms)

    def remove(self, memory_id: str) -> None:
        """删除文档, 从倒排索引与统计量中撤销其贡献。"""
        terms = self._doc_terms.pop(memory_id, None)
        if terms is None:
            return
        self._doc_term_counts.pop(memory_id, None)
        for term in set(terms):
            ids = self._inverted_index.get(term)
            if ids is None:
                continue
            ids.discard(memory_id)
            if not ids:
                del self._inverted_index[term]
        self._total_doc_length -= len(terms)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """稀疏搜索，返回 (memory_id, score) 列表。"""
        query_terms = self._tokenize(query)
        total_docs = len(self._doc_terms)
        if not query_terms or top_k <= 0 or total_docs == 0:
            return []
        average_length = self._total_doc_length / total_docs

        # 用倒排索引只收集「至少命中一个 query term」的候选文档, 不扫描全部文档
        query_term_set = set(query_terms)
        candidate_ids: set[str] = set()
        document_frequency: dict[str, int] = {}
        for term in query_term_set:
            ids = self._inverted_index.get(term)
            if not ids:
                continue
            document_frequency[term] = len(ids)
            candidate_ids.update(ids)

        scored: list[tuple[str, float]] = []
        for memory_id in candidate_ids:
            term_counts = self._doc_term_counts[memory_id]
            doc_length = len(self._doc_terms[memory_id])
            score = 0.0
            for term in query_terms:
                tf = term_counts[term]
                if tf <= 0:
                    continue
                df = document_frequency.get(term, 0)
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                denominator = tf + 1.5 * (1 - 0.75 + 0.75 * doc_length / max(average_length, 1.0))
                score += idf * (tf * 2.5) / denominator
            if score > 0:
                scored.append((memory_id, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:top_k]

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        normalized = str(text or "").lower()
        words = re.findall(r"[a-z0-9_]+|[一-鿿]", normalized)
        bigrams = [normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))]
        return words + [item for item in bigrams if re.search(r"[一-鿿]", item)]
