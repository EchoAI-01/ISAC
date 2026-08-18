"""日志环形缓冲 + SSE 订阅 (T4 错误可诊断)。

logger.py 的 structlog processor 链把每条 event_dict copy 后塞进 LogBuffer 单例,
供 /api/v1/logs/tail SSE 端点 (routes_logs.py) 实时推送给 WebUI 日志台。

设计同构 routes_events._EventStreamState: deque(maxlen=N) + 自增 seq + asyncio 消费者
队列 + Last-Event-ID 断线恢复 + heartbeat。但日志不走 EventBus (EventBus 绑定
EventType 枚举, 无 log 事件类型), 用独立 LogBuffer 单例 + logger processor 注入。

热路径: structlog processor 是同步函数, append 到 deque 是 O(1), 不阻塞主链路。
cache_logger_on_first_use 意味着必须在首次 get_logger 调用前 (main.setup_logger)
就把 buffer processor 装进链, 否则已缓存 logger 不带它。
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any

# 环形缓冲上限。对齐 routes_events._EventStreamState.buffer 的 1000 条; 超限丢最旧,
# 防止日志台不连时内存无界增长。1 条日志约几百字节, 1000 条 ≈ 数百 KB, 可接受。
_MAX_BUFFER = 1000


class LogBuffer:
    """日志环形缓冲单例 + SSE 消费者订阅。

    单例: setup_logger 的 processor 持有 instance 引用, 多次 get_logger 共用一个 buffer。
    消费者用 asyncio.Queue (有界) 推送, SSE 端点 await queue.get() 阻塞等新日志。
    """

    def __init__(self, max_buffer: int = _MAX_BUFFER) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer)
        self._seq: int = 0
        self._consumers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = asyncio.Lock()
        # Fix-72: append 由 structlog processor 同步调用, 而日志可能来自
        # asyncio.to_thread / uvicorn 线程池等**非 event loop 线程** (如
        # safe_download_bytes 的 to_thread 回调内打日志)。此时: ① self._seq += 1
        # 非原子 (LOAD/ADD/STORE 间可被 GIL 切换) → 序号重复/丢失; ② 遍历
        # _consumers 时 loop 线程的 subscribe/unsubscribe 并发增删 → RuntimeError;
        # ③ asyncio.Queue 本身非线程安全, 跨线程 put_nowait 与 loop 的 get 竞争。
        # 用 threading.Lock 保护序号/缓冲/消费者快照, 跨线程推送经
        # call_soon_threadsafe 回到 loop 线程执行。
        self._thread_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def seq(self) -> int:
        return self._seq

    def append(self, event_dict: dict[str, Any]) -> None:
        """structlog processor 调用: 把日志事件塞进 buffer + 推送所有消费者。

        同步函数 (structlog processor 契约), 不 await; 推送用 queue.put_nowait
        (队列满时丢弃该条给该消费者, 不阻塞主链路)。Fix-72: 调用方可能在非
        event loop 线程 (见 _thread_lock 注释), 序号/缓冲/消费者快照在
        threading.Lock 内完成, 跨线程投递经 call_soon_threadsafe 回 loop 线程。
        """
        # copy 防止后续 processor 改动 event_dict (structlog processor 链共享 dict)
        entry = dict(event_dict)
        with self._thread_lock:
            self._seq += 1
            entry["_seq"] = self._seq
            entry["_ts"] = time.time()
            self._buffer.append(entry)
            consumers = list(self._consumers)
            loop = self._loop
        for q in consumers:
            self._deliver(q, entry, loop)

    def _deliver(
        self,
        q: asyncio.Queue[dict[str, Any]],
        entry: dict[str, Any],
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        """把条目推给单个消费者; 非 loop 线程时经 call_soon_threadsafe 投递。"""
        if loop is not None:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                try:
                    loop.call_soon_threadsafe(self._push, q, entry)
                except RuntimeError:  # loop 已关闭 (关停竞态): 丢这条, 不影响日志主链
                    pass
                return
        self._push(q, entry)

    @staticmethod
    def _push(q: asyncio.Queue[dict[str, Any]], entry: dict[str, Any]) -> None:
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            # 消费者跟不上 (SSE 客户端慢/断), 丢这条给它, 不阻塞其他消费者
            pass

    def snapshot_after(self, start_seq: int) -> list[dict[str, Any]]:
        """返回 seq > start_seq 的缓冲条目 (Last-Event-ID 断线恢复用)。"""
        return [e for e in self._buffer if e.get("_seq", 0) > start_seq]

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """注册一个消费者队列, 返回供 await 的 Queue。"""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_BUFFER)
        async with self._lock:
            # Fix-72: 增删消费者同样在 threading.Lock 内, 与非 loop 线程的
            # append 快照互斥; 首个消费者记录所属 loop (跨线程投递的目标)。
            with self._thread_lock:
                self._consumers.append(q)
                if self._loop is None:
                    self._loop = asyncio.get_running_loop()
        return q

    async def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            with self._thread_lock:
                if q in self._consumers:
                    self._consumers.remove(q)


# 全局单例 (setup_logger 注入 processor 时持有; None 表示日志台未启用)
_instance: LogBuffer | None = None


def get_log_buffer() -> LogBuffer | None:
    """取全局 LogBuffer 单例 (未启用时 None, routes_logs 据此决定是否挂载端点)。"""
    return _instance


def enable_log_buffer() -> LogBuffer:
    """全局启用 LogBuffer 单例 (幂等)。main.setup_logger 在装 processor 前调用。"""
    global _instance
    if _instance is None:
        _instance = LogBuffer()
    return _instance


def reset_log_buffer() -> None:
    """重置单例 (测试用: 每个测试隔离 buffer)。"""
    global _instance
    _instance = None
