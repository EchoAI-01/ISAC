"""U1 事件溯源会话内核 (ARCHITECTURE.md / DEVELOPMENT_PLAN.md §四 U1)。

会话存储从可变表升级为事件溯源: append-only 会话事件表 + 状态全部从事件派生
(消息历史=折叠、滑动窗口=窗口派生策略、压缩=带 source_seqs 溯源的 replace 事件)。
入站消息即持久事件 ("Model-visible ⟺ Logged"), 天然解决异步消息/重启续跑/审计合规。

子模块:
- ``models``: SessionEvent 数据模型 + 事件类型白名单。
- ``event_store``: SessionEventStore (append-only 事件表, WAL + write-behind 批处理)。
- ``history``: SessionHistoryDeriver (全量折叠 / 滑动窗口 / 压缩后三种派生策略)。
"""

from isac.session.event_store import SessionEventStore
from isac.session.history import SessionHistoryDeriver
from isac.session.models import (
    EVENT_SESSION_MIGRATED,
    EVENT_TOOL_CALLED,
    EVENT_TOOL_OUTCOME,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_COMPRESSED,
    EVENT_USER_MESSAGE,
    IGNORABLE_EVENT_TYPES,
    KNOWN_EVENT_TYPES,
    SessionEvent,
)

__all__ = [
    "SessionEvent",
    "SessionEventStore",
    "SessionHistoryDeriver",
    "KNOWN_EVENT_TYPES",
    "IGNORABLE_EVENT_TYPES",
    "EVENT_USER_MESSAGE",
    "EVENT_TURN_COMPLETED",
    "EVENT_TURN_COMPRESSED",
    "EVENT_TOOL_CALLED",
    "EVENT_TOOL_OUTCOME",
    "EVENT_SESSION_MIGRATED",
]
