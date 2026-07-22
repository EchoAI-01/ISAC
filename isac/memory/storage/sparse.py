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

    [已完成] 分词 + BM25 打分 (基于 token 频次与文档长度的 Okapi BM25)。
    """

    def __init__(self) -> None:
        self._docs: dict[str, str] = {}  # memory_id -> content

    def add(self, memory_id: str, content: str) -> None:
        self._docs[memory_id] = content

    def remove(self, memory_id: str) -> None:
        self._docs.pop(memory_id, None)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """稀疏搜索，返回 (memory_id, score) 列表。"""
        query_terms = self._tokenize(query)
        if not query_terms or top_k <= 0:
            return []
        doc_terms = {memory_id: self._tokenize(content) for memory_id, content in self._docs.items()}
        doc_terms = {memory_id: terms for memory_id, terms in doc_terms.items() if terms}
        if not doc_terms:
            return []

        total_docs = len(doc_terms)
        average_length = sum(len(terms) for terms in doc_terms.values()) / total_docs
        document_frequency = Counter(
            term for terms in doc_terms.values() for term in set(terms) if term in query_terms
        )
        scored: list[tuple[str, float]] = []
        for memory_id, terms in doc_terms.items():
            term_counts = Counter(terms)
            score = 0.0
            for term in query_terms:
                if term_counts[term] <= 0:
                    continue
                idf = math.log(1 + (total_docs - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                tf = term_counts[term]
                denominator = tf + 1.5 * (1 - 0.75 + 0.75 * len(terms) / max(average_length, 1.0))
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
