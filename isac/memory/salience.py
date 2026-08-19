"""记忆显著度评分 (importance producer, 阶段2-4 P1-3)。

背景: consolidator 的"重要性+时间衰减剪枝"依赖 episode.importance < 阈值 (默认 0.2)
才会软删。此前全仓 importance 只有两个常量写入 (自家回合 0.5 / 旁听 0.3), **没有任何
生产者产出 <0.2 的值** → 剪枝步在默认配置下永远删不到东西, 形同死步 (P1-3 根因)。

本模块提供**规则显著度评分器** ``ImportanceScorer``:
- 纯函数、确定性、无 LLM / 无 IO / 无活动服务依赖 → 稳定、可单测、不拖慢写入路径;
- 产出一个**真实分布**: 琐碎寒暄/应答落在 <0.2 (可被时间衰减剪掉), 普通回合居中,
  含"记住/偏好/事实/约定"等值得记的内容落在高位 → 剪枝与排序都有素材;
- 接口为单一 ``score()`` 方法, 将来要换 LLM 显著度评分只需替换实现 (升级位), 调用方
  (runtime/manager.py 两处写入点) 不变。

评分信号 (对**用户侧文本**为主, 因为值得记的是用户透露的信息):
- 显式记忆指令: "记住/别忘了/remember …"
- 自我事实/偏好: "我叫/我生日/我喜欢/我住在/我的…是 …"
- 约定/计划/具体数字日期: "决定/约好/明天/3月5日/138…"
- 实质度: 文本长度 + 是否有来有回 (user+reply 都在)
- 琐碎应答短路: 纯语气词/寒暄 ("嗯/好的/哈哈/谢谢") → 低位
- 旁听 (observed) 折扣: 非本 Agent 主回合, 天然更低
"""

from __future__ import annotations

import re

# ── 权重与阈值 (集中于此, 便于调参/测试; 将来可经 config 注入) ─────────
# 琐碎应答短路命中时的基础分 (远低于剪枝阈值 0.2)。
TRIVIAL_BASE: float = 0.08
# 旁听 (observed) 折扣系数 —— 非主回合记忆天然更不重要。
OBSERVED_FACTOR: float = 0.6
# 标记加成上限 (防止多重标记叠加把分数顶满)。
MAX_MARKER_BOOST: float = 0.50
# 最终分数钳制范围。
SCORE_MIN: float = 0.0
SCORE_MAX: float = 1.0

# 显式记忆指令: 用户明确要求记住某事。
_REMEMBER_RE = re.compile(
    r"记住|记一下|记得|别忘了|别忘|记好|remember|don'?t\s+forget|keep\s+in\s+mind",
    re.IGNORECASE,
)
# 自我事实 / 偏好 / 身份 —— 值得长期记住的用户画像素材。
_SELF_FACT_RE = re.compile(
    r"我叫|我的名字|我名字|我生日|我的生日|我属|我是|我今年|我住在|我在.{0,6}(住|工作|上班)|"
    r"我(喜欢|讨厌|爱吃|不吃|过敏|害怕|希望|想要|打算|计划)|我的(手机|电话|邮箱|微信|qq|账号|偏好)|"
    r"my\s+name|i\s+am|i\s+like|i\s+love|i\s+hate|i\s+prefer",
    re.IGNORECASE,
)
# 约定 / 计划 / 具体时间日期数字 —— 有明确指代、日后可能要回看的信息。
_COMMIT_RE = re.compile(
    r"决定|说好|约好|约定|定了|安排|提醒我|明天|后天|大后天|下周|下个月|"
    r"\d{1,2}月\d{1,2}[日号]|周[一二三四五六日天]|"
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|\d{1,2}[:：]\d{2}|"
    r"\d{6,}",  # 较长数字串 (电话/订单/编号等)
    re.IGNORECASE,
)
# 琐碎应答 / 寒暄: 整条仅由语气词、简短客套构成。
_TRIVIAL_RE = re.compile(
    r"^[\s~!！。.，,、?？…]*("
    r"嗯+|哦+|喔+|啊+|哈+|嘿+|嘻+|呃+|额+|噢+|诶+|"
    r"好的?|好哒|好呀|行|可以|没问题|没事|没事的|没事了|"
    r"ok|okay|k|嗯嗯|了解|明白|收到|知道|知道了|懂了|get|"
    r"谢谢|多谢|谢了|感谢|thx|thanks?|thank\s+you|3q|"
    r"拜拜|再见|晚安|早安|早安呀|你好|您好|hi|hello|hey|yo|"
    r"对|对的|是的|是|嗯好|成|中|"
    r"哈哈+|呵呵+|嘿嘿+|233+|666+|牛|厉害|nb|yyds"
    r")[\s~!！。.，,、?？…]*$",
    re.IGNORECASE,
)
# 琐碎判定的最大长度 —— 超过则不走琐碎短路 (长文本不太可能只是寒暄)。
_TRIVIAL_MAX_LEN = 16


