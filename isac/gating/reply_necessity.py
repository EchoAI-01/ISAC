"""回复必要性评分 (ARCHITECTURE.md 3.7)。

评分模型 (具体实现见 D1):
  基础分: has_at(100) | has_mention(80) | private(40) | focus(40) | 普通(0)
  + 内容分:
      - 问题: 以疑问词/问号结尾，+15
      - 请求: 含 "请"/"帮我"/"能不能" 等祈使/委托词，+20
      - 征询: 明确征求 Bot 意见（@Bot + 选择/看法问句），+20
      - 长文本: 内容 > 120 字且信息密度高，+5~10
      - 短反应: 内容 <= 5 字（如 "哈哈"、"嗯"），-25
  + 压力分: pending 消息积压 (0~100，按 pending_count 线性递增)
  - 存在感惩罚: 近 5 分钟本 Agent 发言占比 (0~-25)
  × 频率系数 (0.5~1.0，按近 5 分钟本 Agent 回复次数衰减)
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

        TODO(D1): 实现完整评分模型 (基础分 + 内容分 + 压力分 - 存在感惩罚) × 频率系数。
        当前为安全兜底：私聊给 40 分，群聊普通消息给 0 分，避免门控崩溃。
        """
        # 安全兜底：保证主链路可启动，不触发回复，除非强制触发条件（已由 GatingSystem 处理）
        return 40.0 if context.is_private else 0.0
