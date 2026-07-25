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

Fix-13: CONTROL_PLANE_SPEC.md §8.3 "实时通道只发送当前 Token scope 可读的资源"。
``_EVENT_TYPE_SCOPES`` 只覆盖 spec §6.1/§8.3 明确列出资源的事件类型 (agent.*
→ agent:read, model.usage_recorded → usage:read); 未列出的事件类型 (如
channel.status_changed) 视为不需要 scope 收窄, 直接放行, 不臆造 spec 没有定义的
scope 名称。tokens 未配置 (纯扁平 api_token) 时不做任何过滤, 与引入本机制前
完全一致。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.control.auth import TokenScope
    from isac.gateway.event_bus import EventBus


_DEFAULT_HEARTBEAT_SECONDS = 10.0

# CONTROL_PLANE_SPEC.md §8.3 列出的实时事件类型 → 所需 scope。
_EVENT_TYPE_SCOPES: dict[str, str] = {
    "agent.status_changed": "agent:read",
    "provider.health_changed": "provider:read",
    "model.usage_recorded": "usage:read",
    "audit.created": "usage:detail",
}


def build_router(
    event_bus: EventBus,
    auth_dependency: Any = None,
    tokens: list[TokenScope] | None = None,
) -> Any:
    """构造 Events SSE Control API 路由。

    tokens: Fix-12 的 control.tokens[] 解析结果; None (未配置 scope 模型) 时
    事件流不做任何按 scope 过滤, 向后兼容。
    """
    from fastapi import APIRouter, Depends, Header
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
        last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
        authorization: str | None = Header(default=None),
    ) -> Any:
        # Fix-11: 真实浏览器 EventSource 断线重连时按 SSE 规范发 Last-Event-ID
        # 请求头 (不是 query 参数); Header 优先, 缺失时回退 query (手动/测试场景)。
        header_id = _safe_int(last_event_id_header) if last_event_id_header is not None else _safe_int(last_event_id)
        heartbeat = max(0.1, heartbeat_seconds if heartbeat_seconds is not None else _DEFAULT_HEARTBEAT_SECONDS)
        caller_scopes = _resolve_caller_scopes(tokens, authorization)

        async def _gen():
            async for chunk in state.generate(header_id, heartbeat, max_chunks, caller_scopes):
                yield chunk

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    return router


def _resolve_caller_scopes(tokens: list[TokenScope] | None, authorization: str | None) -> frozenset[str] | None:
    """解析调用方 scope 集合; tokens 未配置返回 None (表示不过滤)。"""
    if not tokens:
        return None
    from isac.control.auth import _find_matching_token, extract_bearer

    token = extract_bearer(authorization)
    matched = _find_matching_token(tokens, token)
    return matched.scopes if matched is not None else frozenset()


def _event_visible(event_type: str, caller_scopes: frozenset[str] | None) -> bool:
    """caller_scopes 为 None (未配置 tokens[]) 时不过滤; 事件类型没有预定义所需
    scope 时也不过滤; 否则要求 caller 持有该 scope 或通配符 "*"。"""
    if caller_scopes is None:
        return True
    required = _EVENT_TYPE_SCOPES.get(event_type)
    if required is None:
        return True
    return required in caller_scopes or "*" in caller_scopes


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
        self,
        start_id: int | None,
        heartbeat: float,
        max_chunks: int | None,
        caller_scopes: frozenset[str] | None = None,
    ) -> Any:
        """SSE 事件生成器: 先发 start_id 之后的缓冲事件, 再实时推送 + 心跳。

        caller_scopes 非 None 时, 按 ``_event_visible`` 过滤掉调用方无权查看的
        事件类型 (Fix-13); 被过滤的事件既不 yield 也不计入 max_chunks/last_seen
        之外的推进 (last_seen 仍前进到该事件 id, 避免重连时重复判断)。
        """
        chunks_sent = 0
        sid = start_id or 0
        buffered = [e for e in self.buffer if e["id"] > sid]
        for ev in buffered:
            if not _event_visible(ev["event"], caller_scopes):
                continue
            yield _format_sse(ev["id"], ev["event"], ev["data"])
            chunks_sent += 1
            if max_chunks is not None and chunks_sent >= max_chunks:
                return
        last_seen = buffered[-1]["id"] if buffered else sid
        last_heartbeat = time.monotonic()
        while True:
            new_events = [e for e in self.buffer if e["id"] > last_seen]
            for ev in new_events:
                last_seen = ev["id"]
                if not _event_visible(ev["event"], caller_scopes):
                    continue
                yield _format_sse(ev["id"], ev["event"], ev["data"])
                chunks_sent += 1
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