class ImportanceScorer:
    """规则显著度评分器 (确定性、无副作用)。

    单一入口 ``score()``; 换 LLM 评分只需提供同签名实现替换 (见模块 docstring 升级位)。
    """

    def score(
        self,
        user_text: str,
        reply_text: str = "",
        *,
        observed: bool = False,
        is_group: bool = False,
    ) -> float:
        """评估一轮对话的记忆显著度, 返回 [0,1]。

        user_text: 用户侧文本 (值得记的主要来源); reply_text: Agent 回复 (佐证实质度);
        observed: 是否旁听写入 (非本 Agent 主回合); is_group: 是否群聊 (保留作上下文,
        当前规则不据此调分, 预留给后续策略)。
        """
        user = (user_text or "").strip()
        reply = (reply_text or "").strip()

        # 标记加成优先算 —— 哪怕很短, "记住我生日是3月5日" 也绝不能被当琐碎应答剪掉。
        boost = self._marker_boost(user)

        # 琐碎应答短路: 仅当无任何记忆标记、且整条只是语气词/客套时落低位。
        if boost <= 0.0 and self._is_trivial(user, reply):
            base = TRIVIAL_BASE
        else:
            base = self._substance_baseline(user, reply)

        score = base + min(boost, MAX_MARKER_BOOST)
        if observed:
            score *= OBSERVED_FACTOR
        return max(SCORE_MIN, min(SCORE_MAX, score))

    # ── 子信号 ────────────────────────────────────────────────

    @staticmethod
    def _marker_boost(user: str) -> float:
        """记忆标记加成: 显式指令 > 自我事实/偏好 > 约定/日期数字。

        权重校准目标: 单一标记 + 中等实质度即可越过 0.5 (保留区), 确保值得记的
        内容不会被时间衰减误剪; 琐碎区 (<0.2) 与保留区 (>0.5) 之间留普通带。
        """
        if not user:
            return 0.0
        boost = 0.0
        if _REMEMBER_RE.search(user):
            boost += 0.35
        if _SELF_FACT_RE.search(user):
            boost += 0.30
        if _COMMIT_RE.search(user):
            boost += 0.25
        return boost

    @staticmethod
    def _is_trivial(user: str, reply: str) -> bool:
        """琐碎判定: 用户侧很短且整体只是语气词/客套。

        只看用户侧 —— Agent 回复再长也改变不了"用户没说什么值得记的"这一事实;
        但要 user+reply 都短, 避免把"用户简短提问 + Agent 长答"误判为琐碎。
        """
        if not user:
            # 没有用户文本 (异常/空回合) → 视为低显著。
            return True
        if len(user) > _TRIVIAL_MAX_LEN:
            return False
        if not _TRIVIAL_RE.match(user):
            return False
        # 用户侧命中琐碎; 若回复也很短, 才整体判琐碎 (长回复多半含实质信息)。
        return len(reply) <= 60

    @staticmethod
    def _substance_baseline(user: str, reply: str) -> float:
        """实质度基线: 按合并文本长度映射到 [0.10, 0.45]。

        有来有回 (user 与 reply 都非空) 说明是一轮真实问答, 略加分。
        """
        combined_len = len(user) + len(reply)
        if combined_len <= 0:
            base = 0.10
        elif combined_len <= 10:
            base = 0.18
        elif combined_len <= 40:
            base = 0.25
        elif combined_len <= 120:
            base = 0.32
        elif combined_len <= 400:
            base = 0.38
        else:
            base = 0.45
        if user and reply:
            base += 0.03  # 完整一轮问答
        return base


# 默认实例 (无状态, 全仓共用)。
DEFAULT_SCORER = ImportanceScorer()


def score_importance(
    user_text: str,
    reply_text: str = "",
    *,
    observed: bool = False,
    is_group: bool = False,
) -> float:
    """便捷入口: 用默认评分器评估一轮对话显著度 (见 ``ImportanceScorer.score``)。"""
    return DEFAULT_SCORER.score(
        user_text, reply_text, observed=observed, is_group=is_group
    )
