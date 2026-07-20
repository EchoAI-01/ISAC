"""回复必要性评分 (ARCHITECTURE.md 3.7)。

评分模型:
  基础分: has_at(100) | has_mention(80) | private(40) | focus(40) | 普通(0)
  + 内容分: 问题+15, 请求+20, 征询+20, 长文本+5~10, 短反应-25
  + 压力分: pending 消息积压 (0~100)
  - 存在感惩罚: 近5分钟发言占比 (0~-25)
  × 频率系数 (0.5~1.0)
  阈值: REPLY_NECESSITY_THRESHOLD (80)
"""

from __future__ import annotations

from isac.channel.model import ISACMessage
from isac.core.constants import REPLY_NECESSITY_THRESHOLD
from isac.core.types import GatingContext


class ReplyNecessityJudge:
    """回复必要性评分器。"""

    def __init__(self, threshold: int = REPLY_NECESSITY_THRESHOLD):
        self.threshold = threshold

    async def score(self, pending: list[ISACMessage], context: GatingContext) -> float:
        """计算回复必要性得分。

        TODO(Day 16): 实现完整评分模型 (基础分 + 内容分 + 压力分 - 存在感惩罚) × 频率系数。
        """
        raise NotImplementedError("TODO(Day 16): 实现回复必要性评分模型")
