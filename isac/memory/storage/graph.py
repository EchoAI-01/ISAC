"""GraphStore: 关系图存储 (最小实现: 用户-群-话题关系边)。"""

from __future__ import annotations


class GraphStore:
    """关系图存储。

    [桩] 边 (subject, relation, object, agent_id, weight), 支持按节点查询邻居,
    供 Graph Search 路径使用 (ARCHITECTURE.md 3.6)。待真实图后端落地。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def add_edge(self, agent_id: str, subject: str, relation: str, object_: str, weight: float = 1.0) -> None:
        raise NotImplementedError("GraphStore.add_edge 尚未实现")

    async def neighbors(self, agent_id: str, node: str, relation: str | None = None) -> list[tuple[str, float]]:
        """查询节点邻居，返回 (node, weight) 列表。"""
        raise NotImplementedError("GraphStore.neighbors 尚未实现")
