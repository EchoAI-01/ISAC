"""J4 子 Agent 上下文信封构造 (SPECIFICATION.md 2.5)。

约束 (§2.5.1): 不默认复制主会话全量历史、MoodState、RelationshipState、用户画像或
私有记忆正文; 只带最小任务摘要与显式授权引用, 隔离陪伴上下文避免污染。

骨架状态: 从 SubAgentTask 抽取最小信封; 摘要压缩与授权引用校验留待 J4 实现节点。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.runtime.subagent.models import ContextEnvelope

if TYPE_CHECKING:
    from isac.runtime.subagent.models import SubAgentTask


class ContextEnvelopeBuilder:
    """把主 Agent 的任务请求转换为最小上下文信封。"""

    def build(self, task: SubAgentTask) -> ContextEnvelope:
        """构造最小信封: 只带 objective、显式摘要与授权引用, 不拷贝主会话可变上下文。

        TODO(J4): 对 summary 做长度/敏感度压缩; 校验 authorized_refs 是否在父授权范围内。
        """
        context = task.context or {}
        return ContextEnvelope(
            objective=task.objective,
            summary=str(context.get("summary", "")),
            authorized_refs=list(context.get("authorized_refs", []) or []),
            allowed_memory_scopes=list(task.policy.readable_memory_scopes),
        )
