"""U1 会话事件模型与事件类型白名单。

事件溯源的核心契约: 会话状态全部从 append-only 事件流派生。事件类型用白名单
管理 —— 重建 (重放) 时遇到未知事件类型默认**拒绝** (raise), 仅 ``IGNORABLE_EVENT_TYPES``
里的类型可安全跳过 (前向兼容: 新版本写入的辅助事件, 旧版本重建时忽略而非崩溃)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── 事件类型白名单 ────────────────────────────────────────────
# 入站用户消息 (Model-visible ⟺ Logged: 消息只要可能进 LLM 就必须先落事件)。
EVENT_USER_MESSAGE = "message.user"
# Agent 完成一次回复 (一个话轮的助手输出)。
EVENT_TURN_COMPLETED = "turn.completed"
# 压缩 replace 事件: payload.summary 替代 payload.source_seqs 引用的原始事件区间。
EVENT_TURN_COMPRESSED = "turn.compressed"
# 工具调用开始 (torn-tail 判定用: 有 tool.called 无对应 tool.outcome = 孤儿工具调用)。
EVENT_TOOL_CALLED = "tool.called"
# 工具调用结果 (与 tool.called 配对)。
EVENT_TOOL_OUTCOME = "tool.outcome"
# 旧 sessions 数据迁移标记 (scripts/migrate_sessions_to_events.py 写入): 记录 U1 前
# 既有会话的身份元数据 (legacy session_id / 平台 / 群 / 创建与最后活跃时间),
# 让事件流成为唯一时间线后仍保有迁移前会话的溯源凭证。不参与历史重建。
EVENT_SESSION_MIGRATED = "session.migrated"

# 重建必需的事件类型 (缺失/未知 → 拒绝重建)。
KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_USER_MESSAGE,
        EVENT_TURN_COMPLETED,
        EVENT_TURN_COMPRESSED,
        EVENT_TOOL_CALLED,
        EVENT_TOOL_OUTCOME,
    }
)

# 可忽略事件类型 (重建时安全跳过, 不参与历史折叠)。前向兼容: 新增的辅助事件
# (如 session.note / typing.indicator) 若对历史重建无意义, 登记于此 —— 旧版本
# 重建遇到新版本写入的此类事件时忽略而非崩溃。session.migrated 是首个实例。
IGNORABLE_EVENT_TYPES: frozenset[str] = frozenset({EVENT_SESSION_MIGRATED})

# torn-tail 修复: 孤儿工具调用 (有 called 无 outcome) 合成的结果标记, 不猜结果。
OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


@dataclass
class SessionEvent:
    """一条会话事件 (append-only 事件流的最小单元)。

    session_key 是事件流分区键 (``agent_id:platform:group/user``), 与
    SessionManager.make_session_key 口径一致 —— 同一会话 (跨重启) 的事件聚在一起,
    重放/派生按 session_key 进行。seq 为该分区内单调递增序号 (0 = 由 store 自动分配)。
    """

    session_key: str
    event_type: str
    timestamp: int
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0

    def is_known(self) -> bool:
        return self.event_type in KNOWN_EVENT_TYPES

    def is_ignorable(self) -> bool:
        return self.event_type in IGNORABLE_EVENT_TYPES
