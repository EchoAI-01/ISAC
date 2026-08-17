"""MidTermMemoryInjector: 中期记忆 (上下文压缩, ARCHITECTURE.md 3.6)。

R4-② 真实压缩 (方案 A, 绕开 hook 禁直接调 LLM 规范):
- COMPRESS hook 触发时, assembly 注册的 listener 仅"入队"待压缩会话快照到
  ``MemoryConsolidator`` (不调 LLM);
- consolidator 后台 ``_compress_step`` 低频消费队列, 用注入的 LLM 生成摘要落盘
  到 ``episodes.summary`` 列 (复用既存列 + episodes_fts_au 触发器自动同步);
- 本注入器 ``build()`` 改读本会话最近 episode 已落盘的 summary 注入为 RecallCue,
  不再截断复述 ``pending_messages[-5:]``。

三类承载逻辑:
- ``CompressionPolicy``: 压缩决策阈值 (消息条数/字符数); 供 listener 判定与配置承载。
- ``Summary``: 一次压缩摘要结果 (episode_id/session_id/文本/时间)。
- ``RecallCue``: 从 Summary 派生的可注入提示片段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from isac.core.types import InjectionContext
from isac.memory.injector.base import MemoryInjector

# 默认压缩阈值: pending_messages 条数或总字符数任一超限视为可压缩。
DEFAULT_COMPRESS_MIN_MESSAGES: int = 12
DEFAULT_COMPRESS_MIN_CHARS: int = 4000


@dataclass
class CompressionPolicy:
    """压缩决策阈值 (R4-②); 供 COMPRESS listener 与配置承载。

    实际触发仍由 ``AgentContext.should_compress()`` 主导 (loop.py:185); 本类
    提供 listener 侧二次校验与可配置阈值的承载, 避免对极短会话入队空摘要素材。
    """

    min_messages: int = DEFAULT_COMPRESS_MIN_MESSAGES
    min_chars: int = DEFAULT_COMPRESS_MIN_CHARS

    def should_compress(self, messages: list[Any]) -> bool:
        """消息条数或总字符数任一超阈 → 可压缩。空列表恒不压缩。"""
        if not messages:
            return False
        if len(messages) >= self.min_messages:
            return True
        total = sum(len(str(getattr(m, "content", "") or m if isinstance(m, str) else "")) for m in messages)
        return total >= self.min_chars


@dataclass
class Summary:
    """一次会话压缩摘要结果 (落盘 episodes.summary 的内存承载)。"""

    episode_id: str = ""
    session_id: str = ""
    text: str = ""
    created_at: int = 0


@dataclass
class RecallCue:
    """从 Summary 派生的可注入提示片段 (供 PromptInjector 输出)。"""

    summary: Summary
    extra: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """渲染为注入文本; 无 summary 文本时返回空串 (注入器据此降级)。"""
        text = (self.summary.text or "").strip()
        if not text:
            return ""
        lines = ["【中期记忆-内部参考】", "本会话此前上下文已压缩摘要：", f"- {text}"]
        lines.append("(仅作为推理参考，不要向用户逐字复述)")
        return "\n".join(lines)


class MidTermMemoryInjector(MemoryInjector):
    """中期记忆注入器: 注入本会话已落盘的压缩摘要 (RecallCue)。"""

    @property
    def key(self) -> str:
        return "mid_term_memory"

    @property
    def priority(self) -> int:
        return 30

    @property
    def tokens_estimate(self) -> int:
        return 300

    async def build(self, context: InjectionContext) -> str:
        """读本会话最近 episode 已落盘 summary, 渲染为 RecallCue 注入。

        无 metadata / 无 session_id / 无已落盘 summary 时返回空串 (零行为变化)。
        不再截断复述 ``pending_messages[-5:]`` (旧实现), 改读后台压缩产物。
        """
        metadata = getattr(self.pipeline, "metadata", None)
        if metadata is None or not hasattr(metadata, "get_episode_summary"):
            return ""
        session_id = str(getattr(context.session, "session_id", "") or "")
        if not session_id:
            return ""
        # U4: agent 键统一用 pipeline.namespace —— episodes 写在租户前缀 namespace
        # 下 (pipeline.store_episode), 此前读侧用裸 session.agent_id, tenancy 开启后
        # 必然读空。默认单租户时 namespace == agent_id, 零行为变化。
        agent_id = str(
            getattr(self.pipeline, "namespace", "") or getattr(context.session, "agent_id", "") or ""
        )
        # 取本会话最近 episode 的 summary (consolidator _compress_step 落盘)
        try:
            episode_id = await metadata.latest_episode_id_for_session(agent_id, session_id)
        except Exception:  # noqa: BLE001
            return ""
        if not episode_id:
            return ""
        try:
            summary_text = await metadata.get_episode_summary(agent_id, episode_id)
        except Exception:  # noqa: BLE001
            return ""
        if not summary_text:
            return ""
        cue = RecallCue(summary=Summary(
            episode_id=episode_id, session_id=session_id, text=summary_text,
        ))
        return cue.render()
