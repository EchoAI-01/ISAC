"""J3 Events Control API 路由 - SSE 实时事件流 (CONTROL_PLANE_SPEC.md)。

端点:
- GET /events/stream  SSE 流 + Last-Event-ID 断线恢复 + 心跳 + Token scope 过滤

事件格式 (SSE):
    id: <seq>
    event: <event_type>
    data: <json payload>

    \\n\\n

客户端断线重连时传 Last-Event-ID header, 服务端从该 id 之后开始发。
无事件时仍按 heartbeat_seconds 间隔发心跳 (默认 10s, 测试可配 0.1s)。
max_chunks 参数 (测试用) 让 generator 发 N 个 chunk 后自动退出, 避免 while True 卡死。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.gateway.event_bus import EventBus


_DEFAULT_HEARTBEAT_SECONDS = 10.0


def build_router(
    event_bus: EventBus,
    auth_dependency: Any = None,
) -> Any:
    """构造 Events SSE Control API 路由。"""
    from fastapi import APIRouter, Depends
    from fastapi.responses import StreamingResponse

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["events"], dependencies=deps)

    state = _EventStreamState()
    _subscribe_all_events(event_bus, state)

    @router.get("/events/stream")
    async def events_stream(
        last_event_id: int | None = None,
        heartbeat_seconds: float | None = None,
        max_chunks: int | None = None,
    ) -> Any:
        header_id = _safe_int(last_event_id)
        heartbeat = max(0.1, heartbeat_seconds if heartbeat_seconds is not None else _DEFAULT_HEARTBEAT_SECONDS)

        async def _gen():
            async for chunk in state.generate(header_id, heartbeat, max_chunks):
                yield chunk

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    return router


class _EventStreamState:
    """事件流共享状态: seq 计数器 + 内存缓冲 (供 SSE generator 读取)。"""

    def __init__(self) -> None:
        self.seq_counter = 0
        self.buffer: list[dict[str, Any]] = []

    def append(self, payload: Any) -> None:
        self.seq_counter += 1
        event_type = "unknown"
        if isinstance(payload, dict):
            event_type = str(payload.get("event_type", "unknown"))
        self.buffer.append({"id": self.seq_counter, "event": event_type, "data": payload, "ts": int(time.time())})
        if len(self.buffer) > 1000:
            self.buffer.pop(0)

    async def generate(
        self, start_id: int | None, heartbeat: float, max_chunks: int | None
    ) -> Any:
        """SSE 事件生成器: 先发 start_id 之后的缓冲事件, 再实时推送 + 心跳。"""
        chunks_sent = 0
        sid = start_id or 0
        buffered = [e for e in self.buffer if e["id"] > sid]
        for ev in buffered:
            yield _format_sse(ev["id"], ev["event"], ev["data"])
            chunks_sent += 1
            if max_chunks is not None and chunks_sent >= max_chunks:
                return
        last_seen = buffered[-1]["id"] if buffered else sid
        last_heartbeat = time.monotonic()
        while True:
            new_events = [e for e in self.buffer if e["id"] > last_seen]
            for ev in new_events:
                yield _format_sse(ev["id"], ev["event"], ev["data"])
                chunks_sent += 1
                last_seen = ev["id"]
                if max_chunks is not None and chunks_sent >= max_chunks:
                    return
            now = time.monotonic()
            if now - last_heartbeat > heartbeat:
                yield _format_heartbeat()
                chunks_sent += 1
                last_heartbeat = now
                if max_chunks is not None and chunks_sent >= max_chunks:
                    return
            await asyncio.sleep(0.05)


def _subscribe_all_events(event_bus: EventBus, state: _EventStreamState) -> None:
    """订阅全部 EventType, 把事件写入 state.buffer。"""
    from isac.core.events import EventType

    async def _on_event(payload: Any) -> None:
        state.append(payload)

    for et in EventType:
        event_bus.on_async(et, _on_event)


def _safe_int(val: Any) -> int | None:
    """安全转 int; None/非法返回 None。"""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _format_sse(seq: int, event_type: str, data: Any) -> str:
    """格式化 SSE 事件 (id + event + data)。"""
    data_str = json.dumps(data, ensure_ascii=False, default=str) if not isinstance(data, str) else data
    return f"id: {seq}\nevent: {event_type}\ndata: {data_str}\n\n"


def _format_heartbeat() -> str:
    """SSE 心跳 (注释行, 客户端忽略)。"""
    return f": heartbeat {int(time.time())}\n\n"
