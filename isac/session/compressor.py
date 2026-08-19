"""U1 会话压缩写侧 (阶段3-2 M2: 压缩闭环)。

背景: U1 宣称"压缩=带 source_seqs 溯源的 replace 事件", 但只实现了折叠读取
(``history.py`` fold) 与校验 (``validate_compression``), **生产写侧完全缺失** ——
``EVENT_TURN_COMPRESSED`` 零写入点、``validate_compression`` 零调用方, 后果是
session_events.db 无任何压缩/保留机制、无限增长 (M2)。

本模块实现压缩写侧闭环:
1. 取会话分区事件, **保留最近活跃窗口** (不压缩, 与滑动窗口派生一致);
2. 把较旧前缀的内容事件 (message.user / turn.completed / 既有 turn.compressed)
   用 LLM 归纳为一段摘要 (含对此前压缩摘要的再归并, 即增量卷起);
3. ``validate_compression`` 拒绝"负压缩" (摘要 ≥ 原文); 通过才提交;
4. 追加 ``turn.compressed`` replace 事件 (payload.summary + source_seqs);
5. **保留 GC**: 物理删除被替代的**内容**事件, 遏制无界增长 —— 但**保留** tool.* /
   turn.aborted / session.migrated: DenyGuard 拒绝账本依赖 tool.outcome(DENIED)、
   torn-tail 修复依赖 tool.called/outcome 配对, 均不可删 (安全边界)。

LLM 失败 / 摘要不更短 / 无 LLM 时跳过 (返回 skipped 原因), 不破坏事件流。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from isac.session.history import SessionHistoryDeriver
from isac.session.models import (
    EVENT_TURN_COMPLETED,
    EVENT_TURN_COMPRESSED,
    EVENT_USER_MESSAGE,
    SessionEvent,
)
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.session.event_store import SessionEventStore

logger = get_logger(__name__)

# 可压缩的内容事件类型 (折叠时各自产出一条聊天消息)。tool.* / aborted / migrated
# 不产消息, 不参与压缩 (且 GC 必须保留, 见模块 docstring 安全边界)。
_COMPRESSIBLE_TYPES = frozenset({EVENT_USER_MESSAGE, EVENT_TURN_COMPLETED, EVENT_TURN_COMPRESSED})

# 摘要输入最大字符数 (防 LLM 输入爆炸; 与 consolidator 压缩口径同量级)。
DEFAULT_COMPRESS_INPUT_MAX_CHARS = 6000
# 单次 fetch 分页大小。
_FETCH_PAGE = 1000


@dataclass
class CompressionResult:
    """一次压缩的结果。skipped 非空 = 未压缩 (附原因); compressed_events = 被替代事件数。"""

    compressed_events: int = 0
    summary_chars: int = 0
    deleted_events: int = 0
    skipped: str = ""  # "" | llm_none | too_few | llm_failed | not_smaller


class SessionCompressor:
    """U1 会话压缩器 (写侧): 旧前缀 → LLM 摘要 → turn.compressed replace 事件 + 保留 GC。

    无状态、按 session_key 独立调用; 由上层 (manager 后台任务) 在事件数超阈值时触发。
    ``llm=None`` 时恒跳过 (不压缩, 零行为变化)。
    """

    def __init__(
        self,
        event_store: SessionEventStore,
        *,
        llm: Any = None,
        keep_recent_messages: int = 20,
        min_compress_messages: int = 6,
        input_max_chars: int = DEFAULT_COMPRESS_INPUT_MAX_CHARS,
        trigger_events: int = 0,
    ) -> None:
        self._store = event_store
        self._llm = llm
        # 保留最近 N 条内容消息不压缩 (须 >= 滑动窗口, 避免压掉活跃上下文)。
        self._keep_recent = max(2, int(keep_recent_messages))
        # 前缀至少要有这么多条内容消息才值得压缩 (避免频繁小压缩)。
        self._min_compress = max(2, int(min_compress_messages))
        self._input_max_chars = max(200, int(input_max_chars))
        # 触发阈值: 会话事件数 >= 此值时上层才触发压缩 (0 = 不触发)。随对象携带,
        # 避免在 services 袋里另存一个字符串键 (U9 红线棘轮)。
        self.trigger_events = max(0, int(trigger_events))

    async def compress_session(self, session_key: str) -> CompressionResult:
        """压缩一个会话分区。返回 CompressionResult (不抛异常打断上层)。"""
        if self._llm is None:
            return CompressionResult(skipped="llm_none")
        try:
            events = await self._fetch_all(session_key)
            prefix = self._select_prefix(events)
            if prefix is None:
                return CompressionResult(skipped="too_few")
            original = self._build_original_text(prefix)
            summary = await self._summarize(original)
            if not summary:
                return CompressionResult(skipped="llm_failed")
            # 压缩必须真压缩 (摘要更短), 否则拒绝提交 (validate_compression)。
            if not SessionHistoryDeriver.validate_compression(original, summary):
                return CompressionResult(skipped="not_smaller")
            source_seqs = [e.seq for e in prefix]
            await self._store.append(
                SessionEvent(
                    session_key=session_key,
                    event_type=EVENT_TURN_COMPRESSED,
                    timestamp=int(time.time()),
                    payload={"summary": summary, "source_seqs": source_seqs},
                )
            )
            await self._store.flush()
            # 保留 GC: 只删被替代的内容事件 (tool.*/aborted/migrated 保留)。
            deleted = await self._store.delete_events(session_key, source_seqs)
            logger.info(
                "会话压缩完成",
                session_key=session_key,
                compressed=len(source_seqs),
                deleted=deleted,
                summary_chars=len(summary),
            )
            return CompressionResult(
                compressed_events=len(source_seqs),
                summary_chars=len(summary),
                deleted_events=deleted,
            )
        except Exception as exc:  # noqa: BLE001 压缩失败不破坏事件流
            logger.warning("会话压缩异常, 已跳过", session_key=session_key, error=str(exc))
            return CompressionResult(skipped="error")

    # ── 内部 ──────────────────────────────────────────────────

    async def _fetch_all(self, session_key: str) -> list[SessionEvent]:
        """分页读取分区全部事件 (按 seq 升序)。"""
        out: list[SessionEvent] = []
        after_seq = 0
        while True:
            page = await self._store.fetch(session_key, after_seq=after_seq, limit=_FETCH_PAGE)
            if not page:
                break
            out.extend(page)
            after_seq = page[-1].seq
            if len(page) < _FETCH_PAGE:
                break
        return out

    def _select_prefix(self, events: list[SessionEvent]) -> list[SessionEvent] | None:
        """选出可压缩的旧前缀; 不足阈值返回 None。

        内容事件 = 折叠时产出聊天消息的事件 (user/completed/compressed), 且排除已被
        既有压缩替代者。保留最近 keep_recent 条作活跃窗口, 其余更旧的为前缀; 前缀
        少于 min_compress 不值得压缩。
        """
        superseded: set[int] = set()
        for e in events:
            if e.event_type == EVENT_TURN_COMPRESSED:
                superseded.update(int(s) for s in e.payload.get("source_seqs", []))
        content = [
            e
            for e in sorted(events, key=lambda ev: ev.seq)
            if e.event_type in _COMPRESSIBLE_TYPES and e.seq not in superseded
        ]
        if len(content) < self._keep_recent + self._min_compress:
            return None
        prefix = content[: -self._keep_recent]
        if len(prefix) < self._min_compress:
            return None
        return prefix

    def _build_original_text(self, prefix: list[SessionEvent]) -> str:
        """把前缀事件拼成待压缩文本 (含对此前压缩摘要的再归并)。"""
        lines: list[str] = []
        for e in prefix:
            if e.event_type == EVENT_USER_MESSAGE:
                lines.append(f"用户: {e.payload.get('content', '')}")
            elif e.event_type == EVENT_TURN_COMPLETED:
                lines.append(f"助手: {e.payload.get('content', '')}")
            elif e.event_type == EVENT_TURN_COMPRESSED:
                # 增量卷起: 旧压缩摘要作为素材一并再归纳。
                lines.append(f"此前摘要: {e.payload.get('summary', '')}")
        text = "\n".join(lines)
        if len(text) > self._input_max_chars:
            text = text[: self._input_max_chars]
        return text

    async def _summarize(self, original: str) -> str:
        """LLM 归纳为简洁中文摘要 (失败返回空串)。"""
        prompt = (
            "请将以下会话片段压缩为一段简洁中文摘要 (保留关键事实/结论/决定/待办, "
            "省略寒暄与重复), 不超过 3 句话, 不要 markdown 标记, 不要任何指令性措辞:"
            f"\n\n会话片段:\n{original}"
        )
        try:
            response = await self._llm.chat(
                system="",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("会话压缩: LLM 摘要失败", error=str(exc))
            return ""
        return _sanitize_summary(getattr(response, "content", "") or "")


# ── 摘要清洗 + 注入防护 (对齐 consolidator Fix-105 口径) ─────────
# 压缩摘要经 fold 进入后续 LLM 历史窗口, 素材是攻击者可控的会话原文 —— 须剥离
# 指令前缀行防间接 prompt injection。session 模块保持自包含, 不复用 memory 私函。
_INJECTION_PREFIX_RE = re.compile(
    r"^[ \t]*(?:System|SYSTEM|Assistant|IMPORTANT|CRITICAL|忽略[^\n:：]*|disregard\w*)\s*[:：].*$\n?",
    re.MULTILINE,
)


def _sanitize_summary(text: Any) -> str:
    """清洗 LLM 摘要 (去引号/代码块) + 剥离指令前缀行 (防间接 prompt injection)。"""
    if not text:
        return ""
    out = str(text).strip()
    if len(out) >= 2 and out[0] in "\"'" and out[-1] == out[0]:
        out = out[1:-1].strip()
    if out.startswith("```"):
        lines = out.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        out = "\n".join(lines).strip()
    out = _INJECTION_PREFIX_RE.sub("", out)
    return "\n".join(line for line in out.splitlines() if line.strip()).strip()
