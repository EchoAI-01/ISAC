"""实时日志 SSE 端点 (T4 错误可诊断)。

/api/v1/logs/tail: 仿 routes_events 的 /events/stream SSE 模式, 但消费 LogBuffer 单例
(logger.py 注入的 structlog processor 把日志写入 buffer), 而非 EventBus (EventBus
绑定 EventType 枚举, 无 log 事件类型)。

支持:
- Last-Event-ID 断线恢复 (Header 优先, query 回退)
- heartbeat 保活
- max_connections 连接数上限 (默认 50, 日志台比事件流并发低)
- level 过滤 (query ?level=warning 只推 warning 及以上)

仅会话 Cookie 模式可用 (与 events/stream 一致: EventSource 不支持自定义 Header,
纯 Bearer 客户端无日志台需求)。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from isac.utils.log_buffer import get_log_buffer

_DEFAULT_MAX_CONNECTIONS = 50
_DEFAULT_HEARTBEAT_SECONDS = 10.0

# level 字符串 -> 数值 (对齐 logger._LEVEL_MAP); 用于 ?level= 过滤。
_LEVEL_ORDER: dict[str, int] = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}


def build_router(
    auth_dependency: Any = None,
    max_connections: int = _DEFAULT_MAX_CONNECTIONS,
) -> Any:
    """构造日志 SSE 路由。LogBuffer 未启用 (get_log_buffer() is None) 时返回 None 不挂载。"""
    if get_log_buffer() is None:
        return None

    from fastapi import APIRouter, Depends, Header, HTTPException
    from fastapi.responses import StreamingResponse

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["logs"], dependencies=deps)

    # 连接计数 (同步, 无 await, 同 routes_events._EventStreamState)
    active = [0]
    active_lock = asyncio.Lock()

    @router.get("/logs/tail")
    async def logs_tail(
        last_event_id: int | None = None,
        heartbeat_seconds: float | None = None,
        level: str | None = None,
        max_chunks: int | None = None,
        last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> Any:
        async with active_lock:
            if active[0] >= max_connections:
                raise HTTPException(
                    status_code=429,
                    detail={"code": "TOO_MANY_CONNECTIONS", "message": "日志 SSE 连接数已达上限, 请稍后重试"},
                )
            active[0] += 1

        buf = get_log_buffer()
        assert buf is not None  # build_router 已保证
        header_id = _safe_int(last_event_id_header) if last_event_id_header is not None else _safe_int(last_event_id)
        heartbeat = max(0.1, heartbeat_seconds if heartbeat_seconds is not None else _DEFAULT_HEARTBEAT_SECONDS)
        min_level = _LEVEL_ORDER.get(str(level).lower()) if level else None

        return StreamingResponse(
            _log_generator(buf, header_id or 0, heartbeat, min_level, max_chunks, active_lock, active),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    return router


async def _log_generator(
    buf: Any,
    start_seq: int,
    heartbeat: float,
    min_level: int | None,
    max_chunks: int | None,
    active_lock: asyncio.Lock,
    active: list[int],
) -> Any:
    """日志 SSE generator (抽模块级减 build_router 复杂度)。

    先回放断线期间缓冲条目 (计入 max_chunks), 再 await 新日志; 超时发心跳保活。
    finally 释放消费者与连接计数, 保证异常/客户端断开时不泄漏。
    """
    try:
        q = await buf.subscribe()
        sent = 0
        for entry in buf.snapshot_after(start_seq):
            if min_level is None or _entry_level(entry) >= min_level:
                yield _format_log_sse(entry)
                sent += 1
                if max_chunks is not None and sent >= max_chunks:
                    return
        while max_chunks is None or sent < max_chunks:
            try:
                entry = await asyncio.wait_for(q.get(), timeout=heartbeat)
                if min_level is None or _entry_level(entry) >= min_level:
                    yield _format_log_sse(entry)
                    sent += 1
            except TimeoutError:
                yield _format_heartbeat()
    finally:
        await buf.unsubscribe(q)
        async with active_lock:
            active[0] = max(0, active[0] - 1)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _entry_level(entry: dict[str, Any]) -> int:
    """日志条目的 level 数值 (structlog add_log_level 写入 'level' 字段为小写字符串)。"""
    return _LEVEL_ORDER.get(str(entry.get("level", "")).lower(), 0)


def _format_log_sse(entry: dict[str, Any]) -> str:
    """SSE 帧: id=<seq>\nevent=log\ndata=<json>\n\n。"""
    seq = entry.get("_seq", 0)
    # 把 _seq/_ts 与 event_dict 一起序列化; 渲染器字段 (event/level/timestamp/logger) 已在
    data = json.dumps(entry, ensure_ascii=False, default=str)
    return f"id: {seq}\nevent: log\ndata: {data}\n\n"


def _format_heartbeat() -> str:
    return ": heartbeat\n\n"
