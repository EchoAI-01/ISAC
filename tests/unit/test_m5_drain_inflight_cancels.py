"""2026-08-19 Medium 批清第三批回归 (M5 core-session): drain_inflight 超时后取消在途任务。

此前 drain 超时只记 warning 不取消 —— 随后 LIFO 链关闭 providers/store, 残留任务在
已关闭资源上继续运行并各自抛错, 优雅关闭的"不丢消息"承诺在超时分支不成立。修复后
超时必须取消残留任务并 gather 收尾 (_process_locked 的 finally 释放会话锁)。
"""

from __future__ import annotations

import asyncio

import pytest

import isac.dispatch as dispatch_mod
from isac.channel.model import ISACMessage
from isac.dispatch import make_message_dispatcher
from isac.gateway.lock import SessionLockManager


class _NullRouter:
    """route 返回 None → _process_locked 跳过会话解析/notify 块, 直达锁 + process_message。"""

    async def route(self, message: ISACMessage):  # noqa: ANN001
        return None


def _msg() -> ISACMessage:
    return ISACMessage(
        msg_id="m1", platform="fake", timestamp=0, user_id="u1", user_name="U", content="hi"
    )


async def test_m5_drain_inflight_cancels_lingering_task(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _blocking(message: ISACMessage, **kwargs) -> None:  # noqa: ANN001
        started.set()
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    # process_message 是 dispatch 模块级函数, _process_locked 闭包运行期全局查找 →
    # monkeypatch 模块属性即可让真实管线在 stub 处阻塞。
    monkeypatch.setattr(dispatch_mod, "process_message", _blocking)

    _handle, drain = make_message_dispatcher(
        event_bus=object(),  # 仅转发给被 stub 的 process_message, 不会被使用
        router=_NullRouter(),
        session_mgr=object(),
        user_mapper=object(),
        agent_manager=object(),
        channel_registry=object(),
        metrics=object(),
        session_lock=SessionLockManager(),
        drain_timeout_seconds=0.1,
    )
    await _handle(_msg())
    # 确保任务已进入阻塞的 process_message (否则 drain 可能在任务启动前就判空返回)
    await asyncio.wait_for(started.wait(), timeout=5)
    await drain()  # 等 0.1s 超时后取消残留任务
    assert cancelled.is_set(), "超时后残留任务必须被取消, 不能继续在已关闭资源上运行"
