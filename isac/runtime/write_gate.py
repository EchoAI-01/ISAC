"""U8 SessionWriteGate: 会话写入统一仲裁门 (预约表 + hold 窗口 + fail-closed)。

背景: 主动写入会话流的各路写者 (强制话轮/handoff/插件与 mesh 注入) 此前各靠
会话锁 + 补丁约定串行 (Fix-81/82 两次补丁都在修"写者之间的状态机互踩")。
U8 收编为单一仲裁门 (参考 oh-my-openagent prompt-async-gate 预约表范式):

- **先预约后写入**: 写者动手前 ``reserve(session_key, source)`` 取得租约;
  同一 session_key 同时只允许一个活跃租约 (先到者得, 后来者拿到 None 即放弃,
  不排队不抢锁 —— 主动写入机会性, 让位给在途回合)。
- **hold 窗口**: 租约 ``hold_seconds`` (默认 30s, monotonic) 内有效; 超时作废。
- **fail-closed**: ``commit`` 在租约过期/已取消/已消费时返回 False —— 写入方
  必须丢弃结果, 不得继续把产出推给用户; ``reserve`` 失败不得绕行写入。

反应式消息回合 (process_message 主链路) 不经此门 —— 它是被动响应, 由会话锁串行;
本门只管**主动/注入式**写入 (门内名单见 _ALLOWED_SOURCES)。

AST 审计测试 (tests/unit/test_u8_write_gate_audit.py) 常驻: 门之外出现会话状态机
写入点 (forced_turn 赋值 / transition_to 调用) 即失败 —— 故意绕过当场捕获。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 允许经门预约的写入来源 (门内名单; 新写者接入须在此登记 + 过审计测试)。
# 2026-08-19 (U8 名实相符): 移除 plugin_injection/memory_injection —— 二者全仓零
# reserve() 写者 (实际写者仅 proactive=manager 强制话轮、handoff=会话移交), 留在
# 名单里是"登记了不存在的能力"。未来插件/记忆注入真要经门写入时再登记并补审计测试。
_ALLOWED_SOURCES = frozenset({"proactive", "handoff"})

# hold 窗口上下限 (防配置误填): 太短租约做不完事, 太长卡死会话写入面。
_MIN_HOLD_SECONDS = 1.0
_MAX_HOLD_SECONDS = 600.0
DEFAULT_HOLD_SECONDS = 30.0


@dataclass
class WriteReservation:
    """一次会话写入租约。"""

    reservation_id: str
    session_key: str
    source: str
    created_at: float  # monotonic
    hold_seconds: float
    consumed: bool = False
    cancelled: bool = False

    def expired(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return now >= self.created_at + self.hold_seconds


@dataclass
class SessionWriteGate:
    """会话写入仲裁门 (预约表)。进程内单例, 经 `session_write_gate` 服务键共享。"""

    default_hold_seconds: float = DEFAULT_HOLD_SECONDS
    # session_key -> 活跃租约 (单写者语义: 至多一份)
    _active: dict[str, WriteReservation] = field(default_factory=dict)
    _now_fn: Any = None  # 测试可注入时钟

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.monotonic()

    def _purge_session(self, session_key: str) -> None:
        """回收该会话已过期/已消费的租约。"""
        reservation = self._active.get(session_key)
        if reservation is not None and (
            reservation.expired(self._now()) or reservation.consumed or reservation.cancelled
        ):
            self._active.pop(session_key, None)

    def _purge_stale(self) -> None:
        """Fix-126: 回收**全部**已过期/已消费/已取消的租约 (不限当前 key)。

        此前 `_purge_session` 只清被 reserve/active 显式触及的 key —— 一个会话的租约
        若过期后再无人 reserve/active 它, 该条目永久驻留 `_active`, 长期运行无界增长。
        每次 reserve 顺带全量清扫, 让 `_active` 只保留真正活跃的租约 (数量有界)。
        """
        now = self._now()
        stale = [
            key for key, reservation in self._active.items()
            if reservation.expired(now) or reservation.consumed or reservation.cancelled
        ]
        for key in stale:
            self._active.pop(key, None)

    def reserve(
        self,
        session_key: str,
        source: str,
        *,
        hold_seconds: float | None = None,
    ) -> WriteReservation | None:
        """预约写入租约; 同会话已有活跃租约或来源未登记时返回 None (fail-closed)。"""
        if source not in _ALLOWED_SOURCES:
            logger.warning("会话写入来源未登记, 拒绝预约", session_key=session_key, source=source)
            return None
        self._purge_stale()  # Fix-126: 全量回收陈旧租约, 保持 _active 有界
        self._purge_session(session_key)
        if session_key in self._active:
            existing = self._active[session_key]
            logger.info(
                "会话写入仲裁: 已有活跃租约, 拒绝新预约",
                session_key=session_key,
                holder=existing.source,
                requester=source,
            )
            return None
        hold = hold_seconds if hold_seconds is not None else self.default_hold_seconds
        hold = max(_MIN_HOLD_SECONDS, min(_MAX_HOLD_SECONDS, float(hold)))
        reservation = WriteReservation(
            reservation_id=uuid.uuid4().hex[:16],
            session_key=session_key,
            source=source,
            created_at=self._now(),
            hold_seconds=hold,
        )
        self._active[session_key] = reservation
        return reservation

    def commit(self, reservation: WriteReservation) -> bool:
        """提交租约 (写入完成)。过期/已取消/非当前持有者 → False (fail-closed)。

        返回 False 时写入方**必须丢弃产出** —— 租约失效意味着另一写者可能已接手
        会话, 继续推送会互踩状态机 (Fix-81/82 的根因)。
        """
        current = self._active.get(reservation.session_key)
        if current is None or current.reservation_id != reservation.reservation_id:
            return False
        if reservation.cancelled or current.cancelled:
            return False
        if reservation.expired(self._now()):
            logger.info(
                "会话写入租约超时作废 (fail-closed)",
                session_key=reservation.session_key,
                source=reservation.source,
            )
            self._active.pop(reservation.session_key, None)
            return False
        reservation.consumed = True
        self._active.pop(reservation.session_key, None)
        return True

    def cancel(self, reservation: WriteReservation) -> None:
        """取消租约 (写入放弃/异常): 释放会话写入面, 不产生提交。"""
        reservation.cancelled = True
        current = self._active.get(reservation.session_key)
        if current is not None and current.reservation_id == reservation.reservation_id:
            self._active.pop(reservation.session_key, None)

    def active(self, session_key: str) -> WriteReservation | None:
        """查询会话当前活跃租约 (无/已失效返回 None)。"""
        self._purge_session(session_key)
        return self._active.get(session_key)

    def __len__(self) -> int:
        return len(self._active)
