"""Fix-76: webhook 请求体体积上限 (验签/解析 body **之前**生效)。

feishu/wecom/qq_official 三个 webhook 适配器此前都在验签前用
``request.body()`` / ``request.json()`` 全量读取请求体且无体积上限 ——
攻击者发超大 body (含无 Content-Length 的 chunked 传输) 即可打爆内存。
改为流式累计读取, 超限立即拒绝, 不为超限 body 分配内存/继续等待。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# 平台真实事件回调远低于此值 (文本消息 JSON/XML 通常 KB 级); 2MB 留足富媒体
# 事件元数据余量, 同时封死 GB 级攻击体。可按适配器配置 max_body_bytes 覆盖。
DEFAULT_MAX_WEBHOOK_BODY_BYTES = 2 * 1024 * 1024


async def read_body_limited(request: Any, max_bytes: int) -> bytes | None:
    """流式读取请求体, 累计超过 ``max_bytes`` 返回 None (调用方记日志并拒绝)。

    优先用 ``request.stream()`` 逐块累计, 对无 Content-Length 的 chunked 请求
    同样有效; Starlette 的 ``request.body()``/``request.json()`` 会把整个 body
    读进内存且无上限, 不能在验签前直接使用。无 stream 接口的对象 (测试 fake)
    退回 ``body()`` 并**事后**检查体积 —— 上限语义不变, 仅失去"超限不读全量"
    的优化。
    """
    stream = getattr(request, "stream", None)
    if callable(stream):
        chunks: list[bytes] = []
        total = 0
        async for chunk in stream():
            total += len(chunk)
            if total > max_bytes:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    data = await request.body()
    return data if len(data) <= max_bytes else None
