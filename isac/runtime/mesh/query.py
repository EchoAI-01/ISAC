"""U2 Agent Mesh 记忆查询应答 (P2): 接收端执行授权记忆查询。

原 isac/main.py 的 _answer_memory_query 拆出 (U2 装配层重构)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.runtime.bus import InterAgentMessage
from isac.runtime.manager import AgentManager
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")

async def _answer_memory_query(
    agent_manager: AgentManager, target_agent_id: str, message: InterAgentMessage
) -> str:
    """P2: 接收端执行授权记忆查询, 返回格式化结果 (经 bus response 回到查询方)。

    scope 语义 (ROUTING_AND_AGENT_MESH.md §6.1): "user:<id>" / "group:<id>" ——
    复用 pipeline.search 的 user/group ACL 参数做真实裁剪; 未知格式保守跳过
    (绝不扩大可见范围)。检索失败返回空串 (查询方看到"无相关内容")。

    MVP-Fix (安全): **scopes 为空一律拒绝**。此前空 scopes 走无 user/group 参数
    的全量检索, 而 visible_memory_scopes 的默认值就是空 —— 管理员只授予
    permissions=["memory_query"] 却忘了配 scopes 时, 对端可读取目标 Agent 的
    全部记忆 (含其他用户的私聊), 违背 Link ACL 的 deny-by-default 语义。
    """
    instance = await agent_manager.get(target_agent_id)
    if instance is None or instance.status != "running":
        return ""
    filters = message.context.get("filters") or {}
    scopes = [str(s) for s in (filters.get("scopes") or []) if s]
    if not scopes:
        logger.warning(
            "跨 Agent 记忆查询被拒: Link 未配置 visible_memory_scopes (空 = 拒绝, 非全量)",
            from_agent=message.from_agent,
            target=target_agent_id,
        )
        return ""
    query = message.content
    hits: list[Any] = []
    try:
        for scope in scopes[:5]:
            kind, _, ident = scope.partition(":")
            if kind == "user" and ident:
                hits.extend(await instance.memory.search(query, top_k=3, user_id=ident))
            elif kind == "group" and ident:
                hits.extend(await instance.memory.search(query, top_k=3, group_id=ident))
            else:
                logger.warning("忽略无法识别的记忆可见范围 (保守跳过)", scope=scope)
    except Exception:  # noqa: BLE001
        logger.warning("跨 Agent 记忆查询失败", target=target_agent_id, exc_info=True)
        return ""
    seen: set[str] = set()
    lines: list[str] = []
    for hit in hits:
        if hit.id in seen:
            continue
        seen.add(hit.id)
        lines.append(f"- {hit.content[:200]}")
    return "\n".join(lines[:5])
