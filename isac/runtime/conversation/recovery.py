"""ConversationStateStore: 会话拟人状态恢复 (L5, HUMANLIKE_RUNTIME.md §7)。

L5 实现: 原子写 JSON 落盘到 data/agents/<id>/conversation/<session_id>.json;
load 时读回 → 计算 elapsed → 短/中/长窗口生成 recovery_hint → 复位运行态为
idle、未决 wait 置 None (中断后不续跑旧进度, 与 D9/J4 思路一致)。默认 enabled
=False, 不接入主链路 (store 总是工作但没人调 save), 主链路零行为变化。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from isac.runtime.conversation.models import WaitState
from isac.utils.fs import atomic_write_json
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 短/中/长窗口阈值 (秒); 与 HUMANLIKE_RUNTIME.md §7 对齐。
SHORT_WINDOW_SECONDS = 5 * 60  # < 5min: 自然接上话题
MEDIUM_WINDOW_SECONDS = 60 * 60  # < 1h: 刚上线但记得前情
LONG_WINDOW_SECONDS = 24 * 60 * 60  # > 24h: 不恢复 (视为新会话)

DEFAULT_BASE_DIR = "data/agents"


@dataclass
class ConversationSnapshot:
    """一次会话拟人状态的可持久化快照 (L5)。"""

    agent_id: str
    session_id: str
    state: str = "idle"
    pending_wait: WaitState | None = None
    recent_message_ids: list[str] = field(default_factory=list)
    recovery_hint: str = ""  # 注入下一轮 Prompt 的 "上次中断/恢复" 提示


class ConversationStateStore:
    """会话拟人状态持久化/恢复 (原子写 JSON + 短/中/长窗口判定)。

    与 D9/J4 "中断后不恢复旧进度" 思路一致: 恢复时把运行态标为终止/复位
    (idle) 而非续跑, 只带回参考消息与提示。
    """

    def __init__(self, *, base_dir: str = DEFAULT_BASE_DIR) -> None:
        self._base_dir = base_dir

    def _snapshot_path(self, agent_id: str, session_id: str) -> Path:
        """持久化路径: <base_dir>/<agent_id>/conversation/<session_id>.json。"""
        # session_id 可能含特殊字符 (URL 安全起见用 hash 或转义), 此处取简单实现。
        safe_session = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return Path(self._base_dir) / agent_id / "conversation" / f"{safe_session}.json"

    def save(self, snapshot: ConversationSnapshot) -> None:
        """持久化一次快照 (原子写 + last_active_at=time.time())。

        pending_wait 不持久化 (重启后视为终止, 不续跑旧进度)。
        """
        path = self._snapshot_path(snapshot.agent_id, snapshot.session_id)
        data = {
            "agent_id": snapshot.agent_id,
            "session_id": snapshot.session_id,
            "state": snapshot.state,
            "recent_message_ids": list(snapshot.recent_message_ids),
            "last_active_at": time.time(),
        }
        try:
            atomic_write_json(path, data)
            logger.debug(
                "会话快照已保存",
                agent_id=snapshot.agent_id,
                session_id=snapshot.session_id,
                path=str(path),
            )
        except Exception as exc:  # noqa: BLE001
            # 落盘失败不阻塞关闭流程 (恢复是旁路能力)
            logger.warning("会话快照保存失败, 已忽略", error=str(exc))

    def load(self, agent_id: str, session_id: str) -> ConversationSnapshot | None:
        """启动时恢复某会话快照; 无则 None。

        L5: 读 JSON → 计算 elapsed → 短/中/长窗口生成 recovery_hint →
        复位 state=idle, pending_wait=None (中断后不续跑)。
        """
        path = self._snapshot_path(agent_id, session_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("会话快照读取失败, 视为新会话", path=str(path), error=str(exc))
            return None
        last_active_at = float(data.get("last_active_at", 0.0))
        elapsed = time.time() - last_active_at
        # 超过 24h 不恢复 (视为新会话)
        if elapsed >= LONG_WINDOW_SECONDS:
            logger.info(
                "会话快照已过期, 不恢复",
                agent_id=agent_id,
                session_id=session_id,
                elapsed_hours=round(elapsed / 3600, 1),
            )
            return None
        hint = self._build_recovery_hint(elapsed)
        snap = ConversationSnapshot(
            agent_id=str(data.get("agent_id", agent_id)),
            session_id=str(data.get("session_id", session_id)),
            state="idle",  # 复位运行态 (中断后不续跑旧进度)
            pending_wait=None,  # 未决 wait 标记为终止
            recent_message_ids=list(data.get("recent_message_ids", [])),
            recovery_hint=hint,
        )
        logger.info(
            "会话快照已恢复",
            agent_id=agent_id,
            session_id=session_id,
            elapsed_seconds=round(elapsed, 1),
            hint=hint[:30],
        )
        return snap

    @staticmethod
    def _build_recovery_hint(elapsed_seconds: float) -> str:
        """按 elapsed 生成 recovery_hint (短/中/长窗口文案, HUMANLIKE_RUNTIME.md §7)。"""
        if elapsed_seconds < SHORT_WINDOW_SECONDS:
            return (
                "【内部参考】这是启动时恢复的历史上下文提醒, 不代表当前用户刚刚发来新消息。"
                "你像短暂离线后重新上线, 仍记得上次关机前的聊天内容, "
                "自然接上之前的话题。这是内部参考, 不要向用户逐字复述。"
            )
        if elapsed_seconds < MEDIUM_WINDOW_SECONDS:
            return (
                "【内部参考】这是启动时恢复的历史上下文提醒, 不代表当前用户刚刚发来新消息。"
                "距离上次关机前最后一条可恢复聊天记录已经过去一段时间, "
                "你像刚上线但还记得前情。这是内部参考, 不要向用户逐字复述。"
            )
        return (
            "【内部参考】这是启动时恢复的历史上下文提醒, 不代表当前用户刚刚发来新消息。"
            "距离上次关机前已经过去较长时间, 你像睡了一会儿/刚回来, "
            "仍记得之前聊过的内容但需要重新进入状态。这是内部参考, 不要向用户逐字复述。"
        )
